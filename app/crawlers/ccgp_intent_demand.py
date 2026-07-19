"""CCGP 采购意向 / 需求调查 采集器 (2026-07-01 新增)
==============================================
来源: https://www.ccgp-chongqing.gov.cn (重庆市政府采购网)

数据源策略:
- 2 个分类, 通过 type 参数区分:
  - 采购意向: type=2 (当前 ~33K 条)
  - 需求调查: type=1 (当前 ~4K 条)
- 公共 JSON API (无需登录/Cookie):
  - 列表: GET https://www.ccgp-chongqing.gov.cn/yw-gateway/demand/demand/front
          ?type={1|2}&page={1..N}&pageSize=20
          &createTimeStart={ms}&createTimeEnd={ms}
  - 详情: GET https://www.ccgp-chongqing.gov.cn/yw-gateway/demand/demand/{id}/front
  - 附件: GET https://www.ccgp-chongqing.gov.cn/gwebsite/files?filePath={fp}&fileName={fn}
- aiohttp 异步 HTTP (类 fahcqmu 模式, 不需 Playwright)
- 附件: **1c 模式** - 只存 filePath, 不下载; 走按需端点
- 时间窗: **2c 模式** - 默认 30 天增量 (createTimeStart = now-30d)
- 翻页停止: API 返回 data 长度 < pageSize (默认 20) 时停
- 限速: 2 req/s, 并发 5 (详情)

启用方式:
- python harvest_main.py run --source ccgp_intent_demand --days 30
- 或: python -c "import asyncio; from app.core.harvest.pipeline import run_ccgp_intent_demand_collection; asyncio.run(run_ccgp_intent_demand_collection())"

集成 (PR feat/ccgp-intention-demand-2026-07-01):
- 新表: projects_ccgp_intention_demand (migration 004)
- DB 方法: db.upsert_projects_ccgp_intention_demand(rows)
- 调度: pipeline.py 中加 run_ccgp_intent_demand_collection()
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import urlencode

import aiohttp
from loguru import logger

from app.models.tender import TenderInfo

# ============================================================================
# 配置
# ============================================================================
BASE_URL = "https://www.ccgp-chongqing.gov.cn"
LIST_BASE = f"{BASE_URL}/yw-gateway/demand/demand/front"
DETAIL_TPL = f"{BASE_URL}/yw-gateway/demand/demand/{{id}}/front"
FILES_BASE = f"{BASE_URL}/gwebsite/files"

# lesson 22+ (A2 方案): 详情 API 实际可用 (正确调用: ?type={1|2})
# 之前误判为不可用 (错用 DB 自增 ID 8407 + 没加 type 参数)
DETAIL_API_BASE = f"{BASE_URL}/yw-gateway/demand/demand"
DETAIL_API_TPL = f"{DETAIL_API_BASE}/{{id}}/front"

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": f"{BASE_URL}/info-notice/intention-list",
}
# 默认 pageSize
DEFAULT_PAGE_SIZE = 20
# 限速: 2 req/s
DEFAULT_DELAY = 0.5
# 并发 (详情)
DEFAULT_CONCURRENCY = 5
# 翻页 safety 上限
MAX_PAGES = 50


# ── 分类配置 ──────────────────────────────────────────────────────
@dataclass
class IntentDemandConfig:
    """一个采集分类的配置."""
    type_id: int                # API type (1=需求调查 2=采购意向)
    info_type: str              # DB info_type ('采购意向' / '需求调查')
    source_url: str             # 列表页 URL (source_url 字段)
    description: str = ""


CATEGORIES: List[IntentDemandConfig] = [
    IntentDemandConfig(
        type_id=2,
        info_type="采购意向",
        source_url=f"{BASE_URL}/info-notice/intention-list",
        description="采购意向 (type=2)",
    ),
    IntentDemandConfig(
        type_id=1,
        info_type="需求调查",
        source_url=f"{BASE_URL}/info-notice/demand-list",
        description="需求调查 (type=1)",
    ),
]


# ============================================================================
# 工具函数
# ============================================================================
def build_url(type_id: int, page: int, page_size: int,
              time_start_ms: Optional[int] = None,
              time_end_ms: Optional[int] = None) -> str:
    """构造列表 API URL."""
    params = {
        "type": type_id,
        "page": page,
        "pageSize": page_size,
    }
    if time_start_ms is not None:
        params["createTimeStart"] = time_start_ms
    if time_end_ms is not None:
        params["createTimeEnd"] = time_end_ms
    return f"{LIST_BASE}?{urlencode(params)}"


def build_doc_url(type_id: int, item_id: str) -> str:
    """构造详情页 URL. type=2 → intention-view, type=1 → demand-view.

    实测: 这是合成 URL, 真实详情 API 走 /{id}/front
    """
    path = "intention-view" if type_id == 2 else "demand-view"
    return f"{BASE_URL}/{path}/{item_id}"


def build_annex_url(file_path: str, file_name: str) -> str:
    """构造按需下载 URL (1c 模式, 不预下载)."""
    from urllib.parse import quote
    return f"{FILES_BASE}?filePath={quote(file_path, safe='')}&fileName={quote(file_name, safe='')}"


def ms_to_dt(ms: Optional[int]) -> Optional[datetime]:
    """毫秒时间戳 → datetime (UTC)."""
    if ms is None or ms == 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0)
    except (ValueError, OSError):
        return None


def ms_to_date(ms: Optional[int]) -> Optional[datetime.date]:
    """毫秒时间戳 → date."""
    dt = ms_to_dt(ms)
    return dt.date() if dt else None


def dt_to_ms(dt: datetime) -> int:
    """datetime → 毫秒时间戳."""
    return int(dt.timestamp() * 1000)


def format_detail_list(detail_list: List[Dict]) -> str:
    """把 intentionDetaileList[] 拼成结构化文本 (lesson 22+ A2 方案).

    详情 API 返回的明细含: title / depict / money / catalogName / target / requirement / quantity
    按层级拼: ▸ 标题 → 品类/预算/数量/目标/要求/明细
    """
    parts: List[str] = []
    for d in detail_list:
        t = (d.get("title") or "").strip()
        c = (d.get("depict") or d.get("content") or "").strip()
        cat_name = (d.get("catalogName") or "").strip()
        d_money = (d.get("money") or "").strip()
        target = (d.get("target") or "").strip()
        requirement = (d.get("requirement") or "").strip()
        quantity = (d.get("quantity") or "").strip()

        item_parts: List[str] = []
        if t:
            item_parts.append(f"▸ {t}")
        if cat_name:
            item_parts.append(f"  品类：{cat_name}")
        if d_money:
            item_parts.append(f"  预算：{d_money}万元")
        if quantity:
            item_parts.append(f"  数量：{quantity}")
        if target:
            item_parts.append(f"  目标：{target}")
        if requirement:
            item_parts.append(f"  要求：{requirement}")
        if c:
            item_parts.append(f"  明细：{c}")
        if item_parts:
            parts.append("\n".join(item_parts))
    return "\n\n".join(parts)


async def _fetch_detail_json(
    session: aiohttp.ClientSession,
    item_id: str,
    type_id: int,
    retries: int = 3,
) -> Optional[Dict]:
    """调详情 API 拿 intentionDetaileList[] (含真全文).

    lesson 22+ (A2 方案):
    - 正确调用方式: GET /yw-gateway/demand/demand/{18位id}/front?type={1|2}
    - 之前误判: 用 DB 自增 ID + 没加 type 参数 → {"code":-1,"message":"异常，业务不存在"}
    - list API 返回 intentionDetaileList=null; 必须调详情 API 拿明细
    - 命中率 100% (10/10 测试 ID), 平均 depict 225 chars (vs list 仅 36 chars)
    """
    url = f"{DETAIL_API_TPL.format(id=item_id)}?type={type_id}"
    last_err = None
    for attempt in range(retries):
        try:
            async with session.get(url) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
                return data.get("data") or {}
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            last_err = e
            if attempt < retries - 1:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
    logger.warning(f"详情 API 失败 (id={item_id}, type={type_id}): {last_err}")
    return None


def parse_intent_demand_json(
    data: Dict,
    cat: IntentDemandConfig,
    detail_data: Optional[Dict] = None,
) -> TenderInfo:
    """将 API 返回的单条 JSON 转换为 TenderInfo.

    关键字段映射:
    - id → source_id (合成 url)
    - title → title
    - createTime (ms) → publish_date / publish_date_raw
    - money → budget
    - depict → full_content / content_preview (项目简介部分)
    - intentionDetaileList[] → full_content (采购明细部分, lesson 22+ A2 优先用详情 API)
    - createRegionName → region
    - budgetOrgName → project_overview (首行, 兜底)
    - annex[] → attachments (仅存路径)
    - type=2/1 → info_type (硬映射到分类)

    Args:
        data: list API 返回的单条 JSON
        cat: 分类配置
        detail_data: 详情 API 返回的 data dict (含 intentionDetaileList)，可选
            优先级: detail_api.intentionDetaileList > list.intentionDetaileList
    """
    item_id = str(data.get("id") or "")
    if not item_id:
        raise ValueError("API response missing 'id' field")

    # 时间
    create_time_ms = data.get("createTime")
    publish_date = ms_to_date(create_time_ms)
    publish_date_raw = (
        ms_to_dt(create_time_ms).strftime("%Y-%m-%d %H:%M:%S")
        if create_time_ms else ""
    )

    # 正文 + 明细 (lesson 22+: 详情 API 优先)
    depict = (data.get("depict") or "").strip()
    detail_list: List[Dict] = []
    if detail_data:
        detail_list = detail_data.get("intentionDetaileList") or []
    if not detail_list:
        # fallback: list API 字段 (通常为 null)
        detail_list = data.get("intentionDetaileList") or []
    detail_text = format_detail_list(detail_list)

    # 拼装 full_content (项目简介 + 采购明细)
    full_content_parts: List[str] = []
    if depict:
        full_content_parts.append(f"【项目简介】\n{depict}")
    if detail_text:
        full_content_parts.append(f"【采购明细】\n{detail_text}")
    full_content = "\n\n".join(full_content_parts)
    content_preview = full_content[:300] if full_content else depict[:300]

    # 附件 (1c 模式: 只存路径)
    annex_raw = data.get("annex") or []
    attachments: List[Dict] = []
    if isinstance(annex_raw, list):
        for a in annex_raw:
            if not isinstance(a, dict):
                continue
            attachments.append({
                "fileName": a.get("fileName") or "",
                "filePath": a.get("filePath") or "",
                "contentType": a.get("contentType") or "",
                "size": a.get("size") or 0,
                "time": a.get("time") or "",
                "downloadUrl": build_annex_url(
                    a.get("filePath") or "", a.get("fileName") or ""
                ),
            })

    # 金额
    money = data.get("money") or ""
    budget = f"{money}万元" if money and "万" not in str(money) else str(money)

    item = TenderInfo(
        title=(data.get("title") or "").strip(),
        url=build_doc_url(cat.type_id, item_id),
        publish_date=publish_date,
        publish_date_raw=publish_date_raw,
        info_type=cat.info_type,
        business_type="政府采购",
        category="政府采购",
        source_url=cat.source_url,
        budget=budget,
        region=(data.get("createRegionName") or "").strip(),
        project_overview=depict[:500] if depict else "",
        full_content=full_content,
        content_preview=content_preview,
        # attachments 字段在 TenderInfo 是 List[TenderAttachment] 对象列表
        # 这里由 tender_to_db_row 转 dict 后再放
        scraped_by="tender-scraper v3.2 ccgp_intent_demand",
    )
    # 私有字段 (供 tender_to_db_row 取用)
    item._attachments_json = attachments  # type: ignore[attr-defined]
    item._source_id = item_id  # type: ignore[attr-defined]
    item._source_type = cat.type_id  # type: ignore[attr-defined]
    item._tender_content = detail_text  # type: ignore[attr-defined]
    return item


# ============================================================================
# 采集器主体
# ============================================================================
class CcgpIntentDemandCrawler:
    """CCGP 采购意向 / 需求调查 采集器 (aiohttp, 不需 Playwright).

    用法:
        async with CcgpIntentDemandCrawler() as crawler:
            items = await crawler.fetch_all_lists(days=30)
            detailed = await crawler.fetch_details_parallel(items, limit=300)
    """

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        delay: float = DEFAULT_DELAY,
        max_pages: int = MAX_PAGES,
        page_size: int = DEFAULT_PAGE_SIZE,
    ):
        self._session = session
        self._owns_session = session is None
        self.delay = delay
        self.max_pages = max_pages
        self.page_size = page_size

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

    async def _get_json(self, url: str, retries: int = 3) -> Dict:
        """GET URL, 返回 JSON dict. 3 重试, 指数退避."""
        if self._session is None:
            raise RuntimeError("Use 'async with' or pass session")
        last_err = None
        for attempt in range(retries):
            try:
                async with self._session.get(url) as resp:
                    resp.raise_for_status()
                    return await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                last_err = e
                if attempt < retries - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
        raise last_err  # type: ignore[misc]

    # ─── 列表 ──────────────────────────────────────────────────────

    async def fetch_list_page(
        self,
        cat: IntentDemandConfig,
        page: int = 1,
        time_start_ms: Optional[int] = None,
        time_end_ms: Optional[int] = None,
    ) -> List[TenderInfo]:
        """采集单页列表. 返回本页 items (空表示已到末页)."""
        url = build_url(cat.type_id, page, self.page_size, time_start_ms, time_end_ms)
        try:
            data = await self._get_json(url, retries=3)
        except Exception as e:
            logger.warning(f"[{cat.info_type}] page={page} GET 3次重试后仍失败: {e}")
            return []

        rows = data.get("data") or []
        items: List[TenderInfo] = []
        for r in rows:
            try:
                items.append(parse_intent_demand_json(r, cat))
            except Exception as e:
                logger.warning(f"  parse 失败 (id={r.get('id')}): {e}")
                continue

        if self.delay > 0:
            await asyncio.sleep(self.delay)
        return items

    async def fetch_all_pages(
        self,
        cat: IntentDemandConfig,
        time_start_ms: Optional[int] = None,
        time_end_ms: Optional[int] = None,
    ) -> List[TenderInfo]:
        """循环 page=1..N, 翻页停止条件: 返回 < pageSize 条.

        Returns:
            该分类全部 items (按时间倒序, 服务端默认排序)
        """
        all_items: List[TenderInfo] = []
        for page in range(1, self.max_pages + 1):
            items = await self.fetch_list_page(
                cat, page, time_start_ms, time_end_ms
            )
            if not items:
                logger.info(f"[{cat.info_type}] 翻页结束 at page={page} (空页)")
                break
            all_items.extend(items)
            # 末页判断: 返回条数 < pageSize 即停止
            if len(items) < self.page_size:
                logger.info(
                    f"[{cat.info_type}] 翻页结束 at page={page} (返回 {len(items)} < {self.page_size})"
                )
                break
            logger.info(
                f"[{cat.info_type}] page={page}: +{len(items)} 条 (累计 {len(all_items)})"
            )
        return all_items

    async def fetch_all_lists(
        self,
        categories: Optional[List[IntentDemandConfig]] = None,
        days: int = 30,
    ) -> List[TenderInfo]:
        """采集所有分类的列表, 并行执行.

        Args:
            categories: 分类列表 (默认全 2 类)
            days: 增量时间窗 (默认 30 天). None = 全量 (不限时间)
        """
        cats = categories or CATEGORIES
        time_start_ms = None
        if days is not None and days > 0:
            time_start_ms = dt_to_ms(datetime.now() - timedelta(days=days))
        time_end_ms = None  # 服务端不传 edt (AGENTS.md edt 排他教训)

        tasks = [
            self.fetch_all_pages(cat, time_start_ms, time_end_ms) for cat in cats
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_items: List[TenderInfo] = []
        for cat, result in zip(cats, results):
            if isinstance(result, Exception):
                logger.error(f"[{cat.info_type}] 采集失败: {result}")
                continue
            logger.info(f"[{cat.info_type}] 合计 {len(result)} 条")
            all_items.extend(result)

        # URL 去重
        seen = set()
        unique = []
        for item in all_items:
            if item.url not in seen:
                seen.add(item.url)
                unique.append(item)
        logger.info(
            f"全部分类合计: {len(all_items)} 条 → 去重后 {len(unique)} 条"
        )

        # lesson 22+ (A2): 详情 API 抓 intentionDetaileList[] 真全文
        # list API 返回 intentionDetaileList=null, 必须调详情 API 拿明细
        if unique:
            await self.fetch_details_parallel(unique, concurrency=DEFAULT_CONCURRENCY)

        return unique

    # ─── 详情 ──────────────────────────────────────────────────────

    async def fetch_detail(self, item: TenderInfo) -> TenderInfo:
        """采集单个详情.

        lesson 22+ (A2): 详情 API 拿 intentionDetaileList[] 真全文.
        之前误判: 列表 API 已含完整字段 (实际 intentionDetaileList=null)
        """
        if self._session is None:
            raise RuntimeError("Use 'async with' or pass session")
        item_id = getattr(item, "_source_id", None)
        type_id = getattr(item, "_source_type", None)
        if not item_id or type_id is None:
            return item

        if self.delay > 0:
            await asyncio.sleep(self.delay)
        detail_data = await _fetch_detail_json(self._session, item_id, type_id, retries=3)
        if detail_data is None:
            return item
        # 重新 parse (用 detail_data 补 intentionDetaileList)
        # 但保留 list API 已拿到的字段: title/depict/createTime/money...
        # 简化: 用 detail_data + item 原数据重 build full_content
        detail_list = detail_data.get("intentionDetaileList") or []
        if detail_list:
            detail_text = format_detail_list(detail_list)
            existing_overview = item.project_overview or ""
            full_content_parts: List[str] = []
            if existing_overview:
                full_content_parts.append(f"【项目简介】\n{existing_overview}")
            if detail_text:
                full_content_parts.append(f"【采购明细】\n{detail_text}")
            new_full = "\n\n".join(full_content_parts)
            item.full_content = new_full
            item.content_preview = new_full[:300] if new_full else ""
            item._tender_content = "\n\n".join(  # type: ignore[attr-defined]
                (d.get("depict") or d.get("content") or "").strip() for d in detail_list
            )
        return item

    async def fetch_details_parallel(
        self,
        items: List[TenderInfo],
        concurrency: int = DEFAULT_CONCURRENCY,
    ) -> List[TenderInfo]:
        """详情采集 (并发).

        lesson 22+ (A2): 调详情 API 拿 intentionDetaileList[] 真全文.
        - list API 永远 null, 必须详情 API (命中率 100%, avg depict 225 chars)
        - concurrency 限速 + retry 3 + delay 0.5s
        """
        if not items or self._session is None:
            return items

        sem = asyncio.Semaphore(concurrency)
        success_count = 0
        fail_count = 0

        async def fetch_one(item: TenderInfo):
            nonlocal success_count, fail_count
            async with sem:
                item_id = getattr(item, "_source_id", None)
                type_id = getattr(item, "_source_type", None)
                if not item_id or type_id is None:
                    fail_count += 1
                    return
                if self.delay > 0:
                    await asyncio.sleep(self.delay)
                detail_data = await _fetch_detail_json(self._session, item_id, type_id, retries=3)
                if detail_data is None:
                    fail_count += 1
                    return
                detail_list = detail_data.get("intentionDetaileList") or []
                if not detail_list:
                    # 详情 API 成功但 intentionDetaileList 为空 (不应发生)
                    fail_count += 1
                    return
                # 重 build full_content
                detail_text = format_detail_list(detail_list)
                existing_overview = item.project_overview or ""
                full_content_parts: List[str] = []
                if existing_overview:
                    full_content_parts.append(f"【项目简介】\n{existing_overview}")
                if detail_text:
                    full_content_parts.append(f"【采购明细】\n{detail_text}")
                new_full = "\n\n".join(full_content_parts)
                item.full_content = new_full
                item.content_preview = new_full[:300] if new_full else ""
                item._tender_content = "\n\n".join(  # type: ignore[attr-defined]
                    (d.get("depict") or d.get("content") or "").strip() for d in detail_list
                )
                success_count += 1

        tasks = [fetch_one(item) for item in items]
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info(
            f"详情 API 完成: {success_count}/{len(items)} 条拿到 intentionDetaileList "
            f"({fail_count} 失败/无明细)"
        )
        return items


# ============================================================================
# DB 写入辅助
# ============================================================================
def _s(v) -> str:
    """安全处理 None / 空值."""
    return v if v else ""


def tender_to_db_row(item: TenderInfo) -> Dict:
    """将 TenderInfo 转换为 projects_ccgp_intention_demand upsert 字典."""
    publish_date = item.publish_date
    if isinstance(publish_date, datetime):
        publish_date_str = publish_date.date().isoformat()
    else:
        publish_date_str = publish_date.isoformat() if publish_date else None

    return {
        "url": item.url,
        "title": _s(item.title),
        "category": _s(item.category) or "政府采购",
        "info_type": _s(item.info_type),
        "business_type": _s(item.business_type) or "政府采购",
        "publish_date": publish_date_str,
        "publish_date_raw": _s(item.publish_date_raw),
        "content_preview": _s(item.content_preview),
        "full_content": _s(item.full_content),
        "tender_content": _s(getattr(item, "_tender_content", "")),
        "budget": _s(item.budget),
        "region": _s(item.region),
        "project_overview": _s(item.project_overview),
        "source_url": _s(item.source_url),
        "attachments_count": len(getattr(item, "_attachments_json", []) or []),
        "attachments": getattr(item, "_attachments_json", []) or [],
        "scraped_by": _s(item.scraped_by) or "tender-scraper v3.2 ccgp_intent_demand",
        "source_id": _s(getattr(item, "_source_id", "")),
        "source_type": getattr(item, "_source_type", 0) or 0,
    }


# ============================================================================
# 入口 (CLI 调试用)
# ============================================================================
async def _run_smoke():
    """冒烟测试: 采集 1 个分类 + 1 个详情."""
    async with CcgpIntentDemandCrawler() as crawler:
        cat = CATEGORIES[0]  # 采购意向
        logger.info(f"=== 冒烟测试 {cat.info_type} ===")
        items = await crawler.fetch_list_page(cat, page=1)
        logger.info(f"列表: {len(items)} 条")
        if items:
            first = items[0]
            logger.info(f"第一条: {first.title[:60]}")
            logger.info(f"  url: {first.url}")
            logger.info(f"  date: {first.publish_date}")
            logger.info(f"  budget: {first.budget}")
            logger.info(f"  full_content len: {len(first.full_content)}")
            logger.info(f"  attachments: {len(getattr(first, '_attachments_json', []))}")


if __name__ == "__main__":
    asyncio.run(_run_smoke())
