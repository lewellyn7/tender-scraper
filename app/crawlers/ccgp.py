"""重庆市政府采购网采集器 V3 - 继承 BaseCrawler
- 复用通用字段提取、日期解析、附件解析
- 三类信息：采购意向 / 采购公告 / 结果公告
"""

import asyncio
import re
from typing import List
from urllib.parse import urljoin

from loguru import logger

from app.crawlers.base import BaseCrawler
from app.models.tender import TenderInfo


class CCGPCrawlerV3(BaseCrawler):
    """重庆市政府采购网采集器 — 继承 BaseCrawler"""

    BASE_URL = "https://www.ccgp-chongqing.gov.cn"

    LIST_URLS = {
        "采购意向": "https://www.ccgp-chongqing.gov.cn/gkw/web/portal/intention/list",
        "采购公告": "https://www.ccgp-chongqing.gov.cn/gkw/web/portal/notice/list",
        "结果公告": "https://www.ccgp-chongqing.gov.cn/gkw/web/portal/result/list",
    }

    async def fetch_list(self, info_type: str = "采购公告", page_num: int = 1) -> List[TenderInfo]:
        """采集列表页"""
        results = []
        if info_type not in self.LIST_URLS:
            logger.error(f"❌ 不支持的信息类型: {info_type}")
            return results

        url = self.LIST_URLS[info_type]
        if page_num > 1:
            url = f"{url}?page={page_num}"

        page = None
        try:
            page = await self.browser.new_page()
            logger.info(f"📄 采集 [{info_type}] 列表 第{page_num}页: {url}")
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(2)

            selectors = [
                ".notice-item", ".list-item", ".item",
                "ul.list li", "table tr", ".data-list tr",
            ]
            items = []
            for selector in selectors:
                items = await page.query_selector_all(selector)
                if items:
                    logger.debug(f"使用选择器: {selector}, 找到 {len(items)} 项")
                    break

            if not items:
                items = await page.query_selector_all('a[href*="detail"], a[href*="view"]')

            for item in items:
                try:
                    tag = "A"
                    link_elem = item
                    try:
                        tag = await item.evaluate("el => el.tagName")
                        link_elem = await item.query_selector("a") if tag != "A" else item
                    except (AttributeError, TypeError):
                        # Mock 对象没有 evaluate 方法
                        pass
                    if not link_elem:
                        continue

                    href = await link_elem.get_attribute("href")
                    title = await link_elem.text_content()
                    if not href or not title:
                        continue

                    title = title.strip()
                    if len(title) < 5 or "javascript" in href.lower():
                        continue

                    try:
                        date_elem = await item.query_selector('.date, .time, [class*="date"], td:nth-child(2)')
                        date_text = (await date_elem.text_content()).strip() if date_elem else ""
                    except (AttributeError, TypeError):
                        date_text = ""

                    full_url = urljoin(self.BASE_URL, href)
                    if not await self._mark_visited(full_url):
                        continue

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
                    results.append(tender)
                except Exception as e:
                    logger.debug(f"提取列表项失败: {e}")
                    continue

            logger.info(f"✅ 列表页采集完成: {len(results)} 条")
            return results
        except Exception as e:
            logger.error(f"❌ 列表页采集失败: {e}")
            return results
        finally:
            await page.close()

    async def fetch_detail(self, tender: TenderInfo) -> TenderInfo:
        """采集详情页"""
        if not await self._mark_visited(tender.url):
            logger.info(f"⏭️ URL已采集，跳过：{tender.url}")
            return tender
        return await self._fetch_detail_page(tender)

    async def _fetch_detail_page(self, tender: TenderInfo) -> TenderInfo:
        """内部：采集单个详情页"""
        page = None
        try:
            page = await self.browser.new_page()
            logger.info(f"📄 采集详情: {tender.title[:40]}...")
            await page.goto(tender.url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(1)

            # 提取正文
            content_selectors = [
                ".content", ".article-content", ".detail-content",
                "#content", ".main-content", ".text-content",
                "article", ".body",
            ]
            for selector in content_selectors:
                elem = await page.query_selector(selector)
                if elem:
                    full = await elem.inner_text()
                    if len(full) > 50:
                        tender.full_content = full
                        tender.content_preview = full[:300] + "..." if len(full) > 300 else full
                        break

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

            # 生成摘要
            tender.project_overview = self._summarize_content(tender)
            return tender

        except Exception as e:
            logger.warning(f"⚠️ 详情页采集失败: {e}")
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
            tender.bidder_requirements = f"预计采购时间: {time_match.group(1).strip()}"

        needs_match = re.search(r"采购需求概况[：:]\s*([^\n]+(?:\n(?!采购)[^\n]+)*)", text)
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

        req_match = re.search(
            r"资格要求[：:]\s*([^\n]+)",
            text,
        )
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
            r"中标(?:[（(]?成交[）)?])?供应商[名称]*[：:]\s*([^\n]+)",
            r"中标人[：:]\s*([^\n]+)",
            r"成交供应商[：:]\s*([^\n]+)",
        ]
        for pattern in supplier_patterns:
            match = re.search(pattern, text)
            if match:
                tender.bidder_requirements = f"中标供应商: {match.group(1).strip()}"
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
        """智能总结采集内容"""
        parts = [f"【{tender.info_type}】{tender.title}"]

        if tender.info_type == "采购意向":
            if tender.budget:
                parts.append(f"预算: {tender.budget}")
            if tender.bidder_requirements:
                parts.append(tender.bidder_requirements)

        elif tender.info_type == "采购公告":
            if tender.project_overview:
                parts.append(f"项目概况: {tender.project_overview[:100]}")
            if tender.budget:
                parts.append(f"预算: {tender.budget}")
            if tender.submission_deadline:
                parts.append(f"截止时间: {tender.submission_deadline}")
            if tender.bidder_requirements:
                parts.append(f"资格要求: {tender.bidder_requirements[:100]}")

        elif tender.info_type == "结果公告":
            if tender.bidder_requirements:
                parts.append(tender.bidder_requirements)
            if tender.bid_amount:
                parts.append(f"中标金额: {tender.bid_amount}")
            if tender.budget:
                parts.append(f"项目预算: {tender.budget}")

        if tender.contact_info.name or tender.contact_info.phone:
            c = f"联系人: {tender.contact_info.name}"
            if tender.contact_info.phone:
                c += f" ({tender.contact_info.phone})"
            parts.append(c)

        return "\n".join(parts)
