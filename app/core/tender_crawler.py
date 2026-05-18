"""
招标信息爬虫能力模块
=====================
记录各目标网站的抓取方法、认证方式、选择器策略。

网站能力一览：
┌─────────────────────────────────────────┬──────────┬──────────────┬──────────────┐
│ 网站                                     │ 状态    │ 抓取方式      │ 认证方式       │
├─────────────────────────────────────────┼──────────┼──────────────┼──────────────┤
│ 重庆公共资源交易网 cqggzy.com            │ ✅ 可用  │ Playwright   │ Cookie/Session│
│ 中国政府采购网 ccgp.gov.cn                │ ✅ 可用  │ aiohttp      │ 无需认证       │
│ 重庆市政府采购网 ccgp-chongqing.gov.cn    │ ⚠️ 受限  │ Playwright   │ Cookie/Session│
│ 国家招标投标公共服务平台 cebpubservice.com│ ❌ 待测  │ -            │ -             │
│ 招标投标公共服务平台(重庆) cqggzy.com     │ ⚠️ 受限  │ Playwright   │ Cookie/Session│
└─────────────────────────────────────────┴──────────┴──────────────┴──────────────┘
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional, TYPE_CHECKING
from urllib.parse import urljoin
import hashlib

from loguru import logger

try:
    import aiohttp
except ImportError:
    aiohttp = None

try:
    import httpx
except ImportError:
    httpx = None

try:
    from playwright.sync_api import sync_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


# ─── 网站配置 ───────────────────────────────────────────────────────────────

SITES: List[Dict] = [
    {
        "id": "cqggzy",
        "name": "重庆公共资源交易网",
        "domain": "cqggzy.com",
        "status": "active",  # ✅ 可用
        "method": "playwright",  # Playwright 渲染
        "auth": "cookie",  # 需要先获取 Cookie
        "entry_url": "https://www.cqggzy.com/xxhz/transaction_detail.html",
        "list_urls": [
            # 工程招投标
            "https://www.cqggzy.com/xxhz/zbgg_list.html",      # 招标公告
            "https://www.cqggzy.com/xxhz/zbsx_list.html",      # 招标计划
            "https://www.cqggzy.com/xxhz/zbgg_list.html",      # 中标结果公示
            "https://www.cqggzy.com/xxhz/zzgg_list.html",      # 终止公告
            # 政府采购
            "https://www.cqggzy.com/xxhz/cggg_list.html",      # 采购公告
            "https://www.cqggzy.com/xxhz/cgjg_list.html",      # 采购结果公告
            "https://www.cqggzy.com/xxhz/dybg_list.html",      # 答疑变更
        ],
        "selectors": {
            "list_item": "a[href]",
            "title_kws": ["招标", "公告", "采购", "工程", "结果", "成交", "投标", "中标", "需求", "竞争", "计划", "变更", "答疑"],
            "url_kws": ["zbxx", "zbcg", "xxgg", "jgj", "cjgg", "cggg", "zhaobiao", "cgjy", "dybg", "zzgg"],
            "exclude_kws": ["#", "javascript", "void", "cookie"],
        },
        "pagination": "page_param",
        "pagination_param": "?pageNum={n}",
        "scroll_trigger": True,
        "wait_time": 5,
        "tender_type_rules": [
            # 工程招投标
            ("招标计划", ["计划", "需求预告"]),
            ("招标公告", ["招标", "公告", "工程", "投标"]),
            ("中标结果公示", ["中标", "结果公示", "成交", "结果"]),
            ("终止公告", ["终止", "废标", "流标"]),
            # 政府采购
            ("采购公告", ["采购公告", "采购", "需求"]),
            ("采购结果公告", ["采购结果", "成交", "结果公告"]),
            ("答疑变更", ["答疑", "变更", "澄清"]),
        ],
        "cookies_file": "/tmp/cookies_ggzy.json",
    },
    {
        "id": "ccgp_national",
        "name": "中国政府采购网",
        "domain": "ccgp.gov.cn",
        "status": "active",  # ✅ 可用
        "method": "aiohttp",  # 直接异步 HTTP
        "auth": "none",
        "entry_url": "http://www.ccgp.gov.cn/",
        "list_urls": [
            "http://www.ccgp.gov.cn/",
        ],
        "selectors": {
            "list_item": "a",
            "title_kws": ["招标", "公告", "采购", "工程", "结果", "成交", "投标", "中标", "竞争"],
            "url_kws": ["notice", "zbxx", "zbcg", "cggg", "zfcg"],
            "exclude_kws": ["#", "javascript"],
        },
        "pagination": "none",
        "scroll_trigger": False,
        "wait_time": 0,
        "tender_type_rules": [
            ("中标结果", ["结果", "成交", "中标"]),
            ("政府采购", ["采购", "需求", "竞争"]),
            ("招标公告", ["招标", "公告"]),
        ],
        "cookies_file": None,
        # 令牌桶限速：每秒 5 个请求
        "rate_limit": 5.0,
    },
    {
        "id": "ccgp_chongqing",
        "name": "重庆市政府采购网",
        "domain": "ccgp-chongqing.gov.cn",
        "status": "limited",  # ⚠️ 受限 - CloudFlare 防爬
        "method": "playwright",
        "auth": "cookie",
        "entry_url": "https://www.ccgp-chongqing.gov.cn/",
        "list_urls": [
            "https://www.ccgp-chongqing.gov.cn/info-notice/notice-list",
            "https://www.ccgp-chongqing.gov.cn/info-notice/intention-list",
        ],
        "selectors": {
            "list_item": "a[href]",
            "title_kws": ["招标", "公告", "采购", "工程", "结果"],
            "url_kws": [],
            "exclude_kws": ["#", "javascript", "void"],
        },
        "pagination": "next_button",
        "scroll_trigger": True,
        "wait_time": 8,
        "tender_type_rules": [
            ("中标结果", ["结果", "成交", "中标"]),
            ("政府采购", ["采购"]),
            ("招标公告", ["招标", "公告"]),
        ],
        "cookies_file": "/tmp/cookies_ccgp_chongqing.json",
        "note": "列表页返回空白，需 CloudFlare 绕过或代理池",
    },
]


# ─── Token Bucket Rate Limiter ───────────────────────────────────────────────

class TokenBucket:
    """令牌桶：支持突发流量，但长期速率不超过 bucket_size / refill_period."""

    def __init__(self, rate: float, burst: float = None):
        self.rate = rate  # tokens per second
        self.burst = burst or rate * 2  # max tokens (burst size)
        self.tokens = self.burst
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0):
        """等待直到获取到 tokens."""
        async with self._lock:
            while True:
                self._refill()
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return
                # 计算还差多少tokens
                deficit = tokens - self.tokens
                wait_time = deficit / self.rate
                await asyncio.sleep(min(wait_time, 1.0))

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        refill_amount = elapsed * self.rate
        self.tokens = min(self.burst, self.tokens + refill_amount)
        self.last_refill = now


# ─── Async Crawler Session ───────────────────────────────────────────────────

class AsyncCrawlerSession:
    """
    异步 HTTP 采集 Session，基于 aiohttp。

    特性：
    - aiohttp ClientSession（连接池复用）
    - DNS 缓存（TCPConnector）
    - 令牌桶限速
    - 智能重试（按异常类型分类）
    """

    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    def __init__(
        self,
        rate_limit: float = 5.0,
        burst: float = None,
        timeout: int = 15,
        max_retries: int = 3,
        connector_limit: int = 20,
    ):
        if not aiohttp:
            raise ImportError("aiohttp is required for AsyncCrawlerSession")

        self.rate_limit = rate_limit
        self.bucket = TokenBucket(rate_limit, burst)
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.max_retries = max_retries
        self.connector_limit = connector_limit
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> "aiohttp.ClientSession":
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=self.connector_limit,  # 连接池大小
                limit_per_host=10,
                enable_cleanup_closed=True,
                # DNS 缓存默认开启（aiohttp 使用 asyncio.default_event_loop 的 Resolver）
            )
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=self.timeout,
                headers=self.DEFAULT_HEADERS,
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def fetch(
        self, url: str, headers: Dict = None, retry_count: int = None
    ) -> Tuple[str, int]:
        """
        获取页面 HTML。
        返回 (html_text, status_code)。
        """
        if retry_count is None:
            retry_count = self.max_retries

        session = await self._get_session()
        extra_headers = dict(headers) if headers else {}

        for attempt in range(retry_count):
            try:
                await self.bucket.acquire(1.0)
                async with session.get(url, headers=extra_headers, allow_redirects=True) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        return text, resp.status
                    elif resp.status in (429, 502, 503, 504):
                        # Rate-limit / server error — 重试
                        wait = 2.0 * (attempt + 1)
                        logger.warning(f"[AsyncCrawler] {url} -> {resp.status}, retry in {wait}s")
                        await asyncio.sleep(wait)
                        continue
                    else:
                        return "", resp.status
            except aiohttp.ClientError as e:
                wait = 2.0 * (attempt + 1)
                logger.warning(f"[AsyncCrawler] {url} error={e}, retry {attempt+1}/{retry_count}")
                if attempt < retry_count - 1:
                    await asyncio.sleep(wait)
                else:
                    return "", 0
            except asyncio.TimeoutError:
                wait = 2.0 * (attempt + 1)
                logger.warning(f"[AsyncCrawler] {url} timeout, retry {attempt+1}/{retry_count}")
                if attempt < retry_count - 1:
                    await asyncio.sleep(wait)
                else:
                    return "", 0

        return "", 0


# ─── 核心爬虫类 ─────────────────────────────────────────────────────────────


class TenderCrawler:
    """招标信息爬虫 - 支持多网站（同步 + 异步）"""

    def __init__(self, site_id: str = None):
        self.site_id = site_id
        self.site = None
        if site_id:
            for s in SITES:
                if s["id"] == site_id:
                    self.site = s
                    break
        # 共享异步 session（所有实例复用同一个限速桶）
        self._async_session: Optional[AsyncCrawlerSession] = None

    # ── 异步 session 访问 ──────────────────────────────────────────────────

    def _get_async_session(self, site: Dict = None) -> AsyncCrawlerSession:
        if self._async_session is None:
            rate = site.get("rate_limit", 5.0) if site else 5.0
            self._async_session = AsyncCrawlerSession(rate_limit=rate)
        return self._async_session

    async def _close_async_session(self):
        if self._async_session:
            await self._async_session.close()
            self._async_session = None

    # ── HTTP 获取 ────────────────────────────────────────────────────────────

    async def fetch_aiohttp(self, url: str, headers: Dict = None) -> Tuple[str, int]:
        """用 aiohttp 异步获取页面 HTML"""
        if not aiohttp:
            logger.error("aiohttp not installed — falling back to httpx sync fetch")
            return self.fetch_httpx(url, headers)
        site = self.site or {}
        session = self._get_async_session(site)
        return await session.fetch(url, headers)

    def fetch_httpx(self, url: str, headers: Dict = None) -> Tuple[str, int]:
        """用 httpx 同步获取页面 HTML"""
        if not httpx:
            return "", 0
        default_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        if headers:
            default_headers.update(headers)
        try:
            r = httpx.get(url, timeout=15, headers=default_headers, follow_redirects=True)
            return r.text, r.status_code
        except Exception as e:
            logger.error(f"httpx fetch failed: {url} -> {e}")
            return "", 0

    def fetch_playwright(self, url: str, cookies: List[Dict] = None,
                        scroll: bool = True, wait: int = 5) -> Tuple[str, List]:
        """用 Playwright 获取页面 HTML 和所有链接"""
        if not PLAYWRIGHT_AVAILABLE:
            return "", []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                locale="zh-CN",
                extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9"},
            )
            if cookies:
                ctx.add_cookies(cookies)

            page = ctx.new_page()
            page.goto(url, timeout=30000, wait_until="domcontentloaded")

            if scroll:
                for _ in range(3):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(2)

            time.sleep(wait)

            html = page.inner_text("body")
            links = page.query_selector_all("a[href]")
            browser.close()
            return html, links

    # ── Cookie 管理 ─────────────────────────────────────────────────────────

    def load_cookies(self, cookies_file: str) -> List[Dict]:
        """加载保存的 cookies"""
        try:
            with open(cookies_file) as f:
                return json.load(f)
        except Exception:
            return []

    def save_cookies(self, ctx, cookies_file: str):
        """保存 cookies"""
        cookies = ctx.cookies()
        try:
            with open(cookies_file, "w") as f:
                json.dump(cookies, f)
            logger.info(f"Saved {len(cookies)} cookies to {cookies_file}")
        except Exception as e:
            logger.error(f"Failed to save cookies: {e}")

    # ── 招标类型分类 ────────────────────────────────────────────────────────

    def classify_tender_type(self, title: str, site: Dict) -> str:
        """根据标题关键词分类"""
        rules = site.get("tender_type_rules", [])
        for tender_type, keywords in rules:
            if any(k in title for k in keywords):
                return tender_type
        return "招标公告"

    # ── 链接提取 ────────────────────────────────────────────────────────────

    def extract_links(self, html: str, links, site: Dict, base_url: str) -> List[Dict]:
        """从页面提取招标相关链接"""
        selectors = site["selectors"]
        title_kws = selectors["title_kws"]
        url_kws = selectors["url_kws"]
        exclude_kws = selectors["exclude_kws"]

        results = []
        seen = set()

        if links:
            for a in links:
                href = a.get_attribute("href") or ""
                title = a.inner_text().strip()

                in_title = any(k in title for k in title_kws)
                in_url = any(k in href.lower() for k in url_kws)

                if (in_title or in_url) and len(title) > 5:
                    if not any(k in href.lower() for k in exclude_kws):
                        if href not in seen:
                            seen.add(href)
                            full_url = urljoin(base_url, href)
                            tender_type = self.classify_tender_type(title, site)
                            results.append({
                                "title": title[:200],
                                "url": full_url,
                                "source": site["name"],
                                "tender_type": tender_type,
                                "domain": site["domain"],
                            })

        elif html:
            for match in re.finditer(
                r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]{5,100})</a>', html
            ):
                href, title = match.group(1), match.group(2).strip()
                in_title = any(k in title for k in title_kws)
                in_url = any(k in href.lower() for k in url_kws)
                if (in_title or in_url) and len(title) > 5:
                    if not any(k in href.lower() for k in exclude_kws):
                        if href not in seen:
                            seen.add(href)
                            full_url = urljoin(base_url, href)
                            tender_type = self.classify_tender_type(title, site)
                            results.append({
                                "title": title[:200],
                                "url": full_url,
                                "source": site["name"],
                                "tender_type": tender_type,
                                "domain": site["domain"],
                            })

        return results

    # ── 异步采集 ────────────────────────────────────────────────────────────

    async def async_crawl_site(self, site: Dict = None) -> List[Dict]:
        """异步抓取单个网站"""
        if site is None:
            site = self.site
        if not site:
            return []

        method = site["method"]
        results = []

        try:
            if method == "aiohttp":
                for url in site.get("list_urls", []):
                    html, status = await self.fetch_aiohttp(url)
                    if html and status == 200:
                        results.extend(self.extract_links(html, None, site, url))
                        logger.info(f"[{site['id']}] aiohttp {url}: got {len(results)} links")

            elif method == "httpx":
                for url in site.get("list_urls", []):
                    html, status = self.fetch_httpx(url)
                    if html and status == 200:
                        results.extend(self.extract_links(html, None, site, url))
                        logger.info(f"[{site['id']}] httpx {url}: got {len(results)} links")

            elif method == "playwright":
                cookies = []
                if site.get("cookies_file"):
                    cookies = self.load_cookies(site["cookies_file"])

                for url in site.get("list_urls", []):
                    html, links = self.fetch_playwright(
                        url,
                        cookies=cookies,
                        scroll=site.get("scroll_trigger", True),
                        wait=site.get("wait_time", 5),
                    )
                    if html:
                        results.extend(self.extract_links(html, links, site, url))
                        logger.info(f"[{site['id']}] playwright {url}: got {len(results)} links")

        except Exception as e:
            logger.error(f"[{site['id']}] async_crawl_site failed: {e}")

        # 去重
        seen = set()
        unique = []
        for r in results:
            if r["url"] not in seen:
                seen.add(r["url"])
                unique.append(r)

        logger.info(f"[{site['id']}] Total unique: {len(unique)}")
        return unique

    async def async_crawl_all(self) -> List[Dict]:
        """异步抓取所有启用的网站"""
        all_results = []
        tasks = []
        site_list = []

        for site in SITES:
            if site.get("status") in ("active", "limited"):
                site_list.append(site)

        # 并发执行所有网站
        for site in site_list:
            tasks.append(self.async_crawl_site(site))

        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        for site, result in zip(site_list, results_list):
            if isinstance(result, Exception):
                logger.error(f"[{site['id']}] crawl failed: {result}")
            else:
                all_results.extend(result)

        return all_results

    # ── 同步采集（向后兼容）─────────────────────────────────────────────────

    def crawl_site(self, site: Dict = None) -> List[Dict]:
        """抓取单个网站（同步版，向后兼容）"""
        if site is None:
            site = self.site
        if not site:
            return []

        method = site["method"]
        results = []

        if method == "httpx":
            for url in site.get("list_urls", []):
                html, status = self.fetch_httpx(url)
                if html and status == 200:
                    results.extend(self.extract_links(html, None, site, url))
                    logger.info(f"[{site['id']}] httpx {url}: got {len(results)} links")

        elif method == "playwright":
            cookies = []
            if site.get("cookies_file"):
                cookies = self.load_cookies(site["cookies_file"])

            for url in site.get("list_urls", []):
                html, links = self.fetch_playwright(
                    url,
                    cookies=cookies,
                    scroll=site.get("scroll_trigger", True),
                    wait=site.get("wait_time", 5),
                )
                if html:
                    results.extend(self.extract_links(html, links, site, url))
                    logger.info(f"[{site['id']}] playwright {url}: got {len(results)} links")

        # 去重
        seen = set()
        unique = []
        for r in results:
            if r["url"] not in seen:
                seen.add(r["url"])
                unique.append(r)

        logger.info(f"[{site['id']}] Total unique: {len(unique)}")
        return unique

    def crawl_all(self) -> List[Dict]:
        """抓取所有启用的网站（同步版，向后兼容）"""
        all_results = []
        for site in SITES:
            if site.get("status") in ("active", "limited"):
                try:
                    results = self.crawl_site(site)
                    all_results.extend(results)
                except Exception as e:
                    logger.error(f"[{site['id']}] crawl failed: {e}")
        return all_results

    # ── 数据库写入 ──────────────────────────────────────────────────────────

    def save_to_db(self, results: List[Dict], db_conn):
        """保存结果到数据库 favorites 表"""
        added = 0
        for r in results:
            try:
                existing = db_conn.execute(
                    "SELECT 1 FROM favorites WHERE project_url=?", (r["url"],)
                ).fetchone()
                if existing:
                    continue
                db_conn.execute(
                    """
                    INSERT INTO favorites
                    (project_url, title, source_url, tender_type, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (r["url"], r["title"], r["source"], r["tender_type"]),
                )
                added += 1
            except Exception as e:
                logger.debug(f"Insert failed: {e}")
        db_conn.commit()
        return added

    # ── 批量异步采集 + 写入 ──────────────────────────────────────────────────

    async def async_crawl_and_save(self):
        """异步采集所有网站并写入数据库（完整流程）"""
        from app.database import get_db

        results = await self.async_crawl_all()
        if not results:
            logger.warning("[TenderCrawler] No results collected")
            return {"total": 0, "added": 0, "results": 0}

        db = get_db()
        conn = db._get_conn()
        added = self.save_to_db(results, conn)
        total = conn.execute("SELECT COUNT(*) FROM favorites").fetchone()[0]
        return {"total": total, "added": added, "results": len(results)}


