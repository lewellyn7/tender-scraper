#!/bin/bash
# ============================================================
# 部署脚本 - 由 GitHub Actions 触发 (repository_dispatch)
# 或由 cron 定时调用检查更新
#
# 用法:
#   ./deploy.sh                    # 检查并部署
#   ./deploy.sh --force            # 强制重新部署
#   ./deploy.sh --check            # 仅检查更新
# ============================================================

set -e

GITHUB_REPO="${GITHUB_REPO:-lewellyn7/tender-scraper}"
GITHUB_TOKEN="${GITHUB_TOKEN:-${PAT_TOKEN:-}}"
BRANCH="${BRANCH:-main}"
COMPOSE_FILE="docker-compose.prod.yml"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_CMD="docker compose -f ${COMPOSE_FILE}"

FORCE=${FORCE:-0}
CHECK_ONLY=${CHECK_ONLY:-0}

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ── 检查依赖 ──────────────────────────────────────────────────
check_dependencies() {
    if [ ! -f "$PROJECT_DIR/$COMPOSE_FILE" ]; then
        log_warn "$COMPOSE_FILE not found. Copying from docker-compose.yml..."
        cp "$PROJECT_DIR/docker-compose.yml" "$PROJECT_DIR/$COMPOSE_FILE"
    fi
    
    if [ ! -d "$PROJECT_DIR/.git" ]; then
        log_error "Not a git repository: $PROJECT_DIR"
        exit 1
    fi
}

# ── 获取 GitHub 最新 commit ──────────────────────────────────
get_latest_github_commit() {
    if [ -z "$GITHUB_TOKEN" ]; then
        log_warn "GITHUB_TOKEN not set, using git fetch"
        cd "$PROJECT_DIR"
        git fetch origin $BRANCH --quiet 2>/dev/null
        git rev-parse origin/$BRANCH 2>/dev/null
    else
        # 使用 GitHub API 获取最新 commit
        curl -s -H "Authorization: token $GITHUB_TOKEN" \
            "https://api.github.com/repos/$GITHUB_REPO/commits/$BRANCH" \
            | python3 -c "import sys,json; print(json.load(sys.stdin)['sha'])" 2>/dev/null
    fi
}

# ── 获取当前已部署 commit ──────────────────────────────────
get_deployed_commit() {
    cd "$PROJECT_DIR"
    # 从 docker 标签读取版本
    docker inspect tender-scraper --format '{{.Config.Labels.version}}' 2>/dev/null || echo "none"
}

# ── 执行部署 ────────────────────────────────────────────────
do_deploy() {
    log_info "=========================================="
    log_info "🚀 开始部署 tender-scraper"
    log_info "时间: $(date '+%Y-%m-%d %H:%M:%S')"
    log_info "=========================================="
    
    # 1. 更新代码
    log_info "📥 更新代码..."
    cd "$PROJECT_DIR"
    git fetch origin $BRANCH --quiet 2>/dev/null || true
    
    # 2. 拉取最新镜像
    log_info "📦 拉取最新镜像..."
    $COMPOSE_CMD pull scraper 2>/dev/null || \
    docker pull "ghcr.io/$GITHUB_REPO:main-$(git rev-parse --short origin/$BRANCH)" 2>/dev/null || \
    log_warn "镜像拉取失败，使用本地构建"
    
    # 3. 重启服务
    log_info "🔄 重启服务..."
    $COMPOSE_CMD up -d --force-recreate scraper
    
    # 4. 等待健康检查
    log_info "⏳ 等待服务就绪..."
    sleep 5
    
    # 5. 健康检查
    for i in {1..30}; do
        if curl -sf http://localhost:8002/health > /dev/null 2>&1; then
            log_info "✅ 服务已就绪!"
            return 0
        fi
        sleep 2
    done
    
    log_warn "⚠️  健康检查超时，但服务可能正在启动"
    return 1
}

# ── 主流程 ──────────────────────────────────────────────────
main() {
    cd "$PROJECT_DIR"
    check_dependencies
    
    # 解析参数
    case "${1:-}" in
        --force)
            log_info "强制部署模式"
            do_deploy
            exit $?
            ;;
        --check)
            CHECK_ONLY=1
            ;;
    esac
    
    # 检查更新
    log_info "🔍 检查更新..."
    
    LATEST=$(get_latest_github_commit 2>/dev/null)
    CURRENT=$(git rev-parse HEAD 2>/dev/null)
    
    if [ -z "$LATEST" ]; then
        log_error "无法获取 GitHub 最新版本"
        exit 1
    fi
    
    log_info "GitHub 最新: $LATEST"
    log_info "本地最新:   $CURRENT"
    
    if [ "$LATEST" != "$CURRENT" ] || [ "$FORCE" == "1" ]; then
        log_info "🆕 发现新版本!"
        
        # 切换到最新版本
        git checkout origin/$BRANCH --force 2>/dev/null || \
        git reset --hard $LATEST
        
        do_deploy
        
        # 记录部署
        echo "$(date '+%Y-%m-%d %H:%M:%S') | $LATEST | deployed" >> "$PROJECT_DIR/.deploy_history"
        
        log_info "=========================================="
        log_info "✅ 部署完成!"
        log_info "=========================================="
    else
        log_info "✅ 已是最新版本，无需部署"
    fi
}

main "$@"
