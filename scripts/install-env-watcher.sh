#!/usr/bin/env bash
# install-env-watcher.sh
#
# 用途: 把 env-watch-recreate.sh 加入用户 crontab, 每分钟检测 .env 变更
# 幂等: 可重复执行, 通过注释标记识别旧条目
#
# 设计:
#   - cron 守护崩溃/重启由 cron daemon 自身保证
#   - 1 分钟粒度足够 (env 变更不频繁)
#   - mtime+md5 双因子去重, 变更多次/分钟也只 recreate 一次
#   - crontab 用注释 + 紧随命令行的两行结构, marker 不会污染命令解析

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$PROJECT_DIR/scripts/env-watch-recreate.sh"
LOG_FILE="/var/log/env-watcher.log"
[[ -w "/var/log/env-watcher.log" ]] || LOG_FILE="/tmp/env-watcher.log"
[[ -w "/var/log/" ]] 2>/dev/null || LOG_FILE="/tmp/env-watcher.log"

MARKER="# __ENV_WATCHER_MARKER__"

command -v crontab >/dev/null || { echo "❌ crontab 不可用"; exit 1; }
[[ -x "$SCRIPT" ]] || { echo "❌ $SCRIPT 不可执行, 先 chmod +x"; exit 1; }

# 现有 crontab
existing="$(crontab -l 2>/dev/null || true)"

# 移除:
#   A) 新格式: 注释行 "# __ENV_WATCHER_MARKER__" + 紧跟的 "* * * * * bash ..." 行
#   B) 旧格式: "* * * * * __ENV_WATCHER_MARKER__ bash ..." (早期版本 bug)
new_crontab="$(echo "$existing" | awk '
  /^# __ENV_WATCHER_MARKER__/        { skip=1; next }   # A1: skip 注释
  skip && /^\* \* \* \* \* bash/      { skip=0; next }   # A2: skip 紧随的命令行, 退出 skip 态
  skip                                { skip=0 }        # skip 中非命令行 → 退出 skip 态
  /^\* \* \* \* \* __ENV_WATCHER_MARKER__/ { next }       # B: 旧格式整行删除
  { print }
')"

# 去尾部空行
new_crontab="$(echo "$new_crontab" | sed '/^$/d')"

# 追加新条目 (注释 + 命令各占一行, 用真实换行而非 \n 字符串)
if [[ -n "$new_crontab" ]]; then
  appended="$(printf '%s\n%s\n* * * * * bash %s >> %s 2>&1\n' \
    "$new_crontab" "$MARKER" "$SCRIPT" "$LOG_FILE")"
else
  appended="$(printf '%s\n* * * * * bash %s >> %s 2>&1\n' \
    "$MARKER" "$SCRIPT" "$LOG_FILE")"
fi

echo "$appended" | crontab -

echo "✅ cron 安装完成 (LOG=$LOG_FILE)"
echo ""
echo "=== 新 crontab ==="
crontab -l
echo ""
echo "测试: bash $SCRIPT  (无变更应 exit 0)"
