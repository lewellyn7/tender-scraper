"""
报表生成模块 - 生成 Excel 报表
"""
import pandas as pd
from loguru import logger
from datetime import datetime
import os

class ReportGenerator:
    """招投标报表生成器"""
    
    def __init__(self, output_dir: str = "output"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
    
    def generate_excel(self, projects: list, filename_prefix: str = "tender") -> str:
        """生成 Excel 报表"""
        if not projects:
            logger.warning("⚠️ 无数据可生成报表")
            return ""
        
        try:
            # 转换为 DataFrame
            df = pd.DataFrame(projects)
            
            # 重新排列列顺序
            columns_order = ['项目名称', '类型', '发布日期', '匹配关键词', '链接', '来源网站']
            available_columns = [col for col in columns_order if col in df.columns]
            df = df[available_columns]
            
            # 生成文件名
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{filename_prefix}_{timestamp}.xlsx"
            filepath = os.path.join(self.output_dir, filename)
            
            # 写入 Excel
            with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='采购项目', index=False)
                
                # 自动调整列宽
                worksheet = writer.sheets['采购项目']
                for i, col in enumerate(df.columns):
                    max_length = max(df[col].astype(str).map(len).max(), len(col)) + 2
                    worksheet.column_dimensions[chr(65 + i)].width = min(max_length, 50)
            
            logger.info(f"✅ Excel 报表已生成：{filepath}")
            return filepath
            
        except Exception as e:
            logger.error(f"❌ 报表生成失败：{e}")
            return ""
    
    def generate_summary(self, projects: list) -> str:
        """生成文本摘要"""
        if not projects:
            return "今日无相关采购项目"
        
        summary = []
        summary.append(f"## 采购项目汇总 ({len(projects)} 条)\n")
        
        # 按类型分组
        by_type = {}
        for p in projects:
            p_type = p.get('类型', '未知')
            if p_type not in by_type:
                by_type[p_type] = []
            by_type[p_type].append(p)
        
        for p_type, items in by_type.items():
            summary.append(f"### {p_type} ({len(items)} 条)")
            for item in items:
                summary.append(f"- {item['项目名称']} ({item['匹配关键词']})")
            summary.append("")
        
        return "\n".join(summary)
