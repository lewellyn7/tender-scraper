"""数据库表模块

- favorites.py        : favorites 表 CRUD
- annotations.py     : annotations 表 CRUD
- qualifications.py  : bidder_qualifications 表 CRUD
- users.py           : users 表 CRUD
- modals.py          : filter_presets / scrape_logs / duplicate_records / data_cache / backup / stats / schema
"""

from app.database.tables.annotations import AnnotationsMixin
from app.database.tables.favorites import FavoritesMixin
from app.database.tables.modals import ModalsMixin
from app.database.tables.qualifications import QualificationsMixin
from app.database.tables.users import UsersMixin

__all__ = [
    "FavoritesMixin",
    "AnnotationsMixin",
    "QualificationsMixin",
    "UsersMixin",
    "ModalsMixin",
]
