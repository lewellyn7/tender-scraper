"""爬虫基类 - 所有爬虫的父类"""

import asyncio
from abc import ABC, abstractmethod
from typing import List, Optional

from loguru import logger

from app.core.browser import StealthBrowser
from app.models.tender import TenderInfo


class BaseCrawler(ABC):
    """爬虫基类"""

    BASE_URL: str = ""

    def __init__(self, browser: StealthBrowser):
        self.browser = browser
        self.version = "tender-scraper v3.1"

    @abstractmethod
    async def fetch_list(self, **kwargs) -> List[TenderInfo]:
        """采集列表页 - 子类必须实现"""
        pass

    @abstractmethod
    async def fetch_detail(self, tender: TenderInfo) -> TenderInfo:
        """采集详情页 - 子类必须实现"""
        pass

    async def fetch_details_batch(
        self, tenders: List[TenderInfo], max_concurrent: int = 5, callback=None
    ) -> List[TenderInfo]:
        """批量采集详情页 (并行)

        Args:
            tenders: 招标项目列表
            max_concurrent: 最大并发数
            callback: 进度回调函数

        Returns:
            更新后的项目列表
        """
        results = []
        total = len(tenders)

        # 分批处理
        for i in range(0, total, max_concurrent):
            batch = tenders[i : i + max_concurrent]
            tasks = [self._fetch_with_retry(t) for t in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for j, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    logger.error(f"采集失败: {batch[j].title[:30]} - {result}")
                    results.append(batch[j])  # 保留原始数据
                else:
                    results.append(result)

                if callback:
                    callback(i + j + 1, total)

        return results

    async def _fetch_with_retry(self, tender: TenderInfo, max_retries: int = 2) -> TenderInfo:
        """带重试的详情页采集"""
        for attempt in range(max_retries):
            try:
                return await self.fetch_detail(tender)
            except Exception:
                if attempt == max_retries - 1:
                    raise
                wait_time = 2**attempt  # 指数退避
                logger.warning(f"重试 {attempt + 1}/{max_retries}: {tender.title[:30]}...")
                await asyncio.sleep(wait_time)

        return tender

    def _parse_date(self, date_str: str) -> Optional[str]:
        """解析日期字符串"""
        import re

        patterns = [
            r"(\d{4})-(\d{1,2})-(\d{1,2})",
            r"(\d{4})/(\d{1,2})/(\d{1,2})",
            r"(\d{4})(\d{2})(\d{2})",
        ]

        for pattern in patterns:
            match = re.search(pattern, date_str)
            if match:
                try:
                    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
                except Exception:
                    continue

        return None
