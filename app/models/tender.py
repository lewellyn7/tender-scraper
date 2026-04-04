"""招投标数据模型 - 修复版 (25 字段，支持工程建设/政府采购全量字段)"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class ContactInfo:
    """联系人信息"""

    name: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""


@dataclass
class TenderAttachment:
    """附件信息"""

    name: str = ""
    url: str = ""
    file_type: str = ""
    file_size: str = ""


@dataclass
class TenderInfo:
    """招投标信息 - 完整数据模型 (25 字段)"""

    # === 核心字段 (列表页采集) ===
    title: str = ""  # 标题
    url: str = ""  # 原始访问链接
    category: str = ""  # 分类
    publish_date: Optional[datetime] = None  # 发布日期
    publish_date_raw: str = ""  # 原始日期文本

    # === 来源追踪 ===
    source_url: str = ""  # 来源页面 URL

    # === 业务分类 (新增) ===
    business_type: str = ""  # 业务类型：政府采购/工程招投标
    info_type: str = ""  # 信息类型：采购意向/采购公告/结果公告/招标公告等

    # === 详情页字段 ===
    content_preview: str = ""  # 内容摘要 (前 300 字)
    full_content: str = ""  # 完整内容
    attachments: List[TenderAttachment] = field(default_factory=list)
    contact_info: ContactInfo = field(default_factory=ContactInfo)

    # === 金额相关 ===
    budget: str = ""  # 预算金额
    bid_amount: str = ""  # 中标金额

    # === 时间相关 ===
    deadline: Optional[datetime] = None  # 截止日期
    opening_date: Optional[datetime] = None  # 开标时间

    # === 地区/行业 ===
    region: str = ""  # 所属区域
    industry: str = ""  # 行业分类
    tender_type: str = ""  # 项目类型

    # === 工程建设专用字段 (新增) ===
    project_overview: str = ""  # 项目概况与招标范围
    bidder_requirements: str = ""  # 投标人资格要求
    submission_deadline: str = ""  # 投标文件递交截止时间
    submission_location: str = ""  # 投标文件递交地点

    # === 元数据 ===
    keywords_matched: List[str] = field(default_factory=list)
    scraped_at: datetime = field(default_factory=datetime.now)
    scraped_by: str = "tender-scraper v3.1"

    def to_dict(self) -> Dict:
        """转换为字典 (用于 JSON/Excel 导出)"""
        return {
            "title": self.title,
            "url": self.url,
            "category": self.category,
            "publish_date": self.publish_date.strftime("%Y-%m-%d") if self.publish_date else "",
            "publish_date_raw": self.publish_date_raw,
            "source_url": self.source_url,
            "business_type": self.business_type,
            "info_type": self.info_type,
            "content_preview": self.content_preview,
            "full_content": self.full_content,
            "budget": self.budget,
            "bid_amount": self.bid_amount,
            "deadline": self.deadline.strftime("%Y-%m-%d %H:%M") if self.deadline else "",
            "opening_date": (
                self.opening_date.strftime("%Y-%m-%d %H:%M") if self.opening_date else ""
            ),
            "region": self.region,
            "industry": self.industry,
            "tender_type": self.tender_type,
            "project_overview": self.project_overview,
            "bidder_requirements": self.bidder_requirements,
            "submission_deadline": self.submission_deadline,
            "submission_location": self.submission_location,
            "keywords_matched": ", ".join(self.keywords_matched),
            "scraped_at": self.scraped_at.strftime("%Y-%m-%d %H:%M:%S"),
            "scraped_by": self.scraped_by,
            "contact_name": self.contact_info.name,
            "contact_phone": self.contact_info.phone,
            "contact_email": self.contact_info.email,
            "attachments_count": len(self.attachments),
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "TenderInfo":
        """从字典创建"""
        return cls(
            title=data.get("title", ""),
            url=data.get("url", ""),
            category=data.get("category", ""),
            publish_date=None,
            publish_date_raw=data.get("publish_date_raw", ""),
            source_url=data.get("source_url", ""),
            business_type=data.get("business_type", ""),
            info_type=data.get("info_type", ""),
            content_preview=data.get("content_preview", ""),
            full_content=data.get("full_content", ""),
            budget=data.get("budget", ""),
            bid_amount=data.get("bid_amount", ""),
            region=data.get("region", ""),
            industry=data.get("industry", ""),
            tender_type=data.get("tender_type", ""),
            project_overview=data.get("project_overview", ""),
            bidder_requirements=data.get("bidder_requirements", ""),
            submission_deadline=data.get("submission_deadline", ""),
            submission_location=data.get("submission_location", ""),
            keywords_matched=data.get("keywords_matched", []),
            scraped_by=data.get("scraped_by", "tender-scraper v3.1"),
        )
