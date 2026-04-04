"""报表生成模块 - 生成 Excel 报表 (增强版)"""

import os
from datetime import datetime

import pandas as pd
from loguru import logger


class ReportGenerator:
    """招投标报表生成器 - 增强版 (支持 18 字段)"""

    def __init__(self, output_dir: str = "output"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate_excel(self, projects: list, filename_prefix: str = "tender") -> str:
        """生成 Excel 报表 (增强版)"""
        if not projects:
            logger.warning("⚠️ 无数据可生成报表")
            return ""

        try:
            # 转换为 DataFrame
            df = pd.DataFrame(projects)

            # 定义列顺序 (18 字段完整版)
            columns_order = [
                "项目名称",
                "类型",
                "发布日期",
                "原始日期",
                "分类",
                "预算金额",
                "截止日期",
                "所属区域",
                "项目类型",
                "关键词匹配",
                "内容摘要",
                "联系人",
                "联系电话",
                "邮箱",
                "链接",
                "来源页",
                "采集时间",
                "采集器版本",
            ]

            # 映射旧字段名到新字段名
            field_mapping = {
                "项目名称": "title",
                "类型": "type",
                "发布日期": "publish_date",
                "匹配关键词": "keywords_matched",
                "链接": "url",
                "来源网站": "source_url",
                "预算金额": "budget",
                "联系人": "contact_name",
                "联系电话": "contact_phone",
                "邮箱": "contact_email",
                "内容摘要": "content_preview",
                "截止日期": "deadline",
                "所属区域": "region",
                "项目类型": "tender_type",
                "原始日期": "publish_date_raw",
                "分类": "category",
                "来源页": "source_url",
                "采集时间": "scraped_at",
                "采集器版本": "scraped_by",
            }

            # 选择可用列
            available_columns = []
            for col in columns_order:
                mapped = field_mapping.get(col, col)
                if mapped in df.columns:
                    available_columns.append(mapped)

            # 确保有数据
            if not available_columns:
                available_columns = list(df.columns)

            df = df[available_columns]

            # 重命名为中文
            rename_map = {v: k for k, v in field_mapping.items() if v in available_columns}
            df = df.rename(columns=rename_map)

            # 生成文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{filename_prefix}_{timestamp}.xlsx"
            filepath = os.path.join(self.output_dir, filename)

            # 写入 Excel
            with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name="采购项目", index=False)

                # 自动调整列宽
                worksheet = writer.sheets["采购项目"]
                for i, col in enumerate(df.columns):
                    max_length = max(df[col].astype(str).map(len).max(), len(col)) + 2
                    worksheet.column_dimensions[chr(65 + i)].width = min(max_length, 60)

            logger.info(f"✅ Excel 报表已生成：{filepath}")
            return filepath

        except Exception:
            logger.exception("Report generation error")
            return ""

    def generate_summary(self, projects: list) -> str:
        """生成文本摘要"""
        if not projects:
            return "今日无相关采购项目"

        summary = []
        summary.append(f"## 采购项目汇总 ({len(projects)} 条)\n")

        # 统计信息
        with_budget = sum(1 for p in projects if p.get("budget"))
        with_contact = sum(1 for p in projects if p.get("contact_name"))

        summary.append(f"📊 统计: 有预算 {with_budget} 条, 有联系人 {with_contact} 条\n")

        # 按类型分组
        by_type = {}
        for p in projects:
            p_type = p.get("type", p.get("category", "未知"))
            if p_type not in by_type:
                by_type[p_type] = []
            by_type[p_type].append(p)

        for p_type, items in by_type.items():
            summary.append(f"### {p_type} ({len(items)} 条)")
            for item in items:
                title = item.get("title", "无标题")[:40]
                keywords = item.get("keywords_matched", "")
                budget = item.get("budget", "")
                budget_str = f" | 预算: {budget}" if budget else ""
                summary.append(f"- {title}... [{keywords}]{budget_str}")
            summary.append("")

        return "\n".join(summary)
