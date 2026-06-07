"""收藏项目关联提醒 — 通知触发器

在 `add_project_record()` 写入新 record 后自动调用：
1. 查 `favorites` 表找该 record 关联的收藏用户
2. 5 分钟去重窗口（防止短时间多 record 重复推送）
3. 推 Telegram 消息
4. 写 `notifications` 表记录发送情况

Telegram chat_id 优先级：
- 用户的 telegram_chat_id 字段（未来扩展，目前 favorites 无此字段）
- 环境变量 TELEGRAM_CHAT_ID 兜底（self-mode 单用户场景）
"""

import os
from typing import Optional

from loguru import logger


_INFO_TYPE_EMOJI = {
    "招标公告": "📋",
    "招标计划": "📝",
    "答疑补遗": "❓",
    "中标候选人公示": "🏆",
    "中标结果公示": "🎯",
    "中标结果": "🎯",
    "终止公告": "🚫",
    "相关公告": "📎",
    "采购公告": "📋",
    "采购结果公告": "🎯",
    "采购结果": "🎯",
    "变更公告": "🔄",
    "更正公告": "🔄",
    "结果公告": "🎯",
}


def _emoji_for(info_type: str) -> str:
    return _INFO_TYPE_EMOJI.get(info_type, "📄")


def _build_message(
    project_name: str,
    info_type: str,
    record_title: str,
    record_url: str,
    match_type: str = "name",
) -> str:
    """构建 Telegram 消息内容（HTML 格式）。"""
    emoji = _emoji_for(info_type)
    match_label = {
        "url": "URL 精确匹配",
        "name": "项目名称匹配",
        "project_no": "项目编号匹配",
    }.get(match_type, "项目关联")

    # 截断长标题
    pname = (project_name or "")[:60]
    rtitle = (record_title or "")[:80]

    lines = [
        f"{emoji} <b>收藏项目有新动态</b>",
        "",
        f"📌 收藏项目：<b>{pname}</b>",
        f"📢 新增类型：<b>{info_type}</b>" if info_type else "",
        f"📝 标题：{rtitle}" if rtitle and rtitle != pname else "",
        f"🔗 <a href=\"{record_url}\">查看详情</a>",
        "",
        f"<i>匹配方式：{match_label}</i>",
    ]
    return "\n".join(line for line in lines if line)


async def _send_telegram(bot_token: str, chat_id: str, text: str) -> Optional[str]:
    """推 Telegram 消息，返回 message_id 或 None。

    用 httpx 直接调 Bot API，不依赖 python-telegram-bot 包。
    """
    try:
        import httpx

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                return str(data.get("result", {}).get("message_id", ""))
        logger.warning(f"Telegram API 推送失败: {resp.status_code} {resp.text[:200]}")
        return None
    except Exception as e:
        logger.warning(f"Telegram 推送异常: {e}")
        return None


def _send_telegram_sync(bot_token: str, chat_id: str, text: str) -> Optional[str]:
    """同步版本：调 Telegram Bot API。用于在同步函数（如 add_project_record hook）中推送。"""
    try:
        import httpx

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        with httpx.Client(timeout=15) as client:
            resp = client.post(url, json=payload)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                return str(data.get("result", {}).get("message_id", ""))
        logger.warning(f"Telegram API 推送失败: {resp.status_code} {resp.text[:200]}")
        return None
    except Exception as e:
        logger.warning(f"Telegram 推送异常: {e}")
        return None


def _get_telegram_credentials() -> tuple:
    """从环境变量拿 Telegram bot_token + 默认 chat_id。"""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    default_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    return bot_token, default_chat_id


def try_notify_favorite_match(
    project_id: int,
    record_id: int,
    project_name: str,
    info_type: str,
    record_url: str,
    record_title: str = "",
) -> int:
    """同步入口：检查并触发收藏项目关联提醒。

    返回：成功推送的次数（0 = 无匹配 / 已去重 / 推送失败）。

    此函数被 `add_project_record()` 末尾调用，失败不抛。
    """
    if not project_id or not record_id or not record_url:
        return 0

    bot_token, default_chat_id = _get_telegram_credentials()
    if not bot_token:
        logger.debug("Telegram bot_token 未配置，跳过收藏提醒")
        return 0

    try:
        from app.database import get_db

        db = get_db()
    except Exception as e:
        logger.warning(f"try_notify_favorite_match: 拿 DB 失败: {e}")
        return 0

    # 从 projects 表拿真实 project_name（避免传 None 或空）
    try:
        c = db._get_conn()
        row = c.execute(
            "SELECT project_name, project_no FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if row:
            real_name = row["project_name"] if isinstance(row, dict) else row[0]
            real_no = row["project_no"] if isinstance(row, dict) else row[1]
            if real_name:
                project_name = real_name
        else:
            real_no = ""
    except Exception as e:
        logger.debug(f"get project_name from projects: {e}")
        real_no = ""

    # 找匹配的收藏
    try:
        matches = db.find_favorite_matches(
            record_url=record_url,
            project_name=project_name,
            project_no=real_no or "",
            info_type=info_type,
        )
    except Exception as e:
        logger.warning(f"find_favorite_matches 失败: {e}")
        return 0

    if not matches:
        logger.debug(f"无收藏匹配: record_id={record_id} project={project_name[:30]}")
        return 0

    sent = 0
    for fav in matches:
        user_id = fav.get("user_id", "")
        match_type = fav.get("match_type", "name")

        # 5 分钟去重
        if db.is_recently_notified(user_id, project_id, info_type):
            logger.debug(
                f"去重命中: user={user_id} project_id={project_id} info_type={info_type} — 5min 内已推送"
            )
            continue

        # 决定 chat_id（self-mode 用 env，多用户模式待扩展）
        chat_id = default_chat_id  # 目前 self-mode 单用户
        if not chat_id:
            logger.debug("Telegram chat_id 未配置，跳过")
            continue

        # 推消息
        text = _build_message(
            project_name=project_name,
            info_type=info_type,
            record_title=record_title,
            record_url=record_url,
            match_type=match_type,
        )

        # 同步推 Telegram（在 add_project_record hook 上下文中）
        msg_id = _send_telegram_sync(bot_token, chat_id, text)

        # 写通知记录（即使推送失败也记录，便于回溯）
        db.record_notification(
            user_id=user_id,
            project_id=project_id,
            record_id=record_id,
            project_name=project_name,
            info_type=info_type,
            record_url=record_url,
            record_title=record_title,
            telegram_chat_id=chat_id,
            telegram_msg_id=msg_id or "",
        )

        if msg_id:
            sent += 1
            logger.info(
                f"📨 收藏提醒已推送: user={user_id} project_id={project_id} {info_type} (match={match_type})"
            )

    return sent