# ─── 便捷函数 ──────────────────────────────────────────────────────────────


async def async_quick_crawl(site_id: str = None) -> dict:
    """异步快速抓取 - 用于一次性运行"""
    crawler = TenderCrawler(site_id)
    try:
        if site_id:
            # 找到对应 site
            site = None
            for s in SITES:
                if s["id"] == site_id:
                    site = s
                    break
            results = await crawler.async_crawl_site(site) if site else []
        else:
            results = await crawler.async_crawl_all()
    finally:
        await crawler._close_async_session()

    from app.database import get_db

    db = get_db()
    conn = db._get_conn()
    added = crawler.save_to_db(results, conn)
    total = conn.execute("SELECT COUNT(*) FROM favorites").fetchone()[0]
    return {"total": total, "added": added, "results": len(results)}


def quick_crawl(site_id: str = None) -> List[Dict]:
    """快速抓取 - 用于一次性运行（同步版，向后兼容）"""
    from app.database import get_db

    db = get_db()
    conn = db._get_conn()

    crawler = TenderCrawler(site_id)
    if site_id:
        results = crawler.crawl_site()
    else:
        results = crawler.crawl_all()

    added = crawler.save_to_db(results, conn)
    total = conn.execute("SELECT COUNT(*) FROM favorites").fetchone()[0]
    return {"total": total, "added": added, "results": len(results)}


