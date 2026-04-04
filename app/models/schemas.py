"""Pydantic 数据模型"""

from datetime import datetime
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class UserRole(str, Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class ProjectStatus(str, Enum):
    PENDING = "pending"
    MATCHED = "matched"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class Priority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


# ========== 用户模型 ==========


class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    display_name: Optional[str] = Field(None, max_length=50)


class UserCreate(UserBase):
    password: str = Field(..., min_length=6, max_length=128)


class UserUpdate(BaseModel):
    display_name: Optional[str] = Field(None, max_length=50)
    role: Optional[UserRole] = None
    enabled: Optional[bool] = None


class UserResponse(UserBase):
    user_id: str
    role: UserRole
    enabled: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)


class LoginResponse(BaseModel):
    token: str
    user: UserResponse


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=6)
    new_password: str = Field(..., min_length=6, max_length=128)


# ========== 项目模型 ==========


class ProjectBase(BaseModel):
    project_url: str
    title: Optional[str] = None
    source_url: Optional[str] = None
    tender_type: Optional[str] = None
    budget: Optional[str] = None
    publish_date: Optional[str] = None


class ProjectCreate(ProjectBase):
    pass


class ProjectResponse(ProjectBase):
    id: Optional[int] = None
    status: ProjectStatus = ProjectStatus.PENDING
    keywords_matched: bool = False
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProjectUpdate(BaseModel):
    status: Optional[ProjectStatus] = None


# ========== 收藏模型 ==========


class FavoriteBase(ProjectBase):
    pass


class FavoriteCreate(FavoriteBase):
    pass


class FavoriteResponse(FavoriteBase):
    status: ProjectStatus = ProjectStatus.PENDING
    keywords_matched: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class FavoriteStatusUpdate(BaseModel):
    status: ProjectStatus


class FavoriteBatchCreate(BaseModel):
    projects: List[FavoriteCreate]


# ========== 标注模型 ==========


class AnnotationBase(BaseModel):
    project_url: str
    note: str = ""
    priority: Priority = Priority.NORMAL
    tags: List[str] = []


class AnnotationCreate(AnnotationBase):
    pass


class AnnotationUpdate(BaseModel):
    note: Optional[str] = None
    priority: Optional[Priority] = None
    tags: Optional[List[str]] = None


class AnnotationResponse(AnnotationBase):
    id: Optional[int] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ========== 预设模型 ==========


class PresetBase(BaseModel):
    name: str = Field(..., max_length=50)
    preset_key: str = Field(..., max_length=50)


class PresetCreate(PresetBase):
    filter_config: dict = {}
    is_default: bool = False


class PresetResponse(PresetBase):
    id: Optional[int] = None
    filter_config: dict = {}
    is_default: bool = False

    class Config:
        from_attributes = True


# ========== 日志模型 ==========


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class LogResponse(BaseModel):
    id: Optional[int] = None
    log_level: LogLevel
    message: str
    source: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ========== 统计模型 ==========


class StatsResponse(BaseModel):
    total_projects: int
    favorites_count: int
    annotations_count: int
    presets_count: int
    users_count: int
    logs_count: int
    error_logs_count: int


# ========== 分页模型 ==========


class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int
    page_size: int
    total_pages: int
