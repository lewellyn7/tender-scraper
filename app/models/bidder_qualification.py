"""投标主体资质数据模型"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional


class QualificationCategory(str, Enum):
    """资质类别"""
    ARCHITECTURE = "建筑"      # 建筑工程
    IT = "IT"                 # 信息技术
    SERVICE = "服务"           # 服务类
    EQUIPMENT = "设备"         # 设备类
    OTHER = "其他"


class QualificationLevel(str, Enum):
    """资质等级"""
    LEVEL_1 = "一级"
    LEVEL_2 = "二级"
    LEVEL_3 = "三级"
    LEVEL_A = "甲级"
    LEVEL_B = "乙级"
    LEVEL_C = "丙级"
    LEVEL_SPECIAL = "特级"
    OTHER = "其他"


class QualificationStatus(str, Enum):
    """资质状态"""
    VALID = "有效"
    EXPIRED = "过期"
    PENDING = "待审核"
    REVOKED = "已撤销"


@dataclass
class BidderQualification:
    """投标主体资质"""
    name: str = ""                       # 资质名称
    category: str = ""                   # 资质类别
    level: str = ""                      # 资质等级
    certificate_no: str = ""             # 证书编号
    valid_from: Optional[date] = None    # 有效期开始
    valid_to: Optional[date] = None     # 有效期结束
    issuer: str = ""                     # 发证机关
    file_path: str = ""                  # 资质文件路径
    linked_tenders: List[str] = field(default_factory=list)  # 关联招标项目
    status: str = "有效"                 # 状态
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def is_expired(self) -> bool:
        """检查是否过期"""
        if self.valid_to is None:
            return False
        return self.valid_to < date.today()

    def days_until_expiry(self) -> Optional[int]:
        """距离过期天数"""
        if self.valid_to is None:
            return None
        delta = self.valid_to - date.today()
        return delta.days

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "level": self.level,
            "certificate_no": self.certificate_no,
            "valid_from": self.valid_from.isoformat() if self.valid_from else "",
            "valid_to": self.valid_to.isoformat() if self.valid_to else "",
            "issuer": self.issuer,
            "file_path": self.file_path,
            "linked_tenders": self.linked_tenders,
            "status": self.status,
            "is_expired": self.is_expired(),
            "days_until_expiry": self.days_until_expiry(),
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "BidderQualification":
        """从字典创建"""
        valid_from = None
        valid_to = None
        if data.get("valid_from"):
            try:
                valid_from = date.fromisoformat(str(data["valid_from"]))
            except (ValueError, TypeError):
                pass
        if data.get("valid_to"):
            try:
                valid_to = date.fromisoformat(str(data["valid_to"]))
            except (ValueError, TypeError):
                pass

        linked = data.get("linked_tenders", [])
        if isinstance(linked, str):
            import json
            try:
                linked = json.loads(linked)
            except Exception:
                linked = [linked] if linked else []

        return cls(
            id=data.get("id"),
            name=data.get("name", ""),
            category=data.get("category", ""),
            level=data.get("level", ""),
            certificate_no=data.get("certificate_no", ""),
            valid_from=valid_from,
            valid_to=valid_to,
            issuer=data.get("issuer", ""),
            file_path=data.get("file_path", ""),
            linked_tenders=linked,
            status=data.get("status", "有效"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )
