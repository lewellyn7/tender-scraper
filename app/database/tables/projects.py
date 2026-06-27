"""项目数据库表操作 - ProjectsMixin"""

from loguru import logger


class ProjectsMixin:
    """projects + project_records 表 CRUD 操作（混入 Database 类使用）"""

    # ── Schema (SQLite only; PG uses migration) ────────────────────────────────

    def _init_projects_table(self):
        """初始化 projects + project_records 表（SQLite）"""
        c = self._get_conn()
        c.execute(
            """CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name VARCHAR(500) NOT NULL,
                project_name_raw VARCHAR(500) NOT NULL,
                project_no VARCHAR(100) DEFAULT NULL UNIQUE,
                business_type VARCHAR(50) DEFAULT '',
                region VARCHAR(100) DEFAULT '',
                industry VARCHAR(100) DEFAULT '',
                budget VARCHAR(100) DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_projects_name ON projects(project_name)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at)")
        # project_no: UNIQUE but nullable; multiple NULLs are allowed (absent project_no)

        c.execute(
            """CREATE TABLE IF NOT EXISTS project_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                record_url TEXT NOT NULL UNIQUE,
                record_type VARCHAR(50) DEFAULT '',
                title VARCHAR(500) DEFAULT '',
                publish_date TEXT DEFAULT '',
                budget VARCHAR(100) DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )"""
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_project_records_project ON project_records(project_id)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_project_records_url ON project_records(record_url)"
        )

    # ── projects ─────────────────────────────────────────────────────────────

    def upsert_project(
        self,
        project_name: str,
        project_name_raw: str,
        project_no: str,
        business_type: str = "",
        region: str = "",
        industry: str = "",
        budget: str = "",
    ) -> int:
        """插入或更新项目，返回 project_id。

        - project_no 非空字符串 → 按 project_no 查找，ON CONFLICT UPDATE
        - project_no 为空/None    → 转为 NULL，按 project_name 查找，UPDATE 或 INSERT
        NULL 在 UNIQUE 索引中允许多行（不存在 project_no 的项目）。

        PG 兼容：使用 RETURNING id 拿 lastrowid。
        """
        conn = self._get_conn()
        pno = None if not project_no else project_no
        try:
            if pno is not None:
                # 2026-06-27 修复 (P2 3.11): SELECT-then-UPDATE/INSERT → ON CONFLICT
                # 消除 TOCTOU 竞态: 两线程同时查不到 → 同时 INSERT → duplicate key
                # ON CONFLICT (project_no) 原子化执行, 避免窗口期
                cur = conn.execute(
                    """INSERT INTO projects
                       (project_name, project_name_raw, project_no, business_type, region, industry, budget)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT (project_no) DO UPDATE SET
                           project_name = EXCLUDED.project_name,
                           project_name_raw = EXCLUDED.project_name_raw,
                           business_type = EXCLUDED.business_type,
                           region = EXCLUDED.region,
                           industry = EXCLUDED.industry,
                           budget = EXCLUDED.budget,
                           updated_at = CURRENT_TIMESTAMP
                       RETURNING id""",
                    (
                        project_name,
                        project_name_raw,
                        pno,
                        business_type,
                        region,
                        industry,
                        budget,
                    ),
                )
                conn.commit()
                row = cur.fetchone() if hasattr(cur, "fetchone") else None
                if row:
                    rid = row["id"] if isinstance(row, dict) else row[0]
                    return int(rid)
                return -1
            else:
                # project_no 为空 → 按 project_name 查找，UPDATE 或 INSERT
                existing = conn.execute(
                    "SELECT id FROM projects WHERE project_no IS NULL AND project_name = ?",
                    (project_name,),
                ).fetchone()
                if existing:
                    conn.execute(
                        """UPDATE projects SET
                           project_name_raw=?, business_type=?, region=?, industry=?, budget=?, updated_at=CURRENT_TIMESTAMP
                           WHERE id = ?""",
                        (
                            project_name_raw,
                            business_type,
                            region,
                            industry,
                            budget,
                            existing["id"],
                        ),
                    )
                    conn.commit()
                    return existing["id"]
                else:
                    cur = conn.execute(
                        """INSERT INTO projects
                           (project_name, project_name_raw, project_no, business_type, region, industry, budget)
                           VALUES (?, ?, NULL, ?, ?, ?, ?)
                           RETURNING id""",
                        (
                            project_name,
                            project_name_raw,
                            business_type,
                            region,
                            industry,
                            budget,
                        ),
                    )
                    conn.commit()
                    row = cur.fetchone() if hasattr(cur, "fetchone") else None
                    if row:
                        rid = row["id"] if isinstance(row, dict) else row[0]
                        return int(rid)
                    return -1
        except Exception as e:
            logger.error(f"upsert_project: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
            return -1

    def get_project_by_no(self, project_no: str):
        """按 project_no 查询项目"""
        try:
            c = self._get_conn()
            row = c.execute(
                "SELECT * FROM projects WHERE project_no = ?", (project_no if project_no else None,)
            ).fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"get_project_by_no: {e}")
            return None

    def get_projects_with_records(self, limit: int = 100):
        """返回所有项目及其关联记录（Python 分组）"""
        try:
            c = self._get_conn()
            projects = c.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
            if not projects:
                return []

            project_ids = [int(p["id"]) for p in projects]
            placeholders = ",".join("?" * len(project_ids))
            records = c.execute(
                f"SELECT * FROM project_records WHERE project_id IN ({placeholders}) ORDER BY publish_date DESC",
                project_ids,
            ).fetchall()

            # Python 分组（project_id 统一转 int 避免 SQLite string/int 异型比较）
            records_by_project = {}
            for rec in records:
                pid = int(rec["project_id"])
                if pid not in records_by_project:
                    records_by_project[pid] = []
                records_by_project[pid].append(dict(rec))

            result = []
            for p in projects:
                result.append(
                    {
                        **dict(p),
                        "records": records_by_project.get(int(p["id"]), []),
                    }
                )
            return result
        except Exception as e:
            logger.error(f"get_projects_with_records: {e}")
            return []

    # ── project_records ───────────────────────────────────────────────────────

    def add_project_record(
        self,
        project_id: int,
        record_url: str,
        record_type: str = "",
        title: str = "",
        publish_date: str = "",
        budget: str = "",
    ) -> int:
        """插入或更新项目记录（ON CONFLICT 防止重复），返回 record_id。

        未变动数据返回 -1。
        """
        try:
            conn = self._get_conn()
            cur = conn.execute(
                """INSERT INTO project_records
                   (project_id, record_url, record_type, title, publish_date, budget)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (record_url) DO UPDATE SET
                   record_type=EXCLUDED.record_type,
                   title=EXCLUDED.title,
                   publish_date=EXCLUDED.publish_date,
                   budget=EXCLUDED.budget
                   RETURNING id""",
                (
                    project_id,
                    record_url,
                    record_type,
                    title,
                    publish_date,
                    budget,
                ),
            )
            conn.commit()
            row = cur.fetchone() if hasattr(cur, "fetchone") else None
            record_id = -1
            if row:
                record_id = int(row["id"] if isinstance(row, dict) else row[0])

            # Hook: 写入后触发收藏项目关联提醒（失败不抛）
            if record_id > 0:
                try:
                    self._try_trigger_favorite_notification(
                        project_id=project_id,
                        record_id=record_id,
                        project_name=title,  # 临时用 title，后头会重取
                        info_type=record_type,
                        record_url=record_url,
                        record_title=title,
                    )
                except Exception as e:
                    logger.debug(f"favorite notification hook failed: {e}")
            return record_id
        except Exception as e:
            logger.error(f"add_project_record: {e}")
            return -1

    def _try_trigger_favorite_notification(
        self,
        project_id: int,
        record_id: int,
        project_name: str,
        info_type: str,
        record_url: str,
        record_title: str = "",
    ) -> None:
        """Hook: 写入新 record 后触发收藏项目关联提醒。

        委托给 `app.services.favorite_notifier.try_notify_favorite_match`。
        失败不抛——不干扰采集主流程。
        """
        try:
            from app.services.favorite_notifier import try_notify_favorite_match

            try_notify_favorite_match(
                project_id=project_id,
                record_id=record_id,
                project_name=project_name,
                info_type=info_type,
                record_url=record_url,
                record_title=record_title,
            )
        except Exception as e:
            logger.debug(f"favorite notification hook failed: {e}")

    # ── sync helper ───────────────────────────────────────────

    def _sync_projects_link(self, rows: list, source_table: str = "projects_cqggzy") -> int:
        """联动写入 projects + project_records 关联表。

        对每条 row:
        1. upsert_project() → project_id
        2. add_project_record() → record_id (会触发通知 hook)

        失败被捕获，不阻断主流程。
        """
        if not rows:
            return 0
        synced = 0
        try:
            from app.utils.project_linker import (
                extract_project_no,
                normalize_project_name,
            )
        except Exception as e:
            logger.warning(f"import project_linker failed: {e}")
            return 0

        for r in rows:
            if not isinstance(r, dict):
                continue
            url = r.get("url", "")
            title = r.get("title", "")
            if not url or not title:
                continue

            try:
                # 1. 计算 project_name / project_no
                project_name = normalize_project_name(title)
                project_no_raw = r.get("project_no", "") or ""
                if not project_no_raw:
                    # 从 title / content_preview 提取
                    project_no_raw = extract_project_no(
                        title, r.get("content_preview", "") or ""
                    ) or ""
                # ccgp source 已有 project_no
                project_no = project_no_raw

                # 2. upsert_project
                project_id = self.upsert_project(
                    project_name=project_name,
                    project_name_raw=title,
                    project_no=project_no,
                    business_type=r.get("business_type", "") or r.get("tender_type", ""),
                    region=r.get("region", "") or "",
                    industry=r.get("industry", "") or "",
                    budget=r.get("budget", "") or "",
                )
                if project_id <= 0:
                    continue

                # 3. add_project_record (此函数末尾会触发通知 hook)
                info_type = r.get("info_type", "") or ""
                # publish_date:可能是 datetime/date/str，统一转 str
                pub_date = r.get("publish_date", "")
                if pub_date and not isinstance(pub_date, str):
                    try:
                        pub_date = pub_date.strftime("%Y-%m-%d")
                    except Exception:
                        pub_date = str(pub_date)

                self.add_project_record(
                    project_id=project_id,
                    record_url=url,
                    record_type=info_type,
                    title=title,
                    publish_date=pub_date or "",
                    budget=r.get("budget", "") or "",
                )
                synced += 1
            except Exception as e:
                logger.debug(f"_sync_projects_link 单条失败: {url}: {e}")
                continue

        if synced:
            logger.info(
                f"🔗 {source_table} 联动入 {synced} 条到 projects + project_records"
            )
        return synced
