"""项目路由"""

import json
import os
import re
import time
from pathlib import Path

from fastapi.responses import JSONResponse
from loguru import logger

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi import Request

from app.database import get_db
from app.services.vector_store import get_vector_store
from app.utils.tfidf_matcher import TFIDFMatcher
from app.utils.session import get_user_from_session


def get_current_user_id_optional(request) -> str:
    """获取当前用户ID（可选，未登录返回None）"""
    from app.config.settings import get_settings
    if get_settings().is_self_mode:
        return "admin"
    token = request.cookies.get("session_token") or request.headers.get("X-Session-Token")
    if token:
        user = get_user_from_session(token)
        if user:
            return user["user_id"]
    return None


def get_current_user_id_required(request) -> str:
    """获取当前用户ID（必选，未登录抛出401）"""
    from app.config.settings import get_settings
    if get_settings().is_self_mode:
        return "admin"
    token = request.cookies.get("session_token") or request.headers.get("X-Session-Token")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user = get_user_from_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="无效的session")
    return user["user_id"]

router = APIRouter(prefix="/api", tags=["项目"])
# 检测是否在 Docker 容器内运行（/.dockerenv 存在即容器）
SYS_PATH = Path('/app') if Path('/.dockerenv').exists() else Path(__file__).parent.parent.parent
_cache = {"projects": [], "total": 0, "last_load": 0}

# TF-IDF 缓存
_tfidf_cache = {"matcher": None, "expiry": 0}
TFIDF_CACHE_TTL = 300  # 5分钟


def _batch_load_favorites_and_annotations(urls: list, db):
    """批量预加载 favorites 和 annotations，避免 N+1 查询"""
    if not urls:
        return {}, {}

    fav_map, ann_map = {}, {}

    # 批量查询 favorites (2次查询替代 N×2)
    placeholders = ",".join(["?"] * len(urls))
    try:
        fav_rows = db._get_conn().execute(
            f"SELECT id, project_url, status FROM favorites WHERE project_url IN ({placeholders})",
            urls
        ).fetchall()
        fav_map = {row["project_url"]: row for row in fav_rows}
    except Exception:
        pass

    try:
        ann_rows = db._get_conn().execute(
            f"SELECT project_url, note, priority FROM annotations WHERE project_url IN ({placeholders})",
            urls
        ).fetchall()
        ann_map = {row["project_url"]: row for row in ann_rows}
    except Exception:
        pass

    return fav_map, ann_map


_CACHE_TTL = int(os.getenv("PROJECTS_CACHE_TTL", "300"))  # 5分钟


def _infer_business_type(url: str, title: str = "") -> str:
    """根据 URL 和标题推理业务类型"""
    if "014005" in url or "order" in url:
        return "政府采购"
    if "014001" in url or "bidding" in url:
        return "工程招投标"
    text = title[:500] if title else ""
    if "采购" in text:
        return "政府采购"
    if "招标" in text:
        return "工程招投标"
    return "政府采购"


def _infer_info_type(url: str) -> str:
    """根据 URL 路径推理信息类型"""
    # 政府采购
    if "/014005/014005004/" in url:
        return "采购结果公告"
    if "/014005/014005001/" in url:
        return "采购公告"
    if "/014005/014005002/" in url:
        return "答疑变更"
    if "/014005/014005003/" in url:
        return "废标公告"
    if "/014005/014005005/" in url:
        return "合同公告"
    if "/014005/014005008/" in url:
        return "单一来源公示"
    # 工程招投标
    if "/014001/014001019/" in url:
        return "招标计划"
    if "/014001/014001001/" in url:
        return "招标公告"
    if "/014001/014001014/" in url:
        return "邀标信息"
    if "/014001/014001002/" in url:
        return "答疑补遗"
    if "/014001/014001003/" in url:
        return "中标候选人公示"
    if "/014001/014001004/" in url:
        return "中标结果公示"
    if "/014001/014001020/" in url:
        return "合同签订基本信息公示"
    if "/014001/014001023/" in url:
        return "合同变更基本信息公示"
    if "/014001/014001016/" in url:
        return "相关公告"
    if "/014001/014001021/" in url:
        return "终止公告"
    return "其他"


