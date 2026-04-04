"""API 路由聚合"""

from fastapi import APIRouter

from .analytics import router as analytics_router
from .annotations_presets import router as annotations_presets_router
from .config_backup import router as config_backup_router
from .favorites import router as favorites_router
from .logs import router as logs_router
from .notifications_settings import router as notifications_settings_router
from .projects import router as projects_router

api_router = APIRouter()

api_router.include_router(projects_router)
api_router.include_router(favorites_router)
api_router.include_router(analytics_router)
api_router.include_router(logs_router)
api_router.include_router(annotations_presets_router)
api_router.include_router(config_backup_router)
api_router.include_router(notifications_settings_router)
