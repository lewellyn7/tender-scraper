"""项目服务层 - 业务逻辑"""

import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

from app.database.repositories import AnnotationRepository, FavoriteRepository
from app.utils.tfidf_matcher import TFIDFMatcher

SYS_PATH = Path(__file__).parent.parent.parent

# 内存缓存
_cache = {"projects": [], "total": 0, "last_load": 0}


class ProjectService:
    """项目服务层"""

    def __init__(self):
        self.favorite_repo = FavoriteRepository()
        self.annotation_repo = AnnotationRepository()

    @staticmethod
    def load_projects():
        """加载项目数据"""
        now = time.time()
        if _cache["projects"] and (now - _cache["last_load"]) < 60:
            return _cache["projects"], _cache["total"]

        data_file = SYS_PATH / "output" / "latest.json"
        if data_file.exists():
            try:
                with open(data_file, encoding="utf-8") as f:
                    d = json.load(f)
                _cache["projects"] = d.get("projects", [])
                _cache["total"] = d.get("total", 0)
                _cache["last_load"] = now
                return _cache["projects"], _cache["total"]
            except Exception as e:
                logger.warning(f"Failed to load projects: {e}")
        return [], 0

    @staticmethod
    def clear_cache():
        """清空缓存"""
        _cache["projects"] = []
        _cache["last_load"] = 0

    def get_projects(
        self,
        page: int = 1,
        page_size: int = 20,
        keyword: str = "",
        category: str = "",
        date_start: str = "",
        date_end: str = "",
        preset_key: str = "",
        source: str = "",
        sort_by: str = "date",
        use_tfidf: bool = False,
    ) -> Dict:
        """获取项目列表（带业务逻辑）"""
        from app.database import get_db

        db = get_db()
        projects, _ = self.load_projects()

        # 应用预设
        if preset_key:
            p = db.get_preset(preset_key)
            if p:
                fc = p.get("filter_config", {})
                keyword = keyword or fc.get("keyword", "")
                category = category or fc.get("category", "")
                date_start = date_start or fc.get("date_start", "")
                date_end = date_end or fc.get("date_end", "")

        filtered = projects

        # 关键词过滤
        if keyword:
            if use_tfidf:
                m = TFIDFMatcher()
                m.build_corpus([p.get("title", "") for p in projects])
                kws = [k.strip() for k in keyword.split(",") if k.strip()]
                m.build_keywords(kws)
                mu = set()
                for p in projects:
                    _, matched, _ = m.match(p.get("title", ""), kws)
                    if matched:
                        mu.add(p.get("url", ""))
                filtered = [p for p in projects if p.get("url", "") in mu]
            else:
                kws = [k.strip().lower() for k in keyword.split(",") if k.strip()]
                filtered = [
                    p
                    for p in projects
                    if any(kw in p.get("title", "").lower() for kw in kws)
                    or any(kw in p.get("content_preview", "").lower() for kw in kws)
                ]

        # 分类过滤
        if category:
            filtered = [
                p for p in filtered if p.get("tender_type") == category or p.get("type") == category
            ]

        # 日期范围过滤
        if date_start:
            filtered = [p for p in filtered if p.get("publish_date", "") >= date_start]
        if date_end:
            filtered = [p for p in filtered if p.get("publish_date", "") <= date_end]

        # 来源过滤
        if source:
            filtered = [p for p in filtered if source in p.get("source_url", "")]

        # 排序
        if sort_by == "budget":

            def bnum(p):
                b = p.get("budget", "")
                try:
                    return float(re.sub(r"[^\d.]", "", b)) * (10000 if "万" in b else 1)
                except Exception:
                    return 0

            filtered.sort(key=bnum, reverse=True)
        else:
            filtered.sort(key=lambda p: p.get("publish_date", "") or "", reverse=True)

        # 分页
        total_f = len(filtered)
        start = (page - 1) * page_size
        page_projects = filtered[start : start + page_size]

        # 添加收藏和标注信息
        for p in page_projects:
            p["is_favorite"] = self.favorite_repo.is_favorite(p.get("url", ""))
            p["annotation"] = self.annotation_repo.get(p.get("url", ""))

        return {
            "data": page_projects,
            "total": total_f,
            "page": page,
            "page_size": page_size,
        }

    def add_favorite(self, project: dict, user_id: str = None) -> bool:
        """添加收藏"""
        # 业务逻辑：验证项目有效性
        if not project.get("url"):
            logger.warning("Cannot add favorite: missing URL")
            return False

        # 记录日志
        if user_id:
            logger.info(f"User {user_id} added favorite: {project.get("title", "")[:30]}")

        return self.favorite_repo.add(project)

    def remove_favorite(self, project_url: str, user_id: str = None) -> bool:
        """移除收藏"""
        if user_id:
            logger.info(f"User {user_id} removed favorite: {project_url}")
        return self.favorite_repo.remove(project_url)

    def get_favorites(self, status: str = None) -> List[dict]:
        """获取收藏列表"""
        return self.favorite_repo.get_favorites(status)

    def add_annotation(
        self,
        project_url: str,
        note: str,
        priority: str = "normal",
        tags: list = None,
    ) -> bool:
        """添加标注"""
        return self.annotation_repo.add(project_url, note, priority, tags)

    def get_annotation(self, project_url: str) -> Optional[dict]:
        """获取标注"""
        return self.annotation_repo.get(project_url)

    def get_stats(self) -> dict:
        """获取统计信息"""
        from app.database import get_db

        db = get_db()
        projects, total = self.load_projects()

        data_file = SYS_PATH / "output" / "latest.json"
        last_run = "-"
        if data_file.exists():
            try:
                with open(data_file, encoding="utf-8") as f:
                    d = json.load(f)
                    last_run = d.get("last_run", "-")
            except Exception:
                pass

        return {
            "total": total,
            "filtered": len([p for p in projects if p.get("keywords_matched")]),
            "last_run": last_run,
            "db_stats": db.get_stats(),
        }
