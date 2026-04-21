"""重复检测路由 — 多字段智能查重（分桶优化 O(n²) → O(n×k)）"""

import re
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Query, Depends
from fastapi.responses import JSONResponse

from app.database import get_db
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api/duplicates", tags=["重复检测"])

# 权重配置
FIELD_WEIGHTS = {
    "title": 0.40,
    "budget": 0.20,
    "tender_type": 0.15,
    "url": 0.15,
    "publish_date": 0.10,
}


# ─── 辅助函数 ────────────────────────────────────────────

def _extract_numbers(text: str) -> List[float]:
    """从文本中提取所有数字"""
    if not text:
        return []
    return [float(n.replace(",", "")) for n in re.findall(r"[\d,\.]+(?:\.\d+)?", text) if n.replace(",", "").replace(".", "").isdigit() or re.match(r"^\d[\d,\.]*\.\d+$", n)]


def _budget_similarity(b1: str, b2: str) -> float:
    """预算相似度：都无预算→0.0，一方无→0.3，数字接近→1.0"""
    n1, n2 = _extract_numbers(b1), _extract_numbers(b2)
    if not n1 and not n2:
        return 0.0
    if not n1 or not n2:
        return 0.3
    v1, v2 = max(n1), max(n2)
    if v1 == 0 and v2 == 0:
        return 0.0
    ratio = min(v1, v2) / max(v1, v2) if max(v1, v2) > 0 else 0.0
    return round(ratio, 3)


def _date_proximity(d1: str, d2: str) -> float:
    """日期接近度：完全相同→1.0，年月相同→0.7，年相同→0.4"""
    if not d1 or not d2:
        return 0.0
    if d1 == d2:
        return 1.0
    try:
        m1 = re.match(r"(\d{4})-(\d{2})", d1)
        m2 = re.match(r"(\d{4})-(\d{2})", d2)
        if m1 and m2:
            if m1.group() == m2.group():
                return 0.7
            if m1.group(1) == m2.group(1):
                return 0.4
    except Exception:
        pass
    return 0.0


def _token_similarity(t1: str, t2: str) -> float:
    """基于字符序列的相似度（轻量级，无需语料库）"""
    if not t1 or not t2:
        return 0.0
    return round(SequenceMatcher(None, t1, t2).ratio(), 3)


def _multi_field_compare(p1: dict, p2: dict) -> Tuple[float, dict]:
    """
    多字段相似度比对。
    返回 (综合分数, 各字段详情)
    """
    fields = {}

    # 1. URL 精确匹配
    url_match = 1.0 if p1.get("project_url", "").strip() == p2.get("project_url", "").strip() else 0.0
    fields["url"] = {"score": url_match, "v1": p1.get("project_url", ""), "v2": p2.get("project_url", ""), "matched": url_match > 0}

    # 2. 标题相似度（字符序列 + 共同词比例）
    title1, title2 = p1.get("title", "").strip(), p2.get("title", "").strip()
    title_score = _token_similarity(title1, title2)
    if title1 and title2 and (title1 in title2 or title2 in title1):
        title_score = max(title_score, 0.85)
    fields["title"] = {"score": title_score, "v1": title1, "v2": title2, "matched": title_score >= 0.6}

    # 3. 预算相似度
    b1, b2 = p1.get("budget", ""), p2.get("budget", "")
    budget_score = _budget_similarity(b1, b2)
    fields["budget"] = {"score": budget_score, "v1": b1, "v2": b2, "matched": budget_score >= 0.8}

    # 4. 项目类型精确匹配
    tt1, tt2 = p1.get("tender_type", "").strip(), p2.get("tender_type", "").strip()
    tt_match = 1.0 if tt1 and tt2 and tt1 == tt2 else 0.0
    fields["tender_type"] = {"score": tt_match, "v1": tt1, "v2": tt2, "matched": tt_match > 0}

    # 5. 发布日期接近度
    pd1, pd2 = p1.get("publish_date", ""), p2.get("publish_date", "")
    pd_score = _date_proximity(pd1, pd2)
    fields["publish_date"] = {"score": pd_score, "v1": pd1, "v2": pd2, "matched": pd_score >= 0.7}

    # 综合分数（加权）
    total = sum(FIELD_WEIGHTS[k] * fields[k]["score"] for k in FIELD_WEIGHTS)

    return round(total, 3), fields


def _make_bucket_key(title: str) -> str:
    """提取标题前4字作为桶分界键（标题不同则基本不会重复）"""
    return title[:4].strip().lower() if title else "___"


# ─── API 路由 ────────────────────────────────────────────

@router.get("")
def find_duplicates(
    threshold: float = Query(0.5, ge=0.1, le=1.0, description="综合相似度阈值"),
    user_id: str = Depends(get_current_user),
):
    """
    多字段智能查重（分桶预过滤 O(n²) → O(n×k)）。

    比对维度：标题、预算、项目类型、URL、发布日期
    每组结果包含：综合分数、各字段得分、匹配标记
    """
    db = get_db()
    conn = db._get_conn()

    # 按 user_id 过滤（修复：之前忽略了 user_id 参数）
    if user_id:
        rows = conn.execute(
            "SELECT * FROM favorites WHERE user_id=? ORDER BY updated_at DESC LIMIT 1000",
            (user_id,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM favorites ORDER BY updated_at DESC LIMIT 1000").fetchall()

    projects = [dict(r) for r in rows]

    if len(projects) < 2:
        return JSONResponse({"duplicates": [], "count": 0, "total": 0, "threshold": threshold})

    # ── 优化：分桶预过滤 ──────────────────────────────────
    # 标题前4字作为桶键，仅桶内比对（不同标题基本不会重复）
    buckets: Dict[str, list] = defaultdict(list)
    for p in projects:
        buckets[_make_bucket_key(p.get("title", ""))].append(p)

    duplicate_groups = []
    processed: set = set()

    for bucket_key, bucket_projects in buckets.items():
        # 桶内 O(k²)，桶间无比较，总复杂度 O(Σk_i²) ≈ O(n×k)
        for i in range(len(bucket_projects)):
            pi = bucket_projects[i]
            url_i = pi.get("project_url", "")

            if url_i in processed:
                continue

            group = [{
                "url": url_i,
                "title": pi.get("title", ""),
                "budget": pi.get("budget", ""),
                "tender_type": pi.get("tender_type", ""),
                "publish_date": pi.get("publish_date", ""),
                "sim": 1.0,
                "fields": None,
            }]

            for j in range(i + 1, len(bucket_projects)):
                pj = bucket_projects[j]
                url_j = pj.get("project_url", "")

                if url_j in processed:
                    continue

                sim, fields = _multi_field_compare(pi, pj)

                if sim >= threshold:
                    group.append({
                        "url": url_j,
                        "title": pj.get("title", ""),
                        "budget": pj.get("budget", ""),
                        "tender_type": pj.get("tender_type", ""),
                        "publish_date": pj.get("publish_date", ""),
                        "sim": sim,
                        "fields": fields,
                    })
                    processed.add(url_j)

            if len(group) > 1:
                processed.add(url_i)
                duplicate_groups.append(group)

    return JSONResponse({
        "duplicates": duplicate_groups,
        "count": len(duplicate_groups),
        "total": sum(len(g) for g in duplicate_groups),
        "threshold": threshold,
    })
