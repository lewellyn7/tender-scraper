#!/bin/bash
# 分批次重新采集脚本
# 用法：./scripts/batch-recrawl.sh [cqggzy|ccgp] [batch_size] [delay_seconds]

set -e

SOURCE=${1:-cqggzy}
BATCH_SIZE=${2:-20}
DELAY=${3:-5}
RETRY=${4:-false}

echo "=========================================="
echo "🚀 分批次重新采集"
echo "=========================================="
echo "数据源：$SOURCE"
echo "每批数量：$BATCH_SIZE"
echo "批次延时：${DELAY}秒"
echo "重试失败：$RETRY"
echo "=========================================="

cd ~/tender-scraper

# 检查容器状态
if ! docker compose ps | grep -q "tender-scraper-web.*healthy"; then
    echo "❌ Web 容器未运行"
    exit 1
fi

# 执行采集
if [ "$RETRY" = "true" ] || [ "$RETRY" = "--retry-failed" ]; then
    docker compose exec web python -m scripts.batch_recrawl_simple \
        --source "$SOURCE" \
        --batch-size "$BATCH_SIZE" \
        --delay "$DELAY" \
        --retry-failed
else
    docker compose exec web python -m scripts.batch_recrawl_simple \
        --source "$SOURCE" \
        --batch-size "$BATCH_SIZE" \
        --delay "$DELAY"
fi

echo ""
echo "=========================================="
echo "✅ 采集完成"
echo "=========================================="
