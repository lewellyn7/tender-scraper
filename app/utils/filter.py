"""
数据过滤与关键词匹配模块
"""
from loguru import logger
from typing import List, Dict
import re

class TenderFilter:
    """招投标数据过滤器"""
    
    def __init__(self, keywords: List[str], exclude_keywords: List[str] = None):
        self.keywords = keywords
        self.exclude_keywords = exclude_keywords or []
        
    def filter_by_keywords(self, items: List[Dict]) -> List[Dict]:
        """根据关键词过滤项目"""
        filtered = []
        
        for item in items:
            title = item.get('title', '').lower()
            
            # 检查排除词
            if self._contains_exclude(title):
                logger.debug(f"❌ 排除 (包含排除词): {item['title']}")
                continue
            
            # 检查关键词匹配
            if self._matches_keywords(title):
                filtered.append(item)
                logger.debug(f"✅ 匹配：{item['title']}")
            else:
                logger.debug(f"⭕ 不匹配：{item['title']}")
        
        logger.info(f"📊 过滤完成：{len(items)} -> {len(filtered)} 条")
        return filtered
    
    def _matches_keywords(self, text: str) -> bool:
        """检查文本是否匹配任意关键词"""
        text_lower = text.lower()
        for keyword in self.keywords:
            if keyword.lower() in text_lower:
                return True
        return False
    
    def _contains_exclude(self, text: str) -> bool:
        """检查是否包含排除词"""
        text_lower = text.lower()
        for exclude in self.exclude_keywords:
            if exclude.lower() in text_lower:
                return True
        return False
    
    def extract_project_info(self, item: Dict) -> Dict:
        """提取并标准化项目信息"""
        return {
            '项目名称': item.get('title', ''),
            '类型': item.get('type', ''),
            '发布日期': item.get('publish_date').strftime('%Y-%m-%d') if item.get('publish_date') else '',
            '链接': item.get('link', ''),
            '来源网站': '重庆市政府采购网',
            '匹配关键词': self._find_matched_keywords(item.get('title', ''))
        }
    
    def _find_matched_keywords(self, text: str) -> str:
        """找出文本中匹配的关键词"""
        matched = []
        text_lower = text.lower()
        for keyword in self.keywords:
            if keyword.lower() in text_lower:
                matched.append(keyword)
        return ', '.join(matched)
