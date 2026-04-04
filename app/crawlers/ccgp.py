"""重庆市政府采购网采集器 V3 - 支持内容智能总结"""

import asyncio
import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin

from loguru import logger

from app.core.browser import StealthBrowser
from app.models.tender import ContactInfo, TenderAttachment, TenderInfo


class CCGPCrawlerV3:
    """重庆市政府采购网采集器 V3 - 三类信息 + 内容总结"""

    BASE_URL = "https://www.ccgp-chongqing.gov.cn"

    # 三类信息列表页 URL
    LIST_URLS = {
        "采购意向": "https://www.ccgp-chongqing.gov.cn/gkw/web/portal/intention/list",
        "采购公告": "https://www.ccgp-chongqing.gov.cn/gkw/web/portal/notice/list",
        "结果公告": "https://www.ccgp-chongqing.gov.cn/gkw/web/portal/result/list",
    }

    # 信息类型关键词映射
    INFO_TYPE_KEYWORDS = {
        "采购意向": ["采购意向", "采购计划", "预算"],
        "采购公告": ["采购公告", "招标公告", "竞争性谈判", "询价公告", "单一来源"],
        "结果公告": ["结果公告", "中标公告", "成交公告", "中标结果"],
    }

    def __init__(self, browser: StealthBrowser):
        self.browser = browser
        self.version = "ccgp-crawler v3.0"

    async def fetch_list(self, info_type: str = "采购公告", page_num: int = 1) -> List[TenderInfo]:
        """采集列表页"""
        results = []

        if info_type not in self.LIST_URLS:
            logger.error(f"❌ 不支持的信息类型: {info_type}")
            return results

        url = self.LIST_URLS[info_type]
        if page_num > 1:
            url = f"{url}?page={page_num}"

        try:
            page = await self.browser.new_page()
            logger.info(f"📄 采集 [{info_type}] 列表 第{page_num}页: {url}")

            await page.goto(url, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(2)

            # 尝试多种选择器
            selectors = [
                ".notice-item",
                ".list-item",
                ".item",
                "ul.list li",
                "table tr",
                ".data-list tr",
            ]

            items = []
            for selector in selectors:
                items = await page.query_selector_all(selector)
                if items:
                    logger.debug(f"使用选择器: {selector}, 找到 {len(items)} 项")
                    break

            if not items:
                # 尝试获取所有链接
                items = await page.query_selector_all('a[href*="detail"], a[href*="view"]')

            for item in items:
                try:
                    # 提取标题和链接
                    link_elem = (
                        await item.query_selector("a")
                        if item.evaluate("el => el.tagName") != "A"
                        else item
                    )
                    if not link_elem:
                        continue

                    href = await link_elem.get_attribute("href")
                    title = await link_elem.text_content()

                    if not href or not title:
                        continue

                    title = title.strip()
                    if len(title) < 5 or "javascript" in href.lower():
                        continue

                    # 提取日期
                    date_text = ""
                    date_elem = await item.query_selector(
                        '.date, .time, span[class*="date"], td:nth-child(2)'
                    )
                    if date_elem:
                        date_text = await date_elem.text_content()

                    # 构建完整 URL
                    full_url = urljoin(self.BASE_URL, href)

                    # 创建数据对象
                    tender = TenderInfo(
                        title=title,
                        url=full_url,
                        business_type="政府采购",
                        info_type=info_type,
                        source_url=url,
                        publish_date_raw=date_text.strip(),
                        tender_type=info_type,
                        scraped_by=self.version,
                    )

                    # 解析日期
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
        """采集详情页 + 内容总结"""
        try:
            page = await self.browser.new_page()
            logger.info(f"📄 采集详情: {tender.title[:40]}...")

            await page.goto(tender.url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(1)

            # 提取正文内容
            content_selectors = [
                ".content",
                ".article-content",
                ".detail-content",
                "#content",
                ".main-content",
                ".text-content",
                "article",
                ".body",
            ]

            full_content = ""
            for selector in content_selectors:
                content_elem = await page.query_selector(selector)
                if content_elem:
                    full_content = await content_elem.inner_text()
                    if len(full_content) > 50:
                        break

            tender.full_content = full_content
            tender.content_preview = (
                full_content[:300] + "..." if len(full_content) > 300 else full_content
            )

            # 根据信息类型提取关键字段
            if tender.info_type == "采购意向":
                tender = await self._extract_intention_fields(page, tender)
            elif tender.info_type == "采购公告":
                tender = await self._extract_notice_fields(page, tender)
            elif tender.info_type == "结果公告":
                tender = await self._extract_result_fields(page, tender)

            # 提取联系人信息
            tender.contact_info = await self._extract_contact_info(page)

            # 提取附件
            tender.attachments = await self._extract_attachments(page)

            # 生成内容总结
            tender.project_overview = self._summarize_content(tender)

            return tender

        except Exception as e:
            logger.warning(f"⚠️ 详情页采集失败: {e}")
            return tender
        finally:
            await page.close()

    async def _extract_intention_fields(self, page, tender: TenderInfo) -> TenderInfo:
        """提取采购意向专用字段"""
        try:
            text = await page.inner_text("body")

            # 采购项目名称
            name_match = re.search(r"采购项目[名称]*[：:]\s*([^\n]+)", text)
            if name_match:
                tender.title = name_match.group(1).strip()

            # 预算金额
            budget_patterns = [
                r"预算金额[：:]\s*([\d,\.]+)\s*(万元|元)",
                r"采购预算[：:]\s*([\d,\.]+)\s*(万元|元)",
            ]
            for pattern in budget_patterns:
                match = re.search(pattern, text)
                if match:
                    tender.budget = f"{match.group(1)}{match.group(2)}"
                    break

            # 预计采购时间
            time_match = re.search(r"预计采购时间[：:]\s*([^\n]+)", text)
            if time_match:
                tender.bidder_requirements = f"预计采购时间: {time_match.group(1).strip()}"

            # 采购需求概况
            needs_match = re.search(r"采购需求概况[：:]\s*([^\n]+(?:\n(?!采购)[^\n]+)*)", text)
            if needs_match:
                tender.project_overview = needs_match.group(1).strip()

        except Exception as e:
            logger.debug(f"提取采购意向字段失败: {e}")

        return tender

    async def _extract_notice_fields(self, page, tender: TenderInfo) -> TenderInfo:
        """提取采购公告专用字段"""
        try:
            text = await page.inner_text("body")

            # 项目概况
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

            # 预算金额
            budget_patterns = [
                r"预算金额[：:]\s*([\d,\.]+)\s*(万元|元)",
                r"采购预算[：:]\s*([\d,\.]+)\s*(万元|元)",
                r"项目预算[：:]\s*([\d,\.]+)\s*(万元|元)",
            ]
            for pattern in budget_patterns:
                match = re.search(pattern, text)
                if match:
                    tender.budget = f"{match.group(1)}{match.group(2)}"
                    break

            # 投标人资格要求
            req_match = re.search(
                r"供应商[（(]?投标人[）)?]?[的]?资格要求[：:]\s*([^\n]+(?:\n(?!三|四|五|六|七|八)[^\n]+)*)",
                text,
            )
            if req_match:
                tender.bidder_requirements = req_match.group(1).strip()[:500]

            # 投标截止时间
            deadline_patterns = [
                r"投标截止时间[：:]\s*([^\n]+)",
                r"提交投标文件截止时间[：:]\s*([^\n]+)",
                r"截止时间[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?\s*\d{1,2}[:时]\d{1,2}分?)",
            ]
            for pattern in deadline_patterns:
                match = re.search(pattern, text)
                if match:
                    tender.submission_deadline = match.group(1).strip()
                    tender.deadline = self._parse_datetime(match.group(1))
                    break

            # 开标时间
            opening_match = re.search(r"开标时间[：:]\s*([^\n]+)", text)
            if opening_match:
                tender.opening_date = self._parse_datetime(opening_match.group(1))

        except Exception as e:
            logger.debug(f"提取采购公告字段失败: {e}")

        return tender

    async def _extract_result_fields(self, page, tender: TenderInfo) -> TenderInfo:
        """提取结果公告专用字段"""
        try:
            text = await page.inner_text("body")

            # 中标供应商
            supplier_patterns = [
                r"中标[（(]?成交[）)?]?供应商[名称]*[：:]\s*([^\n]+)",
                r"中标人[：:]\s*([^\n]+)",
                r"成交供应商[：:]\s*([^\n]+)",
            ]
            for pattern in supplier_patterns:
                match = re.search(pattern, text)
                if match:
                    tender.bidder_requirements = f"中标供应商: {match.group(1).strip()}"
                    break

            # 中标金额
            amount_patterns = [
                r"中标金额[：:]\s*([\d,\.]+)\s*(万元|元)",
                r"成交金额[：:]\s*([\d,\.]+)\s*(万元|元)",
                r"合同金额[：:]\s*([\d,\.]+)\s*(万元|元)",
            ]
            for pattern in amount_patterns:
                match = re.search(pattern, text)
                if match:
                    tender.bid_amount = f"{match.group(1)}{match.group(2)}"
                    break

            # 项目预算
            budget_patterns = [
                r"预算金额[：:]\s*([\d,\.]+)\s*(万元|元)",
                r"项目预算[：:]\s*([\d,\.]+)\s*(万元|元)",
            ]
            for pattern in budget_patterns:
                match = re.search(pattern, text)
                if match:
                    tender.budget = f"{match.group(1)}{match.group(2)}"
                    break

            # 公告日期
            date_match = re.search(r"公告日期[：:]\s*([^\n]+)", text)
            if date_match:
                tender.publish_date_raw = date_match.group(1).strip()

        except Exception as e:
            logger.debug(f"提取结果公告字段失败: {e}")

        return tender

    async def _extract_contact_info(self, page) -> ContactInfo:
        """提取联系人信息"""
        contact = ContactInfo()
        try:
            text = await page.inner_text("body")

            # 联系人
            name_patterns = [
                r"联系人[：:]\s*([^\s\n,，/]+)",
                r"项目联系人[：:]\s*([^\s\n,，/]+)",
            ]
            for pattern in name_patterns:
                match = re.search(pattern, text)
                if match:
                    contact.name = match.group(1).strip()
                    break

            # 电话
            phone_patterns = [
                r"联系电话[：:]\s*([\d\-]+)",
                r"电话[：:]\s*([\d\-]+)",
                r"手机[：:]\s*([\d\-]+)",
            ]
            for pattern in phone_patterns:
                match = re.search(pattern, text)
                if match:
                    contact.phone = match.group(1).strip()
                    break

            # 地址
            addr_match = re.search(r"地址[：:]\s*([^\n]+)", text)
            if addr_match:
                contact.address = addr_match.group(1).strip()

        except Exception as e:
            logger.debug(f"提取联系人失败: {e}")

        return contact

    async def _extract_attachments(self, page) -> List[TenderAttachment]:
        """提取附件列表"""
        attachments = []
        try:
            links = await page.query_selector_all(
                'a[href$=".pdf"], a[href$=".doc"], a[href$=".docx"], a[href$=".xls"], a[href$=".xlsx"]'
            )
            for link in links:
                name = await link.inner_text()
                href = await link.get_attribute("href")
                if href and name:
                    full_url = urljoin(self.BASE_URL, href)
                    file_type = href.split(".")[-1].upper()
                    attachments.append(
                        TenderAttachment(name=name.strip(), url=full_url, file_type=file_type)
                    )
        except Exception as e:
            logger.debug(f"提取附件失败: {e}")
        return attachments

    def _summarize_content(self, tender: TenderInfo) -> str:
        """智能总结采集内容"""
        summary_parts = []

        # 基本信息
        summary_parts.append(f"【{tender.info_type}】{tender.title}")

        # 根据类型生成不同摘要
        if tender.info_type == "采购意向":
            if tender.budget:
                summary_parts.append(f"预算: {tender.budget}")
            if tender.bidder_requirements:
                summary_parts.append(tender.bidder_requirements)

        elif tender.info_type == "采购公告":
            if tender.project_overview:
                summary_parts.append(f"项目概况: {tender.project_overview[:100]}")
            if tender.budget:
                summary_parts.append(f"预算: {tender.budget}")
            if tender.submission_deadline:
                summary_parts.append(f"截止时间: {tender.submission_deadline}")
            if tender.bidder_requirements:
                summary_parts.append(f"资格要求: {tender.bidder_requirements[:100]}")

        elif tender.info_type == "结果公告":
            if tender.bidder_requirements:
                summary_parts.append(tender.bidder_requirements)
            if tender.bid_amount:
                summary_parts.append(f"中标金额: {tender.bid_amount}")
            if tender.budget:
                summary_parts.append(f"项目预算: {tender.budget}")

        # 联系方式
        if tender.contact_info.name or tender.contact_info.phone:
            contact_str = f"联系人: {tender.contact_info.name}"
            if tender.contact_info.phone:
                contact_str += f" ({tender.contact_info.phone})"
            summary_parts.append(contact_str)

        return "\n".join(summary_parts)

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """解析日期"""
        if not date_str:
            return None

        date_str = re.sub(r"[\[\]]", "", date_str).strip()
        formats = ["%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"]

        for fmt in formats:
            try:
                return datetime.strptime(date_str[:10], fmt)
            except Exception:
                continue

        match = re.search(r"(\d{4}-\d{2}-\d{2})", date_str)
        if match:
            try:
                return datetime.strptime(match.group(1), "%Y-%m-%d")
            except Exception:
                pass

        return None

    def _parse_datetime(self, datetime_str: str) -> Optional[datetime]:
        """解析日期时间"""
        if not datetime_str:
            return None

        datetime_str = re.sub(r"[年月]", "-", datetime_str)
        datetime_str = re.sub(r"[日]", " ", datetime_str)

        formats = [
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(datetime_str[:16], fmt)
            except Exception:
                continue

        return None

    async def close(self):
        """关闭浏览器"""
        await self.browser.close()
