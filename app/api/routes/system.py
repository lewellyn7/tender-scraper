"""系统管理路由 - 部署模式切换"""
import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config.settings import get_settings, reload_settings
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api/system", tags=["系统管理"])


class ModeResponse(BaseModel):
    mode: str
    is_self_mode: bool
    is_team_mode: bool


class ModeSwitchRequest(BaseModel):
    mode: str  # "self" or "team"


class ModeSwitchResponse(BaseModel):
    mode: str
    message: str


@router.get("/mode", response_model=ModeResponse, summary="获取当前部署模式")
async def get_mode(current_user: dict = Depends(get_current_user)):
    """获取当前部署模式
    
    - 自用模式 (self): 免登录，所有功能开放
    - 团队模式 (team): 完整认证和用户管理
    """
    settings = get_settings()
    return ModeResponse(
        mode=settings.deployment_mode,
        is_self_mode=settings.is_self_mode,
        is_team_mode=settings.is_team_mode,
    )


@router.post("/mode/switch", response_model=ModeSwitchResponse, summary="切换部署模式")
async def switch_mode(
    req: ModeSwitchRequest,
    current_user: dict = Depends(get_current_user),
):
    """切换部署模式
    
    仅 admin 角色可执行。切换后需重启服务生效。
    """
    # 检查是否为 admin
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可切换部署模式")
    
    # 验证模式值
    if req.mode not in ("self", "team"):
        raise HTTPException(status_code=400, detail="模式必须为 'self' 或 'team'")
    
    settings = get_settings()
    if settings.deployment_mode == req.mode:
        return ModeSwitchResponse(
            mode=req.mode,
            message=f"当前已是 {req.mode} 模式，无需切换"
        )
    
    # 写入环境变量（临时生效，重启后需重新设置）
    os.environ["DEPLOYMENT_MODE"] = req.mode
    
    # 重新加载配置
    reload_settings()
    
    return ModeSwitchResponse(
        mode=req.mode,
        message=f"模式已切换为 {req.mode}，重启服务后生效"
    )


@router.get("/info", summary="系统信息")
async def get_system_info(current_user: dict = Depends(get_current_user)):
    """获取系统信息（无需 admin 权限）"""
    settings = get_settings()
    return {
        "deployment_mode": settings.deployment_mode,
        "is_self_mode": settings.is_self_mode,
        "is_team_mode": settings.is_team_mode,
        "version": "3.1",
    }
