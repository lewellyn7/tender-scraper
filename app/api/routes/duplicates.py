"""重复检测路由"""

from fastapi import APIRouter, Query, Depends
from fastapi.responses import JSONResponse

from app.database import get_db
from app.utils.tfidf_matcher import TFIDFMatcher
from app.api.dependencies import get_current_user
from app.utils.tfidf_matcher import TFIDFMatcher
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api/duplicates", tags=["重复检测"])


@router.get("")
def find_duplicates(threshold: float = Query(0.7, ge=0.3, le=0.95), user_id: str = Depends(get_current_user)):
    """查找重复项目"""
    db = get_db()
    conn = db._get_conn()

    # 获取所有项目
    rows = conn.execute("SELECT * FROM favorites LIMIT 1000").fetchall()
    projects = [dict(r) for r in rows]

    if len(projects) < 2:
        return JSONResponse({"duplicates": []})

    # 使用 TF-IDF 计算相似度
    titles = [p.get("title", "") for p in projects]
    matcher = TFIDFMatcher(titles)

    duplicate_groups = []
    processed = set()

    for i in range(len(projects)):
        if projects[i]["project_url"] in processed:
            continue

        group = [projects[i]]
        for j in range(i + 1, len(projects)):
            if projects[j]["project_url"] in processed:
                continue

            sim = matcher.similarity(i, j)
            if sim >= threshold:
                group.append(projects[j])
                processed.add(projects[j]["project_url"])

        if len(group) > 1:
            processed.add(projects[i]["project_url"])
            duplicate_groups.append(group)

            # 存储到数据库
            canonical = group[0]["project_url"]
            for dup in group[1:]:
                db.add_duplicate(canonical, dup["project_url"], dup.get("title", ""), sim)

    return JSONResponse({"duplicates": duplicate_groups, "count": len(duplicate_groups)})
