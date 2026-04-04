"""备份数据仓储"""

import hashlib
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional


class BackupRepository:
    """备份数据仓储"""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.backup_dir = self.db_path.parent / "db_backups"

    def create_backup(self) -> Optional[str]:
        """创建数据库备份"""
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.backup_dir / f"tender_scraper_{timestamp}.db"
            checksum_path = self.backup_dir / f"tender_scraper_{timestamp}.sha256"
            shutil.copy2(self.db_path, backup_path)
            checksum = hashlib.sha256(Path(backup_path).read_bytes()).hexdigest()
            Path(checksum_path).write_text(checksum)
            os.chmod(backup_path, 0o600)
            os.chmod(checksum_path, 0o600)
            return str(backup_path)
        except Exception:
            return None

    def verify_backup(self, backup_path: str) -> bool:
        """验证备份"""
        try:
            checksum_path = backup_path + ".sha256"
            if not Path(checksum_path).exists():
                return False
            stored = Path(checksum_path).read_text().strip()
            current = hashlib.sha256(Path(backup_path).read_bytes()).hexdigest()
            return stored == current
        except Exception:
            return False

    def list_backups(self, limit: int = 10) -> List[dict]:
        """列出备份"""
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            backups = []
            for f in sorted(self.backup_dir.glob("tender_scraper_*.db"), reverse=True)[:limit]:
                stat = f.stat()
                backups.append(
                    {
                        "path": str(f),
                        "name": f.name,
                        "size": stat.st_size,
                        "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "valid": self.verify_backup(str(f)),
                    }
                )
            return backups
        except Exception:
            return []

    def restore_backup(self, backup_path: str) -> bool:
        """恢复备份"""
        try:
            if not self.verify_backup(backup_path):
                return False
            shutil.copy2(backup_path, self.db_path)
            return True
        except Exception:
            return False

    def delete_backup(self, backup_path: str) -> bool:
        """删除备份"""
        try:
            Path(backup_path).unlink()
            checksum_path = backup_path + ".sha256"
            if Path(checksum_path).exists():
                Path(checksum_path).unlink()
            return True
        except Exception:
            return False
