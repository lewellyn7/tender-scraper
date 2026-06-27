"""
CQGGZY curl-based fetcher (2026-06-23 新增)
============================================
使用 curl + python requests 替代 Playwright, 性能提升 ~10x.
从 `/api/special-zone/search-engine-page` 拉取列表, 详情页 curl GET 后用 BS4 提取.

启用方式 (环境变量):
    CRAWLER_MODE=curl  → 使用本模块
    CRAWLER_MODE=playwright  → 默认 (Playwright)

兼容现有 CqggzyCrawlerV2 接口 (fetch_list_page, fetch_detail_page),
可直接替换 main.py 导入.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from datetime import datetime, timedelta
from typing import List, Optional

import aiohttp

from app.crawlers.base import TenderInfo
from app.utils.clean_noise import make_content_preview
from app.crawlers.cqggzy import CQGGZYCrawlerV2  # 复用 LIST_URLS / 字段映射

logger = logging.getLogger(__name__)


# 8 大类白名单 (6 位)
ALLOWED_CATNUM_PREFIXES = {
    '014001019', '014001001', '014001002', '014001003', '014001004',
    '014005001', '014005002', '014005004',
}

# 黑名单 (用户 6-23 17:51 指令)
BLACKLIST_CATNUMS = {'014001015', '014005008'}

# 标题兜底拦截词
BLOCKED_TITLE_KEYWORDS = ('招租', '经营权出让')

# categoryNum 前9位 → info_type 映射 (从循环内上提, P3.3)
_CATEGORY_INFO_TYPE = {
    '014001019': '招标计划',
    '014001001': '招标公告',
    '014001002': '答疑补遗',
    '014001003': '中标候选人公示',
    '014001004': '中标结果公示',
    '014001021': '终止公告',
    '014005001': '采购公告',
    '014005002': '变更公告',
    '014005004': '采购结果公告',
}

# API endpoint
API_URL = "https://www.cqggzy.com/api/special-zone/search-engine-page"
DETAIL_BASE = "https://www.cqggzy.com"


def _filter_record(item: dict) -> Optional[dict]:
    """8 大类白名单 + 黑名单 + 标题兜底过滤. 返回 None = 过滤掉."""
    title = item.get('title', '').strip()
    if len(title) < 5:
        return None
    if any(kw in title for kw in BLOCKED_TITLE_KEYWORDS):
        return None
    raw_catnum = item.get('categorynum', '') or ''
    if not raw_catnum or raw_catnum in BLACKLIST_CATNUMS:
        return None
    cat9 = raw_catnum[:9]
    if cat9 not in ALLOWED_CATNUM_PREFIXES:
        return None
    return item


def _build_payload(category_num: str, pn: int = 0, rn: int = 50) -> dict:
    """构造 API payload (复用 PR #33 的格式)."""
    return {
        "token": "",
        "pn": pn,
        "rn": rn,
        "sdt": "",
        "edt": "",
        "wd": "",
        "inc_wd": "",
        "exc_wd": "",
        "fields": "",
        "sort": '{"istop":"0","ordernum":"0","webdate":"0","newid":"0"}',
        "ssort": "",
        "cl": 10000,
        "terminal": "",
        "highlights": "",
        "statistics": None,
        "accuracy": "",
        "noParticiple": "1",
        "searchRange": None,
        "noWd": True,
        "cnum": "001",
        "condition": [{
            "fieldName": "categorynum",
            "equal": None,
            "notEqual": None,
            "equalList": [category_num],
            "notEqualList": None,
            "isLike": True,
            "likeType": 2,
            "noWd": True,
        }],
        "time": [],
    }


class CqggzyCurlCrawler(CQGGZYCrawlerV2):
    """
    curl-based 替代 CQGGZYCrawlerV2.
    复用父类的 LIST_URLS / INFO_TYPE_MAP / _infer_business_type_by_url,
    仅替换 fetch_list_via_api / fetch_detail_page.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_curl = True
        self._session: Optional[aiohttp.ClientSession] = None
        logger.info("CqggzyCurlCrawler 初始化 (10x 提速 vs Playwright)")

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'application/json, text/plain, */*',
                    'Origin': 'https://www.cqggzy.com',
                    'Referer': 'https://www.cqggzy.com/',
                }
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def fetch_list(
        self, category: str = "gov_purchase", page_num: int = 1,
        start_date=None, end_date=None
    ) -> List["TenderInfo"]:
        """curl 重写: 跳过 Playwright _fetch_list_page, 走 _fetch_list_via_curl"""
        sdt = start_date.strftime('%Y-%m-%d') if start_date else ''
        edt = end_date.strftime('%Y-%m-%d') if end_date else ''
        return await self._fetch_list_via_curl(category, page_num=page_num, sdt=sdt, edt=edt)

    async def fetch_detail(self, tender) -> "TenderInfo":
        """curl 重写: 跳过 Playwright _fetch_detail_page, 走 _fetch_detail_via_curl"""
        return await self._fetch_detail_via_curl(tender)

    async def _fetch_list_via_curl(
        self, category: str, page_num: int = 1, rn: int = 50,
        sdt: str = "", edt: str = "",
    ) -> List[TenderInfo]:
        """通过 API + aiohttp 拉取列表 (curl 路径)."""
        if category in self.LIST_URLS:
            trade_id, category_num = self.LIST_URLS[category]
        else:
            trade_id, category_num = ('014005', '014005001') if 'gov' in category else ('014001', '014001001')

        # API 6 位 prefix 用于列表查询 (PR #33 验证)
        cat6 = category_num[:6]
        pn = page_num - 1
        payload = _build_payload(cat6, pn=pn, rn=rn)
        if sdt:
            payload['sdt'] = sdt
        if edt:
            payload['edt'] = edt

        session = await self._get_session()
        try:
            async with session.post(API_URL, json=payload) as resp:
                api_response = await resp.json(content_type=None)
        except Exception as e:
            logger.error(f"  [curl] API 调用失败: {e}")
            return []

        if not api_response or api_response.get('code') != 200:
            logger.warning(f"  [curl] API 返回非 200: {api_response.get('msg', '?')}")
            return []

        content_str = api_response.get('content', '{}')
        try:
            content_parsed = json.loads(content_str)
        except (json.JSONDecodeError, TypeError):
            logger.debug(f"  [curl] content 解析失败")
            return []

        result_data = content_parsed.get('result', {}) or {}
        items = result_data.get('records', []) if isinstance(result_data, dict) else []
        total = result_data.get('totalcount', 0)
        logger.debug(f"  [curl] API total={total}, page={len(items)}")

        results = []
        seen_urls = set()
        tender_type = self.INFO_TYPE_MAP.get(category, "政府采购" if category == "gov_purchase" else "工程建设")

        for item in items:
            filtered = _filter_record(item)
            if not filtered:
                continue
            item = filtered

            title = item['title'].strip()
            infodate = item.get('infodate', '') or item.get('webdate', '') or ''
            pub_date = None
            if infodate and len(infodate) >= 10:
                try:
                    pub_date = datetime.strptime(infodate[:19], '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    pass

            infoid = item.get('infoid', '') or item.get('syscollectguid', '')
            # CQGGZY API infoid 格式: "1645485773757394944_1" (数字 ID + 版本后缀)
            # 详情页 URL 必须含 _N 后缀, 否则网站返回空 200 响应 (无正文)
            # Fallback: 兼容旧格式裸数字 ID (无下划线) → 自动补 _1
            if infoid and '_' not in infoid and infoid.isdigit():
                infoid = f'{infoid}_1'
            raw_catnum = item['categorynum']

            if raw_catnum.startswith('014001'):
                trade_id_use = '014001'
            elif raw_catnum.startswith('014005'):
                trade_id_use = '014005'
            else:
                continue

            full_url = f"{DETAIL_BASE}/trade/{trade_id_use}/{infoid}?categoryNum={raw_catnum}" if infoid else \
                       f"{DETAIL_BASE}/trade/{trade_id_use}?infoId={item.get('infoid', '')}"

            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            tender = TenderInfo(
                title=title,
                url=full_url,
                category=tender_type,
                source_url=full_url,
                publish_date_raw=infodate,
                tender_type=tender_type,
                business_type=self._infer_business_type_by_url(full_url),
                scraped_by=f"{self.version}-curl",
            )
            if pub_date:
                tender.publish_date = pub_date

            # info_type
            m9 = re.search(r'categoryNum=(\d+)', full_url)
            if m9:
                prefix9 = m9.group(1)[:9]
                tender.info_type = _CATEGORY_INFO_TYPE.get(prefix9, '')

            # content 提取
            raw_content = item.get('content', '') or ''
            if raw_content:
                clean = re.sub(r'<[^>]+>', '', raw_content)
                clean = re.sub(r'\s+', ' ', clean).strip()
                tender.full_content = clean
                tender.content_preview = make_content_preview(clean, tender.title)

            # keywords matched
            try:
                from app.services.keywords_service import KeywordsService
                _text = tender.title + " " + (raw_content or "")
                _match = KeywordsService().match(_text)
                if _match:
                    _inc = _match.get("include", [])
                    _exc = _match.get("exclude", [])
                    if _inc and not _exc:
                        tender.keywords_matched = [k["keyword"] for k in _inc]
            except Exception:
                pass

            results.append(tender)

        logger.debug(f"  [curl] 过滤后 {len(results)} 条 (pn={pn})")
        return results

    async def _fetch_detail_via_curl(self, tender: TenderInfo) -> TenderInfo:
        """curl GET 详情页, BS4 提取正文."""
        if not tender.url:
            return tender
        session = await self._get_session()
        try:
            async with session.get(tender.url) as resp:
                if resp.status != 200:
                    logger.debug(f"  [curl] 详情 {resp.status}: {tender.url[:60]}")
                    return tender
                html = await resp.text()
        except Exception as e:
            logger.debug(f"  [curl] 详情失败: {e}")
            return tender

        # BS4 提取正文
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'lxml')
            # 1. epoint-article-content
            for cls in ('epoint-article-content', 'mainContent', 'epoint-article', 'article-content'):
                div = soup.find(class_=cls) or soup.find(id=cls)
                if div:
                    text = div.get_text(separator='\n', strip=True)
                    if len(text) > 200:
                        tender.full_content = text
                        tender.content_preview = make_content_preview(text, tender.title)
                        return tender
            # 2. 兜底: body 全文本
            body = soup.find('body')
            if body:
                text = body.get_text(separator='\n', strip=True)
                if len(text) > 200:
                    tender.full_content = text
                    tender.content_preview = make_content_preview(text, tender.title)
        except ImportError:
            # 无 BS4, regex 兑底
            text_match = re.search(r'<div[^>]*class="[^"]*article[^"]*"[^>]*>([\s\S]+?)</div>', html)
            if text_match:
                clean = re.sub(r'<[^>]+>', '', text_match.group(1))
                clean = re.sub(r'\s+', ' ', clean).strip()
                if len(clean) > 200:
                    tender.full_content = clean
                    tender.content_preview = make_content_preview(clean, tender.title)

        return tender


# ============== 独立运行模式 (命令行) ==============
async def _run_backfill_curl(date_start: str, date_end: str, output: str, with_details: bool = True):
    """命令行: curl 模式补采 (scripts/fetch_cqggzy_curl.py 的核心逻辑)"""
    crawler = CqggzyCurlCrawler()
    try:
        # 日期: edt 排他 (+1)
        ds = datetime.strptime(date_start, '%Y-%m-%d')
        de = datetime.strptime(date_end, '%Y-%m-%d') + timedelta(days=1)
        sdt = ds.strftime('%Y-%m-%d')
        edt = de.strftime('%Y-%m-%d')

        all_items = []
        for category, (trade_id, cat_num) in crawler.LIST_URLS.items():
            logger.info(f"=== {category} ({cat_num}) ===")
            page = 1
            while True:
                items = await crawler._fetch_list_via_curl(
                    category, page_num=page, rn=50, sdt=sdt, edt=edt
                )
                if not items:
                    break
                all_items.extend(items)
                logger.info(f"  page {page}: {len(items)} 条 (累计 {len(all_items)})")
                if len(items) < 50:
                    break
                page += 1
                if page > 30:  # 安全: 最多 30 页
                    break

        # 详情
        if with_details:
            logger.info(f"采集详情: {len(all_items)} 条")
            for i, t in enumerate(all_items):
                t = await crawler._fetch_detail_via_curl(t)
                if (i + 1) % 50 == 0:
                    logger.info(f"  详情进度: {i + 1}/{len(all_items)}")

        # 输出
        out = []
        for t in all_items:
            out.append({
                'title': t.title,
                'url': t.url,
                'category': t.category,
                'info_type': t.info_type,
                'business_type': t.business_type,
                'publish_date': t.publish_date_raw,
                'full_content': t.full_content or '',
                'content_preview': t.content_preview or '',
                'infoid': t.url.split('/')[-1].split('?')[0] if t.url else '',
            })
        with open(output, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 已保存到 {output}: {len(out)} 条")
    finally:
        await crawler.close()
