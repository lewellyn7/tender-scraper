"""项目路由"""

import json
import os
import re
import time
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from loguru import logger

from fastapi import HTTPException, Request

from app.database import get_db
from app.services.vector_store import get_vector_store
from app.utils.tfidf_matcher import TFIDFMatcher
from app.utils.session import get_user_from_session


def get_current_user_id_optional(request) -> str:
    """获取当前用户ID（可选，未登录返回None）"""
    token = request.cookies.get("session_token") or request.headers.get("X-Session-Token")
    if token:
        user = get_user_from_session(token)
        if user:
            return user["user_id"]
    return None


def get_current_user_id_required(request) -> str:
    """获取当前用户ID（必选，未登录抛出401）"""
    token = request.cookies.get("session_token") or request.headers.get("X-Session-Token")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user = get_user_from_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="无效的session")
    return user["user_id"]

router = APIRouter(prefix="/api", tags=["项目"])
SYS_PATH = Path(__file__).parent.parent.parent.parent
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
            f"SELECT project_url, status FROM favorites WHERE project_url IN ({placeholders})",
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


def _load_projects():
    now = time.time()
    if _cache["projects"] and (now - _cache["last_load"]) < _CACHE_TTL:
        return _cache["projects"], _cache["total"]
    data_file = SYS_PATH / "output" / "latest.json"
    if data_file.exists():
        try:
            with open(data_file, encoding="utf-8") as f:
                d = json.load(f)
            _cache["projects"] = d.get("projects", [])
            _cache["total"] = d.get("total", 0)
            _cache["last_load"] = now
            return _cache["projects"], _cache["total"]
        except Exception as e:
            logger.warning(f"Failed to load projects: {e}")
    return [], 0


def _clear_cache():
    _cache["projects"] = []
    _cache["last_load"] = 0


@router.get("/projects")
def get_projects(request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    keyword: str = Query(""),
    category: str = Query(""),
    date_start: str = Query(""),
    date_end: str = Query(""),
    preset_key: str = Query(""),
    source: str = Query(""),
    sort_by: str = Query("date"),
    use_tfidf: bool = Query(False),
    use_vector: bool = Query(True),
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
        if use_vector:
            try:
                vs = get_vector_store()
                vec_results = vs.search(query=keyword, top_k=500)
                vector_matched_urls = {r["metadata"].get("url") for r in vec_results if r.get("metadata", {}).get("url")}
                url_scores = {r["metadata"].get("url"): r["score"] for r in vec_results if r.get("metadata", {}).get("url")}
                logger.debug(f"[vector] 语义搜索 '{keyword[:20]}...' 召回 {len(vector_matched_urls)} 条")
            except Exception as e:
                logger.warning(f"[vector] 向量搜索失败，回退简单匹配: {e}")
                vector_matched_urls = None

        if vector_matched_urls is None:
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
                filtered = [
                    p
                    for p in projects
                    if any(kw in p.get("title", "").lower() for kw in kws)
                    or any(kw in p.get("content_preview", "").lower() for kw in kws)
                ]

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
            p["annotation"] = ann_map.get(url)
    else:
        for p in page_projects:
            p["is_favorite"] = False
            p["annotation"] = None
    data_file = SYS_PATH / "output" / "latest.json"
    last_run = "-"
    if data_file.exists():
        try:
            with open(data_file, encoding="utf-8") as f:
                d = json.load(f)
                last_run = d.get("last_run", "-")
        except Exception:
            pass
    return JSONResponse(
        {
            "projects": page_projects,
            "total": total_f,
            "page": page,
            "page_size": page_size,
            "last_run": last_run,
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
                p["is_favorite"] = db.is_favorite(project_url)
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
    data_file = SYS_PATH / "output" / "latest.json"
    last_run = "-"
    if data_file.exists():
        try:
            with open(data_file, encoding="utf-8") as f:
                d = json.load(f)
                last_run = d.get("last_run", "-")
        except Exception:
            pass
    return JSONResponse(
        {
            "total": total,
            "filtered": len([p for p in projects if p.get("keywords_matched")]),
            "last_run": last_run,
            "db_stats": db.get_stats(),
        }
    )
