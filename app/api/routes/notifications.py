"""通知路由"""

import os

import httpx
from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from app.database import get_db

router = APIRouter(prefix="/api/notifications", tags=["通知"])


@router.get("/config")
def get_notification_config():
    """获取通知配置"""
    db = get_db()
    conn = db._get_conn()
    row = conn.execute(
        "SELECT config_value FROM config WHERE config_key = 'notification' LIMIT 1"
    ).fetchone()

    if row:
        import json

        return JSONResponse(json.loads(row[0]))
    return JSONResponse(
        {
            "enabled": False,
            "bot_token": "",
            "chat_id": "",
            "min_budget": "",
            "keywords_filter": [],
            "notify_on_count": 1,
        }
    )


@router.post("/config")
def save_notification_config(config: dict = Body(...)):
    """保存通知配置"""
    db = get_db()
    conn = db._get_conn()
    import json

    conn.execute(
        """INSERT OR REPLACE INTO config (config_key, config_value)
           VALUES ('notification', ?)""",
        (json.dumps(config),),
    )
    conn.commit()
    return JSONResponse({"success": True})


@router.post("/test")
async def test_notification():
    """发送测试消息"""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        return JSONResponse({"success": False, "error": "未配置 Telegram"}, status_code=400)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": "🧪 测试消息：招投标采集系统通知测试成功！"},
            )
        if response.status_code == 200:
            return JSONResponse({"success": True})
        return JSONResponse({"success": False, "error": response.text})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
