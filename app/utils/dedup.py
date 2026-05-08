"""查重相似度算法"""

import re
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Dict, List, Tuple

# 字段权重
FIELD_WEIGHTS = {
    "title": 0.40,
    "budget": 0.20,
    "tender_type": 0.15,
    "url": 0.15,
    "publish_date": 0.10,
}

# 标题中需要移除的pattern（用于生成更稳定的桶key）
_TITLE_CLEAN_PATTERNS = [
    r"[第前后]\s*[\d一二三四五六七八九十百]+[期次]",
    r"[（(][\d一二三四五六七八九十百]+[)）]",
    r"\s*第\s*\d+\s*次\s*",
    r"\s*二次\b",
    r"\s*[重改更]正\b",
    r"\s*[补充变]更\b",
]


def _extract_numbers(text: str) -> List[float]:
    if not text:
        return []
    return [
        float(n.replace(",", ""))
        for n in re.findall(r"[\d,\.]+(?:\.\d+)?", text)
        if n.replace(",", "").replace(".", "").isdigit() or bool(re.match(r"^\d[\d,\.]*\.\d+$", n))
    ]


def _budget_similarity(b1: str, b2: str) -> float:
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
    if not t1 or not t2:
        return 0.0
    return round(SequenceMatcher(None, t1, t2).ratio(), 3)


def _normalize_title(title: str) -> str:
    """清理标题，移除次数/更正等易变suffix，保留核心项目名"""
    t = title.strip()
    for pat in _TITLE_CLEAN_PATTERNS:
        t = re.sub(pat, "", t)
    return re.sub(r"\s+", " ", t).strip()


def _make_bucket_key(title: str) -> str:
    """提取规范化标题前6字作为桶分界键"""
    normalized = _normalize_title(title)
    return normalized[:6].strip().lower() if normalized else "___"


def _multi_field_compare(p1: dict, p2: dict) -> Tuple[float, dict]:
    """多字段相似度比对，返回 (综合分数, 各字段详情)"""
    fields = {}

    url_match = 1.0 if p1.get("project_url", "").strip() == p2.get("project_url", "").strip() else 0.0
    fields["url"] = {"score": url_match, "v1": p1.get("project_url", ""), "v2": p2.get("project_url", ""), "matched": url_match > 0}

    title1, title2 = p1.get("title", "").strip(), p2.get("title", "").strip()
    title_score = _token_similarity(title1, title2)
    if title1 and title2 and (title1 in title2 or title2 in title1):
        title_score = max(title_score, 0.85)
    fields["title"] = {"score": title_score, "v1": title1, "v2": title2, "matched": title_score >= 0.6}

    b1, b2 = p1.get("budget", ""), p2.get("budget", "")
    budget_score = _budget_similarity(b1, b2)
    fields["budget"] = {"score": budget_score, "v1": b1, "v2": b2, "matched": budget_score >= 0.8}

    tt1, tt2 = p1.get("tender_type", "").strip(), p2.get("tender_type", "").strip()
    tt_match = 1.0 if tt1 and tt2 and tt1 == tt2 else 0.0
    fields["tender_type"] = {"score": tt_match, "v1": tt1, "v2": tt2, "matched": tt_match > 0}

    pd1, pd2 = p1.get("publish_date", ""), p2.get("publish_date", "")
    pd_score = _date_proximity(pd1, pd2)
    fields["publish_date"] = {"score": pd_score, "v1": pd1, "v2": pd2, "matched": pd_score >= 0.7}

    total = sum(FIELD_WEIGHTS[k] * fields[k]["score"] for k in FIELD_WEIGHTS)
    return round(total, 3), fields


def find_duplicate_groups(
    projects: List[dict],
    threshold: float = 0.5,
) -> Tuple[List[dict], List[dict]]:
    """对项目列表进行多字段智能查重（分桶优化 O(n²) → O(n×k)）

    Returns:
        duplicate_groups: [{canonical, duplicates: [{url, title, sim, fields}, ...]}, ...]
        all_pairs: [{canonical_url, duplicate_url, title, similarity}, ...]
    """
    if len(projects) < 2:
        return [], []

    buckets: Dict[str, list] = defaultdict(list)
    for p in projects:
        buckets[_make_bucket_key(p.get("title", ""))].append(p)

    duplicate_groups = []
    all_pairs = []
    processed: set = set()

    for bucket_key, bucket_projects in buckets.items():
        for i in range(len(bucket_projects)):
            pi = bucket_projects[i]
            url_i = pi.get("project_url", "")

            if url_i in processed:
                continue

            duplicates = []
            for j in range(i + 1, len(bucket_projects)):
                pj = bucket_projects[j]
                url_j = pj.get("project_url", "")

                if url_j in processed:
                    continue

                sim, fields = _multi_field_compare(pi, pj)

                if sim >= threshold:
                    duplicates.append({
                        "url": url_j,
                        "title": pj.get("title", ""),
                        "budget": pj.get("budget", ""),
                        "tender_type": pj.get("tender_type", ""),
                        "publish_date": pj.get("publish_date", ""),
                        "sim": sim,
                        "fields": fields,
                    })
                    all_pairs.append({
                        "canonical_url": url_i,
                        "duplicate_url": url_j,
                        "title": pj.get("title", ""),
                        "similarity": sim,
                    })
                    processed.add(url_j)

            if duplicates:
                processed.add(url_i)
                duplicate_groups.append({
                    "canonical": {
                        "url": url_i,
                        "title": pi.get("title", ""),
                        "budget": pi.get("budget", ""),
                        "tender_type": pi.get("tender_type", ""),
                        "publish_date": pi.get("publish_date", ""),
                        "sim": 1.0,
                        "fields": None,
                    },
                    "duplicates": duplicates,
                    "count": len(duplicates),
                })

    return duplicate_groups, all_pairs
