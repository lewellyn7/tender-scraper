"""敏感信息处理模块"""

import hashlib
import re
from typing import Any, Dict, List


class SensitiveDataHandler:
    """敏感数据处理器"""

    # 敏感字段列表
    SENSITIVE_FIELDS = {
        "contact_phone",
        "phone",
        "tel",
        "telephone",
        "mobile",
        "contact_email",
        "email",
        "e_mail",
        "id_card",
        "id_number",
        "identity",
        "身份证",
        "bank_account",
        "bank_no",
        "账号",
        "银行卡",
        "password",
        "passwd",
        "secret",
        "api_key",
        "apikey",
        "bot_token",
        "chat_id",
        "token",
        "access_token",
        "private_key",
        "secret_key",
        "n8n_webhook_key",
    }

    # 联系方式模式（用于日志脱敏）
    PHONE_PATTERN = re.compile(r"(\d{3,4}[-\s]?\d{7,8}|\d{11})")
    EMAIL_PATTERN = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
    ID_PATTERN = re.compile(r"\d{17}[\dXx]")

    @classmethod
    def is_sensitive_field(cls, field_name: str) -> bool:
        """判断字段是否为敏感字段"""
        if not field_name:
            return False
        field_lower = field_name.lower()
        return any(s in field_lower for s in cls.SENSITIVE_FIELDS)

    @classmethod
    def mask_phone(cls, phone: str) -> str:
        """手机号脱敏: 138****5678"""
        if not phone:
            return ""
        # 只保留前3后4位
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 7:
            return digits[:3] + "****" + digits[-4:]
        elif len(digits) >= 3:
            return digits[:3] + "****"
        return "****"

    @classmethod
    def mask_email(cls, email: str) -> str:
        """邮箱脱敏: t***@example.com"""
        if not email or "@" not in email:
            return email
        local, domain = email.rsplit("@", 1)
        if len(local) <= 2:
            masked_local = local[0] + "***"
        else:
            masked_local = local[0] + "***" + local[-1]
        return f"{masked_local}@{domain}"

    @classmethod
    def mask_id_card(cls, id_card: str) -> str:
        """身份证脱敏: 110***1234"""
        if not id_card:
            return ""
        digits = re.sub(r"\D", "", id_card)
        if len(digits) >= 10:
            return digits[:3] + "***" + digits[-4:]
        return "***********"

    @classmethod
    def mask_string(cls, value: str, visible_start: int = 2, visible_end: int = 2) -> str:
        """通用字符串脱敏"""
        if not value or len(value) <= visible_start + visible_end:
            return "****"
        return value[:visible_start] + "****" + value[-visible_end:]

    @classmethod
    def hash_value(cls, value: str, salt: str = "") -> str:
        """哈希敏感值（用于唯一标识但不暴露原始值）"""
        if not value:
            return ""
        combined = f"{value}{salt}".encode("utf-8")
        return hashlib.sha256(combined).hexdigest()[:16]

    @classmethod
    def sanitize_field(cls, field_name: str, value: Any) -> Any:
        """对敏感字段进行脱敏处理"""
        if not cls.is_sensitive_field(field_name):
            return value

        if value is None:
            return None

        value_str = str(value)

        if any(x in field_name.lower() for x in ["phone", "tel", "mobile"]):
            return cls.mask_phone(value_str)
        elif any(x in field_name.lower() for x in ["email", "mail"]):
            return cls.mask_email(value_str)
        elif any(x in field_name.lower() for x in ["id_card", "id_number", "identity", "身份证"]):
            return cls.mask_id_card(value_str)
        elif any(x in field_name.lower() for x in ["token", "key", "secret", "password", "api_"]):
            return cls.mask_string(value_str, 4, 0)
        else:
            return cls.mask_string(value_str)

    @classmethod
    def sanitize_dict(
        cls, data: Dict[str, Any], exclude_fields: List[str] = None
    ) -> Dict[str, Any]:
        """对字典中的敏感字段进行脱敏"""
        if not data:
            return data

        exclude_fields = set(exclude_fields or [])
        result = {}

        for key, value in data.items():
            if key in exclude_fields:
                result[key] = value
            elif cls.is_sensitive_field(key):
                result[key] = cls.sanitize_field(key, value)
            elif isinstance(value, dict):
                result[key] = cls.sanitize_dict(value, exclude_fields)
            elif isinstance(value, list) and value and isinstance(value[0], dict):
                result[key] = [cls.sanitize_dict(item, exclude_fields) for item in value]
            else:
                result[key] = value

        return result

    @classmethod
    def sanitize_log(cls, message: str) -> str:
        """对日志消息进行脱敏"""
        if not message:
            return message

        # 脱敏手机号
        message = cls.PHONE_PATTERN.sub(lambda m: cls.mask_phone(m.group()), message)

        # 脱敏邮箱
        message = cls.EMAIL_PATTERN.sub(lambda m: cls.mask_email(m.group()), message)

        # 脱敏身份证
        message = cls.ID_PATTERN.sub(lambda m: cls.mask_id_card(m.group()), message)

        return message

    @classmethod
    def filter_dict(cls, data: Dict[str, Any], remove_fields: List[str] = None) -> Dict[str, Any]:
        """完全移除敏感字段（不返回这些字段）"""
        if not data:
            return data

        remove_fields = set(remove_fields or [])
        sensitive_to_remove = {k for k in data.keys() if cls.is_sensitive_field(k)}
        fields_to_remove = remove_fields | sensitive_to_remove

        return {k: v for k, v in data.items() if k not in fields_to_remove}

    @classmethod
    def get_public_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """只返回非敏感的公开字段"""
        if not data:
            return {}

        public_fields = {
            "title",
            "url",
            "source_url",
            "publish_date",
            "tender_type",
            "type",
            "category",
            "budget",
            "bid_amount",
            "status",
            "keywords_matched",
            "business_type",
            "info_type",
            "region",
            "deadline",
            "submission_deadline",
            "project_overview",
            "bidder_requirements",
            "content_preview",
            "attachments",
            "created_at",
            "updated_at",
        }

        return {
            k: v for k, v in data.items() if k in public_fields and not cls.is_sensitive_field(k)
        }


# 全局实例
sensitive_handler = SensitiveDataHandler()


def sanitize_response(data: Dict[str, Any], include_sensitive: bool = False) -> Dict[str, Any]:
    """
    清理 API 响应中的敏感信息

    Args:
        data: 原始响应数据
        include_sensitive: 是否包含敏感字段（管理员可设为 True）

    Returns:
        清理后的安全响应
    """
    if not include_sensitive:
        # 默认移除敏感字段
        return sensitive_handler.filter_dict(data)
    else:
        # 仅脱敏不删除
        return sensitive_handler.sanitize_dict(data)


def mask_sensitive_value(field_name: str, value: Any) -> Any:
    """快捷函数：对指定字段脱敏"""
    return sensitive_handler.sanitize_field(field_name, value)


def clean_log_message(message: str) -> str:
    """快捷函数：清理日志中的敏感信息"""
    return sensitive_handler.sanitize_log(message)
