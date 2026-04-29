"""分析统计路由 - 基于所有项目分析"""

from datetime import datetime, timedelta
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pathlib import Path
import json
import re
from collections import Counter

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SYS_PATH = Path('/app') if Path('/.dockerenv').exists() else Path(__file__).parent.parent.parent

router = APIRouter(prefix="/api/analytics", tags=["分析"])

STOP_WORDS = {
    '的', '了', '和', '与', '或', '及', '在', '为', '于', '对', '等',
    '由', '以', '被', '将', '把', '给', '向', '从', '通过', '关于',
    '项目', '采购', '招标', '公告', '进行中', '公告的', '一', '二', '三'
}


def _load_projects():
    """从 latest.json 加载项目数据"""
    data_file = SYS_PATH / "output" / "latest.json"
    if data_file.exists():
        try:
            with open(data_file, encoding="utf-8") as f:
                d = json.load(f)
            return d.get("projects", []), d.get("total", 0)
        except Exception:
            pass
    return [], 0


def get_analytics(days: int = Query(365, ge=1, le=3650)):
    """获取分析数据"""
    projects, total = _load_projects()
    
    # 过滤指定天数内的项目
    try:
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    except:
        start_date = "1970-01-01"
    
    recent_projects = [
        p for p in projects
        if p.get("publish_date", "") >= start_date or not p.get("publish_date")
    ]
    
    # 统计
    matched_projects = [p for p in recent_projects if p.get("keywords_matched")]
    
    # 有预算的项目
    budget_projects = [
        p for p in recent_projects
        if p.get("budget") and p.get("budget") != ""
    ]
    
    # 按类型统计
    type_counter = Counter(p.get("tender_type", "未知") for p in recent_projects)
    categories = [
        {"name": k, "count": v}
        for k, v in type_counter.most_common(10)
    ]
    
    # 预算分布
    budget_dist = []
    for p in budget_projects[:50]:
        try:
            budget = float(re.sub(r'[^\d.]', '', str(p.get("budget", "0"))))
            if budget > 0:
                if budget < 100000:
                    bucket = "10万以下"
                elif budget < 500000:
                    bucket = "10-50万"
                elif budget < 1000000:
                    bucket = "50-100万"
                elif budget < 5000000:
                    bucket = "100-500万"
                else:
                    bucket = "500万+"
                budget_dist.append(bucket)
        except:
            pass
    
    budget_counter = Counter(budget_dist)
    budget_distribution = [
        {"range": k, "count": v}
        for k, v in budget_counter.most_common(10)
    ]
    
    # 来源分布
    source_counter = Counter(p.get("source_name", "未知") for p in recent_projects)
    source_distribution = [
        {"source": k, "count": v}
        for k, v in source_counter.most_common(10)
    ]
    
    # 关键词热度
    keyword_heat = {}
    for p in matched_projects:
        kws = p.get("keywords_matched", "")
        if kws:
            for kw in kws.split(","):
                kw = kw.strip()
                if kw and kw not in STOP_WORDS:
                    keyword_heat[kw] = keyword_heat.get(kw, 0) + 1
    
    # 按热度排序
    keyword_heat = dict(
        sorted(keyword_heat.items(), key=lambda x: x[1], reverse=True)[:20]
    )
    
    # 趋势数据（按天）
    trends = []
    days_list = sorted(set(p.get("publish_date", "") for p in recent_projects))
    for day in days_list[-30:]:
        day_projects = [p for p in recent_projects if p.get("publish_date", "") == day]
        trends.append({
            "date": day,
            "count": len(day_projects),
            "matched": len([p for p in day_projects if p.get("keywords_matched")])
        })
    
    return JSONResponse({
        "summary": {
            "total": len(recent_projects),
            "pending": len([p for p in recent_projects if not p.get("keywords_matched")]),
            "matched": len(matched_projects),
        },
        "trends": trends,
        "categories": categories,
        "budget_dist": budget_distribution,
        "source_dist": source_distribution,
        "keyword_heat": keyword_heat,
        "days": days,
    })


# 注册路由
router.get("")(get_analytics)


@router.get("/health")
def get_health():
    """健康度仪表盘"""
    try:
        hm = get_health_monitor()
        return JSONResponse(hm.get_status())
    except:
        return JSONResponse({
            "status": "ok",
            "services": {},
            "message": "Health monitor not available"
        })
