"""重庆烟草采集器 (2026-07-06 新增)
============================================
来源：https://www.966599.com/c/4/ (重庆烟草网)

采集源策略:
- 列表页：/c/4/ (page 1), /c/4/N (page N≥2)
- 总页数：210 页
- 每页条数：15 条
- 详情页：/a/YYYYMMDD/{uuid}.html
- Cookie/UA: 需设 Chrome UA (站点拦截 bot)
- aiohttp 异步 HTTP (类似 fahcqmu 模式，不需 Playwright)
- BeautifulSoup 提取：ul.ul-news > li > a (SSR HTML)
- 正文提取：<p> 标签拼接

5 分类 + 关键词规则:
- 结果公示 (result_notice): 成交结果公告、谈判结果公示、中标候选人公示、中选结果公示、结果公告、结果公示表
- 采购公告 (purchase_notice): 采购公告、询价公告、采购邀请函、竞争性谈判公告、竞争谈判公告、公开招标公告
- 变更公告 (change_notice): 变更公示、变更补遗、澄清补遗、澄清说明
- 流标 (failed_notice): 流标公示、流标公示表、流标公告
- 招租公告 (rental_notice): 招租公告、招租结果公示

数据规模 (预计):
- 全量：210 页 × 15 条 = ~3150 条

启用方式:
- 作为 pipeline 的 source='cqyc' 分支调用
- 或直接：python -c "import asyncio; from app.crawlers.cqyc import CqycCrawler; asyncio.run(CqycCrawler().run())"

集成:
- 新表：projects_cqyc (migration 006)
- DB 方法：db.upsert_projects_cqyc(rows)
- 调度：pipeline.py 中加 source=='cqyc' 分支
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional as _Optional
from typing import List, Optional, Dict, Tuple
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

from app.models.tender import TenderInfo
from app.utils.clean_noise import make_content_preview

logger = logging.getLogger(__name__)


# ============================================================================
# 配置
# ============================================================================
BASE_URL = "https://www.966599.com"
LIST_BASE_PATH = "/c/4"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
# 翻页 safety 上限
MAX_PAGES = 210  # 固定 210 页
# 每页请求间隔 (防反爬)
PAGE_DELAY_SECONDS = 0.5


# ============================================================================
# 分类关键词 (按顺序匹配，先命中优先)
# ============================================================================
INFO_TYPE_KEYWORDS = {
    "result_notice": [
        # 2026-07-07 补充: 用户报 '成交结果公示' '中标候选人公示表' 被归 other
        # "成交结果公告" 已被命中, 但 "成交结果公示" / "中标候选人公示表" 漏匹配
        "中标候选人公示表",   # 用户明示 (含'表'后缀, 与'中标候选人公示'并存以保证命中)
        "中标候选人公示",     # 原有 (保持)
        "成交结果公示",       # 用户明示 (新增)
        "成交结果公告",       # 原有 (保持)
        "谈判结果公示",       # 原有 (保持)
        "中选人确认公示表",   # 类似 '中标候选人公示表' 模式 (新增)
        "中选结果公示",       # 原有 (保持)
        "结果公示表",         # 原有 (保持)
        "结果公告",           # 原有 (保持)
    ],
    "purchase_notice": [
        "采购公告", "询价公告", "采购邀请函", "竞争性谈判公告",
        "竞争谈判公告", "公开招标公告",
        "直接采购邀请",       # 用户明示 (新增)
    ],
    "change_notice": [
        # 2026-07-07 补充: 用户报 '变更公告' '暂停招投标活动的公告' 被归 other
        "变更公告",           # 用户明示 (新增)
        "暂停招投标活动的公告",  # 用户明示 (新增)
        "变更公示", "变更补遗", "澄清补遗", "澄清说明"
    ],
    "failed_notice": [
        "流标公示", "流标公示表", "流标公告"
    ],
    "rental_notice": [
        "招租公告", "招租结果公示"
    ],
}


def classify_by_title(title: str) -> str:
    """根据标题分类 (顺序匹配，先命中优先).

    Args:
        title: 项目标题

    Returns:
        info_type: result_notice / purchase_notice / change_notice / failed_notice / rental_notice / other
    """
    # 按顺序匹配
    for info_type, keywords in INFO_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in title:
                return info_type
    return "other"


def parse_date_from_url(url: str) -> Optional[date]:
    """从 URL 解析日期 /a/YYYYMMDD/{uuid}.html → date(YYYY, MM, DD).

    示例：/a/20260706/561b8310-...html → date(2026, 7, 6)
    """
    m = re.search(r"/a/(\d{4})(\d{2})(\d{2})/", url)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def build_list_url(page: int = 1) -> str:
    """构造列表页 URL.

    page=1 → /c/4/
    page=N (N≥2) → /c/4/N
    """
    if page <= 1:
        return f"{BASE_URL}{LIST_BASE_PATH}/"
    return f"{BASE_URL}{LIST_BASE_PATH}/{page}"


def build_doc_url(doc_path: str) -> str:
    """构造详情页 URL. doc_path 如 /a/20260706/uuid.html"""
    return f"{BASE_URL}{doc_path}"


# ============================================================================
# 采集器主体
# ============================================================================
class CqycCrawler:
    """重庆烟草采集器 (aiohttp, 不需 Playwright).

    用法:
        async with CqycCrawler() as crawler:
            items = await crawler.fetch_all_lists()  # 210 页全采
            details = await crawler.fetch_details_parallel(items, limit=300)
    """

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        delay: float = PAGE_DELAY_SECONDS,
        max_pages: int = MAX_PAGES,
    ):
        self._session = session
        self._owns_session = session is None
        self.delay = delay
        self.max_pages = max_pages

    async def __aenter__(self):
        if self._session is None:
            self._session = aiohttp.ClientSession(
                headers=DEFAULT_HEADERS,
                timeout=DEFAULT_TIMEOUT,
            )
        return self

    async def __aexit__(self, *exc):
        if self._owns_session and self._session:
            await self._session.close()

    # ─── HTTP ──────────────────────────────────────────────────────

    async def _get(self, url: str, retries: int = 3) -> str:
        """GET URL, 返回 HTML 文本.

        自动重试 (3 次), 网络错误不中断采集.
        """
        for attempt in range(retries):
            try:
                async with self._session.get(url) as resp:
                    resp.raise_for_status()
                    return await resp.text(encoding="utf-8")
            except Exception as e:
                if attempt == retries - 1:
                    logger.error(f"GET {url} 失败 (retries={retries}): {e}")
                    return ""
                await asyncio.sleep(1.0 * (attempt + 1))
        return ""

    # ─── 列表页采集 ──────────────────────────────────────────────────

    async def fetch_list_page(self, page: int = 1) -> List[TenderInfo]:
        """采集单个列表页."""
        url = build_list_url(page)
        html = await self._get(url)
        if not html:
            logger.warning(f"[cqyc] 列表页为空 page={page}")
            return []

        soup = BeautifulSoup(html, "html.parser")
        ul = soup.find("ul", class_="ul-news")
        if not ul:
            logger.warning(f"[cqyc] 未找到 ul.ul-news page={page}")
            return []

        items = []
        for li in ul.find_all("li", recursive=False):
            if li.get("class") and "line" in li.get("class"):
                continue  # 跳过分隔线
            a = li.find("a")
            date_span = li.find("span", class_="date")
            if not a or not a.get("href"):
                continue

            title = a.get_text(strip=True)
            doc_path = a["href"]
            doc_url = build_doc_url(doc_path)

            # 日期优先从 <span class="date"> 解析，fallback 从 URL 解析
            pub_date = None
            if date_span:
                date_str = date_span.get_text(strip=True)
                try:
                    pub_date = datetime.strptime(date_str, "%Y-%m-%d")
                except ValueError:
                    pd = parse_date_from_url(doc_url)
                    pub_date = datetime.combine(pd, datetime.min.time()) if pd else None
            else:
                pd = parse_date_from_url(doc_url)
                pub_date = datetime.combine(pd, datetime.min.time()) if pd else None

            # 分类
            info_type = classify_by_title(title)

            item = TenderInfo(
                url=doc_url,
                title=title,
                info_type=info_type,
                category="烟草采购",
                business_type="烟草采购",
                publish_date=pub_date,
                source_url=url,
            )
            items.append(item)

        logger.debug(f"[cqyc] page={page} 采集 {len(items)} 条")
        return items

    async def fetch_all_lists(self) -> List[TenderInfo]:
        """采集全部 210 页列表 (并行 + 延时控制).

        返回:
            List[TenderInfo]: 所有项目 (已按 URL 去重)
        """
        all_items: List[TenderInfo] = []
        seen_urls: set = set()

        for page in range(1, self.max_pages + 1):
            items = await self.fetch_list_page(page)
            for it in items:
                if it.url not in seen_urls:
                    seen_urls.add(it.url)
                    all_items.append(it)

            # 分页延迟 (防反爬)
            if page < self.max_pages:
                await asyncio.sleep(self.delay)

            # 提前终止：如果某页 < 15 条，可能是最后一页
            if len(items) < 15:
                logger.info(f"[cqyc] page={page} 只有 {len(items)} 条，提前终止")
                break

        logger.info(f"[cqyc] 全量列表采集完成：{len(all_items)} 条 / {self.max_pages} 页")
        return all_items

    # ─── 详情页采集 ──────────────────────────────────────────────────

    async def fetch_detail(self, item: TenderInfo) -> TenderInfo:
        """采集单条详情."""
        html = await self._get(item.url)
        if not html:
            logger.warning(f"[cqyc] 详情页为空 {item.url}")
            return item

        soup = BeautifulSoup(html, "html.parser")

        # 提取正文：<p> 标签拼接
        paragraphs = soup.find_all("p")
        content_parts = []
        for p in paragraphs:
            text = p.get_text(strip=True)
            if text and len(text) > 5:  # 过滤空/太短段落
                content_parts.append(text)

        full_content = "\n".join(content_parts)
        content_preview = make_content_preview(full_content or item.title, item.title)

        item.full_content = full_content
        item.content_preview = content_preview

        # 提取预算 (如有)
        budget_match = re.search(r"(?:预算|金额|限价)[：:]\s*([￥¥]?[\d,\.]+ 万?元?)", full_content)
        if budget_match:
            item.budget = budget_match.group(1)

        # 提取项目编号 (如有)
        proj_no_match = re.search(r"(?:项目编号|招标编号)[：:]\s*([A-Z0-9\-]+)", full_content)
        if proj_no_match:
            item.project_no = proj_no_match.group(1)

        # 提取联系人/电话/邮箱
        contact_name_match = re.search(r"联系人 [：:]\s*(\S+)", full_content)
        contact_phone_match = re.search(r"电话 [：:]\s*(\S+)", full_content)
        contact_email_match = re.search(r"邮箱 [：:]\s*(\S+)", full_content)
        # TenderInfo.contact_info 是 ContactInfo 子对象, 7-06 修复
        if contact_name_match:
            item.contact_info.name = contact_name_match.group(1)
        if contact_phone_match:
            item.contact_info.phone = contact_phone_match.group(1)
        if contact_email_match:
            item.contact_info.email = contact_email_match.group(1)

        logger.debug(f"[cqyc] 详情采集完成 {item.url[:60]}... 正文 {len(full_content)} chars")
        return item

    async def fetch_details_parallel(
        self, items: List[TenderInfo], limit: int = 300, concurrency: int = 5
    ) -> List[TenderInfo]:
        """并发采集详情 (限 limit 条).

        Args:
            items: 待采集列表
            limit: 采集上限 (默认 300)
            concurrency: 并发数 (默认 5)

        Returns:
            List[TenderInfo]: 已采集详情的项目
        """
        targets = items[:limit]
        logger.info(f"[cqyc] 并发采集详情 {len(targets)} 条 (concurrency={concurrency})")

        semaphore = asyncio.Semaphore(concurrency)

        async def _fetch_with_semaphore(it: TenderInfo) -> TenderInfo:
            async with semaphore:
                return await self.fetch_detail(it)

        tasks = [_fetch_with_semaphore(it) for it in targets]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        detailed = []
        for it, res in zip(targets, results):
            if isinstance(res, Exception):
                logger.warning(f"[cqyc] 详情采集失败 {it.url}: {res}")
                detailed.append(it)
            else:
                detailed.append(res)

        ok_count = sum(1 for it in detailed if it.full_content)
        logger.info(f"[cqyc] 详情完成：{ok_count}/{len(detailed)} 有正文")
        return detailed

    # ─── 封装运行 ────────────────────────────────────────────────────

    async def run(self, detail_limit: int = 300) -> dict:
        """运行完整采集流程.

        Returns:
            dict: {total, filtered, detailed, ok_count}
        """
        logger.info("=" * 60)
        logger.info("🚬 重庆烟草采集 (966599.com)")
        logger.info(f"   列表页：{self.max_pages} 页预计 ~{self.max_pages * 15} 条")
        logger.info(f"   详情上限：{detail_limit} 条")
        logger.info("=" * 60)

        async with self:
            # 列表阶段
            all_items = await self.fetch_all_lists()
            logger.info(f"📥 列表合计 (去重后): {len(all_items)} 条")

            if not all_items:
                logger.warning("⚠️ 未采集到任何数据")
                return {"total": 0, "filtered": 0, "detailed": 0, "ok_count": 0}

            # 详情阶段
            detailed = await self.fetch_details_parallel(all_items, limit=detail_limit)
            ok_count = sum(1 for it in detailed if it.full_content)

            return {
                "total": len(all_items),
                "filtered": len(all_items),  # 暂不过滤关键词
                "detailed": len(detailed),
                "ok_count": ok_count,
            }