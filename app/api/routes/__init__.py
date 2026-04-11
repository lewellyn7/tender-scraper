"""API 路由聚合"""

from fastapi import APIRouter

from .analytics import router as analytics_router
from .annotations import router as annotations_router
from .annotations_presets import router as annotations_presets_router
from .bidder_qualifications import router as bidder_qualifications_router
from .config_backup import router as config_backup_router
from .qualification_categories import router as qualification_categories_router
from .database import router as database_router
from .document_upload import router as document_upload_router
from .duplicates import router as duplicates_router
from .exports import router as exports_router
from .health import router as health_router
from .favorites import router as favorites_router
from .logs import router as logs_router
from .notifications import router as notifications_router
from .notifications_settings import router as notifications_settings_router
from .presets import router as presets_router
from .projects import router as projects_router
from .search import router as search_router
from .chat import router as chat_router
from .quality import router as quality_router
from .stats import router as stats_router

api_router = APIRouter()

api_router.include_router(projects_router)
api_router.include_router(favorites_router)
api_router.include_router(analytics_router)
api_router.include_router(stats_router)
api_router.include_router(logs_router)
api_router.include_router(annotations_router)
api_router.include_router(annotations_presets_router)
api_router.include_router(config_backup_router)
api_router.include_router(qualification_categories_router)
api_router.include_router(database_router)
api_router.include_router(notifications_router)
api_router.include_router(notifications_settings_router)
api_router.include_router(bidder_qualifications_router)
api_router.include_router(document_upload_router)
api_router.include_router(duplicates_router)
api_router.include_router(exports_router)
api_router.include_router(health_router)
api_router.include_router(presets_router)
api_router.include_router(search_router)
api_router.include_router(chat_router)
api_router.include_router(quality_router)
