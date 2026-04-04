"""通知和设置路由"""

import json
from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse
from loguru import logger

from app.utils.notifications import get_notif_manager

router = APIRouter(prefix="/api", tags=["通知和设置"])
SYS_PATH = Path(__file__).parent.parent.parent.parent
SETTINGS_FILE = SYS_PATH / "config" / "settings.json"

# ========== notifications ==========


@router.get("/notifications/config")
def get_notif_config():
    return JSONResponse(get_notif_manager().get_config())


@router.post("/notifications/config")
def update_notif_config(
    enabled: bool = Body(False),
    bot_token: str = Body(""),
    chat_id: str = Body(""),
    min_budget: str = Body(""),
    keywords_filter: List = Body([]),
    notify_on_count: int = Body(1),
):
    nm = get_notif_manager()
    nm.update_config(
        enabled=enabled,
        bot_token=bot_token,
        chat_id=chat_id,
        min_budget=min_budget,
        keywords_filter=keywords_filter,
        notify_on_count=notify_on_count,
    )
    return {"success": True}


@router.post("/notifications/test")
async def test_notification():
    nm = get_notif_manager()
    if not nm.config.enabled:
        return JSONResponse({"error": "not enabled"}, status_code=400)
    ok = await nm.send_immediate(
        {
            "title": "Test",
            "url": "https://example.com",
            "tender_type": "Test",
            "budget": "100万",
            "keywords_matched": "test",
            "submission_deadline": "2026-04-30",
        }
    )
    return {"success": ok}


# ========== settings ==========


@router.get("/settings")
def get_settings():
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                return JSONResponse(json.load(f))
        except Exception:
            pass
    return JSONResponse({"tasks": [], "schedule": {}, "config": {}})


@router.post("/settings")
def save_settings(data: Dict = Body(...)):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # Clear project cache when settings change
        from app.api.routes.projects import _clear_cache

        _clear_cache()
        return {"success": True}
    except (OSError, IOError, ValueError) as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# ========== collection trigger ==========


@router.post("/collect")
async def trigger_collection():
    from app.api.routes.projects import _clear_cache

    _clear_cache()
    try:
        from main import run_collection

        result = await run_collection()
        return JSONResponse({"success": True, "result": result})
    except (OSError, IOError, RuntimeError) as e:
        logger.error(f"Collection failed: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
