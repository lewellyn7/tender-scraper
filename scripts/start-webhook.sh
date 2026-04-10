#!/bin/bash
# ============================================================
# 启动 Webhook 部署服务器
# 通过 Tailscale HTTPS 暴露到互联网，接收 GitHub Actions 部署触发
#
# 用法:
#   ./start-webhook.sh                    # 前台运行
#   ./start-webhook.sh --daemon           # 后台运行
#   ./start-webhook.sh --tailscale        # 通过 Tailscale 暴露
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
WEBHOOK_PORT=8084
DEPLOY_SECRET="${DEPLOY_SECRET:-tender_scraper_deploy_secret_2026}"

echo "============================================================"
echo "  🚀 Tender-Scraper Webhook 部署服务器"
echo "============================================================"
echo "  项目目录: $PROJECT_DIR"
echo "  监听端口: $WEBHOOK_PORT"
echo "  Tailscale: $(which tailscale >/dev/null 2>&1 && echo '可用' || echo '不可用')"
echo ""

# 检查 docker compose prod 文件
if [ ! -f "$PROJECT_DIR/docker-compose.prod.yml" ]; then
    echo "⚠️  docker-compose.prod.yml 不存在，从 docker-compose.yml 复制..."
    cp "$PROJECT_DIR/docker-compose.yml" "$PROJECT_DIR/docker-compose.prod.yml"
fi

# 检查 Python webhook 脚本
if [ ! -f "$SCRIPT_DIR/deploy-webhook.py" ]; then
    echo "❌ deploy-webhook.py 不存在！"
    exit 1
fi

# 检查环境变量
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "⚠️  .env 文件不存在，从 .env.production 复制..."
    cp "$PROJECT_DIR/.env.production" "$PROJECT_DIR/.env"
    echo "⚠️  请编辑 $PROJECT_DIR/.env 填入实际值！"
fi

# 启动方式
case "${1:-}" in
    --daemon)
        echo "📡 以守护进程启动..."
        nohup python3 "$SCRIPT_DIR/deploy-webhook.py" \
            --port $WEBHOOK_PORT \
            --secret "$DEPLOY_SECRET" \
            >> /tmp/deploy-webhook.log 2>&1 &
        echo "✅ Webhook 服务已后台启动 (PID: $!)"
        echo "📝 日志: /tmp/deploy-webhook.log"
        ;;
    --tailscale)
        echo "📡 通过 Tailscale 暴露服务..."
        # 先启动 webhook
        python3 "$SCRIPT_DIR/deploy-webhook.py" \
            --port $WEBHOOK_PORT \
            --secret "$DEPLOY_SECRET" \
            &
        WEBHOOK_PID=$!
        sleep 2
        
        # 通过 Tailscale serve 暴露
        echo "🌐 配置 Tailscale HTTPS 暴露..."
        sudo tailscale serve --bg tcp $WEBHOOK_PORT 2>/dev/null || \
            tailscale serve --bg tcp $WEBHOOK_PORT 2>/dev/null || \
            echo "⚠️  tailscale serve 需要 sudo 或 Tailscale 设置"
        
        TAILSCALE_URL=$(tailscale serve status 2>/dev/null | grep -oP 'https://[^ ]+' | head -1)
        echo ""
        echo "============================================================"
        echo "  ✅ Webhook 服务已启动"
        echo "  🌐 URL: ${TAILSCALE_URL:-http://localhost:$WEBHOOK_PORT}"
        echo "  📝 在 GitHub Actions 中设置 WEBHOOK_URL secret"
        echo ""
        echo "  GitHub Actions 配置示例:"
        echo "    - name: Trigger Deploy"
        echo "      run: |
        echo "        curl -X POST \${WEBHOOK_URL}/webhook/deploy \"
        echo "          -H 'Content-Type: application/json' \"
        echo "          -d '{\"action\":\"deploy\",\"ref\":\"\${{ github.ref }}\"}'"
        echo "============================================================"
        ;;
    --stop)
        echo "🛑 停止 Webhook 服务..."
        pkill -f "deploy-webhook.py" && echo "✅ 已停止" || echo "⚠️  未运行"
        ;;
    *)
        echo "📝 启动选项:"
        echo "   ./start-webhook.sh              # 前台运行"
        echo "   ./start-webhook.sh --daemon     # 后台守护进程"
        echo "   ./start-webhook.sh --tailscale  # 通过 Tailscale HTTPS 暴露"
        echo "   ./start-webhook.sh --stop       # 停止服务"
        echo ""
        echo "🌐 前台启动..."
        python3 "$SCRIPT_DIR/deploy-webhook.py" \
            --port $WEBHOOK_PORT \
            --secret "$DEPLOY_SECRET"
        ;;
esac
