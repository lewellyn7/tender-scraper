"""重庆市公共资源交易网采集器 V3 - 继承 BaseCrawler
- 复用通用字段提取、日期解析、附件解析
- URL 缓存避免重复采集
- 并行采集列表页 + 详情页
"""

import asyncio
import os
from datetime import datetime
import json
import random
import re
from typing import List

import httpx
from loguru import logger

from app.crawlers.base import BaseCrawler
from app.database import get_db
from app.models.tender import TenderInfo
from app.utils.summarize import summarize as make_summary
from app.utils.project_linker import normalize_project_name, extract_project_no


class CQGGZYCrawlerV2(BaseCrawler):
    """重庆市公共资源交易网采集器 — 继承 BaseCrawler"""

    BASE_URL = "https://www.cqggzy.com"
    GOV_PURCHASE_URL = "https://www.cqggzy.com/xxhz/014005/order.html"
    ENGINEERING_URL = "https://www.cqggzy.com/xxhz/014001/bidding.html"

    async def fetch_list(
        self, category: str = "gov_purchase", page_num: int = 1,
        start_date: datetime = None, end_date: datetime = None
    ) -> List[TenderInfo]:
        """"采集单个列表页，可按日期范围过滤

        Args:
            category: gov_purchase | engineering
            page_num: 页码
            start_date: 起始日期（只采集此日期之后的项目）
            end_date: 结束日期（只采集此日期之前的项目）
        """
        return await self._fetch_list_page(category, page_num, start_date, end_date)

    async def fetch_lists_parallel(
        self, category: str = "gov_purchase", pages: List[int] = None,
        start_date: datetime = None, end_date: datetime = None
    ) -> List[TenderInfo]:
        """并行采集多个列表页（可按日期范围过滤）"""
        if pages is None:
            pages = list(range(1, 6))
        tasks = [self._fetch_list_page(category, p, start_date, end_date) for p in pages]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_items = []
        for r in results:
            if isinstance(r, list):
                all_items.extend(r)
            elif isinstance(r, Exception):
                logger.warning(f"列表页采集异常: {r}")
        logger.info(f"✅ 并行列表页采集完成：{len(all_items)} 条")
        return all_items

    async def _fetch_list_page(
        self, category: str, page_num: int,
        start_date: datetime = None, end_date: datetime = None
    ) -> List[TenderInfo]:
        """内部：采集单个列表页，可按日期范围过滤"""
        results = []
        url = self.GOV_PURCHASE_URL if category == "gov_purchase" else self.ENGINEERING_URL
        tender_type = "政府采购" if category == "gov_purchase" else "工程建设"
        page = None

        try:
            page = await self.browser.new_page()
            logger.info(f"📑 采集 {tender_type} 列表 第{page_num}页")
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await self._smart_wait()


            items = await page.query_selector_all("ul li")
            for item in items:
                try:
                    link_elem = await item.query_selector("a")
                    if not link_elem:
                        continue
                    href = await link_elem.get_attribute("href")
                    title = await link_elem.text_content()

                    if not href or not title or href.startswith("javascript"):
                        continue
                    if len(title.strip()) < 10:
                        continue

                    full_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"

                    # 日期从 URL 路径提取（格式: /YYYYMMDD/）
                    date_from_url = None
                    date_match = re.search(r'/(\d{4})(\d{2})(\d{2})/', full_url)
                    if date_match:
                        try:
                            date_from_url = datetime(
                                int(date_match.group(1)),
                                int(date_match.group(2)),
                                int(date_match.group(3))
                            )
                        except ValueError:
                            pass

                    # 日期优先从列表页 DOM 提取，其次用 URL 日期
                    date_elem = await item.query_selector('[class*="date"]')
                    if not date_elem:
                        next_span = await item.query_selector('span + span')
                        date_elem = next_span if next_span else await item.query_selector('span')
                    date_text = await date_elem.text_content() if date_elem else ""


                    # 日期过滤（列表页通常按时间倒序，发现早于起始日期即可停止）
                    effective_date = date_from_url
                    if not effective_date and date_text:
                        parsed = self._parse_date(date_text)
                        if parsed and isinstance(parsed, datetime):
                            effective_date = parsed
                    if start_date and effective_date and effective_date < start_date:
                        logger.debug(f"  ⏹  [{title[:30]}...] 日期 {effective_date.date()} < {start_date.date()}，停止本页")
                        break
                    if end_date and effective_date and effective_date > end_date:
                        continue

                    # 跳过不采集的类型（按 URL 判断）
                    NO_COLLECT_PATTERNS = [
                        "/bszn/",           # 办事指南
                        "/014005008/",       # 单一来源公示
                        "/014001014/",       # 邀标信息
                        "/014001020/",       # 合同签订
                        "/014001023/",       # 合同变更
                        "/zcfg/",            # 政策法规
                        "czj.cq.gov.cn",      # 财政局文件
                        "test.local",         # 测试数据
                    ]
                    if any(p in full_url for p in NO_COLLECT_PATTERNS):
                        continue

                    tender = TenderInfo(
                        title=title.strip(),
                        url=full_url,
                        category=tender_type,
                        source_url=url,
                        publish_date_raw=date_text.strip(),
                        tender_type=tender_type,
                        scraped_by=self.version,
                    )
                    if date_from_url:
                        tender.publish_date = date_from_url
                    elif date_text:
                        tender.publish_date = self._parse_date(date_text)
                    results.append(tender)
                except Exception as e:
                    logger.warning(f"⚠️ 提取列表项失败：{e}")
                    continue

            logger.info(f"✅ 列表页第{page_num}页：{len(results)} 条")
            return results
        except Exception as e:
            logger.error(f"❌ 列表页第{page_num}页失败：{e}")
            return results
        finally:
            if page:
                await page.close()

    async def fetch_detail(self, tender: TenderInfo) -> TenderInfo:
        """采集详情页（URL 是否已访问由 fetch_list 统一管理）"""
        return await self._fetch_detail_page(tender)

    async def fetch_details_parallel(
        self, tenders: List[TenderInfo], concurrency: int = 5
    ) -> List[TenderInfo]:
        """并行采集多个详情页"""
        return await self.fetch_details_batch(tenders, max_concurrent=concurrency)

    async def _fetch_detail_page(self, tender: TenderInfo) -> TenderInfo:
        """内部：采集单个详情页"""
        page = None
        try:
            page = await self.browser.new_page()
            logger.info(f"📄 采集详情页：{tender.title[:30]}...")
            await page.goto(tender.url, wait_until="networkidle", timeout=30000)
            await self._smart_wait()

            # 提取正文
            await self._extract_content(page, tender)

            # 提取标题（详情页从 .article-title 提取，覆盖列表噪声标题）
            try:
                title_elem = await page.query_selector("h3.article-title")
                if title_elem:
                    real_title = (await title_elem.text_content()).strip()
                    if real_title and len(real_title) > 5:
                        tender.title = real_title
                        logger.debug(f"  📌 标题校正: {tender.title[:40]}")
            except Exception:
                pass

            # 批量提取字段（使用基类通用方法）
            tender.contact_info = await self._extract_contact_info(page)
            tender.budget = await self._extract_budget(page)
            deadline_raw, deadline_dt = await self._extract_deadline(page)
            if deadline_dt:
                tender.deadline = deadline_dt
            tender.attachments = await self._extract_attachments(page)
            tender.region = await self._extract_region(page)
            tender.business_type = await self._extract_business_type(page)
            tender.info_type = await self._extract_info_type(page)
            # Fallback: 从 URL 路径提日期（格式: /YYYYMMDD/）
            if not tender.publish_date:
                date_from_url = self._extract_date_from_url(tender.url)
                if date_from_url:
                    tender.publish_date = date_from_url
                    logger.debug(f"  📅 从URL提取日期: {tender.publish_date}")

            tender.project_overview = await self._extract_field_by_kw(
                page, ["项目概况"], max_len=300
            )
            tender.bidder_requirements = await self._extract_field_by_kw(
                page, ["投标人资格要求", "供应商资格要求", "资格条件"]
            )
            tender.submission_deadline = await self._extract_field(
                page,
                [
                    r"截止时间[^为]{0,30}为\s*(\d{4}[年\-]\d{1,2}[月\-]\d{1,2}[日]?(?:\s*\d{1,2}[时:]\d{1,2}(?:分)?)?)",
                    r"(?:递交)?截止时间[：:]*\s*(\d{4}[年\-]\d{1,2}[月\-]\d{1,2}[日]?(?:\s*\d{1,2}[时:]\d{1,2}(?:分)?)?)",
                    r"(?:递交的|文件递交的)截止时间[^。,，\n]{0,20}(\d{4}[年\-]\d{1,2}[月\-]\d{1,2}[日]?(?:\s*\d{1,2}[时:]\d{1,2}(?:分)?)?)",
                    r"投标(?:文件)?递交截止时间[：:]*\s*(\d{4}[年\-]\d{1,2}[月\-]\d{1,2}[日]?(?:\s*\d{1,2}[时:]\d{1,2}(?:分)?)?)",
                    r"(?:投标|响应)截止时间[：:]*\s*(\d{4}[年\-]\d{1,2}[月\-]\d{1,2}[日]?(?:\s*\d{1,2}[时:]\d{1,2}(?:分)?)?)",
                ],
                default="",
            )
            tender.bid_amount = await self._extract_bid_amount(page)
            tender.project_no = extract_project_no(tender.title, tender.full_content or "")
            tender.project_name = normalize_project_name(tender.title)

            # 生成结构化摘要（按 info_type 规则），写入 content_preview 替代原始 raw text
            tender.content_preview = make_summary(
                info_type=tender.info_type or "",
                budget=tender.budget or "",
                bid_amount=tender.bid_amount or "",
                submission_deadline=tender.submission_deadline or "",
                contact_name=tender.contact_info.name if tender.contact_info else "",
                contact_phone=tender.contact_info.phone if tender.contact_info else "",
                region=tender.region or "",
                full_content=tender.full_content or "",
                business_type=tender.business_type or "",
            )

            # 写入 projects_cqggzy（直接 upsert，包含 project_overview）
            try:
                db = get_db()
                att_count = len(tender.attachments) if tender.attachments else 0
                att_str = ", ".join(a.name for a in tender.attachments if a.name) if tender.attachments else ""

                def _v(val):
                    """Ensure value is string, detect coroutines"""
                    if asyncio.iscoroutine(val):
                        logger.warning(f"⚠️ coroutine detected in field, using empty string: {type(val)}")
                        return ""
                    return str(val) if val is not None else ""

                # Debug: log deadline type and value
                if tender.deadline:
                    logger.debug(f"DEBUG deadline: {type(tender.deadline)} = {repr(tender.deadline)}")
                else:
                    logger.debug("DEBUG deadline: None/empty")

                row = {
                    "url": _v(tender.url),
                    "title": _v(tender.title),
                    "category": _v(tender.tender_type or ""),
                    "info_type": _v(tender.info_type or ""),
                    "business_type": _v(tender.business_type or ""),
                    "publish_date": tender.publish_date or None,  # date type
                    "publish_date_raw": _v(tender.publish_date or ""),
                    "content_preview": _v((tender.content_preview or "")[:2000]),
                    "full_content": _v(tender.full_content or ""),
                    "budget": _v(tender.budget or ""),
                    "bid_amount": _v(tender.bid_amount or ""),
                    "deadline": tender.deadline if isinstance(tender.deadline, datetime) else None,  # timestamp
                    "region": _v(tender.region or ""),
                    "industry": "",
                    "tender_type": _v(tender.tender_type or ""),
                    "project_overview": _v(tender.project_overview),
                    "bidder_requirements": _v(tender.bidder_requirements or ""),
                    "submission_deadline": _v(tender.submission_deadline or ""),
                    "contact_name": _v(tender.contact_info.name if tender.contact_info else ""),
                    "contact_phone": _v(tender.contact_info.phone if tender.contact_info else ""),
                    "contact_email": _v(tender.contact_info.email if tender.contact_info else ""),
                    "attachments_count": att_count,  # integer
                    "attachments": json.dumps([a.name for a in tender.attachments]) if tender.attachments else "[]",
                    "keywords_matched": "",
                    "source_url": _v(tender.source_url or tender.url),
                    "scraped_at": None,  # timestamp, let DB set default
                    "scraped_by": "",
                    "contract_amount": "",
                    "planned_publish_date": "",
                    "tender_content": "",
                    "opening_date": None,  # timestamp
                }
                db.upsert_projects([row])

                # 清除 API 缓存，确保新数据立即可见
                web_url = os.getenv("WEB_URL", "http://tender-scraper-web:8000")
                cache_key = os.getenv("INTERNAL_CACHE_CLEAR_KEY", "")
                try:
                    httpx.post(f"{web_url}/api/cache/clear", json={"internal_key": cache_key}, timeout=5)
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"⚠️ 写入 projects_cqggzy 失败: {e}")

            logger.info("  ✅ 详情页采集完成")
            return tender
        except Exception as e:
            import traceback; logger.warning(f"⚠️ 详情页采集失败: {e}\n{traceback.format_exc()}")
            return tender
        finally:
            if page:
                await page.close()

    async def _extract_content(self, page, tender: TenderInfo) -> None:
        """提取正文内容（滚动加载完整正文）"""
        # 先尝试滚动内容区触发懒加载
        try:
            for _ in range(8):
                await page.evaluate(
                    """() => {
                        const el = document.querySelector('.content,.article,.detail-content,#content,.main-content,.zw_c,.con_r');
                        if (el) { el.scrollTop = el.scrollHeight; }
                        else { window.scrollTo(0, document.body.scrollHeight); }
                    }"""
                )
                await asyncio.sleep(0.5)
        except Exception:
            pass

        # 等待正文区加载
        try:
            await page.wait_for_selector('.zw_c, .con_r, .content, #content', timeout=5000)
        except Exception:
            pass

        selectors = [
            ".epoint-article-content", "#mainContent", ".epoint-article",
            ".content", ".article", ".detail-content", "#content",
            ".main-content", ".text-content", ".news-content",
            ".TREmpty", ".zw_c", ".con_r",
        ]
        for selector in selectors:
            try:
                elem = await page.query_selector(selector)
                if elem:
                    # 滚动该元素到底部
                    try:
                        await page.evaluate(
                            "(el) => { el.scrollTop = el.scrollHeight; }",
                            elem
                        )
                        await asyncio.sleep(0.3)
                    except Exception:
                        pass
                    full = await elem.inner_text()
                    if len(full) > 20:
                        tender.full_content = full
                        tender.content_preview = (
                            full[:500] + "..." if len(full) > 500 else full
                        )
                        logger.info(f"  ✅ 正文提取成功 ({len(full)} 字)")
                        return
            except Exception:
                continue

        # fallback: body 提取（过滤导航噪音）
        try:
            text = await page.inner_text("body")
            lines, in_content = [], False
            skip_kw = ["首 页", "重要通知", "交易信息", "当前访问", "收藏",
                       "您当前的位置", "版权所有", "技术支持", "<delete_file>"]
            for line in text.split("\n"):
                line = line.strip()
                if any(s in line for s in skip_kw):
                    continue
                if "项目" in line or "采购" in line or "招标" in line:
                    in_content = True
                if in_content and len(line) > 20:
                    lines.append(line)
            full = "\n".join(lines)
            if len(full) > 20:
                tender.full_content = full
                tender.content_preview = full[:500] + "..." if len(full) > 500 else full
        except Exception:
            pass

    # ─── 站点特征提取 ────────────────────────────────────────────

    async def _extract_region(self, page) -> str:
        """提取所属区域"""
        try:
            text = await page.inner_text("body")
            districts = [
                "渝中区", "大渡口区", "江北区", "沙坪坝区", "九龙坡区", "南岸区",
                "北碚区", "渝北区", "巴南区", "万州区", "涪陵区", "永川区",
                "合川区", "江津区", "綦江区", "长寿区", "大足区", "璧山区",
                "铜梁区", "潼南区", "荣昌区", "黔江区", "两江新区",
            ]
            for district in districts:
                if district in text:
                    logger.debug(f"  ✅ 区域: {district}")
                    return district
        except Exception:
            pass
        return "重庆市"

    async def _extract_business_type(self, page) -> str:
        """提取业务类型"""
        try:
            url = page.url
            text = (await page.inner_text("body"))[:500]
            if "014005" in url or "order" in url:
                return "政府采购"
            elif "014001" in url or "bidding" in url:
                return "工程招投标"
            if "采购" in text:
                return "政府采购"
            if "招标" in text:
                return "工程招投标"
        except Exception:
            pass
        return "政府采购"

    def _extract_info_type_by_url(self, url: str) -> str:
        """根据 URL 路径提取信息类型（优先级最高）"""
        # 政府采购
        if "/014005/014005001/" in url:
            return "采购公告"
        if "/014005/014005004/" in url:
            return "采购结果公告"
        if "/014005/014005002/" in url:
            return "答疑变更"
        if "/014005/014005008/" in url:
            return "单一来源公示"
        # 工程招投标
        if "/014001/014001019/" in url:
            return "招标计划"
        if "/014001/014001001/" in url:
            return "招标公告"
        if "/014001/014001014/" in url:
            return "邀标信息"
        if "/014001/014001002/" in url:
            return "答疑补遗"
        if "/014001/014001003/" in url:
            return "中标候选人公示"
        if "/014001/014001004/" in url:
            return "中标结果公示"
        if "/014001/014001020/" in url:
            return "合同签订基本信息公示"
        if "/014001/014001023/" in url:
            return "合同变更基本信息公示"
        if "/014001/014001016/" in url:
            return "相关公告"
        if "/014001/014001021/" in url:
            return "终止公告"
        return ""

    def _is_collectible_info_type(self, info_type: str) -> bool:
        """判断该信息类型是否应该采集（不采集的返回 False）"""
        NO_COLLECT = {"单一来源公示", "邀标信息", "合同签订基本信息公示", "合同变更基本信息公示"}
        return info_type not in NO_COLLECT

    def _extract_date_from_url(self, url: str):
        """从 URL 路径提取日期（格式: /YYYYMMDD/），返回 datetime 或 None"""
        import re
        m = re.search(r'/(\d{4})(\d{2})(\d{2})/', url)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
        return None

    async def _extract_info_type(self, page) -> str:
        """提取信息类型：优先 URL 推断，再页面内容兜底"""
        try:
            url = page.url
            itype = self._extract_info_type_by_url(url)
            if itype:
                logger.debug(f"  ✅ 信息类型(URL): {itype}")
                return itype
            text = (await page.inner_text("body"))[:2000]
            patterns = [
                ("中标结果公告", "中标结果公告"),
                ("中标候选人公示", "中标候选人公示"),
                ("结果公告", "结果公告"),
                ("采购意向", "采购意向"),
                ("招标公告", "招标公告"),
                ("答疑补遗", "答疑补遗"),
                ("变更公告", "变更公告"),
            ]
            for pattern, itype in patterns:
                if pattern in text:
                    logger.debug(f"  ✅ 信息类型(内容): {itype}")
                    return itype
        except Exception:
            pass
        return "招标公告"

    # ─── 工具方法 ────────────────────────────────────────────────

    async def _smart_wait(self) -> None:
        """智能随机等待 (0.3-0.8s)"""
        await asyncio.sleep(0.3 + random.random() * 0.5)
