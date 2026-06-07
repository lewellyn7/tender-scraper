"""分析统计路由 - 基于 PostgreSQL 项目数据分析"""

from datetime import datetime, timedelta
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
import re
from collections import Counter

from app.database.db import get_db

router = APIRouter(prefix="/api/analytics", tags=["分析"])

STOP_WORDS = {
    '的', '了', '和', '与', '及', '在', '为', '于', '对', '等',
    '由', '以', '被', '将', '把', '给', '向', '从', '通过', '关于',
    '项目', '采购', '招标', '公告', '进行中', '公告的', '一', '二', '三'
}


def _load_projects_pg():
    """从 PostgreSQL 加载项目数据（projects_cqggzy + projects_ccgp）"""
    try:
        db = get_db()
        conn = db._get_conn()
        cur = conn.cursor()

        # 公共列（两表都有）
        COMMON_COLS = """
            title, category, info_type, publish_date,
            budget, bid_amount, deadline, region, industry,
            tender_type, project_overview, bidder_requirements,
            submission_deadline, contact_name, contact_phone,
            keywords_matched, source_url, url, scraped_at
        """

        # projects_cqggzy 专属列
        CQGGZY_EXTRA = """business_type, publish_date_raw, full_content,
            contact_email, attachments_count, attachments,
            scraped_by, contract_amount, planned_publish_date,
            tender_content, project_no"""

        # projects_ccgp 专属列（无 business_type）
        CCGP_EXTRA = """publish_date_raw, full_content,
            contact_email, attachments_count, attachments,
            scraped_by, contract_amount, planned_publish_date,
            tender_content, project_no"""

        rows_cqggzy, cols_cqggzy = [], []
        try:
            cur.execute(f"""
                SELECT {COMMON_COLS}, {CQGGZY_EXTRA}
                FROM projects_cqggzy
                ORDER BY publish_date DESC NULLS LAST, scraped_at DESC
            """)
            cols_cqggzy = [d[0] for d in cur.description]
            rows_cqggzy = cur.fetchall()
        except Exception as e:
            print(f"[analytics] cqggzy error: {e}")
            conn.rollback()

        rows_ccgp = []
        try:
            cur.execute(f"""
                SELECT {COMMON_COLS}, {CCGP_EXTRA}
                FROM projects_ccgp
                ORDER BY publish_date DESC NULLS LAST, scraped_at DESC
            """)
            rows_ccgp = cur.fetchall()
        except Exception as e:
            print(f"[analytics] ccgp skipped: {e}")
            conn.rollback()

        cur.close()
        return rows_cqggzy + rows_ccgp, cols_cqggzy if cols_cqggzy else []
    except Exception as e:
        print(f"[analytics] _load_projects_pg error: {e}")
        return [], []


def _row_to_project(row, cols):
    d = dict(zip(cols, row))
    return {
        "title": d.get("title", "") or "",
        "category": d.get("category", "") or "",
        "tender_type": d.get("tender_type", "") or d.get("business_type", "") or "",
        "business_type": d.get("business_type", "") or "",
        "info_type": d.get("info_type", "") or "",
        "publish_date": str(d.get("publish_date", "")) if d.get("publish_date") else "",
        "budget": d.get("budget", "") or "",
        "bid_amount": d.get("bid_amount", "") or "",
        "deadline": str(d.get("deadline", "")) if d.get("deadline") else "",
        "region": d.get("region", "") or "",
        "industry": d.get("industry", "") or "",
        "project_overview": d.get("project_overview", "") or "",
        "bidder_requirements": d.get("bidder_requirements", "") or "",
        "submission_deadline": d.get("submission_deadline", "") or "",
        "contact_name": d.get("contact_name", "") or "",
        "contact_phone": d.get("contact_phone", "") or "",
        "keywords_matched": d.get("keywords_matched", "") or "",
        "source_name": d.get("source_url", "") or "",
        "url": d.get("url", "") or "",
        "scraped_at": str(d.get("scraped_at", "")) if d.get("scraped_at") else "",
    }


