"""重庆市公共资源交易网采集器 V3 - 继承 BaseCrawler
- 复用通用字段提取、日期解析、附件解析
- URL 缓存避免重复采集
- 并行采集列表页 + 详情页
"""

import asyncio
import random
from typing import List

from loguru import logger

from app.crawlers.base import BaseCrawler
from app.database import get_db
from app.models.tender import TenderInfo
from app.utils.project_linker import normalize_project_name, extract_project_no


class CQGGZYCrawlerV2(BaseCrawler):
    """重庆市公共资源交易网采集器 — 继承 BaseCrawler"""

    BASE_URL = "https://www.cqggzy.com"
    GOV_PURCHASE_URL = "https://www.cqggzy.com/xxhz/014005/order.html"
    ENGINEERING_URL = "https://www.cqggzy.com/xxhz/014001/bidding.html"

    async def fetch_list(
        self, category: str = "gov_purchase", page_num: int = 1
    ) -> List[TenderInfo]:
        """采集单个列表页"""
        return await self._fetch_list_page(category, page_num)

    async def fetch_lists_parallel(
        self, category: str = "gov_purchase", pages: List[int] = None
    ) -> List[TenderInfo]:
        """并行采集多个列表页"""
        if pages is None:
            pages = list(range(1, 6))
        tasks = [self._fetch_list_page(category, p) for p in pages]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_items = []
        for r in results:
            if isinstance(r, list):
                all_items.extend(r)
            elif isinstance(r, Exception):
                logger.warning(f"列表页采集异常: {r}")
        logger.info(f"✅ 并行列表页采集完成：{len(all_items)} 条")
        return all_items

    async def _fetch_list_page(self, category: str, page_num: int) -> List[TenderInfo]:
        """内部：采集单个列表页"""
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

                    date_elem = await item.query_selector('[class*="date"], span')
                    date_text = await date_elem.text_content() if date_elem else ""
                    full_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"

                    if not await self._mark_visited(full_url, source="cqggzy"):
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
                    if date_text:
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
        """采集详情页"""
        if not await self._mark_visited(tender.url, source="cqggzy"):
            logger.info(f"⏭️ URL已采集，跳过：{tender.url}")
            return tender
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
            tender.project_overview = await self._extract_field_by_kw(
                page, ["项目概况"], max_len=300
            )
            tender.bidder_requirements = await self._extract_field_by_kw(
                page, ["投标人资格要求", "供应商资格要求", "资格条件"]
            )
            tender.submission_deadline = await self._extract_field_by_kw(
                page, ["投标文件递交截止时间", "递交截止时间", "投标截止时间"]
            )
            tender.bid_amount = self._extract_bid_amount(page)
            tender.project_no = extract_project_no(tender.title, tender.full_content or "")
            tender.project_name = normalize_project_name(tender.title)

            # 写入 projects 表
            try:
                db = get_db()
                project_id = db.upsert_project(
                    project_name=tender.project_name,
                    project_name_raw=tender.project_name,
                    project_no=tender.project_no or "",
                    business_type=tender.business_type or "",
                    region=tender.region or "",
                    industry="",
                    budget=tender.budget or "",
                )
                if project_id > 0:
                    db.add_project_record(
                        project_id=project_id,
                        record_url=tender.url,
                        record_type=tender.info_type or "",
                        title=tender.title,
                        publish_date=tender.publish_date or "",
                        budget=tender.budget or "",
                    )
            except Exception as e:
                logger.warning(f"⚠️ 写入 projects 表失败: {e}")

            logger.info("  ✅ 详情页采集完成")
            return tender
        except Exception as e:
            logger.warning(f"⚠️ 详情页采集失败 {tender.url}: {e}")
            return tender
        finally:
            if page:
                await page.close()

    async def _extract_content(self, page, tender: TenderInfo) -> None:
        """提取正文内容"""
        selectors = [
            ".content", ".article", ".detail-content", "#content",
            ".main-content", ".text-content", ".news-content",
            ".TREmpty", ".zw_c", ".con_r",
        ]
        for selector in selectors:
            try:
                elem = await page.query_selector(selector)
                if elem:
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
                       "您当前的位置", "版权所有", "技术支持", "ICP备"]
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

    async def _extract_info_type(self, page) -> str:
        """提取信息类型"""
        try:
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
                    logger.debug(f"  ✅ 信息类型: {itype}")
                    return itype
        except Exception:
            pass
        return "招标公告"

    # ─── 工具方法 ────────────────────────────────────────────────

    async def _smart_wait(self) -> None:
        """智能随机等待 (0.3-0.8s)"""
        await asyncio.sleep(0.3 + random.random() * 0.5)
