"""重庆市公共资源交易网采集器 V3 - 优化版
- URL 缓存避免重复采集
- 并行采集列表页 (asyncio.gather)
- 并行采集详情页 (concurrency=5)
- 公共提取逻辑减少重复代码
- 智能随机等待 (0.3-0.8s)
"""

import asyncio
import random
import re
from typing import List, Set

from loguru import logger

from app.core.browser import StealthBrowser
from app.models.tender import ContactInfo, TenderAttachment, TenderInfo


class CQGGZYCrawlerV2:
    """重庆市公共资源交易网采集器 V3 - 优化版"""

    BASE_URL = "https://www.cqggzy.com"
    GOV_PURCHASE_URL = "https://www.cqggzy.com/xxhz/014005/order.html"
    ENGINEERING_URL = "https://www.cqggzy.com/xxhz/014001/bidding.html"

    def __init__(self, browser: StealthBrowser):
        self.browser = browser
        self.version = "tender-scraper v3.1"
        # URL 缓存集合，避免重复采集
        self._visited_urls: Set[str] = set()
        self._visited_lock = asyncio.Lock()

    # ─── 智能等待 ────────────────────────────────────────────────

    async def _smart_wait(self):
        """智能随机等待 (0.3-0.8s)"""
        await asyncio.sleep(0.3 + random.random() * 0.5)

    # ─── URL 去重 ────────────────────────────────────────────────

    async def _mark_visited(self, url: str) -> bool:
        """标记 URL 为已访问，返回是否是新 URL"""
        async with self._visited_lock:
            if url in self._visited_urls:
                return False
            self._visited_urls.add(url)
            return True

    # ─── 公共提取逻辑 ────────────────────────────────────────────

    async def _extract_field(self, page, patterns: list, default: str = "") -> str:
        """通用字段提取：尝试多个正则模式，返回第一个匹配"""
        try:
            text = await page.inner_text("body")
            for pattern in patterns:
                match = re.search(pattern, text)
                if match:
                    return match.group(1).strip() if match.groups() else match.group(0).strip()
        except Exception:
            pass
        return default

    async def _extract_field_by_kw(
        self, page, keywords: list, max_len: int = 200, context_chars: int = 100
    ) -> str:
        """按关键词提取字段，返回含关键词的行片段"""
        try:
            text = await page.inner_text("body")
            for kw in keywords:
                if kw in text:
                    idx = text.find(kw)
                    snippet = text[idx : idx + context_chars].split("\n")[0].strip()
                    if len(snippet) > 20:
                        return snippet[:max_len]
        except Exception:
            pass
        return ""

    async def _extract_multi_field(self, page, fields: list) -> dict:
        """批量提取多个字段 (name, patterns/default) -> value"""
        result = {}
        for name, patterns_or_kw in fields.items():
            if isinstance(patterns_or_kw, list):
                result[name] = await self._extract_field(page, patterns_or_kw)
            else:
                result[name] = patterns_or_kw
        return result

    # ─── 并行采集列表页 ──────────────────────────────────────────

    async def fetch_list(
        self, category: str = "gov_purchase", page_num: int = 1
    ) -> List[TenderInfo]:
        """采集单个列表页（保持签名兼容）"""
        return await self._fetch_list_page(category, page_num)

    async def fetch_lists_parallel(
        self, category: str = "gov_purchase", pages: list = None
    ) -> List[TenderInfo]:
        """并行采集多个列表页（新增）"""
        if pages is None:
            pages = list(range(1, 6))  # 默认采集前5页
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

                    # URL 去重检查
                    if not await self._mark_visited(full_url):
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

    # ─── 并行采集详情页 ──────────────────────────────────────────

    async def fetch_detail(self, tender: TenderInfo) -> TenderInfo:
        """采集详情页（保持签名兼容，内部增加 URL 去重）"""
        # URL 去重检查
        if not await self._mark_visited(tender.url):
            logger.info(f"⏭️  URL已采集，跳过：{tender.url}")
            return tender
        return await self._fetch_detail_page(tender)

    async def fetch_details_parallel(
        self, tenders: List[TenderInfo], concurrency: int = 5
    ) -> List[TenderInfo]:
        """并行采集多个详情页（新增，concurrency=5）"""
        semaphore = asyncio.Semaphore(concurrency)

        async def _bounded_fetch(t: TenderInfo) -> TenderInfo:
            async with semaphore:
                return await self.fetch_detail(t)

        tasks = [asyncio.create_task(_bounded_fetch(t)) for t in tenders]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed = []
        for r in results:
            if isinstance(r, TenderInfo):
                processed.append(r)
            elif isinstance(r, Exception):
                logger.warning(f"详情页采集异常: {r}")

        logger.info(f"✅ 并行详情页采集完成：{len(processed)} 条")
        return processed

    async def _fetch_detail_page(self, tender: TenderInfo) -> TenderInfo:
        """内部：采集单个详情页"""
        page = None
        try:
            page = await self.browser.new_page()
            logger.info(f"📄 采集详情页：{tender.title[:30]}...")

            await page.goto(tender.url, wait_until="networkidle", timeout=30000)
            await self._smart_wait()

            # 提取正文内容
            content_selectors = [
                ".content",
                ".article",
                ".detail-content",
                "#content",
                ".main-content",
                ".text-content",
                ".news-content",
                ".TREmpty",
                ".zw_c",
                ".con_r",
                "body",
            ]

            for selector in content_selectors:
                try:
                    content_elem = await page.query_selector(selector)
                    if content_elem:
                        full_content = await content_elem.inner_text()
                        if selector == "body":
                            lines = full_content.split("\n")
                            content_lines = []
                            in_content = False
                            for line in lines:
                                line = line.strip()
                                if any(
                                    skip in line
                                    for skip in [
                                        "首 页",
                                        "重要通知",
                                        "交易信息",
                                        "当前访问",
                                        "收藏",
                                        "您当前的位置",
                                        "版权所有",
                                        "技术支持",
                                        "ICP备",
                                    ]
                                ):
                                    continue
                                if "项目" in line or "采购" in line or "招标" in line:
                                    in_content = True
                                if in_content and len(line) > 20:
                                    content_lines.append(line)
                            full_content = "\n".join(content_lines)

                        if len(full_content) > 20:
                            tender.full_content = full_content
                            tender.content_preview = (
                                full_content[:500] + "..."
                                if len(full_content) > 500
                                else full_content
                            )
                            logger.info(f"  ✅ 正文提取成功 ({len(full_content)} 字)")
                            break
                except Exception:
                    continue

            # 批量提取各字段（利用公共提取逻辑）
            tender.contact_info = await self._extract_contact_info(page)
            tender.budget = await self._extract_field(
                page,
                [
                    r"预算金额[：: ]*([\d,\.]+)\s*(?:万元|元)",
                    r"采购预算[：: ]*([\d,\.]+)\s*(?:万元|元)",
                    r"项目预算[：: ]*([\d,\.]+)\s*(?:万元|元)",
                    r"最高限价[：: ]*([\d,\.]+)\s*(?:万元|元)",
                ],
            )
            tender.deadline = await self._extract_field(
                page,
                [
                    r"投标截止时间[：: ]*(\d{4}年\d{1,2}月\d{1,2}日[^\n]*)",
                    r"截止时间[：: ]*(\d{4}年\d{1,2}月\d{1,2}日[^\n]*)",
                    r"投标文件递交截止时间[：: ]*(\d{4}年\d{1,2}月\d{1,2}日[^\n]*)",
                    r"截止日期[：: ]*(\d{4}年\d{1,2}月\d{1,2}日[^\n]*)",
                    r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s*\d{1,2}:\d{1,2})",
                ],
            )
            tender.attachments = await self._extract_attachments(page)
            tender.region = await self._extract_region(page)
            tender.business_type = await self._extract_business_type(page)
            tender.info_type = await self._extract_info_type(page)
            tender.project_overview = await self._extract_field_by_kw(page, ["项目概况"])
            tender.bidder_requirements = await self._extract_field_by_kw(
                page, ["投标人资格要求", "供应商资格要求", "资格条件"]
            )
            tender.submission_deadline = await self._extract_field_by_kw(
                page, ["投标文件递交截止时间", "递交截止时间", "投标截止时间"]
            )
            tender.bid_amount = await self._extract_field(
                page,
                [
                    r"中标金额[：: ]*([\d,\.]+)\s*(?:万元|元)",
                    r"中标价[：: ]*([\d,\.]+)\s*(?:万元|元)",
                    r"成交金额[：: ]*([\d,\.]+)\s*(?:万元|元)",
                ],
            )

            logger.info("  ✅ 详情页采集完成")
            return tender
        except Exception as e:
            logger.warning(f"⚠️ 详情页采集失败 {tender.url}: {e}")
            return tender
        finally:
            if page:
                await page.close()

    # ─── 提取方法（精简，使用公共提取逻辑） ──────────────────────────

    async def _extract_contact_info(self, page) -> ContactInfo:
        """提取联系人信息"""
        contact = ContactInfo()
        try:
            text = await page.inner_text("body")

            name_patterns = [
                r"联系人[：:]\s*([^\s\n,，]+)",
                r"联 系 人[：:]\s*([^\s\n,，]+)",
                r"项目联系人[：:]\s*([^\s\n,，]+)",
            ]
            for pattern in name_patterns:
                match = re.search(pattern, text)
                if match:
                    contact.name = match.group(1).strip()
                    break

            phone_patterns = [
                r"电话[：:]\s*([\d\-]+)",
                r"联系电话[：:]\s*([\d\-]+)",
                r"联系方式[：:]\s*([\d\-]+)",
                r"Tel[：:]\s*([\d\-]+)",
            ]
            for pattern in phone_patterns:
                match = re.search(pattern, text)
                if match:
                    contact.phone = match.group(1).strip()
                    break

            email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", text)
            if email_match:
                contact.email = email_match.group(0)

            addr_patterns = [
                r"地址[：:]\s*([^\n]+?)(?=\s*(?:电话|联系|邮编|$))",
                r"联系地址[：:]\s*([^\n]+)",
            ]
            for pattern in addr_patterns:
                match = re.search(pattern, text)
                if match:
                    contact.address = match.group(1).strip()
                    break

            if contact.name or contact.phone:
                logger.info(f"  ✅ 联系人: {contact.name} ({contact.phone})")
        except Exception as e:
            logger.warning(f"  ⚠️ 提取联系人失败：{e}")
        return contact

    async def _extract_attachments(self, page) -> List[TenderAttachment]:
        """提取附件列表"""
        attachments = []
        try:
            link_elements = await page.query_selector_all(
                'a[href$=".pdf"], a[href$=".doc"], a[href$=".docx"], a[href$=".xls"], a[href$=".xlsx"]'
            )
            for link in link_elements[:10]:
                href = await link.get_attribute("href")
                text = await link.text_content()
                if href and text:
                    if not href.startswith("http"):
                        href = (
                            f"{self.BASE_URL}{href}"
                            if href.startswith("/")
                            else f"{self.BASE_URL}/{href}"
                        )
                    attachments.append(
                        TenderAttachment(
                            name=text.strip(),
                            url=href,
                            file_type=href.split(".")[-1] if "." in href else "unknown",
                        )
                    )
            if attachments:
                logger.info(f"  ✅ 附件: {len(attachments)} 个")
        except Exception as e:
            logger.warning(f"  ⚠️ 提取附件失败：{e}")
        return attachments

    async def _extract_region(self, page) -> str:
        """提取所属区域"""
        try:
            text = await page.inner_text("body")
            districts = [
                "渝中区",
                "大渡口区",
                "江北区",
                "沙坪坝区",
                "九龙坡区",
                "南岸区",
                "北碚区",
                "渝北区",
                "巴南区",
                "万州区",
                "涪陵区",
                "永川区",
                "合川区",
                "江津区",
                "綦江区",
                "长寿区",
                "大足区",
                "璧山区",
                "铜梁区",
                "潼南区",
                "荣昌区",
                "黔江区",
                "两江新区",
            ]
            for district in districts:
                if district in text:
                    logger.info(f"  ✅ 区域: {district}")
                    return district
        except Exception as e:
            logger.warning(f"  ⚠️ 提取区域失败：{e}")
        return "重庆市"

    async def _extract_business_type(self, page) -> str:
        """提取业务类型"""
        try:
            url = page.url
            text = await page.inner_text("body")
            if "014005" in url or "order" in url:
                return "政府采购"
            elif "014001" in url or "bidding" in url:
                return "工程招投标"
            elif "采购" in text[:500]:
                return "政府采购"
            elif "招标" in text[:500]:
                return "工程招投标"
        except Exception as e:
            logger.warning(f"  ⚠️ 提取业务类型失败：{e}")
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
                    logger.info(f"  ✅ 信息类型: {itype}")
                    return itype
        except Exception as e:
            logger.warning(f"  ⚠️ 提取信息类型失败：{e}")
        return "招标公告"

    def _parse_date(self, date_text: str) -> str:
        """解析日期文本"""
        try:
            patterns = [
                (r"\[(\d{4}-\d{2}-\d{2})\]", "%Y-%m-%d"),
                (r"(\d{4}年\d{1,2}月\d{1,2}日)", "%Y年%m月%d日"),
                (r"(\d{4}-\d{1,2}-\d{1,2})", "%Y-%m-%d"),
                (r"(\d{4}/\d{1,2}/\d{1,2})", "%Y/%m/%d"),
            ]
            for pattern, fmt in patterns:
                match = re.search(pattern, date_text)
                if match:
                    date_str = match.group(1)
                    if "年" in date_str:
                        date_str = date_str.replace("年", "-").replace("月", "-").replace("日", "")
                    return date_str
        except Exception:
            logger.warning(f"  ⚠️ 解析日期失败：{date_text}")
        return ""
