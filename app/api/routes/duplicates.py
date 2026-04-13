"""重复检测路由"""

from fastapi import APIRouter, Query, Depends
from fastapi.responses import JSONResponse

from app.database import get_db
from app.utils.tfidf_matcher import TFIDFMatcher
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api/duplicates", tags=["重复检测"])


@router.get("")
def find_duplicates(threshold: float = Query(0.7, ge=0.3, le=0.95), user_id: str = Depends(get_current_user)):
    """查找重复项目（简化输出：仅URL和相似度）"""
    db = get_db()
    conn = db._get_conn()

    rows = conn.execute("SELECT * FROM favorites LIMIT 1000").fetchall()
    projects = [dict(r) for r in rows]

    if len(projects) < 2:
        return JSONResponse({"duplicates": [], "count": 0, "total": 0})

    titles = [p.get("title", "") for p in projects]
    matcher = TFIDFMatcher(titles)

    duplicate_groups = []
    processed = set()

    for i in range(len(projects)):
        if projects[i]["project_url"] in processed:
            continue

        group = [{"url": projects[i]["project_url"], "title": projects[i].get("title", ""), "sim": 1.0}]
        for j in range(i + 1, len(projects)):
            if projects[j]["project_url"] in processed:
                continue

            sim = matcher.similarity(i, j)
            if sim >= threshold:
                group.append({"url": projects[j]["project_url"], "title": projects[j].get("title", ""), "sim": round(sim, 3)})
                processed.add(projects[j]["project_url"])

        if len(group) > 1:
            processed.add(projects[i]["project_url"])
            duplicate_groups.append(group)

    return JSONResponse({
        "duplicates": duplicate_groups,
        "count": len(duplicate_groups),
        "total": sum(len(g) for g in duplicate_groups)
    })
