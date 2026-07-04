#!/usr/bin/env bash
# env-watch-recreate.sh
#
# 用途: 监听 .env 变更, 触发 docker compose force-recreate 受影响服务
# 被 cron 每分钟调用一次, 通过 mtime+md5 检测变更, 无变更直接退出 (零开销)
#
# 为什么需要这个:
#   docker-compose.yml 的 ${VAR} 在 `up` 时一次性解析, 容器 env 启动后锁定。
#   .env 后续改动对运行中容器无效 (已踩坑 2026-07-04 TG 通道静默失效)。
#   修复 docker-compose.yml 加 env_file 仅保证 *未来* 重创时生效;
#   此脚本让 .env 改动自动触发现有容器的重创。
#
# 调用: 手动 `bash scripts/env-watch-recreate.sh` 或 cron `* * * * *`
#
# 返回:
#   0 - 无变更 / 正常
#   非 0 - 重创失败 (cron 会把 stdout/stderr 邮到 MAILTO)

set -euo pipefail

cd "$(dirname "$0")/.."  # 项目根

ENV_FILE=".env"
STATE_FILE="/tmp/.env-watcher-state"
LOG_FILE="/var/log/env-watcher.log"
SERVICES="web scheduler collector"

# 1) 文件存在性检查
[[ -f "$ENV_FILE" ]] || { echo "[$(date)] $ENV_FILE 不存在, 跳过"; exit 0; }

# 2) 计算指纹 (mtime + md5, 双因子防误判)
new_fp="$(stat -c %Y "$ENV_FILE") $(md5sum "$ENV_FILE" | awk '{print $1}')"

# 3) 与上次比对
old_fp="$(cat "$STATE_FILE" 2>/dev/null || echo 'INITIAL')"
if [[ "$new_fp" == "$old_fp" ]]; then
  exit 0  # 无变更, 静默退出
fi

# 4) 变更: 记录 + 触发重创
echo "[$(date)] .env 变更检测: $old_fp -> $new_fp" | tee -a "$LOG_FILE"

if ! docker compose up -d --force-recreate --no-deps $SERVICES >> "$LOG_FILE" 2>&1; then
  echo "[$(date)] ERROR: docker compose force-recreate 失败, 见 $LOG_FILE" | tee -a "$LOG_FILE"
  exit 1
fi

# 5) 更新 state (即使 force-recreate 部分成功, 也算已尝试)
echo "$new_fp" > "$STATE_FILE"
echo "[$(date)] 已 force-recreate: $SERVICES" | tee -a "$LOG_FILE"
exit 0
