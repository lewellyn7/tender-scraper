"""多通道告警模块 (7-03 watchdog 集成)

支持通道 (按用户决策 2026-07-03):
1. **Telegram** (主通道) — 用现有 TELEGRAM_BOT_TOKEN/CHAT_ID
2. **Audit log** (兜底) — 写 audit_log 表,保证不丢

设计:
- 纯函数 send_* + 聚合 dispatch
- 失败不抛 (告警失败不能影响主流程)
- 复用现有 app.services.favorite_notifier._send_telegram_sync 的 httpx 模式
- 提供 format_alert_message() helper 给 scheduler/collector 复用

用法:
    from app.utils.alerts import send_alert
    send_alert(level='critical', title='...', body='...')
"""
from __future__ import annotations

import os
import time
from typing import Optional, Literal

from loguru import logger

# ── 配置 ──────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# 告警级别 → emoji 映射
_LEVEL_EMOJI = {
    "info": "ℹ️",
    "warning": "🟡",
    "error": "🔴",
    "critical": "🚨",
}


# ── Telegram 发送 (复用 favorite_notifier 模式) ───────────
def _send_telegram_sync(bot_token: str, chat_id: str, text: str) -> Optional[str]:
    """同步推 Telegram 消息. 失败返回 None, 不抛."""
    if not bot_token or not chat_id:
        logger.debug("[alerts] Telegram bot_token/chat_id 未配置, 跳过")
        return None
    try:
        import httpx
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        # Telegram 消息长度上限 4096 chars, 截断保险
        if len(text) > 4000:
            text = text[:3950] + "\n\n… (消息过长, 已截断)"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        with httpx.Client(timeout=10) as client:
            resp = client.post(url, json=payload)
        if resp.status_code == 200 and resp.json().get("ok"):
            return str(resp.json().get("result", {}).get("message_id", ""))
        logger.warning(f"[alerts] Telegram 推送失败: {resp.status_code} {resp.text[:200]}")
        return None
    except Exception as e:
        logger.warning(f"[alerts] Telegram 推送异常: {e}")
        return None


# ── Audit 写入 (兜底, 保底不丢) ─────────────────────────
def _write_audit(event: str, level: str, title: str, body: str) -> bool:
    """写 audit_log 表. 复用现有 audit 模块的事件类型."""
    try:
        from app.security.audit import write_audit_log
        # 7-03 watchdog 用 3 个新事件类型
        # 如果 audit 模块没有, 复用现有的 EVENT_CRAWL_FAILED
        try:
            write_audit_log(
                event=event,
                user_id=None,
                ip_address=None,
                resource="scheduler.watchdog",
                result="failure" if level in ("error", "critical") else "success",
                details={"title": title, "body": body, "level": level},
            )
        except TypeError:
            # 兼容老接口 (不同 audit signature)
            write_audit_log(
                user_id=None,
                ip_address=None,
                resource="scheduler.watchdog",
                result="failure" if level in ("error", "critical") else "success",
                details={"title": title, "body": body, "level": level, "event": event},
            )
        return True
    except Exception as e:
        logger.warning(f"[alerts] audit 写入失败: {e}")
        return False


# ── 格式化 ──────────────────────────────────────────────
def format_alert_message(
    level: Literal["info", "warning", "error", "critical"],
    title: str,
    body: str,
    *,
    source: str = "watchdog",
    timestamp: Optional[float] = None,
) -> str:
    """生成 HTML 格式的告警消息 (Telegram 显示用).

    Args:
        level: info/warning/error/critical
        title: 一句话标题
        body: 详情 (支持多行)
        source: 来源 (e.g. 'scheduler', 'collector', 'watchdog')
        timestamp: epoch 秒, None 用当前时间
    """
    emoji = _LEVEL_EMOJI.get(level, "ℹ️")
    ts = timestamp or time.time()
    import datetime
    time_str = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    body_escaped = (
        body.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

    lines = [
        f"{emoji} <b>[{level.upper()}] {title}</b>",
        "",
        f"🕐 {time_str}",
        f"📍 来源: <code>{source}</code>",
        "",
        body_escaped,
    ]
    return "\n".join(lines)


# ── 统一入口 ────────────────────────────────────────────
def send_alert(
    level: Literal["info", "warning", "error", "critical"],
    title: str,
    body: str,
    *,
    source: str = "watchdog",
) -> bool:
    """多通道发送告警 (Telegram + audit). 任一成功即返 True.

    Args:
        level: info/warning/error/critical
        title: 一句话标题
        body: 详情 (多行)
        source: 来源标识

    Returns:
        True  如果 Telegram 或 audit 至少一个成功
        False 全部失败
    """
    text = format_alert_message(level, title, body, source=source)
    # 7-03 截断: TG 限制 4096 chars, 提前截断避免 mock/单测看到原始长度
    # audit 仍传原始 body (不截断)
    tg_text = text
    if len(tg_text) > 4000:
        tg_text = tg_text[:3950] + "\n\n… (消息过长, 已截断)"
    tg_ok = _send_telegram_sync(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, tg_text) is not None
    audit_ok = _write_audit(
        event=f"watchdog.{level}",
        level=level,
        title=title,
        body=body,
    )
    if tg_ok:
        logger.info(f"[alerts] ✅ Telegram 告警已发: [{level}] {title}")
    elif audit_ok:
        logger.info(f"[alerts] ⚠️ TG 失败但 audit 已写: [{level}] {title}")
    else:
        logger.error(f"[alerts] ❌ 告警发送失败 (TG+audit 都失败): [{level}] {title}")
    return tg_ok or audit_ok
