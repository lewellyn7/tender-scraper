"""数据过滤与关键词匹配模块 - 增强版 V2"""

import difflib
from typing import Any, Dict, List

from loguru import logger


class TenderFilter:
    """招投标数据过滤器 — 支持 TenderInfo 对象和字典"""

    def __init__(self, keywords: List[str], exclude_keywords: List[str] = None):
        self.keywords = keywords
        self.exclude_keywords = exclude_keywords or []
        self._fuzzy_threshold = 0.8

    def check_keywords(self, title: str) -> List[str]:
        """检查标题匹配的关键词列表（支持模糊匹配）"""
        title_lower = title.lower()
        matched = []
        for kw in self.keywords:
            kw_lower = kw.lower()
            # 精确匹配优先
            if kw_lower in title_lower:
                matched.append(kw)
            else:
                # 模糊匹配
                ratio = difflib.SequenceMatcher(None, kw_lower, title_lower).ratio()
                if ratio >= self._fuzzy_threshold:
                    matched.append(kw)
        return matched

    def fuzzy_match(self, keyword: str, text: str, threshold: float = 0.8) -> tuple:
        """
        模糊匹配单关键词
        返回: (是否匹配, 相似度)
        """
        text_lower = text.lower()
        kw_lower = keyword.lower()
        if kw_lower in text_lower:
            return True, 1.0
        ratio = difflib.SequenceMatcher(None, kw_lower, text_lower).ratio()
        return ratio >= threshold, ratio

    def filter_by_keywords(self, items: List[Dict]) -> List[Dict]:
        """根据关键词过滤项目（字典列表）"""
        filtered = []
        for item in items:
            title = self._get_title(item).lower()
            if self._contains_exclude(title):
                continue
            if self._matches_keywords(title):
                filtered.append(item)
        logger.info(f"📊 过滤完成：{len(items)} -> {len(filtered)} 条")
        return filtered

    def _matches_keywords(self, text: str) -> bool:
        return bool(self.check_keywords(text))

    def _contains_exclude(self, text: str) -> bool:
        text_lower = text.lower()
        return any(ex.lower() in text_lower for ex in self.exclude_keywords)

    def _get_title(self, item: Any) -> str:
        """兼容 TenderInfo 对象和字典的标题提取"""
        if hasattr(item, "title"):
            return item.title
        return item.get("title", "") if isinstance(item, dict) else ""

    def _get_field(self, item: Any, key: str, default: Any = "") -> Any:
        """兼容 TenderInfo 对象属性和字典键的字段提取"""
        if hasattr(item, key):
            return getattr(item, key, default)
        if isinstance(item, dict):
            return item.get(key, default)
        return default

    def _get_contact(self, item: Any) -> tuple:
        """从 TenderInfo 或字典提取联系人信息"""
        if hasattr(item, "contact_info"):
            ci = item.contact_info
            return ci.name if ci else "", getattr(ci, "phone", "") if ci else "", getattr(ci, "email", "") if ci else ""
        # dict
        return item.get("contact_name", ""), item.get("contact_phone", ""), item.get("contact_email", "")

    def _get_attachments(self, item: Any) -> tuple:
        """从 TenderInfo 或字典提取附件信息"""
        if hasattr(item, "attachments"):
            atts = item.attachments or []
            names = ", ".join(a.name for a in atts) if atts else ""
            return len(atts), names
        # dict
        return item.get("attachments_count", 0), item.get("attachments", "")

    def _fmt_date(self, dt) -> str:
        """格式化日期对象或字符串"""
        if dt is None:
            return ""
        if hasattr(dt, "strftime"):
            try:
                return dt.strftime("%Y-%m-%d")
            except Exception:
                pass
        return str(dt)[:10]

    def _fmt_kw(self, kw: Any) -> str:
        """格式化关键词列表"""
        if isinstance(kw, list):
            return ", ".join(kw)
        return kw or ""

    def extract_project_info(self, item: Any) -> Dict:
        """提取并标准化项目信息（统一入口，兼容 TenderInfo / dict）

        返回 22 字段的标准化字典。
        """
        title = self._get_title(item)
        url = self._get_field(item, "url") or self._get_field(item, "link", "")
        category = self._get_field(item, "category") or self._get_field(item, "type", "")
        publish_date = self._fmt_date(self._get_field(item, "publish_date"))
        publish_date_raw = self._get_field(item, "publish_date_raw", "")
        source_url = self._get_field(item, "source_url", "")
        content_preview = self._get_field(item, "content_preview", "")
        budget = self._get_field(item, "budget", "")
        deadline = self._fmt_date(self._get_field(item, "deadline"))
        region = self._get_field(item, "region", "")
        tender_type = self._get_field(item, "tender_type", "")
        keywords_matched = self._fmt_kw(self._get_field(item, "keywords_matched", []))
        scraped_at = self._fmt_date(self._get_field(item, "scraped_at"))
        scraped_by = self._get_field(item, "scraped_by", "tender-scraper v3.2")
        business_type = self._get_field(item, "business_type", "")
        info_type = self._get_field(item, "info_type", "")
        project_overview = self._get_field(item, "project_overview", "")
        bidder_requirements = self._get_field(item, "bidder_requirements", "")
        submission_deadline = self._get_field(item, "submission_deadline", "")
        bid_amount = self._get_field(item, "bid_amount", "")
        contact_name, contact_phone, contact_email = self._get_contact(item)
        attachments_count, attachments_str = self._get_attachments(item)

        return {
            "title": title,
            "type": category,
            "publish_date": publish_date,
            "publish_date_raw": publish_date_raw,
            "url": url,
            "source_url": source_url,
            "content_preview": content_preview,
            "budget": budget,
            "deadline": deadline,
            "region": region,
            "tender_type": tender_type,
            "keywords_matched": keywords_matched,
            "contact_name": contact_name,
            "contact_phone": contact_phone,
            "contact_email": contact_email,
            "attachments_count": attachments_count,
            "attachments": attachments_str,
            "scraped_at": scraped_at,
            "scraped_by": scraped_by,
            "business_type": business_type,
            "info_type": info_type,
            "project_overview": project_overview,
            "bidder_requirements": bidder_requirements,
            "submission_deadline": submission_deadline,
            "bid_amount": bid_amount,
        }
