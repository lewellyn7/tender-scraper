#!/bin/bash
# backfill_daily_v2.sh — 按日回填 v2 启动脚本
# 启动 5 个 worker 进程 (静态分片), 每 worker 处理一段日期范围
# 设计: 5 worker × ~103 天 = 517 天 (2026-05-31 → 2024-01-01)
#
# 5 worker 静态分片 (倒序: 最近日→最旧日, 882 天 ÷ 5 = ~176 天/worker):
#   w1: 2026-05-31 → 2025-12-06 (177 天)
#   w2: 2025-12-05 → 2025-06-12 (177 天)
#   w3: 2025-06-11 → 2024-12-18 (176 天)
#   w4: 2024-12-17 → 2024-06-25 (176 天)
#   w5: 2024-06-24 → 2024-01-01 (176 天)
#
# 注意: 2024Q1 (2024-01-01 ~ 2024-03-31) 已在之前的 backfill_recent.py 跑过,
#       w5 起步时 tracker 表里部分日期可能已 success, worker 自动跳过
#
# 用法:
#   ./scripts/backfill_daily_v2.sh start    # 启动 5 worker
#   ./scripts/backfill_daily_v2.sh status   # 查看状态
#   ./scripts/backfill_daily_v2.sh stop     # 停止所有 worker
#   ./scripts/backfill_daily_v2.sh restart  # 重启

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$( cd "${SCRIPT_DIR}/.." && pwd )"
# 默认 logs 目录, 可用 BACKFILL_LOG_DIR 覆盖 (容器内可能用 /tmp 或 /app/logs)
LOG_DIR="${BACKFILL_LOG_DIR:-logs/backfill_v2}"
mkdir -p "$LOG_DIR" 2>/dev/null || LOG_DIR="/tmp/backfill_v2" && mkdir -p "$LOG_DIR"
echo "日志目录: $LOG_DIR"

# 日期分片 (倒序: start > end), 882 天 / 5 ≈ 176 天/worker
W1_START="2026-05-31"; W1_END="2025-12-06"
W2_START="2025-12-05"; W2_END="2025-06-12"
W3_START="2025-06-11"; W3_END="2024-12-18"
W4_START="2024-12-17"; W4_END="2024-06-25"
W5_START="2024-06-24"; W5_END="2024-01-01"

start_worker() {
    local wid=$1
    local s=$2
    local e=$3
    local logfile="$LOG_DIR/${wid}.log"
    
    # 检查是否已跑 (用 ps + grep, 容器内可能没 pgrep)
    if ps -ef | grep "backfill_day_worker.py --worker-id $wid" | grep -v grep > /dev/null; then
        local existing_pid=$(ps -ef | grep "backfill_day_worker.py --worker-id $wid" | grep -v grep | awk '{print $2}' | head -1)
        echo "⚠️  $wid 已在跑 (PID: $existing_pid)"
        return 1
    fi
    
    echo "🚀 启动 $wid: $s → $e"
    nohup python3 scripts/backfill_day_worker.py \
        --worker-id "$wid" \
        --start "$s" \
        --end "$e" \
        > "$logfile" 2>&1 &
    local pid=$!
    echo "   PID: $pid, log: $logfile"
    sleep 2
    if ! kill -0 $pid 2>/dev/null; then
        echo "❌ $wid 启动后立即退出, 查看 $logfile"
        return 1
    fi
    return 0
}

start_all() {
    echo "=========================================="
    echo "  按日回填 v2 — 5 worker 启动"
    echo "  起点: 2026-05-31 (最近日)"
    echo "  终点: 2024-01-01 (最旧日)"
    echo "  总计: ~517 天 / 5 worker = ~103 天/worker"
    echo "  估算: ~12-15 小时 (含重试缓冲)"
    echo "=========================================="
    echo ""
    start_worker w1 $W1_START $W1_END
    start_worker w2 $W2_START $W2_END
    start_worker w3 $W3_START $W3_END
    start_worker w4 $W4_START $W4_END
    start_worker w5 $W5_START $W5_END
    echo ""
    echo "✅ 5 worker 全部启动"
    echo "📊 状态: ./scripts/backfill_daily_v2.sh status"
    echo "📜 实时日志: tail -f $LOG_DIR/w1.log"
}