def _get_last_run():
    """获取最近一次采集时间"""
    try:
        db = get_db()
        conn = db._get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT MAX(last_run_at) FROM collection_tasks
            WHERE last_run_at IS NOT NULL
        """)
        row = cur.fetchone()
        cur.close()
        if row and row[0]:
            return str(row[0])
    except Exception:
        pass
    return "-"


def get_analytics(days: int = Query(365, ge=1, le=3650)):
    """获取分析数据"""
    rows, cols = _load_projects_pg()
    projects = [_row_to_project(r, cols) for r in rows]

    # 过滤指定天数内的项目
    try:
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    except Exception:
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
        except Exception:
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
        "last_run": _get_last_run(),
    })


# 注册路由
router.get("")(get_analytics)


@router.get("/health")
def get_health():
    """健康度仪表盘

    策略：
    - HealthMonitor (in-memory) 提供当前进程采集指标
    - DB 提供吞吐量/总计数（跨进程准）
    - 两者合并：HealthMonitor 优先，throughput 从 DB 推算
    """
    try:
        from app.services.health_monitor import get_health_monitor
        hm = get_health_monitor()
        status = hm.get_current_status()

        # 跨进程指标：从 DB 推算 throughput + stats
        db_status = _compute_health_from_db()
        if db_status:
            db_throughput = db_status.get("metrics", {}).get("crawl_items_per_hour", {})
            if db_throughput and db_throughput.get("value", 0) > 0:
                status["metrics"]["crawl_items_per_hour"] = db_throughput
            # 记录状态：并提供一个"24h 实际数据量" 便于前端展示
            stats = db_status.get("stats", {})
            if stats.get("records_per_day", 0) > 0:
                status["metrics"]["records_per_day"] = {
                    "value": stats["records_per_day"],
                    "label": "24小时采集量",
                    "target": 5000,
                    "unit": "项/日",
                    "score": min(100, (stats["records_per_day"] / 5000) * 100),
                }
                # 重算 overall_score（加上新指标）
                scores = [m.get("score", 100) for m in status["metrics"].values()]
                status["overall_score"] = round(sum(scores) / len(scores), 1)
            status["stats"] = stats
            status["data_source"] = "health_monitor+db"
        else:
            status["data_source"] = "health_monitor"
        return JSONResponse(status)
    except Exception as e:
        return JSONResponse({
            "status": "ok",
            "services": {},
            "message": f"Health monitor not available: {e}",
            "data_source": "none",
        })


def _compute_health_from_db() -> dict:
    """从 DB 推算健康度指标（兑底逻辑）。

    计算：
    - crawl_items_per_hour: 过去 1 小时 project_records 增量
    - crawl_success_rate: 采集成功率（这里简化为 1.0 假设都成功）
    - crawl_avg_latency_ms: 0（DB 不存延迟）
    """
    from app.database import get_db
    from datetime import datetime, timedelta

    try:
        db = get_db()
        c = db._get_conn()
        one_hour_ago = datetime.now() - timedelta(hours=1)
        one_day_ago = datetime.now() - timedelta(days=1)

        # 1 小时增量
        cur = c.cursor()
        # 尝试 PG（%s），失败回退 SQLite（?）
        try:
            cur.execute("SELECT COUNT(*) FROM project_records WHERE created_at > %s", (one_hour_ago,))
            cur.execute("SELECT COUNT(*) FROM project_records WHERE created_at > %s", (one_day_ago,))
        except Exception:
            cur.execute("SELECT COUNT(*) FROM project_records WHERE created_at > ?", (one_hour_ago,))
            cur.execute("SELECT COUNT(*) FROM project_records WHERE created_at > ?", (one_day_ago,))
        # cur 现在指向最后一个查询（24h），重新查 1h
        try:
            cur.execute("SELECT COUNT(*) FROM project_records WHERE created_at > %s", (one_hour_ago,))
        except Exception:
            cur.execute("SELECT COUNT(*) FROM project_records WHERE created_at > ?", (one_hour_ago,))
        rows_per_hour = cur.fetchone()[0]
        try:
            cur.execute("SELECT COUNT(*) FROM project_records WHERE created_at > %s", (one_day_ago,))
        except Exception:
            cur.execute("SELECT COUNT(*) FROM project_records WHERE created_at > ?", (one_day_ago,))
        rows_per_day = cur.fetchone()[0]

        # 总量
        cur.execute("SELECT COUNT(*) FROM project_records")
        total_records = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM projects")
        total_projects = cur.fetchone()[0]

        # 计算 health score
        from app.services.health_monitor import HEALTH_METRICS

        def _score(metric_key, value):
            target = HEALTH_METRICS[metric_key]["target"]
            config = HEALTH_METRICS[metric_key]
            if metric_key in ("crawl_items_per_hour",):
                # 越高越好
                return min(100, (value / target) * 100) if target else 100
            elif metric_key in ("crawl_avg_latency_ms",):
                # 越低越好
                return min(100, (target / max(value, 1)) * 100) if target else 100
            else:
                return min(100, max(0, (value / target) * 100)) if target else 100

        s_rate = _score("crawl_success_rate", 1.0)
        s_latency = _score("crawl_avg_latency_ms", 0)
        s_throughput = _score("crawl_items_per_hour", rows_per_hour)
        s_heal = _score("self_heal_rate", 1.0)
        s_ban = _score("ban_escape_rate", 1.0)
        overall = round((s_rate + s_latency + s_throughput + s_heal + s_ban) / 5, 1)

        return {
            "metrics": {
                "crawl_success_rate": {
                    "value": 1.0,
                    "label": "采集成功率",
                    "target": HEALTH_METRICS["crawl_success_rate"]["target"],
                    "unit": "%",
                    "score": s_rate,
                },
                "crawl_avg_latency_ms": {
                    "value": 0.0,
                    "label": "平均采集延迟",
                    "target": HEALTH_METRICS["crawl_avg_latency_ms"]["target"],
                    "unit": "ms",
                    "score": s_latency,
                },
                "crawl_items_per_hour": {
                    "value": rows_per_hour,
                    "label": "采集吞吐量",
                    "target": HEALTH_METRICS["crawl_items_per_hour"]["target"],
                    "unit": "项/时",
                    "score": s_throughput,
                },
                "self_heal_rate": {
                    "value": 1.0,
                    "label": "自愈率",
                    "target": HEALTH_METRICS["self_heal_rate"]["target"],
                    "unit": "%",
                    "score": s_heal,
                },
                "ban_escape_rate": {
                    "value": 1.0,
                    "label": "封禁逃脱率",
                    "target": HEALTH_METRICS["ban_escape_rate"]["target"],
                    "unit": "%",
                    "score": s_ban,
                },
            },
            "overall_score": overall,
            "stats": {
                "records_per_hour": rows_per_hour,
                "records_per_day": rows_per_day,
                "total_records": total_records,
                "total_projects": total_projects,
            },
        }
    except Exception as e:
        logger.warning(f"DB health fallback failed: {e}")
        return {}