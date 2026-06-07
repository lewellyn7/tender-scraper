"""数据库表模块

- favorites.py        : favorites 表 CRUD
- annotations.py     : annotations 表 CRUD
- qualifications.py  : bidder_qualifications 表 CRUD
- users.py           : users 表 CRUD
- modals.py          : filter_presets / scrape_logs / duplicates / cache / backup / stats / schema
- keywords.py         : keywords 表 CRUD（包含/排除关键词，精确/模糊匹配）
- projects.py        : projects + project_records 表 CRUD
- notifications.py   : notifications 表 CRUD（收藏项目关联提醒）
"""

from app.database.tables.annotations import AnnotationsMixin
from app.database.tables.favorites import FavoritesMixin
from app.database.tables.modals import ModalsMixin
from app.database.tables.notifications import NotificationsMixin
from app.database.tables.qualifications import QualificationsMixin
from app.database.tables.users import UsersMixin
from app.database.tables.keywords import KeywordsMixin
from app.database.tables.projects import ProjectsMixin

__all__ = [
    "FavoritesMixin",
    "AnnotationsMixin",
    "QualificationsMixin",
    "UsersMixin",
    "ModalsMixin",
    "KeywordsMixin",
    "ProjectsMixin",
    "NotificationsMixin",
]