def _load_projects():
    now = time.time()
    if _cache["projects"] and (now - _cache["last_load"]) < _CACHE_TTL:
        return _cache["projects"], _cache["total"]

    all_projects = {}

    # 1. Load from PostgreSQL (projects_cqggzy, projects_ccgp) — single source of truth
    try:
        db = get_db()
        conn = db._get_conn()

        def row_to_project(row, cols):
            """Convert DB row to project dict matching JSON format."""
            d = dict(zip(cols, row))
            return {
                "title": d.get("title", ""),
                "type": d.get("category", ""),
                "publish_date": str(d.get("publish_date", "")) if d.get("publish_date") else "",
                "publish_date_raw": d.get("publish_date_raw", ""),
                "url": d.get("url", ""),
                "source_url": d.get("url", ""),
                "content_preview": (d.get("content_preview") or "").replace("\n", " "),
                "budget": d.get("budget", ""),
                "deadline": str(d.get("deadline", "")) if d.get("deadline") else "",
                "region": d.get("region", ""),
                "tender_type": d.get("tender_type", ""),
                "keywords_matched": d.get("keywords_matched", ""),
                "contact_name": d.get("contact_name", ""),
                "contact_phone": d.get("contact_phone", ""),
                "contact_email": d.get("contact_email", ""),
                "attachments_count": d.get("attachments_count", 0) or 0,
                "attachments": d.get("attachments", "[]"),
                "scraped_at": str(d.get("created_at", "")) if d.get("created_at") else "",
                "scraped_by": d.get("scraped_by", ""),
                "business_type": d.get("business_type", ""),
                "info_type": d.get("info_type", ""),
                "project_no": d.get("project_no", ""),
                "project_overview": (d.get("project_overview") or "").replace("\n", " "),
                "bidder_requirements": d.get("bidder_requirements", ""),
                "submission_deadline": d.get("submission_deadline", ""),
                "bid_amount": d.get("bid_amount", ""),
                "full_content": d.get("full_content", "") or "",
                "tender_content": d.get("tender_content", "") or "",
            }

        for table in ("projects_cqggzy", "projects_ccgp"):
            try:
                rows = conn.execute(f'SELECT * FROM {table}').fetchall()
                cols = [d[0] for d in conn.execute(f'SELECT * FROM {table} LIMIT 0').description]

                for row in rows:
                    p = row_to_project(row, cols)
                    if p.get("url"):
                        all_projects[p["url"]] = p
            except Exception as e:
                logger.warning(f"Failed to load from {table}: {e}")
    except Exception as e:
        logger.warning(f"Failed to load projects from DB: {e}")

    # 对所有记录填充空白的 business_type / info_type（根据 URL 推理）
    for p in all_projects.values():
        if not p.get("business_type"):
            if "ccgp-chongqing.gov.cn" in p.get("url", ""):
                p["business_type"] = "政府采购"
            else:
                p["business_type"] = _infer_business_type(p.get("url", ""), p.get("title", ""))
        if not p.get("info_type"):
            p["info_type"] = _infer_info_type(p.get("url", ""))

    project_list = list(all_projects.values())
    _cache["projects"] = project_list
    _cache["total"] = len(project_list)
    _cache["last_load"] = now
    return _cache["projects"], _cache["total"]


def _clear_cache():
    _cache["projects"] = []
    _cache["last_load"] = 0


def _get_last_run():
    """从 PostgreSQL 获取最近采集时间"""
    try:
        db = get_db()
        conn = db._get_conn()
        cur = conn.cursor()
        cur.execute("SELECT MAX(last_run_at) FROM collection_tasks WHERE last_run_at IS NOT NULL")
        row = cur.fetchone()
        cur.close()
        if row and row[0]:
            return str(row[0])
    except Exception:
        pass
    return "-"


