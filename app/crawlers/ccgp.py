"""重庆市政府采购网采集器 V3 - 继承 BaseCrawler - 复用通用字段提取、日期解析、附件解析 - 三类信息：采购意向 / 采购公告 / 结果公告 """

import asyncio
import os
import json
from datetime import datetime
import re
from typing import List
from urllib.parse import urljoin

import httpx
from loguru import logger

from app.crawlers.base import BaseCrawler
from app.database import get_db
from app.models.tender import TenderInfo
from app.services.keywords_service import KeywordsService
from app.utils.summarize import summarize as make_summary
from app.utils.project_linker import normalize_project_name, extract_project_no


class CCGPCrawlerV3(BaseCrawler):
    """重庆市政府采购网采集器 — 继承 BaseCrawler"""

    BASE_URL = "https://www.ccgp-chongqing.gov.cn"

    LIST_URLS = {
        "采购意向": "https://www.ccgp-chongqing.gov.cn/gkw/web/portal/intention/list",
        "采购公告": "https://www.ccgp-chongqing.gov.cn/gkw/web/portal/notice/list",
        "结果公告": "https://www.ccgp-chongqing.gov.cn/gkw/web/portal/result/list",
    }

    async def fetch_list(
        self, info_type: str = "采购公告", page_num: int = 1,
        start_date: datetime = None, end_date: datetime = None
    ) -> List[TenderInfo]:
        """采集列表页，可按日期范围过滤"""
        results = []
        if info_type not in self.LIST_URLS:
            logger.error(f"❌ 不支持的信息类型：{info_type}")
            return results

        url = self.LIST_URLS[info_type]
        if page_num > 1:
            url = f"{url}?page={page_num}"

        page = None
        try:
            page = await self.browser.new_page()
            logger.info(f"📄 采集 [{info_type}] 列表 第{page_num}页：{url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(6)

            # 主选择器：.block-item（React SPA 页面 - 等待 SPA 渲染后再采集）
            items = await page.query_selector_all(".block-item")
            if not items:
                # 兜底选择器
                list_item_selectors = [
                    ".item-title",
                    "[class*=TitleCol]",
                    "[class*=ListItem]",
                    ".notice-item",
                    ".list-item",
                    ".item",
                    "ul.list li",
                    "table tr",
                    ".data-list tr",
                ]
                for selector in list_item_selectors:
                    items = await page.query_selector_all(selector)
                    if items:
                        logger.debug(f"使用选择器：{selector}, 找到 {len(items)} 项")
                        break

            if not items:
                items = await page.query_selector_all('a[href*="detail"], a[href*="view"]')

            # 从 React fiber 提取每个 block-item 的 data id（用于构造详情页 URL）
            # 方法：拦截 window.open，点击每个标题，捕获 SPA 导航 URL
            item_ids = []
            try:
                await page.evaluate("""() => {
                    window.__ccgpItemUrls = window.__ccgpItemUrls || [];
                    if (!window.__ccgpOriginalOpen) {
                        window.__ccgpOriginalOpen = window.open.bind(window);
                    }
                    window.open = function(url) {
                        window.__ccgpItemUrls.push(url);
                        return null;
                    };
                }""")
                logger.debug("window.open intercepted")

                title_elements = await page.query_selector_all(".block-item .item-title")
                logger.debug(f"Title elements: {len(title_elements)}, block items: {len(items)}")

                for title_el in title_elements:
                    try:
                        await title_el.click()
                        await asyncio.sleep(0.3)
                    except Exception as e:
                        logger.debug(f"click title error: {e}")
                logger.debug(f"After clicks, checking urls")

                urls = await page.evaluate("window.__ccgpItemUrls || []")
                logger.debug(f"Captured {len(urls)} urls: {urls[:2]}")
                item_ids = [url.split("/")[-1] for url in urls if "/info-notice/" in url and url.split("/")[-1]]
                logger.debug(f"Extracted {len(item_ids)} ids: {item_ids[:2]}")

                if item_ids:
                    await page.evaluate("if(window.__ccgpOriginalOpen){window.open=window.__ccgpOriginalOpen}")
            except Exception as e:
                import traceback
                logger.error(f"提取 item IDs 失败：{e}\n{traceback.format_exc()}")
                item_ids = []
            logger.info(f"Block items: {len(items)}, item IDs: {len(item_ids)}, ids: {item_ids[:3]}")

            for item_idx, item in enumerate(items):
                try:
                    tag = "A"
                    link_elem = item
                    try:
                        tag = await item.evaluate("el => el.tagName")
                        link_elem = await item.query_selector("a") if tag != "A" else item
                    except (AttributeError, TypeError):
                        # Mock 对象没有 evaluate 方法
                        pass

                    # 修复：新版 ListItem 结构 - 标题在 .item-title 的 title 属性中
                    title = ""
                    title_elem = await item.query_selector(".item-title")
                    if title_elem:
                        title = (await title_elem.get_attribute("title")).strip()
                    
                    if not title:
                        title_elem = await item.query_selector(".title")
                        if title_elem:
                            title = (await title_elem.text_content()).strip()
                    
                    if not title:
                        title = (await item.text_content()).strip()[:200]

                    # 尝试从 .desc a 获取链接
                    desc_link = await item.query_selector(".desc a, [class*=desc] a")
                    href = ""
                    if desc_link:
                        href = await desc_link.get_attribute("href")
                    elif tag == "A":
                        href = await item.get_attribute("href")
                    
                    if not href and link_elem and tag != "A":
                        href = await link_elem.get_attribute("href")

                    if not title or len(title.strip()) < 5:
                        continue

                    if href and "javascript" in href.lower():
                        href = None

                    # 提取日期
                    date_text = ""
                    try:
                        date_elem = await item.query_selector('.date, .time, [class*="date"], td:nth-child(2)')
                        if date_elem:
                            date_text = (await date_elem.text_content()).strip()
                    except (AttributeError, TypeError):
                        pass

                    # 如果没有 href，使用 React fiber 中提取的 data id 构造详情页 URL
                    if href:
                        full_url = urljoin(self.BASE_URL, href)
                    elif item_idx < len(item_ids):
                        # 使用 React fiber 中提取的 id 构造详情页 URL
                        item_id = item_ids[item_idx]
                        # noticeType 200 -> procument-notice-detail, 300 -> result-notice-detail
                        info_type_route = "procument-notice-detail" if info_type == "采购公告" else "result-notice-detail"
                        full_url = f"{self.BASE_URL}/info-notice/{info_type_route}/{item_id}"
                    else:
                        # 兜底：使用标题哈希生成唯一 URL（避免相同列表 URL 导致去重失败）
                        import hashlib
                        title_hash = hashlib.md5(title.encode("utf-8")).hexdigest()[:8]
                        full_url = f"{self.BASE_URL}/gkw/web/portal/{info_type}/{title_hash}"
                        logger.warning(f"无 item_id，使用标题哈希 URL：{full_url}")

                    tender = TenderInfo(
                        title=title,
                        url=full_url,
                        business_type="政府采购",
                        info_type=info_type,
                        source_url=url,
                        publish_date_raw=date_text,
                        tender_type=info_type,
                        scraped_by=self.version,
                    )
                    if date_text:
                        tender.publish_date = self._parse_date(date_text)

                    # 日期过滤（列表页通常按时间倒序，发现早于起始日期即可停止）
                    effective_date = tender.publish_date
                    if start_date and effective_date and effective_date < start_date:
                        logger.debug(f"  ⏹  [{tender.title[:30]}...] 日期 {effective_date.date()} < {start_date.date()}，停止本页")
                        break
                    if end_date and effective_date and effective_date > end_date:
                        continue

                    results.append(tender)
                except Exception as e:
                    logger.debug(f"提取列表项失败：{e}")
                    continue

            logger.info(f"✅ 列表页采集完成：{len(results)} 条")
            return results

        except Exception as e:
            logger.error(f"❌ 列表页采集失败：{e}")
            return results
        finally:
            if page:
                await page.close()

    async def fetch_detail(self, tender: TenderInfo) -> TenderInfo:
        """采集详情页（URL 是否已访问由 fetch_list 统一管理）"""
        return await self._fetch_detail_page(tender)

    async def _fetch_detail_page(self, tender: TenderInfo) -> TenderInfo:
        """内部：采集单个详情页"""
        page = None
        try:
            page = await self.browser.new_page()
            logger.info(f"📄 采集详情：{tender.title[:40]}...")
            await page.goto(tender.url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(8)  # 等待 SPA 渲染详情页内容

            # 提取正文（滚动加载完整内容）
            try:
                for _ in range(8):
                    await page.evaluate(
                        """() => {
                            const el = document.querySelector('.content,.article-content,.detail-content,#content,.main-content,.text-content,article,.body');
                            if (el) { el.scrollTop = el.scrollHeight; }
                            else { window.scrollTo(0, document.body.scrollHeight); }
                        }"""
                    )
                    await asyncio.sleep(0.5)
            except Exception:
                pass

            # 先尝试专用选择器，再尝试 body.innerText（SPA 页面的内容在 body 层级）
            content_selectors = [
                ".content",
                ".article-content",
                ".detail-content",
                "#content",
                ".main-content",
                ".text-content",
                "article",
            ]
            full = ""
            for selector in content_selectors:
                elem = await page.query_selector(selector)
                if elem:
                    try:
                        await page.evaluate("(el) => { el.scrollTop = el.scrollHeight; }", elem)
                        await asyncio.sleep(0.3)
                    except Exception:
                        pass
                    candidate = await elem.inner_text()
                    if len(candidate) > 100 and "项目概况" in candidate:
                        full = candidate
                        break
            if not full:
                # SPA 页面：直接从 body.innerText 提取（等待 8 秒后 SPA 已渲染完毕）
                body_text = await page.evaluate("document.body.innerText")
                if "项目概况" in body_text or "项目基本情况" in body_text:
                    full = body_text

            if full:
                tender.full_content = full
                tender.content_preview = full[:300] + "..." if len(full) > 300 else full

            # 按信息类型提取专用字段
            if tender.info_type == "采购意向":
                await self._extract_intention_fields(page, tender)
            elif tender.info_type == "采购公告":
                await self._extract_notice_fields(page, tender)
            elif tender.info_type == "结果公告":
                await self._extract_result_fields(page, tender)

            # 通用字段（使用基类方法）
            tender.contact_info = await self._extract_contact_info(page)
            tender.attachments = await self._extract_attachments(page)

            # 生成结构化摘要（按 info_type 规则）
            # 清空 raw content_preview，用结构化摘要替代
            tender.content_preview = ""
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
            # project_overview 保留（给 favorites 等引用）
            tender.project_overview = tender.content_preview

            # 提取项目编号和名称
            tender.project_no = extract_project_no(tender.title, tender.full_content or "")
            tender.project_name = normalize_project_name(tender.title)

            # 关键词匹配（基于内容摘要 + 标题）
            kw_text = f"{tender.title} {tender.content_preview or ''}"
            ks = KeywordsService()
            kw_result = ks.match(kw_text)
            tender.keywords_matched = [m['keyword'] for m in kw_result.get('matched', [])]

            # 写入 projects_ccgp 表（与 cqggzy.py 相同的格式）
            try:
                db = get_db()
                att_count = len(tender.attachments) if tender.attachments else 0
                att_list = [a.name for a in tender.attachments] if tender.attachments else []

                def _v(val):
                    """Ensure value is string, detect coroutines"""
                    if asyncio.iscoroutine(val):
                        logger.warning(f"⚠️ coroutine in field: {type(val)}")
                        return ""
                    return str(val) if val is not None else ""

                row = {
                    "url": _v(tender.url),
                    "title": _v(tender.title),
                    "category": _v(tender.tender_type or ""),
                    "info_type": _v(tender.info_type or ""),
                    "publish_date": tender.publish_date or None,
                    "publish_date_raw": _v(tender.publish_date or ""),
                    "content_preview": _v((tender.content_preview or "")[:2000]),
                    "full_content": _v(tender.full_content or ""),
                    "budget": _v(tender.budget or ""),
                    "bid_amount": _v(tender.bid_amount or ""),
                    "deadline": tender.deadline if isinstance(tender.deadline, datetime) else None,
                    "region": _v(tender.region or ""),
                    "industry": "",
                    "tender_type": _v(tender.tender_type or ""),
                    "project_overview": _v(tender.project_overview),
                    "bidder_requirements": _v(tender.bidder_requirements or ""),
                    "submission_deadline": _v(tender.submission_deadline or ""),
                    "contact_name": _v(tender.contact_info.name if tender.contact_info else ""),
                    "contact_phone": _v(tender.contact_info.phone if tender.contact_info else ""),
                    "contact_email": _v(tender.contact_info.email if tender.contact_info else ""),
                    "attachments_count": att_count,
                    "attachments": json.dumps(att_list) if att_list else "[]",
                    "keywords_matched": ",".join(tender.keywords_matched) if tender.keywords_matched else "",
                    "source_url": _v(tender.source_url or tender.url),
                    "scraped_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "scraped_by": "",
                    "contract_amount": "",
                    "planned_publish_date": "",
                    "tender_content": "",
                    "project_no": _v(tender.project_no or ""),
                }
                db.upsert_projects_ccgp([row])

                # 清除 API 缓存，确保新数据立即可见
                web_url = os.getenv("WEB_URL", "http://tender-scraper-web:8000")
                cache_key = os.getenv("INTERNAL_CACHE_CLEAR_KEY", "")
                try:
                    httpx.post(f"{web_url}/api/cache/clear", json={"internal_key": cache_key}, timeout=5)
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"⚠️ 写入 projects_ccgp 失败: {e}")

            return tender
        except Exception as e:
            import traceback; logger.warning(f"⚠️ 详情页采集失败: {e}\n{traceback.format_exc()}")
            return tender
        finally:
            if page:
                await page.close()

    # ─── 信息类型专用字段提取 ─────────────────────────────────────

    async def _extract_intention_fields(self, page, tender: TenderInfo) -> None:
        """提取采购意向专用字段"""
        text = await page.inner_text("body")
        name_match = re.search(r"采购项目[名称]*[：:]\s*([^\n]+)", text)
        if name_match:
            tender.title = name_match.group(1).strip()

        tender.budget = await self._extract_field(
            page,
            [
                r"预算金额[：:]\s*([\d,\.]+)\s*(?:万元|元)",
                r"采购预算[：:]\s*([\d,\.]+)\s*(?:万元|元)",
            ],
        )

        time_match = re.search(r"预计采购时间[：:]\s*([^\n]+)", text)
        if time_match:
            tender.bidder_requirements = f"预计采购时间：{time_match.group(1).strip()}"

        needs_match = re.search(r"采购需求概况[：:]\s*([^\n]+(?:\n(?! 采购) [^\n]+)*)", text)
        if needs_match:
            tender.project_overview = needs_match.group(1).strip()

    async def _extract_notice_fields(self, page, tender: TenderInfo) -> None:
        """提取采购公告专用字段"""
        text = await page.inner_text("body")
        overview_patterns = [
            r"项目概况[：:]\s*([^\n]+)",
            r"采购内容[：:]\s*([^\n]+)",
            r"项目简介[：:]\s*([^\n]+)",
        ]
        for pattern in overview_patterns:
            match = re.search(pattern, text)
            if match:
                tender.project_overview = match.group(1).strip()
                break

        tender.budget = await self._extract_field(
            page,
            [
                r"预算金额[：:]\s*([\d,\.]+)\s*(?:万元|元)",
                r"采购预算[：:]\s*([\d,\.]+)\s*(?:万元|元)",
                r"项目预算[：:]\s*([\d,\.]+)\s*(?:万元|元)",
            ],
        )

        req_match = re.search(r"资格要求[：:]\s*([^\n]+)", text)
        if req_match:
            tender.bidder_requirements = req_match.group(1).strip()[:500]

        deadline_raw, deadline_dt = await self._extract_deadline(page)
        if deadline_dt:
            tender.deadline = deadline_dt
        if tender.submission_deadline:
            tender.submission_deadline = tender.submission_deadline
        else:
            tender.submission_deadline = deadline_raw

        opening_match = re.search(r"开标时间[：:]\s*([^\n]+)", text)
        if opening_match:
            tender.opening_date = self._parse_datetime(opening_match.group(1))

    async def _extract_result_fields(self, page, tender: TenderInfo) -> None:
        """提取结果公告专用字段"""
        text = await page.inner_text("body")
        supplier_patterns = [
            r"中标供应商[：:]\s*([^\n]+)",
            r"中标人[：:]\s*([^\n]+)",
            r"成交供应商[：:]\s*([^\n]+)",
        ]
        for pattern in supplier_patterns:
            match = re.search(pattern, text)
            if match:
                tender.bidder_requirements = f"中标供应商：{match.group(1).strip()}"
                break

        tender.bid_amount = await self._extract_field(
            page,
            [
                r"中标金额[：:]\s*([\d,\.]+)\s*(?:万元|元)",
                r"成交金额[：:]\s*([\d,\.]+)\s*(?:万元|元)",
                r"合同金额[：:]\s*([\d,\.]+)\s*(?:万元|元)",
            ],
        )

        tender.budget = await self._extract_field(
            page,
            [
                r"预算金额[：:]\s*([\d,\.]+)\s*(?:万元|元)",
                r"项目预算[：:]\s*([\d,\.]+)\s*(?:万元|元)",
            ],
        )

        date_match = re.search(r"公告日期[：:]\s*([^\n]+)", text)
        if date_match:
            tender.publish_date_raw = date_match.group(1).strip()

    # ─── 内容摘要 ────────────────────────────────────────────────

    def _summarize_content(self, tender: TenderInfo) -> str:
        """智能总结采集内容（不重复标题）"""
        parts = [f"【{tender.info_type}】"]  # 不再附标题，标题已在【】前体现

        if tender.info_type == "采购意向":
            if tender.budget:
                parts.append(f"预算：{tender.budget}")
            if tender.bidder_requirements:
                parts.append(tender.bidder_requirements)
        elif tender.info_type == "采购公告":
            if tender.project_overview:
                # project_overview 可能是标题兜底，避免重复
                overview_text = tender.project_overview
                if tender.title and overview_text.startswith(tender.title):
                    overview_text = overview_text[len(tender.title):].strip()
                    if overview_text and overview_text[:2] in ('：', ':', '】'):
                        overview_text = overview_text[2:].strip()
                parts.append(f"项目概况：{overview_text[:100]}")
            if tender.budget:
                parts.append(f"预算：{tender.budget}")
            if tender.submission_deadline:
                parts.append(f"截止时间：{tender.submission_deadline}")
            if tender.bidder_requirements:
                parts.append(f"资格要求：{tender.bidder_requirements[:100]}")
        elif tender.info_type == "结果公告":
            if tender.bidder_requirements:
                parts.append(tender.bidder_requirements)
            if tender.bid_amount:
                parts.append(f"中标金额：{tender.bid_amount}")
            if tender.budget:
                parts.append(f"项目预算：{tender.budget}")

        if tender.contact_info.name or tender.contact_info.phone:
            c = f"联系人：{tender.contact_info.name}"
            if tender.contact_info.phone:
                c += f" ({tender.contact_info.phone})"
            parts.append(c)

        return "\n".join(parts)
