#!/usr/bin/env bash
# install-env-watcher.sh
#
# 用途: 把 env-watch-recreate.sh 加入用户 crontab, 每分钟检测 .env 变更
# 幂等: 可重复执行, 重复会替换已有行 (通过 marker 注释识别)
#
# 设计:
#   - cron 守护崩溃/重启由 cron daemon 自身保证 (Linux cron 标准行为)
#   - 1 分钟粒度足够 (env 变更不频繁)
#   - 变更多次/分钟靠 mtime+md5 双因子去重

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$PROJECT_DIR/scripts/env-watch-recreate.sh"
MARKER="__ENV_WATCHER_MARKER__"
CRON_LINE="* * * * * $MARKER bash $SCRIPT >> /var/log/env-watcher.log 2>&1"

# 前置检查
command -v crontab >/dev/null || { echo "❌ crontab 不可用"; exit 1; }
[[ -x "$SCRIPT" ]] || { echo "❌ $SCRIPT 不可执行, 先 chmod +x"; exit 1; }
[[ -f "$PROJECT_DIR/.env" ]] || { echo "⚠️  $PROJECT_DIR/.env 不存在, watcher 会空跑 (直到 .env 创建)"; }

# 确保 log 文件存在 + 可写
sudo touch /var/log/env-watcher.log 2>/dev/null || touch /var/log/env-watcher.log 2>/dev/null || {
  echo "⚠️  无法写 /var/log/env-watcher.log, 改用 /tmp/env-watcher.log"
  CRON_LINE="* * * * * $MARKER bash $SCRIPT >> /tmp/env-watcher.log 2>&1"
}

# 当前 crontab (空 crontab 会报错, 用 || true)
existing="$(crontab -l 2>/dev/null || true)"

# 移除旧 marker 行 + 重写
new_crontab="$(echo "$existing" | grep -v "$MARKER" || true)"
# 去掉尾部空行
new_crontab="$(echo "$new_crontab" | sed '/^$/d')"

# 追加新行
new_crontab="${new_crontab}${new_crontab:+$'\n'}${CRON_LINE}"

echo "$new_crontab" | crontab -

echo "✅ cron 安装完成"
echo ""
echo "=== 新 crontab ==="
crontab -l
echo ""
echo "测试: bash $SCRIPT  (应该退出 0 = 无变更)"
