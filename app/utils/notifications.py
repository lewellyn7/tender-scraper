"""Telegram 推送通知模块"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

CONFIG_FILE = Path(__file__).parent.parent.parent / "config" / "notifications.json"


class NotificationConfig:
    def __init__(self):
        self.enabled = False
        self.bot_token = ""
        self.chat_id = ""
        self.min_budget = ""
        self.keywords_filter = []
        self.notify_on_count = 1
        self._load()

    def _load(self):
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                self.enabled = data.get("enabled", False)
                self.bot_token = data.get("bot_token", "")
                self.chat_id = data.get("chat_id", "")
                self.min_budget = data.get("min_budget", "")
                self.keywords_filter = data.get("keywords_filter", [])
                self.notify_on_count = data.get("notify_on_count", 1)
            except Exception:
                pass

    def _save(self):
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "enabled": self.enabled,
            "bot_token": self.bot_token,
            "chat_id": self.chat_id,
            "min_budget": self.min_budget,
            "keywords_filter": self.keywords_filter,
            "notify_on_count": self.notify_on_count,
        }
        CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def update(self, **kwargs):
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)
        self._save()

    def get(self):
        return {
            "enabled": self.enabled,
            "bot_token": self.bot_token,
            "chat_id": self.chat_id,
            "min_budget": self.min_budget,
            "keywords_filter": self.keywords_filter,
            "notify_on_count": self.notify_on_count,
        }


async def send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    try:
        import telegram

        bot = telegram.Bot(token=bot_token)
        await bot.send_message(
            chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True
        )
        logger.info("Telegram message sent")
        return True
    except Exception as e:
        logger.error(f"TG send failed: {e}")
        return False


def _fmt_budget(amount: float) -> str:
    if amount >= 100000000:
        return f"{amount/100000000:.2f}亿元"
    elif amount >= 10000:
        return f"{amount/10000:.2f}万元"
    return f"{amount:.0f}元"


def format_project_message(project: Dict) -> str:
    title = project.get("title", "无标题")[:80]
    url = project.get("url", "")
    tender_type = project.get("tender_type", "")
    budget = project.get("budget", "")
    keywords = project.get("keywords_matched", "")
    deadline = project.get("submission_deadline", project.get("deadline", ""))
    msg = "<b>" + title + "</b>\n\n"
    if tender_type:
        msg += "类型: " + tender_type + "\n"
    if budget:
        msg += "预算: " + budget + "\n"
    if keywords:
        msg += "关键词: " + keywords + "\n"
    if deadline:
        msg += "截止: " + deadline + "\n"
    msg += '<a href="' + url + '">查看原文</a>\n'
    return msg


def format_summary_message(count: int, projects: List[Dict]) -> str:
    total = 0
    for p in projects:
        b = p.get("budget", "")
        if b:
            try:
                n = float(re.sub(r"[^\d.]", "", b)) * (10000 if "万" in b else 1)
                total += n
            except Exception:
                pass
    msg = "<b>招投标采集汇总</b>\n\n"
    msg += "本次新增: <b>" + str(count) + "</b> 条匹配项目\n"
    if total > 0:
        msg += "总预算: " + _fmt_budget(total) + "\n"
    msg += "\n"
    for p in projects[:3]:
        msg += format_project_message(p) + "\n"
    return msg


class NotificationManager:
    def __init__(self):
        self.config = NotificationConfig()
        self._pending: List[Dict] = []

    def should_notify(self, project: Dict) -> bool:
        if not self.config.enabled or not self.config.bot_token or not self.config.chat_id:
            return False
        if self.config.keywords_filter:
            title = project.get("title", "")
            if not any(kw.lower() in title.lower() for kw in self.config.keywords_filter):
                return False
        if self.config.min_budget:
            b = project.get("budget", "")
            if b:
                try:
                    bn = float(re.sub(r"[^\d.]", "", b)) * (10000 if "万" in b else 1)
                    mn = float(re.sub(r"[^\d.]", "", self.config.min_budget))
                    if bn < mn:
                        return False
                except Exception:
                    pass
        return True

    async def process_new_projects(self, projects: List[Dict]) -> int:
        if not self.config.enabled:
            return 0
        for p in projects:
            if self.should_notify(p):
                self._pending.append(p)
        if len(self._pending) >= self.config.notify_on_count:
            msg = format_summary_message(len(self._pending), self._pending)
            if await send_telegram_message(self.config.bot_token, self.config.chat_id, msg):
                cnt = len(self._pending)
                self._pending = []
                return cnt
        return 0

    async def send_immediate(self, project: Dict) -> bool:
        if not self.config.enabled:
            return False
        return await send_telegram_message(
            self.config.bot_token, self.config.chat_id, format_project_message(project)
        )

    def get_config(self):
        return self.config.get()

    def update_config(self, **kwargs):
        self.config.update(**kwargs)


_nm: Optional[NotificationManager] = None


def get_notif_manager() -> NotificationManager:
    global _nm
    if _nm is None:
        _nm = NotificationManager()
    return _nm