# ─── 能力报告 ──────────────────────────────────────────────────────────────


def capability_report() -> str:
    """生成网站能力报告"""
    lines = ["# 招标网站抓取能力报告", "", "## 状态一览", ""]
    lines.append("| 网站 | 状态 | 方式 | 认证 | 备注 |")
    lines.append("|------|------|------|------|------|")
    for s in SITES:
        status_icon = {"active": "✅", "limited": "⚠️", "disabled": "❌"}.get(s["status"], "❓")
        lines.append(
            f"| {s['name']} | {status_icon} {s['status']} | {s['method']} | "
            f"{s.get('auth','-')} | {s.get('note','')} |"
        )
    lines.append("")
    lines.append("## 抓取策略")
    strategy = [
        "Playwright: JS动态渲染页面，需Cookie认证",
        "aiohttp: 异步HTTP，支持高并发 + 令牌桶限速 + 智能重试",
        "httpx: 同步HTTP静态HTML页面，无需认证",
        "滚动触发: 懒加载需滚动页面触发",
        "tender_type分类: 根据标题关键词自动判断类型",
    ]
    lines.extend(strategy)
    return "\n".join(lines)


if __name__ == "__main__":
    print(capability_report())
    print("\n=== 同步快速测试 ===")
    r = quick_crawl("ccgp_national")
    print(f"Saved: {r['added']} new, total: {r['total']}")
