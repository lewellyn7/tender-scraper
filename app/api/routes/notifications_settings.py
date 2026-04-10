"""通知和设置路由"""

import json
import os
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
    cfg = nm.get_config()
    if not cfg.get("enabled"):
        return JSONResponse({"error": "Telegram通知未启用"}, status_code=400)
    if not cfg.get("bot_token") or not cfg.get("chat_id"):
        return JSONResponse({"error": "Bot Token 或 Chat ID 未配置"}, status_code=400)
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


@router.get("/ragflow/config")
def get_ragflow_config():
    return JSONResponse({
        "base_url": os.getenv("RAGFLOW_BASE_URL", "http://localhost:8088"),
        "api_key": os.getenv("RAGFLOW_API_KEY", "")[:4] + "****" if os.getenv("RAGFLOW_API_KEY") else "",
        "dataset_id": os.getenv("RAGFLOW_DATASET_ID", ""),
        "mcp_url": os.getenv("RAGFLOW_MCP_URL", "http://host.docker.internal:9382"),
    })


@router.post("/ragflow/config")
def update_ragflow_config(
    base_url: str = Body("http://localhost:8088"),
    api_key: str = Body(""),
    dataset_id: str = Body(""),
    mcp_url: str = Body(""),
):
    env_path = pathlib.Path(SYS_PATH) / ".env"
    lines = []
    if env_path.exists():
        lines = env_path.read_text().splitlines()
    updated_keys = set()
    new_lines = []
    for line in lines:
        if line.startswith("RAGFLOW_BASE_URL="):
            new_lines.append(f"RAGFLOW_BASE_URL={base_url}")
            updated_keys.add("RAGFLOW_BASE_URL")
        elif line.startswith("RAGFLOW_API_KEY="):
            if api_key:
                new_lines.append(f"RAGFLOW_API_KEY={api_key}")
            updated_keys.add("RAGFLOW_API_KEY")
        elif line.startswith("RAGFLOW_DATASET_ID="):
            new_lines.append(f"RAGFLOW_DATASET_ID={dataset_id}")
            updated_keys.add("RAGFLOW_DATASET_ID")
        elif line.startswith("RAGFLOW_MCP_URL="):
            new_lines.append(f"RAGFLOW_MCP_URL={mcp_url}")
            updated_keys.add("RAGFLOW_MCP_URL")
        else:
            new_lines.append(line)
    for key, val in [
        ("RAGFLOW_BASE_URL", base_url),
        ("RAGFLOW_API_KEY", api_key),
        ("RAGFLOW_DATASET_ID", dataset_id),
        ("RAGFLOW_MCP_URL", mcp_url),
    ]:
        if key not in updated_keys and (val or key != "RAGFLOW_API_KEY"):
            new_lines.append(f"{key}={val}")
    env_path.write_text("\n".join(new_lines) + "\n")
    return {"success": True}


@router.get("/llm/config")
def get_llm_config():
    return JSONResponse({
        "provider": os.getenv("LLM_PROVIDER", "none"),
        "model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
        "api_key": os.getenv("OPENAI_API_KEY", "")[:4] + "****" if os.getenv("OPENAI_API_KEY") else "",
    })


@router.post("/llm/config")
def update_llm_config(api_key: str = Body(""), model: str = Body("gpt-4o-mini"), provider: str = Body("openai")):
    import pathlib
    env_path = pathlib.Path(SYS_PATH) / ".env"
    lines = []
    if env_path.exists():
        lines = env_path.read_text().splitlines()
    # Update or add lines
    updated = False
    new_lines = []
    for line in lines:
        if line.startswith("LLM_PROVIDER="):
            new_lines.append(f"LLM_PROVIDER={provider}")
            updated = True
        elif line.startswith("LLM_MODEL="):
            new_lines.append(f"LLM_MODEL={model}")
            updated = True
        elif line.startswith("OPENAI_API_KEY="):
            if api_key:
                new_lines.append(f"OPENAI_API_KEY={api_key}")
                updated = True
            else:
                new_lines.append(line)
                updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.extend([f"LLM_PROVIDER={provider}", f"LLM_MODEL={model}"])
        if api_key:
            new_lines.append(f"OPENAI_API_KEY={api_key}")
    env_path.write_text("\n".join(new_lines) + "\n")
    return {"success": True}


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
