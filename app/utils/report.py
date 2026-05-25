"""报表生成模块 - 生成 Excel 报表 V2

字段名统一使用英文（与 extract_project_info 输出保持一致），
导出时重命名为中文列名。
"""

import os
from datetime import datetime

import pandas as pd
from loguru import logger

# 中文列名映射
COLUMN_RENAME = {
    "title": "项目名称",
    "type": "类型",
    "publish_date": "发布日期",
    "publish_date_raw": "原始日期",
    "url": "链接",
    "source_url": "来源页",
    "content_preview": "内容摘要",
    "budget": "预算金额",
    "deadline": "截止日期",
    "region": "所属区域",
    "tender_type": "项目类型",
    "keywords_matched": "关键词匹配",
    "contact_name": "联系人",
    "contact_phone": "联系电话",
    "contact_email": "邮箱",
    "attachments_count": "附件数",
    "attachments": "附件列表",
    "scraped_at": "采集时间",
    "scraped_by": "采集器版本",
    "business_type": "业务类型",
    "info_type": "信息类型",
    "project_overview": "项目概况",
    "bidder_requirements": "投标人资格要求",
    "submission_deadline": "递交截止时间",
    "bid_amount": "中标金额",
}


class ReportGenerator:
    """招投标报表生成器 V2"""

    def __init__(self, output_dir: str = "output"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate_excel(self, projects: list, filename_prefix: str = "tender") -> str:
        """生成 Excel 报表"""
        if not projects:
            logger.warning("⚠️ 无数据可生成报表")
            return ""

        try:
            df = pd.DataFrame(projects)

            # 重命名为中文列名
            rename = {k: v for k, v in COLUMN_RENAME.items() if k in df.columns}
            df = df.rename(columns=rename)

            # 选择优先列顺序
            priority_cols = [
                "项目名称", "类型", "发布日期", "预算金额", "截止日期",
                "所属区域", "关键词匹配", "中标金额", "联系人", "联系电话",
                "业务类型", "信息类型", "项目概况", "投标人资格要求",
                "内容摘要", "链接", "来源页", "采集时间", "采集器版本",
                "附件数", "附件列表", "递交截止时间",
            ]
            available = [c for c in priority_cols if c in df.columns]
            remaining = [c for c in df.columns if c not in priority_cols]
            df = df[available + remaining]

            # 生成文件
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{filename_prefix}_{timestamp}.xlsx"
            filepath = os.path.join(self.output_dir, filename)

            with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name="采购项目", index=False)
                ws = writer.sheets["采购项目"]
                for i, col in enumerate(df.columns):
                    col_data = df[col].fillna('').astype(str)
                    max_len = max(col_data.map(len).max(), len(col)) + 2
                    ws.column_dimensions[chr(65 + i) if i < 26 else "A"].width = min(max_len, 60)

            logger.info(f"✅ Excel 报表已生成：{filepath}")
            return filepath
        except Exception:
            logger.exception("报表生成异常")
            return ""

    def generate_summary(self, projects: list) -> str:
        """生成文本摘要"""
        if not projects:
            return "今日无相关采购项目"

        lines = [f"## 采购项目汇总 ({len(projects)} 条)\n"]

        with_budget = sum(1 for p in projects if p.get("budget"))
        with_contact = sum(1 for p in projects if p.get("contact_name"))
        lines.append(f"📊 统计：有预算 {with_budget} 条，有联系人 {with_contact} 条\n")

        by_type = {}
        for p in projects:
            t = p.get("type") or p.get("category", "未知")
            by_type.setdefault(t, []).append(p)

        for p_type, items in by_type.items():
            lines.append(f"### {p_type} ({len(items)} 条)")
            for item in items:
                title = (item.get("title") or "无标题")[:40]
                kw = item.get("keywords_matched", "")
                budget = item.get("budget", "")
                b_str = f" | 预算: {budget}" if budget else ""
                lines.append(f"- {title}... [{kw}]{b_str}")
            lines.append("")
        return "\n".join(lines)