status() {
    echo "=========================================="
    echo "  Worker 进程状态 (查 collector 容器内 /proc)"
    echo "=========================================="
    for wid in w1 w2 w3 w4 w5; do
        # host 查
        local host_pids=$(pgrep -f "backfill_day_worker.py --worker-id $wid" 2>/dev/null | tr '\n' ' ')
        # 容器内查 (/proc 方式, 容器内可能无 ps)
        local container_pids=$(docker exec tender-scraper-collector sh -c "
            for pid in /proc/[0-9]*; do
                pid_num=\$(basename \$pid)
                cmdline=\$(cat \$pid/cmdline 2>/dev/null | tr '\0' ' ')
                if echo \"\$cmdline\" | grep -q \"backfill_day_worker.py --worker-id $wid\"; then
                    echo -n \"\$pid_num \"
                fi
            done
        " 2>/dev/null | tr -d '\n' | sed 's/ $//')
        local pids="${host_pids}${container_pids}"
        if [ -n "$pids" ]; then
            local logfile="$LOG_DIR/${wid}.log"
            local last_line=$(tail -1 "$logfile" 2>/dev/null | head -c 100)
            echo "✅ $wid  PID: $pids"
            echo "   最后日志: $last_line"
        else
            echo "❌ $wid  未运行"
        fi
    done
    echo ""
    echo "=========================================="
    echo "  DB 进度 (回填记忆表)"
    echo "=========================================="
    docker exec tender-scraper-postgres psql -U root -d tender_scraper -c "
        SELECT 
            status, COUNT(*) as rows
        FROM backfill_tracker
        GROUP BY status
        ORDER BY status;
    " 2>&1
    echo ""
    docker exec tender-scraper-postgres psql -U root -d tender_scraper -c "
        SELECT 
            target_date, 
            SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success,
            SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed,
            SUM(CASE WHEN status='blocked' THEN 1 ELSE 0 END) as blocked,
            SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) as running,
            SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending,
            SUM(expected_count) as expected,
            SUM(actual_count) as actual
        FROM backfill_tracker
        GROUP BY target_date
        ORDER BY target_date DESC
        LIMIT 10;
    " 2>&1
}

stop_all() {
    echo "=========================================="
    echo "  停止所有 worker (host + collector 容器)"
    echo "=========================================="
    for wid in w1 w2 w3 w4 w5; do
        # host 进程
        local host_pids=$(pgrep -f "backfill_day_worker.py --worker-id $wid" 2>/dev/null)
        if [ -n "$host_pids" ]; then
            echo "🛑 停止 host $wid (PID: $host_pids)"
            kill $host_pids 2>/dev/null || true
            sleep 1
            if kill -0 $host_pids 2>/dev/null; then
                kill -9 $host_pids 2>/dev/null || true
            fi
        fi
        # 容器内进程 (/proc 方式)
        local container_pids=$(docker exec tender-scraper-collector sh -c "
            for pid in /proc/[0-9]*; do
                pid_num=\$(basename \$pid)
                cmdline=\$(cat \$pid/cmdline 2>/dev/null | tr '\0' ' ')
                if echo \"\$cmdline\" | grep -q \"backfill_day_worker.py --worker-id $wid\"; then
                    echo \$pid_num
                fi
            done
        " 2>/dev/null)
        if [ -n "$container_pids" ]; then
            echo "🛑 停止 container $wid (PID: $container_pids)"
            docker exec tender-scraper-collector kill $container_pids 2>/dev/null || true
            sleep 1
        fi
    done
    echo "✅ 全部停止"
}

case "${1:-status}" in
    start)   start_all ;;
    stop)    stop_all ;;
    restart) stop_all; sleep 2; start_all ;;
    status)  status ;;
    *)       echo "用法: $0 {start|stop|restart|status}"; exit 1 ;;
esac