@router.get("/projects")
def get_projects(request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=20000),
    keyword: str = Query(""),
    category: str = Query(""),
    date_start: str = Query(""),
    date_end: str = Query(""),
    preset_key: str = Query(""),
    source: str = Query(""),
    sort_by: str = Query("date"),
    use_tfidf: bool = Query(False),
    use_vector: bool = Query(False),  # 修复 6-5: 默认改为 False (top_k=500 会返回 500 条松散相关结果，不如精确匹配可控)
):
    db = get_db()
    projects, _ = _load_projects()
    if preset_key:
        p = db.get_preset(preset_key)
        if p:
            fc = p.get("filter_config", {})
            keyword = keyword or fc.get("keyword", "")
            category = category or fc.get("category", "")
            date_start = date_start or fc.get("date_start", "")
            date_end = date_end or fc.get("date_end", "")

    vector_matched_urls = None
    url_scores = {}

    filtered = projects
    if keyword:
        vector_attempted = False
        vector_had_url_overlap = False
        if use_vector:
            vector_attempted = True
            try:
                vs = get_vector_store()
                vec_results = vs.search(query=keyword, top_k=500)
                raw_vec_urls = {r["metadata"].get("url") for r in vec_results if r.get("metadata", {}).get("url")}
                url_scores = {r["metadata"].get("url"): r["score"] for r in vec_results if r.get("metadata", {}).get("url")}
                # 检测向量库 URL 与项目 URL 是否能匹配（修复 6-5: 老向量库 URL 格式过期问题）
                project_url_set = {p.get("url", "") for p in projects}
                vector_matched_urls = {u for u in raw_vec_urls if u in project_url_set}
                vector_had_url_overlap = len(vector_matched_urls) > 0
                logger.debug(
                    f"[vector] 语义搜索 '{keyword[:20]}...' 召回 {len(raw_vec_urls)} 条, "
                    f"URL 匹配 {len(vector_matched_urls)} 条, overlap={vector_had_url_overlap}"
                )
            except Exception as e:
                logger.warning(f"[vector] 向量搜索失败，回退简单匹配: {e}")
                vector_matched_urls = None

        # 修复 6-5: 向量库返回结果但 URL 与项目库不匹配（向量库过期）→ 回退简单匹配
        if (vector_attempted and not vector_had_url_overlap) or vector_matched_urls is None:
            if vector_attempted and not vector_had_url_overlap:
                logger.warning(
                    f"[vector] URL 不匹配项目库 (向量库可能过期)，回退到 title+content 简单匹配"
                )
            if use_tfidf:
                m = TFIDFMatcher()
                m.build_corpus([p.get("title", "") for p in projects])
                kws = [k.strip() for k in keyword.split(",") if k.strip()]
                m.build_keywords(kws)
                mu = set()
                for p in projects:
                    _, matched, _ = m.match(p.get("title", ""), kws)
                    if matched:
                        mu.add(p.get("url", ""))
                filtered = [p for p in projects if p.get("url", "") in mu]
            else:
                kws = [k.strip().lower() for k in keyword.split(",") if k.strip()]
                # 修复 6-5: 简单匹配也检查 full_content (之前只查 title+content_preview)
                filtered = [
                    p
                    for p in projects
                    if any(kw in (p.get("title", "") or "").lower() for kw in kws)
                    or any(kw in (p.get("content_preview", "") or "").lower() for kw in kws)
                    or any(kw in (p.get("full_content", "") or "").lower() for kw in kws)
                ]
            # 标记回退后不要再用 vector_matched_urls 二次过滤
            vector_matched_urls = None

    if vector_matched_urls is not None:
        filtered = [p for p in filtered if p.get("url", "") in vector_matched_urls]

    if vector_matched_urls is not None:
        filtered = [p for p in filtered if p.get("url", "") in vector_matched_urls]
        if url_scores:
            filtered.sort(key=lambda p: url_scores.get(p.get("url", ""), 0), reverse=True)

    if category:
        filtered = [
            p for p in filtered if p.get("tender_type") == category or p.get("type") == category
        ]
    if date_start:
        filtered = [p for p in filtered if p.get("publish_date", "") >= date_start]
    if date_end:
        filtered = [p for p in filtered if p.get("publish_date", "") <= date_end]
    if source:
        filtered = [p for p in filtered if source in p.get("source_url", "")]
    if sort_by == "budget":

        def bnum(p):
            b = p.get("budget", "")
            try:
                return float(re.sub(r"[^\d.]", "", b)) * (10000 if "万" in b else 1)
            except Exception:
                return 0

        filtered.sort(key=bnum, reverse=True)
    else:
        filtered.sort(key=lambda p: p.get("publish_date", "") or "", reverse=True)
    total_f = len(filtered)
    start = (page - 1) * page_size
    page_projects = filtered[start : start + page_size]
    # 批量预加载 favorites 和 annotations（用户个性化数据，需登录）
    urls = [p.get("url", "") for p in page_projects]
    user_id = get_current_user_id_optional(request)
    if user_id:
        fav_map, ann_map = _batch_load_favorites_and_annotations(urls, db)
        for p in page_projects:
            url = p.get("url", "")
            p["is_favorite"] = url in fav_map
            p["_fid"] = fav_map[url]["id"] if url in fav_map else None
            p["annotation"] = ann_map.get(url)
    else:
        for p in page_projects:
            p["is_favorite"] = False
            p["annotation"] = None
    return JSONResponse(
        {
            "projects": page_projects,
            "total": total_f,
            "page": page,
            "page_size": page_size,
            "last_run": _get_last_run(),
        }
    )


@router.get("/project/{project_url}")
def get_project(request: Request, project_url: str):
    db = get_db()
    projects, _ = _load_projects()
    user_id = get_current_user_id_optional(request)
    for p in projects:
        if p.get("url", "") == project_url:
            if user_id:
                fav = db.get_favorite(project_url, user_id)
                p["is_favorite"] = bool(fav)
                p["_fid"] = fav["id"] if fav else None
                p["annotation"] = db.get_annotation(project_url)
            else:
                p["is_favorite"] = False
                p["annotation"] = None
            return JSONResponse(p)
    return JSONResponse({"error": "not found"}, status_code=404)


