#!/bin/bash
# check_backfill_health.sh — 回填心跳检查 (cron 每小时跑)
# 
# 检查项:
#   1. 5 worker 进程都在?
#   2. tracker: status='running' 且 started_at > 30min? → 标记 blocked
#   3. tracker: diff_count > 0? → 漏采报警
#   4. tracker: 连续 retry > 3 → blocked 报警
#   5. 当前进度: 完成率
# 
# 用法: 
#   ./scripts/check_backfill_health.sh            # 跑检查 + 打印报告
#   ./scripts/check_backfill_health.sh --alert    # 检查 + 发送 telegram (TODO)

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$( cd "${SCRIPT_DIR}/.." && pwd )"

# 1. 检查 worker 进程
echo "=========================================="
echo "  $(date '+%Y-%m-%d %H:%M:%S') 心跳检查"
echo "=========================================="
echo ""
echo "▶ Worker 进程状态 (查 host + collector 容器 /proc):"
WORKER_OK=0
WORKER_DOWN=0
for wid in w1 w2 w3 w4 w5; do
    # host
    host_pids=$(pgrep -f "backfill_day_worker.py --worker-id $wid" 2>/dev/null | tr '\n' ' ')
    # 容器内 (/proc)
    container_pids=$(docker exec tender-scraper-collector sh -c "
        for pid in /proc/[0-9]*; do
            pid_num=\$(basename \$pid)
            cmdline=\$(cat \$pid/cmdline 2>/dev/null | tr '\0' ' ')
            if echo \"\$cmdline\" | grep -q \"backfill_day_worker.py --worker-id $wid\"; then
                echo -n \"\$pid_num \"
            fi
        done
    " 2>/dev/null | tr -d '\n' | sed 's/ $//')
    pids="${host_pids}${container_pids}"
    if [ -n "$pids" ]; then
        echo "  ✅ $wid  PID: $pids"
        WORKER_OK=$((WORKER_OK+1))
    else
        echo "  ❌ $wid  DOWN"
        WORKER_DOWN=$((WORKER_DOWN+1))
    fi
done
echo ""
echo "  汇总: ${WORKER_OK} 个 up, ${WORKER_DOWN} 个 down"
echo ""

# 2. 检查 status='running' 但 started_at > 30min → 标记 blocked
echo "▶ 卡死检测 (running > 30min → blocked):"
STUCK_BEFORE=$(date -u -d '30 minutes ago' '+%Y-%m-%d %H:%M:%S')
STUCK_COUNT=$(docker exec tender-scraper-postgres psql -U root -d tender_scraper -t -A -c "
    UPDATE backfill_tracker 
    SET status='blocked', last_error='stuck: running > 30min, auto-blocked by health check'
    WHERE status='running' AND started_at < '$STUCK_BEFORE'
    RETURNING id;
" 2>&1 | grep -c "^[0-9]" || echo "0")

STUCK_DETAILS=$(docker exec tender-scraper-postgres psql -U root -d tender_scraper -c "
    SELECT target_date, category, retry_count, last_error
    FROM backfill_tracker
    WHERE status='blocked' AND last_error LIKE 'stuck: running%'
    ORDER BY updated_at DESC LIMIT 5;
" 2>&1 | tail -n +3)
if [ -n "$STUCK_DETAILS" ]; then
    echo "$STUCK_DETAILS" | sed 's/^/    /'
fi
echo "  标记了 $STUCK_COUNT 条卡死任务"
echo ""

# 3. 当前进度
echo "▶ 回填进度:"
docker exec tender-scraper-postgres psql -U root -d tender_scraper -c "
    SELECT 
        status, 
        COUNT(*) as rows,
        ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as pct
    FROM backfill_tracker
    GROUP BY status
    ORDER BY rows DESC;
" 2>&1
echo ""

# 4. 数据量核对 (diff_count > 0)
echo "▶ 数量核对 (diff_count > 0 → 漏采):"
DIFF_COUNT=$(docker exec tender-scraper-postgres psql -U root -d tender_scraper -t -A -c "
    SELECT COUNT(*) FROM backfill_tracker 
    WHERE status='success' AND diff_count > 0;
" 2>&1 | tr -d ' ')
echo "  $DIFF_COUNT 条有差异"
docker exec tender-scraper-postgres psql -U root -d tender_scraper -c "
    SELECT target_date, category, expected_count, actual_count, diff_count
    FROM backfill_tracker
    WHERE status='success' AND diff_count > 0
    ORDER BY diff_count DESC LIMIT 5;
" 2>&1 | tail -n +3 | sed 's/^/    /'
echo ""

# 5. 最近 5 天完成度
echo "▶ 最近 5 天完成度:"
docker exec tender-scraper-postgres psql -U root -d tender_scraper -c "
    SELECT 
        target_date,
        COUNT(*) FILTER (WHERE status='success') as success,
        COUNT(*) FILTER (WHERE status='failed') as failed,
        COUNT(*) FILTER (WHERE status='blocked') as blocked,
        COUNT(*) FILTER (WHERE status='pending') as pending,
        SUM(expected_count) as expected,
        SUM(actual_count) as actual,
        ROUND(SUM(actual_count) * 100.0 / NULLIF(SUM(expected_count), 0), 1) as pct
    FROM backfill_tracker
    WHERE target_date >= (CURRENT_DATE - INTERVAL '5 days')
    GROUP BY target_date
    ORDER BY target_date DESC;
" 2>&1
echo ""

# 6. 总览
TOTAL_DATES=$(docker exec tender-scraper-postgres psql -U root -d tender_scraper -t -A -c "SELECT COUNT(DISTINCT target_date) FROM backfill_tracker;" 2>&1 | tr -d ' ')
TOTAL_ROWS=$(docker exec tender-scraper-postgres psql -U root -d tender_scraper -t -A -c "SELECT COUNT(*) FROM backfill_tracker;" 2>&1 | tr -d ' ')
SUCCESS_ROWS=$(docker exec tender-scraper-postgres psql -U root -d tender_scraper -t -A -c "SELECT COUNT(*) FROM backfill_tracker WHERE status='success';" 2>&1 | tr -d ' ')
echo "=========================================="
echo "  总览: ${TOTAL_DATES} 天 × 9 分类 = ${TOTAL_ROWS} 行 tracker"
echo "  Success: ${SUCCESS_ROWS} (${SUCCESS_ROWS}*100/${TOTAL_ROWS:-1} = $(echo "scale=1; ${SUCCESS_ROWS:-0} * 100 / ${TOTAL_ROWS:-1}" | bc)%)"
echo "  Worker: ${WORKER_OK}/5 up, ${WORKER_DOWN}/5 down"
echo "  Stuck: ${STUCK_COUNT} 条标记 blocked"
echo "  Diff: ${DIFF_COUNT} 条 success 有差异"
echo "=========================================="

# TODO: 发送 telegram
# if [ "$WORKER_DOWN" -gt 0 ] || [ "$STUCK_COUNT" -gt 0 ] || [ "$DIFF_COUNT" -gt 50 ]; then
#     curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
#         -d "chat_id=${TELEGRAM_CHAT_ID}" \
#         -d "text=⚠️ 回填异常: ${WORKER_DOWN} worker down, ${STUCK_COUNT} stuck, ${DIFF_COUNT} diff"
# fi
