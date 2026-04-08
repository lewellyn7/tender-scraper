"""其他表操作：presets / logs / duplicates / cache / backup / stats / schema"""

import hashlib
import json
import os
import queue
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from loguru import logger


class ModalsMixin:
    """其他表混合操作（filter_presets / scrape_logs / duplicate_records / data_cache / schema_version / backup）"""

    # ==================== presets ====================

    def save_preset(
        self, name: str, preset_key: str, filter_config: dict, is_default: bool = False
    ) -> bool:
        try:
            conn = self._get_conn()
            if is_default:
                conn.execute("UPDATE filter_presets SET is_default=0")
            conn.execute(
                """INSERT OR REPLACE INTO filter_presets
                           (name, preset_key, filter_config, is_default)
                           VALUES (?,?,?,?)""",
                (
                    name,
                    preset_key,
                    json.dumps(filter_config, ensure_ascii=False),
                    1 if is_default else 0,
                ),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"save_preset: {e}")
            return False

    def get_presets(self) -> List[dict]:
        try:
            c = self._get_conn()
            rows = c.execute(
                "SELECT * FROM filter_presets ORDER BY is_default DESC, created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"get_presets: {e}")
            return []

    def get_preset(self, preset_key: str) -> Optional[dict]:
        try:
            c = self._get_conn()
            row = c.execute(
                "SELECT * FROM filter_presets WHERE preset_key=?", (preset_key,)
            ).fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"get_preset: {e}")
            return None

    def delete_preset(self, preset_key: str) -> bool:
        try:
            self._batch_queue.put(("DELETE FROM filter_presets WHERE preset_key=?", (preset_key,)))
            return True
        except (queue.Full, OSError) as e:
            logger.error(f"delete_preset: {e}")
            return False

    # ==================== logs ====================

    def add_log(self, level: str, message: str, source: str = "system") -> bool:
        try:
            self._batch_queue.put(
                (
                    "INSERT INTO scrape_logs(log_level, message, source) VALUES (?,?,?)",
                    (level, message, source),
                )
            )
            return True
        except (queue.Full, OSError, IOError) as e:
            logger.error(f"add_log: {e}")
            return False

    def get_logs(self, level: str = None, limit: int = 200) -> List[dict]:
        try:
            c = self._get_conn()
            if level:
                rows = c.execute(
                    """SELECT * FROM scrape_logs WHERE log_level=?
                                   ORDER BY created_at DESC LIMIT ?""",
                    (level, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM scrape_logs ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"get_logs: {e}")
            return []

    def clear_logs(self, before_days: int = 7) -> bool:
        try:
            self._batch_queue.put(
                (
                    f"DELETE FROM scrape_logs WHERE created_at < datetime('now', '-{before_days} days')",
                    (),
                )
            )
            return True
        except (queue.Full, OSError) as e:
            logger.error(f"clear_logs: {e}")
            return False

    # ==================== duplicates ====================

    def add_duplicate(
        self, canonical_url: str, duplicate_url: str, title: str = "", similarity: float = 0
    ) -> bool:
        try:
            self._batch_queue.put(
                (
                    """INSERT OR IGNORE INTO duplicate_records
                   (canonical_url, duplicate_url, duplicate_title, similarity_score) VALUES (?,?,?,?)""",
                    (canonical_url, duplicate_url, title, similarity),
                )
            )
            return True
        except (queue.Full, OSError, IOError) as e:
            logger.error(f"add_duplicate: {e}")
            return False

    def get_duplicates(self, canonical_url: str = None, limit: int = 200) -> List[dict]:
        try:
            c = self._get_conn()
            if canonical_url:
                rows = c.execute(
                    """SELECT * FROM duplicate_records WHERE canonical_url=?
                                   ORDER BY similarity_score DESC LIMIT ?""",
                    (canonical_url, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM duplicate_records ORDER BY similarity_score DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"get_duplicates: {e}")
            return []

    # ==================== cache ====================

    def get_cached(self, key: str) -> Optional[dict]:
        try:
            c = self._get_conn()
            row = c.execute(
                """SELECT cache_value FROM data_cache
                              WHERE cache_key=? AND (expires_at IS NULL OR expires_at > datetime('now'))""",
                (key,),
            ).fetchone()
            return json.loads(row[0]) if row else None
        except Exception as e:
            logger.error(f"get_cached: {e}")
            return None

    def set_cached(self, key: str, value: dict, ttl_seconds: int = 3600) -> bool:
        try:
            self._batch_queue.put(
                (
                    """INSERT OR REPLACE INTO data_cache (cache_key, cache_value, expires_at)
                   VALUES (?,?,datetime('now', '+' || ? || ' seconds'))""",
                    (key, json.dumps(value, ensure_ascii=False), ttl_seconds),
                )
            )
            return True
        except (queue.Full, OSError, IOError) as e:
            logger.error(f"set_cached: {e}")
            return False

    def invalidate_cache(self, pattern: str = None) -> bool:
        try:
            conn = self._get_conn()
            if pattern:
                if not re.match(r"^[\w*-]+$", pattern):
                    logger.warning(f"Invalid cache pattern: {pattern}")
                    return False
                safe_pattern = pattern.replace("*", "%")
                conn.execute("DELETE FROM data_cache WHERE cache_key LIKE ?", (safe_pattern,))
            else:
                conn.execute("DELETE FROM data_cache")
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"invalidate_cache: {e}")
            return False

    # ==================== stats ====================

    def get_stats(self) -> dict:
        """获取统计信息（合并为1次查询）"""
        try:
            c = self._get_conn()
            rows = c.execute("""
                SELECT 'favorites' as tbl, COUNT(*) as cnt FROM favorites
                UNION ALL SELECT 'annotations', COUNT(*) FROM annotations
                UNION ALL SELECT 'filter_presets', COUNT(*) FROM filter_presets
                UNION ALL SELECT 'config_backups', COUNT(*) FROM config_backups
                UNION ALL SELECT 'scrape_logs', COUNT(*) FROM scrape_logs
                UNION ALL SELECT 'duplicate_records', COUNT(*) FROM duplicate_records
            """).fetchall()
            return {row["tbl"] + "_count": row["cnt"] for row in rows}
        except Exception as e:
            logger.error(f"get_stats: {e}")
            return {}

    # ==================== 数据库文件备份 ====================

    def backup_database(self) -> Optional[str]:
        """备份整个数据库文件"""
        try:
            backup_dir = Path(self.db_path).parent / "db_backups"
            backup_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = backup_dir / f"tender_scraper_{timestamp}.db"

            if hasattr(self, "_local") and getattr(self._local, "conn", None):
                self._local.conn.close()
                self._local.conn = None

            shutil.copy2(self.db_path, str(backup_path))

            wal_path = Path(self.db_path + "-wal")
            shm_path = Path(self.db_path + "-shm")
            if wal_path.exists():
                shutil.copy2(str(wal_path), str(backup_path) + "-wal")
            if shm_path.exists():
                shutil.copy2(str(shm_path), str(backup_path) + "-shm")

            checksum_path = str(backup_path) + ".sha256"
            with open(backup_path, "rb") as f:
                checksum = hashlib.sha256(f.read()).hexdigest()
            with open(checksum_path, "w") as f:
                f.write(checksum)

            os.chmod(backup_path, 0o600)
            os.chmod(checksum_path, 0o600)

            logger.info(f"数据库备份成功: {backup_path}")
            return str(backup_path)
        except Exception as e:
            logger.error(f"数据库备份失败: {e}")
            return None

    def verify_backup(self, backup_path: str) -> bool:
        """验证备份完整性"""
        try:
            checksum_path = backup_path + ".sha256"
            if not Path(checksum_path).exists():
                return False
            stored = open(checksum_path).read()
            current = hashlib.sha256(open(backup_path, "rb").read()).hexdigest()
            return stored == current
        except Exception as e:
            logger.error(f"备份校验失败: {e}")
            return False

    def list_db_backups(self, limit: int = 10) -> List[dict]:
        """列出数据库备份"""
        try:
            backup_dir = Path(self.db_path).parent / "db_backups"
            if not backup_dir.exists():
                return []

            backups = []
            for f in sorted(backup_dir.glob("tender_scraper_*.db"), reverse=True)[:limit]:
                stat = f.stat()
                backups.append(
                    {
                        "path": str(f),
                        "filename": f.name,
                        "size": stat.st_size,
                        "size_mb": round(stat.st_size / 1024 / 1024, 2),
                        "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    }
                )
            return backups
        except Exception as e:
            logger.error(f"列出数据库备份失败: {e}")
            return []

    def restore_database(self, backup_path: str) -> bool:
        """从备份恢复数据库"""
        try:
            backup_file = Path(backup_path)
            if not backup_file.exists():
                logger.error(f"备份文件不存在: {backup_path}")
                return False

            if hasattr(self, "_local") and getattr(self._local, "conn", None):
                self._local.conn.close()
                self._local.conn = None

            current_backup = (
                Path(self.db_path).parent
                / "db_backups"
                / f"auto_recover_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            )
            shutil.copy2(self.db_path, str(current_backup))

            shutil.copy2(backup_path, self.db_path)

            if Path(backup_path + "-wal").exists():
                shutil.copy2(backup_path + "-wal", self.db_path + "-wal")
            if Path(backup_path + "-shm").exists():
                shutil.copy2(backup_path + "-shm", self.db_path + "-shm")

            logger.info(f"数据库恢复成功: {backup_path}")
            return True
        except Exception as e:
            logger.error(f"数据库恢复失败: {e}")
            return False

    def delete_db_backup(self, backup_path: str) -> bool:
        """删除数据库备份"""
        try:
            backup_file = Path(backup_path)
            if backup_file.exists():
                os.remove(backup_path)
                wal_path = backup_path + "-wal"
                shm_path = backup_path + "-shm"
                if Path(wal_path).exists():
                    os.remove(wal_path)
                if Path(shm_path).exists():
                    os.remove(shm_path)
                logger.info(f"删除备份: {backup_path}")
            return True
        except Exception as e:
            logger.error(f"删除备份失败: {e}")
            return False

    def cleanup_old_backups(self, keep_count: int = 10) -> int:
        """清理旧备份，保留最近的 N 个"""
        try:
            backup_dir = Path(self.db_path).parent / "db_backups"
            if not backup_dir.exists():
                return 0

            backups = sorted(
                backup_dir.glob("tender_scraper_*.db"),
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )

            deleted = 0
            for old_backup in backups[keep_count:]:
                self.delete_db_backup(str(old_backup))
                deleted += 1

            logger.info(f"清理了 {deleted} 个旧备份")
            return deleted
        except Exception as e:
            logger.error(f"清理旧备份失败: {e}")
            return 0

    # ==================== schema version ====================

    def get_schema_version(self) -> int:
        try:
            c = self._get_conn()
            row = c.execute("SELECT version FROM schema_version").fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    def set_schema_version(self, version: int):
        try:
            conn = self._get_conn()
            conn.execute("INSERT OR REPLACE INTO schema_version VALUES (?)", (version,))
            conn.commit()
        except Exception as e:
            logger.error(f"set_schema_version: {e}")
