"""通知和设置路由"""

import json
import os
from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from loguru import logger
from app.utils.log_sanitizer import sanitize_error_message

from app.utils.notifications import get_notif_manager
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api", tags=["通知和设置"])
SYS_PATH = Path(__file__).parent.parent.parent.parent
SETTINGS_FILE = SYS_PATH / "config" / "settings.json"

# ========== notifications ==========


@router.get("/notifications/config")
def get_notif_config(user_id: str = Depends(get_current_user)):
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
async def test_notification(user_id: str = Depends(get_current_user)):
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
def get_ragflow_config(user_id: str = Depends(get_current_user)):
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
def get_llm_config(user_id: str = Depends(get_current_user)):
    """获取 LLM 多模型配置（API Key 已脱敏）"""
    providers = _load_llm_providers()
    # 脱敏处理
    safe_providers = []
    for p in providers:
        masked = dict(p)
        if masked.get("api_key"):
            masked["api_key"] = masked["api_key"][:4] + "****"
        safe_providers.append(masked)
    return JSONResponse({"providers": safe_providers})


@router.post("/llm/config")
def update_llm_config(
    providers: list = Body(default=None),
    user_id: str = Depends(get_current_user),
):
    """更新 LLM 多模型配置（支持 fallback 链）"""
    if providers is None:
        return JSONResponse({"success": False, "error": "providers required"}, status_code=400)
    if not isinstance(providers, list):
        return JSONResponse({"success": False, "error": "providers must be a list"}, status_code=400)
    # 验证配置
    for p in providers:
        if not isinstance(p, dict) or not p.get("provider_type"):
            return JSONResponse({"success": False, "error": "each provider needs provider_type"}, status_code=400)

    # 写入配置
    _save_llm_providers(providers)
    # 热更新全局 LLM Service
    try:
        from app.services.llm_service import reload_llm_service
        reload_llm_service()
    except Exception:
        pass
    return {"success": True, "providers": len(providers)}


@router.post("/llm/config/test")
async def test_llm_config(
    provider_type: str = Body(...),
    api_key: str = Body(""),
    model: str = Body(""),
    base_url: str = Body(""),
    user_id: str = Depends(get_current_user),
):
    """测试单个 LLM Provider 连接"""
    from app.services.llm_service import LLMService, LLMProviderConfig, PROVIDER_OPENAI, PROVIDER_ANTHROPIC, PROVIDER_OLLAMA, PROVIDER_QWEN, PROVIDER_MINIMAX

    defaults = {
        PROVIDER_OPENAI: "gpt-4o-mini",
        PROVIDER_ANTHROPIC: "claude-sonnet-4-20250514",
        PROVIDER_OLLAMA: "llama3",
        PROVIDER_QWEN: "qwen-plus",
        PROVIDER_MINIMAX: "MiniMax-M2",
    }
    config = LLMProviderConfig(
        name=f"test-{provider_type}",
        provider_type=provider_type,
        api_key=api_key,
        base_url=base_url,
        model=model or defaults.get(provider_type, "gpt-4o-mini"),
        max_retries=2,
        enabled=True,
    )
    service = LLMService([config])

    try:
        result = await service.chat(
            prompt="请回复 JSON 格式：{\"status\": \"ok\", \"message\": \"连接成功\"}",
            json_mode=True,
            max_tokens=256,
        )
        if result.success:
            return JSONResponse({"success": True, "provider": provider_type, "model": result.model, "latency_ms": result.latency_ms})
        else:
            return JSONResponse({"success": False, "error": result.error}, status_code=502)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# ── LLM 配置存储 ─────────────────────────────────────────

def _mask_key(key: str) -> str:
    if not key:
        return ""
    return key[:4] + "****"


def _load_llm_providers() -> list:
    """从 config/llm_providers.json 加载配置"""
    config_path = SYS_PATH / "config" / "llm_providers.json"
    if not config_path.exists():
        # 兼容旧的 .env 格式
        primary = {
            "name": os.getenv("LLM_PROVIDER", "openai"),
            "provider_type": os.getenv("LLM_PROVIDER", "openai"),
            "model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
            "api_key": os.getenv("OPENAI_API_KEY", ""),
            "base_url": os.getenv("OPENAI_BASE_URL", ""),
            "max_retries": 3,
            "timeout": 60,
            "enabled": True,
        }
        return [p for p in [primary] if p["provider_type"] != "none"]
    try:
        return json.loads(config_path.read_text())
    except Exception:
        return []


def _save_llm_providers(providers: list):
    """保存多 Provider 配置到 JSON 文件"""
    config_path = SYS_PATH / "config" / "llm_providers.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    # 写入时保留 api_key 明文（文件本身在 .gitignore 中）
    config_path.write_text(json.dumps(providers, ensure_ascii=False, indent=2))
    logger.info(f"LLM config saved: {len(providers)} providers")


@router.get("/settings")
def get_settings(user_id: str = Depends(get_current_user)):
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                return JSONResponse(json.load(f))
        except Exception:
            pass
    return JSONResponse({"tasks": [], "schedule": {}, "config": {}})


@router.post("/settings")
def save_settings(data: Dict = Body(...), user_id: str = Depends(get_current_user)):
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
async def trigger_collection(user_id: str = Depends(get_current_user)):
    from app.api.routes.projects import _clear_cache

    _clear_cache()
    try:
        from main import run_collection

        result = await run_collection()
        return JSONResponse({"success": True, "result": result})
    except (OSError, IOError, RuntimeError) as e:
        logger.error(f"Collection failed: {sanitize_error_message(str(e))}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
