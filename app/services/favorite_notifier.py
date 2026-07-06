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

        # 7-06: 关闭实时推送, 改为 daily digest 统一汇报 (21:30)
        # 保留 record_notification 调用, 数据落到 notifications 表供 digest 读取
        msg_id = ""
        logger.debug(
            f"favorite match queued for daily digest: "
            f"user={user_id} project_id={project_id} info_type={info_type} (match={match_type})"
        )

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
            telegram_msg_id="daily-digest-pending",
        )

        # 不再实时推送, sent 永远为 0
        # sent 计数保留供上游判断调用是否成功

    return sent


# ============================================================
# 7-06: 收藏项目 daily digest (用户拍板 2026-07-06)
# ============================================================
# 需求: "收藏项目有新动态" 每日只汇报1次, 当收藏的项目更新为归档后, 不再汇报新进展
# 设计:
#   - 实时推送关闭 (见 try_notify_favorite_match 修改)
#   - data 落到 notifications 表
#   - 21:30 聚合过去 24h, 按 project 分组, 排除 archived, 发 1 条 TG
# ============================================================


def _build_digest_message(
    project_groups: dict,
    archived_count: int,
    total_records: int,
) -> str:
    """构建 daily digest 的 TG 消息 (HTML 格式)。

    Args:
        project_groups: {project_id: {name, info_types, latest_record, total_count, project_url}}
        archived_count: 被归档过滤掉的记录数
        total_records: 查询到的总记录数 (含归档)

    Returns:
        HTML 格式的 TG 消息文本
    """
    from datetime import datetime

    today = datetime.now().strftime('%Y-%m-%d')

    lines = [
        f"📬 <b>收藏项目日报</b> | {today}",
        "",
        f"过去 24 小时共 <b>{total_records}</b> 条更新，"
        f"涉及 <b>{len(project_groups)}</b> 个收藏项目：",
        "",
    ]

    for i, (pid, grp) in enumerate(project_groups.items(), 1):
        info_types_str = " / ".join(grp['info_types']) if grp['info_types'] else "未知"
        latest = grp['latest_record'] or {}
        latest_title = (latest.get('record_title') or '')[:60]
        latest_url = latest.get('record_url', '')
        latest_time = latest.get('sent_at', '')
        if hasattr(latest_time, 'strftime'):
            latest_time = latest_time.strftime('%m-%d %H:%M')
        elif latest_time:
            latest_time = str(latest_time)[:16]

        pname = (grp['name'] or '')[:50]

        # 项目编号
        url = grp.get('project_url', '')
        lines.append(
            f"<b>{i}. {pname}</b>\n"
            f"   📢 类型: {info_types_str} ({grp['total_count']} 条)\n"
            f"   🕐 最新: {latest_time}\n"
            f"   📝 {latest_title}\n"
            f"   🔗 <a href=\"{latest_url}\">查看详情</a>"
        )

    if archived_count > 0:
        lines.extend([
            "",
            "─" * 20,
            f"📦 <i>另有 {archived_count} 条来自已归档项目（已停止汇报）</i>",
        ])

    return "\n".join(lines)


