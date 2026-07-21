"""重医附一院采集器 (2026-06-25 新增)
============================================
来源: https://www.fahcqmu.cn (重庆医科大学附属第一医院)

采集源策略:
- 7 个分类, 翻页方式: URL + '/p/N' 后缀 (/p/1 ~ /p/N, 0 items 停止)
- Cookie: 必须设 Cookie: visited=1 (否则详情页返 1.3KB shell)
- aiohttp 异步 HTTP (类似 cqggzy_curl 模式, 不需 Playwright)
- BeautifulSoup 提取: 列表 li > a (SSR HTML), 详情 div.news-content

7 分类 + 数据规模 (首次全量):
- 信息数据处 (xxsjc1):
  - 阳光推介 ygtjgg /p/1-2   → 24 条
  - 调研公告 dygg   /p/1-11  → 154 条
  - 采购公告 cggg   /p/1     → 3 条
  - 采购结果 cgjggs /p/1     → 5 条
- 总务处 (cgglczb2):
  - 采购公告 cggg   /p/1-47  → 702 条 ⭐
  - 采购结果 jggs   /p/1-51  → 763 条 ⭐
- 其他 (qt):
  - qt             /p/1-2    → 16 条
- 合计: 1667 条

启用方式:
- 作为 pipeline 的 source='fahcqmu' 分支调用
- 或直接: python -c "import asyncio; from app.crawlers.fahcqmu import FahcqmuCrawler; asyncio.run(FahcqmuCrawler().run())"

集成 (PR #39):
- 新表: projects_fahcqmu (migration 003)
- DB 方法: db.upsert_projects_fahcqmu(rows)
- 调度: pipeline.py 中加 source=='fahcqmu' 分支
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, date
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
BASE_URL = "https://www.fahcqmu.cn"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
# 关键: 不设此 cookie, 详情页返 1.3KB shell; 列表页 /p/N 也需要
COOKIE_VISITED = "visited=1"
# 翻页 safety 上限
MAX_PAGES_PER_CAT = 100
# 每页请求间隔 (防反爬)
PAGE_DELAY_SECONDS = 0.3


@dataclass
class CategoryConfig:
    """一个采集分类的配置."""
    info_type: str           # 写入 TenderInfo.info_type (ygtjgg/dygg/cggg/cgjggs/jggs/qt)
    org_unit: str            # 信息数据处 / 总务处 / 其他
    url_path: str            # URL 路径 (不含 base)
    description: str = ""


# 7 分类配置
CATEGORIES: List[CategoryConfig] = [
    # 信息数据处
    CategoryConfig("ygtjgg", "信息数据处", "gzb_cgxx_xxsjc1_ygtjgg", "阳光推介公告"),
    CategoryConfig("dygg",   "信息数据处", "gzb_cgxx_xxsjc1_dygg",   "调研公告"),
    CategoryConfig("cggg",   "信息数据处", "gzb_cgxx_xxsjc1_cggg",   "采购公告"),
    CategoryConfig("cgjggs", "信息数据处", "gzb_cgxx_xxsjc1_cgjggs", "采购结果公告"),
    # 总务处
    CategoryConfig("cggg",   "总务处",     "gw_yygg_zbgg_cgglczb2_cgxx_cggg", "采购公告"),
    CategoryConfig("jggs",   "总务处",     "gw_yygg_zbgg_cgglczb2_cgxx_jggs", "采购结果公告"),
    # 其他
    CategoryConfig("qt",     "其他",       "gzb_cgxx_qt", "其他公告"),
]


# ============================================================================
# 工具函数
# ============================================================================
def infer_org_unit(url: str) -> str:
    """从 URL 推断 org_unit (信息数据处 / 总务处 / 其他).

    规则:
    - 含 'xxsjc1' → 信息数据处
    - 含 'cgglczb2' → 总务处
    - 含 '_qt' → 其他
    """
    if "xxsjc1" in url:
        return "信息数据处"
    if "cgglczb2" in url:
        return "总务处"
    if "_qt" in url or url.endswith("/qt") or "/qt/" in url:
        return "其他"
    return "其他"


def infer_info_type(url: str) -> str:
    """从 URL 路径推断 info_type."""
    if "ygtjgg" in url:
        return "ygtjgg"
    if "cgjggs" in url:
        return "cgjggs"
    if "jggs" in url:
        return "jggs"
    if "_cggg" in url or url.endswith("/cggg"):
        return "cggg"
    if "dygg" in url:
        return "dygg"
    if "_qt" in url or url.endswith("/qt") or "/qt/" in url:
        return "qt"
    return "其他"


def parse_date_dot(text: str) -> Optional[date]:
    """解析 'YYYY.MM.DD' 格式日期.

    示例: '2026.06.18' → date(2026, 6, 18)
    """
    text = (text or "").strip()
    m = re.match(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})$", text)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def build_doc_url(base_path: str, doc_id: str) -> str:
    """构造详情页 URL. doc_id 是不带 .html 的 15 位数字."""
    return f"{BASE_URL}/{base_path}/{doc_id}.html"


def build_list_url(base_path: str, page: int = 1) -> str:
    """构造列表页 URL. page=1 等同 base (无 /p/1 后缀)."""
    if page <= 1:
        return f"{BASE_URL}/{base_path}"
    return f"{BASE_URL}/{base_path}/p/{page}"


# ============================================================================
# 采集器主体
# ============================================================================
class FahcqmuCrawler:
    """重医附一院采集器 (aiohttp, 不需 Playwright).

    用法:
        async with FahcqmuCrawler() as crawler:
            items = await crawler.fetch_all_lists()           # 7 类全采
            details = await crawler.fetch_details_parallel(items, limit=200)
    """

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        delay: float = PAGE_DELAY_SECONDS,
        max_pages: int = MAX_PAGES_PER_CAT,
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
                cookies={"visited": "1"},  # 默认 cookie
            )
        return self

    async def __aexit__(self, *exc):
        if self._owns_session and self._session:
            await self._session.close()

    # ─── HTTP ──────────────────────────────────────────────────────

    async def _get(self, url: str, retries: int = 3) -> str:
        """GET URL, 返回 HTML 文本. 始终带 visited=1 cookie.
        
        3.3 fix: 添加 retry(3), 网络错误不中断采集.
        """
        if self._session is None:
            raise RuntimeError("Use 'async with' or pass session")
        last_err = None
        for attempt in range(retries):
            try:
                async with self._session.get(url) as resp:
                    resp.raise_for_status()
                    return await resp.text()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_err = e
                if attempt < retries - 1:
                    await asyncio.sleep(1.0 * (attempt + 1))  # 递增退避
                    continue
        raise last_err  # type: ignore[misc]

    # ─── 列表解析 ──────────────────────────────────────────────────

    def _parse_list_html(self, html: str, cat: CategoryConfig) -> List[TenderInfo]:
        """解析列表页 HTML, 提取 TenderInfo 列表.

        HTML 结构 (实测):
        <li>
          <a href=".../<doc_id>.html">
            <i class="iconfont">&#xe620;</i>
            <p><span>title</span></p>
            <span class="time">2026.06.18</span>
          </a>
        </li>

        空页 fallback: ~46KB HTML 但无 li > a (返回空列表).
        """
        items: List[TenderInfo] = []
        soup = BeautifulSoup(html, "html.parser")
        # 找所有 li > a (内含 iconfont/title/time)
        for li in soup.find_all("li"):
            a = li.find("a", href=True)
            if not a:
                continue
            href = a["href"]
            # 必须是本站的详情 URL
            if not href.endswith(".html"):
                continue
            # 提取 doc_id (15 位数字, 含 .html 后缀)
            m = re.search(r"/(\d{15})\.html$", href)
            if not m:
                continue
            doc_id = m.group(1)
            detail_url = href if href.startswith("http") else f"{BASE_URL}{href}"

            # title
            title_span = li.find("span", class_=None) or li.find("p")
            title = title_span.get_text(strip=True) if title_span else ""
            # time (class="time")
            time_span = li.find("span", class_="time")
            time_text = time_span.get_text(strip=True) if time_span else ""

            # 推断字段
            org_unit = infer_org_unit(detail_url)
            info_type = cat.info_type if cat else infer_info_type(detail_url)
            publish_date = parse_date_dot(time_text)

            item = TenderInfo(
                title=title,
                url=detail_url,
                publish_date=publish_date,
                publish_date_raw=time_text,
                info_type=info_type,
                business_type="医院采购",
                category=cat.description if cat else "医院采购",
                source_url=f"{BASE_URL}/{cat.url_path}" if cat else "",
            )
            # 加 org_unit 到 TenderInfo (自定义属性, 在 upsert 时提取)
            item._org_unit = org_unit  # type: ignore[attr-defined]
            item._doc_id = doc_id  # type: ignore[attr-defined]
            items.append(item)
        return items

    # ─── 详情解析 ──────────────────────────────────────────────────

    def _parse_detail_html(
        self,
        html: str,
        item: TenderInfo,
    ) -> TenderInfo:
        """解析详情页 HTML, 填充 item.full_content / content_preview."""
        soup = BeautifulSoup(html, "html.parser")

        # 主内容 div.news-content
        news_div = soup.find("div", class_=re.compile(r"news-content"))
        if news_div:
            # 清理 script/style
            for tag in news_div.find_all(["script", "style"]):
                tag.decompose()
            text = news_div.get_text(separator="\n", strip=True)
            # 清理多余空白
            text = re.sub(r"\n{3,}", "\n\n", text)
            text = re.sub(r"[ \t]+", " ", text)
            item.full_content = text.strip()

        # content_preview (签名: make_content_preview(full_content, title, max_len=500))
        if item.full_content:
            item.content_preview = make_content_preview(
                item.full_content, item.title or "", max_len=300
            )

        # 标题: <h1> 或 <title>
        h1 = soup.find("h1")
        if h1:
            h1_text = h1.get_text(strip=True)
            if h1_text:
                item.title = h1_text
        if not item.title or item.title == "":
            title_tag = soup.find("title")
            if title_tag:
                t = title_tag.get_text(strip=True)
                # 去除 "-重庆医科大学附属第一医院" 后缀
                t = re.sub(r"-重庆医科大学附属第一医院$", "", t).strip()
                if t:
                    item.title = t

        # 发布时间: span.time (在详情页也存在)
        if not item.publish_date:
            time_span = soup.find("span", class_="time")
            if time_span:
                t = time_span.get_text(strip=True)
                d = parse_date_dot(t)
                if d:
                    item.publish_date = d
                    item.publish_date_raw = t

        return item

    # ─── 公开 API ──────────────────────────────────────────────────

    async def fetch_list_page(
        self,
        cat: CategoryConfig,
        page: int = 1,
    ) -> List[TenderInfo]:
        """采集单页列表. 返回本页 items.

        page=1 等同 base URL (无 /p/1 后缀).
        空页: 返回 [] (调用方应停止翻页).
        3.3 fix: retry(3) 后仍失败才返回 []; 单页失败不中断整类翻页.
        """
        url = build_list_url(cat.url_path, page)
        try:
            html = await self._get(url, retries=3)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.warning(f"[{cat.info_type}] page={page} GET {url} 3次重试后仍失败: {e}")
            return []  # 不中止翻页, 跳过此页继续
        # 检测 shell (1.3KB 无 news-content)
        if "<html" in html and len(html) < 3000:
            logger.warning(f"[{cat.info_type}] page={page} got shell (size={len(html)}), cookie 失效?")
            return []
        items = self._parse_list_html(html, cat)
        if self.delay > 0 and items:
            await asyncio.sleep(self.delay)
        return items

    async def fetch_all_pages(self, cat: CategoryConfig) -> List[TenderInfo]:
        """循环 /p/1..N 直到空页. 返回该分类所有 items."""
        all_items: List[TenderInfo] = []
        for page in range(1, self.max_pages + 1):
            items = await self.fetch_list_page(cat, page)
            if not items:
                logger.info(f"[{cat.info_type}] 翻页结束 at /p/{page}")
                break
            all_items.extend(items)
            logger.info(f"[{cat.info_type}] /p/{page}: +{len(items)} 条 (累计 {len(all_items)})")
        return all_items

    async def fetch_all_lists(
        self,
        categories: Optional[List[CategoryConfig]] = None,
    ) -> List[TenderInfo]:
        """采集所有 7 个分类的列表, 并行执行."""
        cats = categories or CATEGORIES
        tasks = [self.fetch_all_pages(cat) for cat in cats]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_items: List[TenderInfo] = []
        for cat, result in zip(cats, results):
            if isinstance(result, Exception):
                logger.error(f"[{cat.info_type}] 采集失败: {result}")
                continue
            all_items.extend(result)
            logger.info(f"[{cat.info_type}] 合计 {len(result)} 条")
        # URL 去重
        seen = set()
        unique = []
        for item in all_items:
            if item.url not in seen:
                seen.add(item.url)
                unique.append(item)
        logger.info(f"全部分类合计: {len(all_items)} 条 → 去重后 {len(unique)} 条")
        return unique

    async def fetch_detail(self, item: TenderInfo) -> TenderInfo:
        """采集单个详情页. 3.3 fix: 加 retry(3)."""
        try:
            html = await self._get(item.url, retries=3)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.warning(f"详情页 GET {item.url} 3次重试后仍失败: {e}")
            return item
        if len(html) < 3000:
            logger.warning(f"详情页 {item.url} 返回 shell (size={len(html)})")
            return item
        return self._parse_detail_html(html, item)

    async def fetch_details_parallel(
        self,
        items: List[TenderInfo],
        concurrency: int = 5,
    ) -> List[TenderInfo]:
        """并发采集详情. 默认 5 路并发 (防反爬)."""
        sem = asyncio.Semaphore(concurrency)

        async def _one(item: TenderInfo) -> TenderInfo:
            async with sem:
                result = await self.fetch_detail(item)
                if self.delay > 0:
                    await asyncio.sleep(self.delay)
                return result

        tasks = [_one(item) for item in items]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: List[TenderInfo] = []
        for item, result in zip(items, results):
            if isinstance(result, Exception):
                logger.warning(f"详情 {item.url} 失败: {result}")
                out.append(item)  # 保留原 item (至少有 title/date)
            else:
                out.append(result)
        return out


# ============================================================================
# DB 写入辅助
# ============================================================================

# 3.7 fix: 从 tender_to_db_row 内部函数上提到模块级 (避免每次调用重定义)
def _s(v):
    """安全处理 None / 空值."""
    return v if v else ""


def tender_to_db_row(item: TenderInfo, org_unit: str) -> Dict:
    """将 TenderInfo 转换为 projects_fahcqmu upsert 字典."""

    publish_date = item.publish_date
    if isinstance(publish_date, date) and not isinstance(publish_date, datetime):
        publish_date_str = publish_date.isoformat()
    elif isinstance(publish_date, datetime):
        publish_date_str = publish_date.date().isoformat()
    else:
        publish_date_str = None

    return {
        "url": item.url,
        "title": _s(item.title),
        "category": _s(item.category) or "医院采购",
        "info_type": _s(item.info_type),
        "business_type": _s(item.business_type) or "医院采购",
        "org_unit": org_unit,
        "publish_date": publish_date_str,
        "publish_date_raw": _s(item.publish_date_raw),
        "content_preview": _s(item.content_preview),
        "full_content": _s(item.full_content),
        "source_url": _s(item.source_url),
        "scraped_at": datetime.now().isoformat(),
        "scraped_by": "tender-scraper v3.2 fahcqmu",
        # 其他字段保持空 (ccgp/cqggzy 表也有大量空字段, 这是常态)
    }


def collect_org_unit(item: TenderInfo) -> str:
    """从 TenderInfo 提取 org_unit (由 _parse_list_html 注入到 _org_unit)."""
    return getattr(item, "_org_unit", "") or infer_org_unit(item.url)


# ============================================================================
# 入口 (CLI 调试用)
# ============================================================================
async def _run_smoke():
    """冒烟测试: 采集 1 个分类 + 1 个详情."""
    async with FahcqmuCrawler() as crawler:
        cat = CATEGORIES[0]  # ygtjgg 阳光推介
        logger.info(f"=== 冒烟测试 {cat.info_type} ===")
        items = await crawler.fetch_list_page(cat, page=1)
        logger.info(f"列表: {len(items)} 条")
        if items:
            first = items[0]
            logger.info(f"第一条: {first.title[:50]}")
            logger.info(f"  url: {first.url}")
            logger.info(f"  date: {first.publish_date}")
            detailed = await crawler.fetch_detail(first)
            logger.info(f"详情 fc len: {len(detailed.full_content)}")
            logger.info(f"  cp: {detailed.content_preview[:80]}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    asyncio.run(_run_smoke())
