"""数据过滤与关键词匹配模块 - 增强版"""

from typing import Dict, List

from loguru import logger


class TenderFilter:
    """招投标数据过滤器"""

    def __init__(self, keywords: List[str], exclude_keywords: List[str] = None):
        self.keywords = keywords
        self.exclude_keywords = exclude_keywords or []

    def filter_by_keywords(self, items: List[Dict]) -> List[Dict]:
        """根据关键词过滤项目"""
        filtered = []
        for item in items:
            title = item.get("title", "").lower()
            if self._contains_exclude(title):
                continue
            if self._matches_keywords(title):
                filtered.append(item)
        logger.info(f"📊 过滤完成：{len(items)} -> {len(filtered)} 条")
        return filtered

    def check_keywords(self, title: str) -> List[str]:
        """检查标题匹配的关键词列表"""
        matched = []
        title_lower = title.lower()
        for keyword in self.keywords:
            if keyword.lower() in title_lower:
                matched.append(keyword)
        return matched

    def _matches_keywords(self, text: str) -> bool:
        """检查文本是否匹配任意关键词"""
        return bool(self.check_keywords(text))

    def _contains_exclude(self, text: str) -> bool:
        """检查是否包含排除词"""
        text_lower = text.lower()
        for exclude in self.exclude_keywords:
            if exclude.lower() in text_lower:
                return True
        return False

    def extract_project_info(self, item) -> Dict:
        """提取并标准化项目信息 (支持 TenderInfo 对象)

        返回 18 个字段的标准化字典
        """
        # 检查是否是 TenderInfo 对象
        if hasattr(item, "title"):
            # TenderInfo 对象
            title = item.title
            url = item.url
            category = item.category
            publish_date = item.publish_date
            publish_date_raw = item.publish_date_raw
            source_url = item.source_url
            content_preview = item.content_preview
            budget = item.budget
            deadline = item.deadline
            region = item.region
            tender_type = item.tender_type
            keywords_matched = item.keywords_matched
            scraped_at = item.scraped_at
            scraped_by = item.scraped_by
            # 新增字段
            business_type = getattr(item, "business_type", "")
            info_type = getattr(item, "info_type", "")
            project_overview = getattr(item, "project_overview", "")
            bidder_requirements = getattr(item, "bidder_requirements", "")
            submission_deadline = getattr(item, "submission_deadline", "")
            bid_amount = getattr(item, "bid_amount", "")

            # 联系人信息
            contact_name = item.contact_info.name if item.contact_info else ""
            contact_phone = item.contact_info.phone if item.contact_info else ""
            contact_email = item.contact_info.email if item.contact_info else ""

            # 附件信息
            attachments_count = (
                len(item.attachments) if hasattr(item, "attachments") and item.attachments else 0
            )
            attachments_str = (
                ", ".join([a.name for a in item.attachments]) if item.attachments else ""
            )
        else:
            # 字典
            title = item.get("title", "")
            url = item.get("url", item.get("link", ""))
            category = item.get("category", item.get("type", ""))
            publish_date = item.get("publish_date")
            publish_date_raw = item.get("publish_date_raw", "")
            source_url = item.get("source_url", "")
            content_preview = item.get("content_preview", "")
            budget = item.get("budget", "")
            deadline = item.get("deadline")
            region = item.get("region", "")
            tender_type = item.get("tender_type", "")
            keywords_matched = item.get("keywords_matched", [])
            contact_name = item.get("contact_name", "")
            contact_phone = item.get("contact_phone", "")
            contact_email = item.get("contact_email", "")
            scraped_at = item.get("scraped_at")
            scraped_by = item.get("scraped_by", "tender-scraper v3.1")
            attachments_count = item.get("attachments_count", 0)
            # 新字段
            business_type = item.get("business_type", "")
            info_type = item.get("info_type", "")
            project_overview = item.get("project_overview", "")
            bidder_requirements = item.get("bidder_requirements", "")
            submission_deadline = item.get("submission_deadline", "")
            bid_amount = item.get("bid_amount", "")
            attachments_str = item.get("attachments", "")

        # 处理关键词列表
        if isinstance(keywords_matched, list):
            keywords_str = ", ".join(keywords_matched)
        else:
            keywords_str = keywords_matched or ""

        # 日期格式化
        publish_date_str = ""
        if publish_date:
            try:
                publish_date_str = publish_date.strftime("%Y-%m-%d")
            except Exception:
                pass

        deadline_str = ""
        if deadline:
            try:
                deadline_str = deadline.strftime("%Y-%m-%d")
            except Exception:
                pass

        # 时间戳格式化
        scraped_at_str = ""
        if scraped_at:
            try:
                scraped_at_str = scraped_at.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

        return {
            "title": title,
            "type": category,  # 统一使用 type 字段名
            "publish_date": publish_date_str,
            "publish_date_raw": publish_date_raw,
            "url": url,
            "source_url": source_url,
            "content_preview": content_preview,
            "budget": budget,
            "deadline": deadline_str,
            "region": region,
            "tender_type": tender_type,
            "keywords_matched": keywords_str,
            "contact_name": contact_name,
            "contact_phone": contact_phone,
            "contact_email": contact_email,
            "attachments_count": attachments_count,
            "attachments": attachments_str,
            "scraped_at": scraped_at_str,
            "scraped_by": scraped_by,
            "business_type": business_type,
            "info_type": info_type,
            "project_overview": project_overview,
            "bidder_requirements": bidder_requirements,
            "submission_deadline": submission_deadline,
            "bid_amount": bid_amount,
        }

    def _find_matched_keywords(self, text: str) -> str:
        """找出文本中匹配的关键词"""
        matched = self.check_keywords(text)
        return ", ".join(matched)
