"""预设仓储"""

import json
from typing import Dict, Optional

from .base import BaseRepository


class PresetRepository(BaseRepository):
    """预设数据仓储"""

    def __init__(self):
        super().__init__("filter_presets")

    def get_by_key(self, preset_key: str) -> Optional[Dict]:
        """根据 key 获取预设"""
        row = self.conn.execute(
            "SELECT * FROM filter_presets WHERE preset_key = ?", (preset_key,)
        ).fetchone()
        return dict(row) if row else None

    def save(
        self, name: str, preset_key: str, filter_config: Dict, is_default: bool = False
    ) -> bool:
        """保存预设"""
        try:
            if is_default:
                self.conn.execute("UPDATE filter_presets SET is_default = 0")

            self.conn.execute(
                """INSERT OR REPLACE INTO filter_presets
                   (name, preset_key, filter_config, is_default)
                   VALUES (?, ?, ?, ?)""",
                (
                    name,
                    preset_key,
                    json.dumps(filter_config, ensure_ascii=False),
                    1 if is_default else 0,
                ),
            )
            self.conn.commit()
            return True
        except Exception as e:
            self.db.logger.error(f"Save preset error: {e}")
            return False

    def delete_by_key(self, preset_key: str) -> bool:
        """根据 key 删除预设"""
        return self.delete("preset_key", preset_key)
