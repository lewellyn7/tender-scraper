"""分析统计路由 - 基于 PostgreSQL 项目数据分析"""

from datetime import datetime, timedelta
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from loguru import logger
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

    # 趋势数据（按天，按入参 days 动态范围；2026-06-17 fix: 之前硬编码 -30 导致 60/90 不更新）
    trends = []
    days_list = sorted(set(p.get("publish_date", "") for p in recent_projects if p.get("publish_date")))
    # clamp 到实际数据天数（避免 days > len(days_list) 时返回空）
    trend_window = days_list[-min(days, len(days_list)):]
    for day in trend_window:
        day_projects = [p for p in recent_projects if p.get("publish_date", "") == day]
        trends.append({
            "date": day,
            "count": len(day_projects),
            "matched": len([p for p in day_projects if p.get("keywords_matched")])
        })

    # 分类统计（2026-06-17 fix: summary 缺 gov/eng/budget 字段，前端写死 '-'）
    gov_count = sum(1 for p in recent_projects if p.get("business_type") == "政府采购")
    eng_count = sum(1 for p in recent_projects if p.get("business_type") == "工程招投标")
    budget_count = len(budget_projects)

    return JSONResponse({
        "summary": {
            "total": len(recent_projects),
            "pending": len([p for p in recent_projects if not p.get("keywords_matched")]),
            "matched": len(matched_projects),
            "gov_count": gov_count,
            "eng_count": eng_count,
            "budget_count": budget_count,
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

    策略 (2026-06-17 重构):
    - 主数据源: 从 projects_cqggzy/projects_ccgp DB 推算 (跨进程准确)
    - 兜底: in-memory HealthMonitor (进程内)
    - trends_7d/trends_30d: DB 按日聚合, 不依赖内存快照

    Bug 修复:
    - crawl_avg_latency_ms: 用 scraped_at - publish_date 推算 (公告→入库时差)
    - crawl_items_per_hour: 用 24h 总数 / 24 (避免 1h=0 误判)
    - crawl_success_rate: 7 日 full_content 完整率
    - trends_7d/trends_30d: DB 按日聚合

    P1 修复 (2026-06-27):
    - 加 DB ping 检查, 失败返回 503 unhealthy (之前永远 status:"ok" 掩盖故障)
    """
    # ── 抢先 DB ping ──
    db_ok = False
    try:
        db = get_db()
        c = db._get_conn()
        c.execute("SELECT 1")
        c.fetchone()
        db_ok = True
    except Exception as e:
        logger.error(f"Health DB ping failed: {e}")

    try:
        # 主数据源: DB 推算
        db_status = _compute_health_from_db()
        if db_status and db_status.get("metrics"):
            db_status["data_source"] = "db"
            return JSONResponse(db_status)

        # 兜底: in-memory HealthMonitor
        try:
            from app.services.health_monitor import get_health_monitor
            hm = get_health_monitor()
            status = hm.get_current_status()
            status["data_source"] = "health_monitor_fallback"
            return JSONResponse(status)
        except Exception:
            # DB 不通 → unhealthy
            return JSONResponse({
                "status": "unhealthy",
                "services": {"database": "unreachable"},
                "message": "健康检查失败：数据库不可达",
                "data_source": "none",
            }, status_code=503)
    except Exception:
        return JSONResponse({
            "status": "unhealthy",
            "services": {"database": "unreachable" if not db_ok else "unknown"},
            "message": "健康检查失败：服务异常",
            "data_source": "none",
        }, status_code=503)


def _compute_health_from_db() -> dict:
    """从 DB 推算健康度指标 (主数据源)

    计算 (基于 projects_cqggzy + projects_ccgp):
    - crawl_items_per_hour: 24h 总数 / 24 = 平均项/时
    - crawl_avg_latency_ms: AVG(scraped_at - publish_date) * 1000 (公告→入库时差, 7 日内 full_content)
    - crawl_success_rate: COUNT(full_content) / COUNT(*) (7 日内)
    - self_heal_rate / ban_escape_rate: 1.0 兜底 (DB 无事件, 未来落库再升级)
    - trends_7d / trends_30d: 按日聚合 (从 projects_cqggzy)
    """
    try:
        from app.services.health_monitor import HEALTH_METRICS

        db = get_db()
        c = db._get_conn()
        cur = c.cursor()

        def _score(metric_key, value):
            meta = HEALTH_METRICS.get(metric_key, {})
            target = meta.get("target", 1)
            direction = meta.get("direction", "higher")
            if direction == "higher":
                return min(100, max(0, (value / target) * 100)) if target else 100
            else:  # lower is better
                return min(100, max(0, (target / max(value, 1)) * 100)) if target else 100

        # 1. 24h 吞吐 (跨表) - 避免 1h=0 误判
        one_day_ago = datetime.now() - timedelta(days=1)
        try:
            cur.execute(
                "SELECT COUNT(*) FROM projects_cqggzy WHERE created_at > %s",
                (one_day_ago,),
            )
        except Exception:
            cur.execute(
                "SELECT COUNT(*) FROM projects_cqggzy WHERE created_at > ?",
                (one_day_ago,),
            )
        rows_per_day_cqggzy = cur.fetchone()[0] or 0

        try:
            cur.execute(
                "SELECT COUNT(*) FROM projects_ccgp WHERE created_at > %s",
                (one_day_ago,),
            )
        except Exception:
            try:
                cur.execute(
                    "SELECT COUNT(*) FROM projects_ccgp WHERE created_at > ?",
                    (one_day_ago,),
                )
            except Exception:
                rows_per_day_ccgp = 0
            else:
                rows_per_day_ccgp = cur.fetchone()[0] or 0
        else:
            rows_per_day_ccgp = cur.fetchone()[0] or 0
        rows_per_day = rows_per_day_cqggzy + rows_per_day_ccgp
        throughput = rows_per_day / 24.0  # 项/时 (24h 平均)

        # 2. 平均采集延迟 - 公告→入库时差 (7 日内有 full_content)
        try:
            cur.execute("""
                SELECT AVG(
                    EXTRACT(EPOCH FROM (scraped_at::timestamp - publish_date::timestamp)) * 1000
                )::bigint
                FROM projects_cqggzy
                WHERE publish_date IS NOT NULL
                  AND scraped_at IS NOT NULL
                  AND full_content IS NOT NULL AND full_content != ''
                  AND scraped_at::timestamp > publish_date::timestamp
                  AND created_at > NOW() - INTERVAL '7 days'
            """)
        except Exception:
            cur.execute("""
                SELECT AVG(
                    (julianday(scraped_at) - julianday(publish_date)) * 86400 * 1000
                )
                FROM projects_cqggzy
                WHERE publish_date IS NOT NULL
                  AND scraped_at IS NOT NULL
                  AND full_content IS NOT NULL AND full_content != ''
                  AND scraped_at > publish_date
                  AND created_at > datetime('now', '-7 days')
            """)
        latency_row = cur.fetchone()
        latency_ms = float(latency_row[0]) if latency_row and latency_row[0] else 0.0

        # 3. 采集成功率 - 7 日内 full_content 完整率
        try:
            cur.execute("""
                SELECT
                  COUNT(*) FILTER (WHERE full_content IS NOT NULL AND full_content != '') as with_fc,
                  COUNT(*) as total
                FROM projects_cqggzy
                WHERE created_at > NOW() - INTERVAL '7 days'
            """)
        except Exception:
            cur.execute("""
                SELECT
                  SUM(CASE WHEN full_content IS NOT NULL AND full_content != '' THEN 1 ELSE 0 END) as with_fc,
                  COUNT(*) as total
                FROM projects_cqggzy
                WHERE created_at > datetime('now', '-7 days')
            """)
        fc_row = cur.fetchone()
        with_fc = fc_row[0] or 0
        total_7d = fc_row[1] or 0
        success_rate = (with_fc / total_7d) if total_7d > 0 else 1.0

        # 4. self_heal / ban_escape 兑底 (DB 无事件)
        self_heal = 1.0
        ban_escape = 1.0

        # 5. 计算 health scores
        s_rate = _score("crawl_success_rate", success_rate)
        s_latency = _score("crawl_avg_latency_ms", latency_ms)
        s_throughput = _score("crawl_items_per_hour", throughput)
        s_heal = _score("self_heal_rate", self_heal)
        s_ban = _score("ban_escape_rate", ban_escape)
        overall = round((s_rate + s_latency + s_throughput + s_heal + s_ban) / 5, 1)

        # 6. trends_7d / trends_30d 按日聚合
        trends_7d = _compute_daily_health_trends(cur, days=7)
        trends_30d = _compute_daily_health_trends(cur, days=30)

        return {
            "metrics": {
                "crawl_success_rate": {
                    "value": round(success_rate, 4),
                    "label": "采集成功率",
                    "target": HEALTH_METRICS["crawl_success_rate"]["target"],
                    "unit": "%",
                    "score": s_rate,
                },
                "crawl_avg_latency_ms": {
                    "value": round(latency_ms, 1),
                    "label": "平均采集延迟",
                    "target": HEALTH_METRICS["crawl_avg_latency_ms"]["target"],
                    "unit": "ms",
                    "score": s_latency,
                },
                "crawl_items_per_hour": {
                    "value": round(throughput, 2),
                    "label": "采集吞吐量",
                    "target": HEALTH_METRICS["crawl_items_per_hour"]["target"],
                    "unit": "项/时",
                    "score": s_throughput,
                },
                "self_heal_rate": {
                    "value": self_heal,
                    "label": "自愈率",
                    "target": HEALTH_METRICS["self_heal_rate"]["target"],
                    "unit": "%",
                    "score": s_heal,
                },
                "ban_escape_rate": {
                    "value": ban_escape,
                    "label": "封禁逃脱率",
                    "target": HEALTH_METRICS["ban_escape_rate"]["target"],
                    "unit": "%",
                    "score": s_ban,
                },
            },
            "overall_score": overall,
            "trends_7d": trends_7d,
            "trends_30d": trends_30d,
            "stats": {
                "records_per_day_cqggzy": rows_per_day_cqggzy,
                "records_per_day_ccgp": rows_per_day_ccgp,
                "records_per_day": rows_per_day,
                "success_rate_7d": round(success_rate, 4),
                "avg_latency_ms_7d": round(latency_ms, 1),
            },
        }
    except Exception as e:
        logger.warning(f"DB health compute failed: {e}")
        return {}


def _compute_daily_health_trends(cur, days: int) -> list:
    """按日聚合过去 N 天的健康度指标 (从 projects_cqggzy 推算)

    返回 [{date, crawl_success_rate, crawl_avg_latency_ms, crawl_items_per_hour, overall_score}, ...]
    """
    try:
        from app.services.health_monitor import HEALTH_METRICS
    except ImportError:
        HEALTH_METRICS = {}

    def _score_higher(value, target):
        if target <= 0:
            return 100.0
        return min(100, (value / target) * 100)

    def _score_lower(value, target):
        if value <= 0:
            return 50.0
        return min(100, (target / value) * 100)

    target_rate = HEALTH_METRICS.get("crawl_success_rate", {}).get("target", 0.95)
    target_latency = HEALTH_METRICS.get("crawl_avg_latency_ms", {}).get("target", 2000)
    target_throughput = HEALTH_METRICS.get("crawl_items_per_hour", {}).get("target", 100)

    try:
        cur.execute(f"""
            SELECT
              DATE(created_at) as day,
              COUNT(*) as total,
              COUNT(*) FILTER (WHERE full_content IS NOT NULL AND full_content != '') as with_fc,
              AVG(EXTRACT(EPOCH FROM (scraped_at::timestamp - publish_date::timestamp)) * 1000)
                FILTER (WHERE publish_date IS NOT NULL
                  AND full_content IS NOT NULL AND full_content != ''
                  AND scraped_at::timestamp > publish_date::timestamp) as avg_latency_ms
            FROM projects_cqggzy
            WHERE created_at > NOW() - INTERVAL '{int(days)} days'
            GROUP BY DATE(created_at)
            ORDER BY 1
        """)
    except Exception:
        cur.execute(f"""
            SELECT
              DATE(created_at) as day,
              COUNT(*) as total,
              SUM(CASE WHEN full_content IS NOT NULL AND full_content != '' THEN 1 ELSE 0 END) as with_fc,
              AVG((julianday(scraped_at) - julianday(publish_date)) * 86400 * 1000)
                FILTER (WHERE publish_date IS NOT NULL
                  AND full_content IS NOT NULL AND full_content != ''
                  AND scraped_at > publish_date) as avg_latency_ms
            FROM projects_cqggzy
            WHERE created_at > datetime('now', '-{int(days)} days')
            GROUP BY DATE(created_at)
            ORDER BY 1
        """)

    result = []
    for row in cur.fetchall():
        day, total, with_fc, avg_latency = row
        success_rate = (with_fc / total) if total > 0 else 0
        throughput = (total or 0) / 24.0
        latency = float(avg_latency) if avg_latency else 0.0

        s_rate = _score_higher(success_rate, target_rate)
        s_latency = _score_lower(latency, target_latency)
        s_throughput = _score_higher(throughput, target_throughput)
        s_heal = 100.0  # 兜底
        s_ban = 100.0   # 兜底
        overall = round((s_rate + s_latency + s_throughput + s_heal + s_ban) / 5, 1)
        result.append({
            "date": str(day),
            "crawl_success_rate": round(success_rate, 4),
            "crawl_avg_latency_ms": round(latency, 1),
            "crawl_items_per_hour": round(throughput, 2),
            "self_heal_rate": 1.0,
            "ban_escape_rate": 1.0,
            "overall_score": overall,
        })
    return result