@router.get("/duplicates")
def find_duplicates(request: Request, threshold: float = Query(0.7, ge=0, le=1)):
    get_current_user_id_required(request)  # require auth
    db = get_db()
    projects, _ = _load_projects()
    if not projects:
        return JSONResponse({"duplicates": [], "total": 0})
    m = TFIDFMatcher(min_similarity=threshold)
    m.build_corpus([p.get("title", "") for p in projects])
    groups = []
    checked = set()
    for i, p1 in enumerate(projects):
        u1 = p1.get("url", "")
        if u1 in checked:
            continue
        group = [{"url": u1, "title": p1.get("title", ""), "similarity": 1.0}]
        for j, p2 in enumerate(projects[i + 1 :], i + 1):
            u2 = p2.get("url", "")
            if u2 in checked:
                continue
            sim = m.title_similarity(p1.get("title", ""), p2.get("title", ""))
            if sim >= threshold:
                group.append({"url": u2, "title": p2.get("title", ""), "similarity": round(sim, 3)})
                checked.add(u2)
                db.add_duplicate(u1, u2, p2.get("title", ""), sim)
        if len(group) > 1:
            groups.append(group)
            for item in group:
                checked.add(item["url"])
    return JSONResponse({"duplicates": groups, "total": len(groups)})


@router.get("/stats")
def get_stats(request: Request):
    get_current_user_id_required(request)  # require auth
    db = get_db()
    projects, total = _load_projects()
    return JSONResponse(
        {
            "total": total,
            "filtered": len([p for p in projects if p.get("keywords_matched")]),
            "last_run": _get_last_run(),
            "db_stats": {},
        }
    )


@router.get("/projects/groups")
def get_project_groups(request: Request, limit: int = Query(100, le=500), biz_type: str = None):
    """获取按项目分组的聚合数据（从 PostgreSQL，按 project_no 分组）"""
    user_id = get_current_user_id_required(request)
    try:
        db = get_db()
        conn = db._get_conn()

        # 用 SQL 聚合查询：按 project_no 分组，无 project_no 则按 url
        # 注意：LIKE 'http%%' 双%转义，psycopg2 将 %% 视为单个 %
        where_clause = "(NULLIF(project_no, '') IS NOT NULL OR url LIKE 'http%%' OR url LIKE 'https%%')"
        params = []
        if biz_type:
            where_clause += " AND business_type = ?"
            params.append(biz_type)
        params.append(limit)

        rows = conn.execute(
            "SELECT "
            "  COALESCE(NULLIF(project_no, ''), url) as group_key, "
            "  MAX(title) as name, "
            "  MAX(COALESCE(NULLIF(project_no, ''), '')) as code, "
            "  MAX(business_type) as business_type, "
            "  MAX(project_overview) as project_overview, "
            "  MAX(publish_date) as latest_date, "
            "  STRING_AGG(DISTINCT NULLIF(info_type,''), '|') as info_types, "
            "  COUNT(*) as cnt, "
            "  MAX(CASE WHEN url LIKE 'http%%' OR url LIKE 'https%%' THEN url ELSE NULL END) as sample_url "
            "FROM projects_cqggzy "
            "WHERE " + where_clause + " "
            "GROUP BY COALESCE(NULLIF(project_no, ''), url) "
            "ORDER BY MAX(publish_date) DESC NULLS LAST "
            "LIMIT ?",
            params
        ).fetchall()

        result = []
        for row in rows:
            key, name, code, biz_type, overview, latest_date, info_types_str, cnt, sample_url = row
            # 过滤掉被污染的分组 key（过短或含中文）
            if not key or len(key) < 6 or re.search(r'[\u4e00-\u9fff]', key):
                continue
            result.append({
                "name": name or key,
                "code": code if code and len(code) >= 5 else "-",
                "business_type": biz_type or "",
                "record_types": sorted([it for it in (info_types_str.split("|") if info_types_str else []) if it]),
                "count": cnt,
                "updated_at": str(latest_date) if latest_date else "",
                "overview": overview or "",
                "url": sample_url or (key if key.startswith("http") else None),
            })

        return JSONResponse({"groups": result})
    except Exception as e:
        import traceback; traceback.print_exc()
        logger.error(f"get_project_groups: {e}")
        return JSONResponse({"groups": [], "error": str(e)}, status_code=500)


@router.post("/cache/clear")
def clear_cache_endpoint(request: Request, body: dict = None):
    """清除项目缓存（供 collector 内部调用）"""
    import os
    expected = os.getenv("INTERNAL_CACHE_CLEAR_KEY", "")
    internal_key = (body or {}).get("internal_key", "") if body else ""
    if expected and internal_key != expected:
        raise HTTPException(status_code=403, detail="Forbidden")
    _cache["projects"] = []
    _cache["last_load"] = 0
    return {"success": True}