def send_daily_favorite_digest() -> int:
    """聚合过去 24h notifications, 排除 archived, 发 1 条 TG 日报。

    流程:
        1. 查 notifications 表过去 24h 的所有记录 (LEFT JOIN projects + favorites)
        2. 过滤掉 status='archived' 的项目 (用户拍板: 归档后不再汇报)
        3. 按 project_id 分组, 统计 info_type 分布 + 最新一条
        4. 发 1 条 TG 消息 (HTML 格式)

    Returns:
        推送的项目数 (0 = 无更新或全部归档或 TG 未配置)

    Note:
        - 此函数被 scheduler.py::job_daily_favorite_digest 每日 21:30 调用
        - 实时推送已关闭 (见 try_notify_favorite_match), 所有 notifications 表数据
          都视为待汇总到 daily digest
    """
    from datetime import datetime, timedelta
    from collections import OrderedDict

    bot_token, chat_id = _get_telegram_credentials()
    if not bot_token:
        logger.debug("Telegram bot_token 未配置，跳过 daily digest")
        return 0
    if not chat_id:
        logger.debug("Telegram chat_id 未配置，跳过 daily digest")
        return 0

    try:
        from app.database import get_db

        db = get_db()
    except Exception as e:
        logger.warning(f"send_daily_favorite_digest: 拿 DB 失败: {e}")
        return 0

    cutoff = datetime.utcnow() - timedelta(hours=24)

    try:
        c = db._get_conn()
        # 7-06: 拉过去 24h notifications
        rows = c.execute(
            """
            SELECT id, project_id, project_name, info_type,
                   record_url, record_title, sent_at
            FROM notifications
            WHERE sent_at >= ?
            ORDER BY sent_at DESC
            """,
            (cutoff,),
        ).fetchall()
    except Exception as e:
        logger.warning(f"send_daily_favorite_digest: query notifications 失败: {e}")
        return 0

    if not rows:
        logger.info("send_daily_favorite_digest: 过去 24h 无 notifications")
        return 0

    # 7-06: 加载 favorites 到内存 (规模小 <5000) 用于 URL/name 匹配 + status 查询
    # try_notify_favorite_match 通过以下策略匹配:
    #   1. URL 完全相同 (record_url == favorites.project_url)
    #   2. 规范化名称相同
    # 因此需双路匹配才能判定归档状态
    try:
        from app.utils.project_linker import normalize_project_name

        fav_rows = c.execute(
            "SELECT user_id, project_url, title, status FROM favorites"
        ).fetchall()
        fav_list = [dict(r) if not isinstance(r, dict) else r for r in fav_rows]
    except Exception as e:
        logger.warning(f"send_daily_favorite_digest: query favorites 失败: {e}")
        fav_list = []

    # 构建两个索引: url -> status, name_normalized -> status (多 user 可能多个, 取非 archived 优先)
    url_to_status: dict = {}
    name_to_status: dict = {}
    for fav in fav_list:
        url = fav.get("project_url", "")
        status = fav.get("status", "")
        title = fav.get("title", "")
        if url:
            url_to_status[url] = status
        if title:
            n_name = normalize_project_name(title)
            if n_name:
                # 同一名称多个收藏: 优先取非 archived
                existing = name_to_status.get(n_name)
                if existing is None or existing == "archived":
                    name_to_status[n_name] = status

    def _resolve_fav_status(record_url: str, project_name: str) -> Optional[str]:
        """查该 record 关联的 favorite 状态。None = 找不到匹配 (无收藏)。"""
        # URL 精确匹配
        if record_url and record_url in url_to_status:
            return url_to_status[record_url]
        # 名称归一化匹配
        if project_name:
            n_name = normalize_project_name(project_name)
            if n_name and n_name in name_to_status:
                return name_to_status[n_name]
        return None

    # 按 project_id 分组 + 分类
    # OrderedDict 保持 SQL 返回顺序 (sent_at DESC) — 最新活跃的排前面
    project_groups: "OrderedDict[int, dict]" = OrderedDict()
    archived_count = 0

    for r in rows:
        pid = r['project_id']
        record_url = r['record_url']
        project_name = r['project_name']

        # 7-06: 解析 favorite 状态, 归档 → 不汇报
        fav_status = _resolve_fav_status(record_url, project_name)
        if fav_status == 'archived':
            archived_count += 1
            continue

        if pid not in project_groups:
            project_groups[pid] = {
                'name': r['project_name'],
                'project_url': record_url,  # 用 record_url 作为详情跳转
                'info_types': [],  # 保序去重
                'latest_record': None,
                'total_count': 0,
            }
        grp = project_groups[pid]
        info_type = r['info_type']
        if info_type and info_type not in grp['info_types']:
            grp['info_types'].append(info_type)
        if grp['latest_record'] is None:
            grp['latest_record'] = dict(r) if not isinstance(r, dict) else r
        grp['total_count'] += 1

    if not project_groups:
        logger.info(
            f"send_daily_favorite_digest: 24h 有 {len(rows)} 条记录但全部归档 "
            f"(archived={archived_count}), 跳过推送"
        )
        return 0

    # 构建 TG 消息
    text = _build_digest_message(project_groups, archived_count, len(rows))

    # 推送
    msg_id = _send_telegram_sync(bot_token, chat_id, text)

    if msg_id:
        logger.info(
            f"📨 收藏 daily digest 已推送: {len(project_groups)} 项目, "
            f"{len(rows)} 条记录, archived={archived_count}, msg_id={msg_id}"
        )
    else:
        logger.warning(
            f"send_daily_favorite_digest: TG 推送失败 "
            f"(但 {len(project_groups)} 项目 / {len(rows)} 条已查询)"
        )

    return len(project_groups) if msg_id else 0
