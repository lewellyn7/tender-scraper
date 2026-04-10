"""爬虫基类 - 所有爬虫的父类 V2

职责：
- 定义爬虫抽象接口
- 提供通用工具方法（字段提取、日期解析、附件解析）
- 所有具体爬虫必须继承此类
"""

import asyncio
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional, Set, Tuple
from urllib.parse import urljoin

from loguru import logger

from app.core.browser import StealthBrowser
from app.models.tender import ContactInfo, TenderAttachment, TenderInfo


class BaseCrawler(ABC):
    """爬虫基类 V2 — 统一接口 + 通用工具"""

    BASE_URL: str = ""

    def __init__(self, browser: StealthBrowser):
        self.browser = browser
        self.version = "tender-scraper v3.2"
        self._visited_urls: Set[str] = set()
        self._visited_lock = asyncio.Lock()

    # ─── URL 去重 ────────────────────────────────────────────────

    async def _mark_visited(self, url: str) -> bool:
        """标记 URL 为已访问，返回是否是新 URL（线程安全）"""
        async with self._visited_lock:
            if url in self._visited_urls:
                return False
            self._visited_urls.add(url)
            return True

    # ─── 公共字段提取 ────────────────────────────────────────────

    async def _extract_field(self, page, patterns: List[str], default: str = "") -> str:
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
        self, page, keywords: List[str], max_len: int = 200, context_chars: int = 100
    ) -> str:
        """按关键词提取字段，返回含关键词的行片段"""
        try:
            text = await page.inner_text("body")
            for kw in keywords:
                idx = text.find(kw)
                if idx >= 0:
                    snippet = text[idx: idx + context_chars].split("\n")[0].strip()
                    if len(snippet) > 20:
                        return snippet[:max_len]
        except Exception:
            pass
        return ""

    async def _extract_contact_info(self, page) -> ContactInfo:
        """提取联系人信息（通用实现）"""
        contact = ContactInfo()
        try:
            text = await page.inner_text("body")

            name_patterns = [
                r"联系人[：:]\s*([^\s\n,，/]+)",
                r"联\s*系\s*人[：:]\s*([^\s\n,，/]+)",
                r"项目联系人[：:]\s*([^\s\n,，/]+)",
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
                r"手机[：:]\s*([\d\-]+)",
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
                logger.debug(f"  ✅ 联系人: {contact.name} ({contact.phone})")
        except Exception as e:
            logger.debug(f"  ⚠️ 提取联系人失败: {e}")
        return contact

    async def _extract_attachments(self, page) -> List[TenderAttachment]:
        """提取附件列表（通用实现）"""
        attachments = []
        try:
            links = await page.query_selector_all(
                'a[href$=".pdf"], a[href$=".doc"], a[href$=".docx"], '
                'a[href$=".xls"], a[href$=".xlsx"], a[href$=".zip"]'
            )
            for link in links[:10]:
                href = await link.get_attribute("href")
                name = await link.text_content()
                if href and name:
                    if not href.startswith("http"):
                        href = urljoin(self.BASE_URL, href) if href.startswith("/") \
                            else f"{self.BASE_URL}/{href}"
                    attachments.append(
                        TenderAttachment(
                            name=name.strip(),
                            url=href,
                            file_type=href.rsplit(".", 1)[-1].lower() if "." in href else "unknown",
                        )
                    )
            if attachments:
                logger.debug(f"  ✅ 附件: {len(attachments)} 个")
        except Exception as e:
            logger.debug(f"  ⚠️ 提取附件失败: {e}")
        return attachments

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """解析日期字符串为 datetime（通用实现）"""
        if not date_str:
            return None
        date_str = re.sub(r"[\[\]]", "", date_str).strip()
        formats = [
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y年%m月%d日",
            "%Y.%m.%d",
        ]
        for fmt in formats:
            # Slice date_str to match format length; Chinese format needs full string
            date_part = date_str if '年' in fmt else date_str[:10]
            try:
                return datetime.strptime(date_part, fmt)
            except Exception:
                pass
        match = re.search(r"(\d{4}-\d{2}-\d{2})", date_str)
        if match:
            try:
                return datetime.strptime(match.group(1), "%Y-%m-%d")
            except Exception:
                pass
        return None

    def _parse_datetime(self, datetime_str: str) -> Optional[datetime]:
        """解析日期时间字符串（通用实现）"""
        if not datetime_str:
            return None
        # Normalize Chinese datetime: 2024年05月10日 14时30分 -> 2024-05-10 14:30:00
        s = re.sub(r'[年]', '-', datetime_str)
        s = re.sub(r'[月]', '-', s)
        s = re.sub(r'[日]', ' ', s)
        s = re.sub(r'[时]', ':', s)
        s = re.sub(r'[分]', '', s)
        # Clean up any double spaces/dots
        s = re.sub(r'\s+', ' ', s).strip()
        formats = [
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                pass
        return None

    async def _extract_budget(self, page) -> str:
        """提取预算金额（通用实现）"""
        return await self._extract_field(page, [
            r"预算金额[：:]\s*([\d,\.]+)\s*(?:万元|元)",
            r"采购预算[：:]\s*([\d,\.]+)\s*(?:万元|元)",
            r"项目预算[：:]\s*([\d,\.]+)\s*(?:万元|元)",
            r"最高限价[：:]\s*([\d,\.]+)\s*(?:万元|元)",
        ])

    async def _extract_deadline(self, page) -> Tuple[str, Optional[datetime]]:
        """提取截止时间（通用实现），返回 (原始文本, datetime)"""
        raw = await self._extract_field(page, [
            r"投标截止时间[：:]*\s*([^\n]+)",
            r"截止时间[：:]*\s*([^\n]+)",
            r"投标文件递交截止时间[：:]*\s*([^\n]+)",
            r"截止日期[：:]*\s*([^\n]+)",
            r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?\s*\d{1,2}[:时]\d{1,2}分?)",
        ])
        dt = self._parse_datetime(raw) if raw else None
        return raw, dt

    async def _extract_bid_amount(self, page) -> str:
        """提取中标金额（通用实现）"""
        return await self._extract_field(page, [
            r"中标金额[：:]\s*([\d,\.]+)\s*(?:万元|元)",
            r"成交金额[：:]\s*([\d,\.]+)\s*(?:万元|元)",
            r"合同金额[：:]\s*([\d,\.]+)\s*(?:万元|元)",
        ])

    # ─── 批量采集 ────────────────────────────────────────────────

    async def fetch_details_batch(
        self,
        tenders: List[TenderInfo],
        max_concurrent: int = 5,
        callback=None,
    ) -> List[TenderInfo]:
        """批量采集详情页（并行，信号量控制并发）"""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _bounded_fetch(idx: int, t: TenderInfo) -> Tuple[int, TenderInfo]:
            async with semaphore:
                try:
                    return idx, await self.fetch_detail(t)
                except Exception as e:
                    logger.error(f"采集失败: {t.title[:30]} - {e}")
                    return idx, t

        tasks = [_bounded_fetch(i, t) for i, t in enumerate(tenders)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        ordered = []
        for r in results:
            if isinstance(r, tuple):
                ordered.append(r)
            elif isinstance(r, Exception):
                logger.warning(f"批次采集异常: {r}")

        ordered.sort(key=lambda x: x[0])
        if callback:
            for i, _ in enumerate(ordered):
                callback(i + 1, len(ordered))
        return [r for _, r in ordered]

    async def _fetch_with_retry(
        self, tender: TenderInfo, max_retries: int = 2
    ) -> TenderInfo:
        """带指数退避重试的详情页采集"""
        for attempt in range(max_retries):
            try:
                return await self.fetch_detail(tender)
            except Exception:
                if attempt == max_retries - 1:
                    raise
                wait_time = 2 ** attempt
                logger.warning(f"重试 {attempt + 1}/{max_retries}: {tender.title[:30]}...")
                await asyncio.sleep(wait_time)
        return tender

    # ─── 抽象接口（子类必须实现） ─────────────────────────────────

    @abstractmethod
    async def fetch_list(self, **kwargs) -> List[TenderInfo]:
        """采集列表页"""
        pass

    @abstractmethod
    async def fetch_detail(self, tender: TenderInfo) -> TenderInfo:
        """采集详情页"""
        pass
