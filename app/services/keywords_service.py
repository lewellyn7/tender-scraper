"""关键词管理服务 - 支持精确匹配和模糊匹配"""

import difflib
from typing import List, Dict, Optional
from app.database import get_db
from loguru import logger

DEFAULT_THRESHOLD = 0.8


class FuzzyMatcher:
    """模糊匹配器 - 使用 difflib.SequenceMatcher"""
    
    @staticmethod
    def match(keyword: str, text: str, threshold: float = 0.8) -> tuple:
        """
        模糊匹配
        返回: (是否匹配, 相似度分数)
        """
        text_lower = text.lower()
        kw_lower = keyword.lower()
        
        if kw_lower in text_lower:
            return True, 1.0
        
        if any(kw_lower in seg for seg in text_lower.split()):
            return True, 0.95
        
        ratio = difflib.SequenceMatcher(None, kw_lower, text_lower).ratio()
        return ratio >= threshold, ratio
    
    @staticmethod
    def partial_match(keyword: str, text: str, threshold: float = 0.6) -> tuple:
        """部分匹配"""
        kw_lower = keyword.lower()
        text_lower = text.lower()
        
        if len(kw_lower) <= 3:
            if text_lower.startswith(kw_lower):
                return True, 1.0
            if kw_lower in text_lower:
                return True, 0.95
        
        ratio = difflib.SequenceMatcher(None, kw_lower, text_lower).ratio()
        return ratio >= threshold, ratio


class KeywordsService:
    """关键词服务"""
    
    def __init__(self):
        self.db = get_db()
    
    def list_all(self) -> List[Dict]:
        return self.db.get_all_keywords()
    
    def list_by_category(self, category: str) -> List[Dict]:
        return self.db.get_keywords_by_category(category)
    
    def add(self, keyword: str, category: str = "include",
            match_mode: str = "exact", threshold: float = 0.8) -> Dict:
        if not keyword or not keyword.strip():
            return {"success": False, "error": "关键词不能为空"}
        
        keyword = keyword.strip()
        
        c = self.db._get_conn()
        existing = c.execute(
            "SELECT id FROM keywords WHERE keyword = ?", (keyword,)
        ).fetchone()
        if existing:
            return {"success": False, "error": f"关键词「{keyword}」已存在"}
        
        ok = self.db.add_keyword(keyword, category, match_mode, threshold)
        
        if ok:
            logger.info(f"[Keywords] 添加: {keyword} ({match_mode})")
            return {"success": True, "keyword": keyword}
        return {"success": False, "error": "添加失败"}
    
    def update(self, keyword_id: int, **kwargs) -> Dict:
        ok = self.db.update_keyword(keyword_id, **kwargs)
        if ok:
            logger.info(f"[Keywords] 更新 id={keyword_id}")
            return {"success": True}
        return {"success": False, "error": "更新失败"}
    
    def delete(self, keyword_id: int) -> Dict:
        ok = self.db.delete_keyword(keyword_id)
        if ok:
            logger.info(f"[Keywords] 删除 id={keyword_id}")
            return {"success": True}
        return {"success": False, "error": "删除失败"}
    
    def toggle(self, keyword_id: int) -> Dict:
        ok = self.db.toggle_keyword(keyword_id)
        return {"success": ok}
    
    def match(self, text: str, categories: List[str] = None) -> Dict:
        """对文本进行关键词匹配"""
        text_lower = text.lower()
        active = self.db.get_active_keywords()
        
        matched = []
        unmatched = []
        scores = {}
        
        cats = categories if categories else list(active.keys())
        
        for cat in cats:
            if cat not in active:
                continue
            for item in active[cat]:
                kw = item['keyword']
                mode = item.get('match_mode', 'exact')
                threshold = item.get('threshold', DEFAULT_THRESHOLD)
                
                if mode == 'fuzzy':
                    is_match, score = FuzzyMatcher.match(kw, text_lower, threshold)
                elif mode == 'partial':
                    is_match, score = FuzzyMatcher.partial_match(kw, text_lower, threshold)
                else:
                    is_match = kw.lower() in text_lower
                    score = 1.0 if is_match else 0.0
                
                kw_entry = {
                    "keyword": kw,
                    "mode": mode,
                    "threshold": threshold,
                    "score": round(score, 3) if score else 0
                }
                
                if is_match:
                    matched.append(kw_entry)
                else:
                    unmatched.append(kw_entry)
                
                scores[kw] = round(score, 3) if score else 0
        
        return {
            "matched": matched,
            "unmatched": unmatched,
            "scores": scores,
            "text": text
        }
    
    def filter_titles(self, titles: List[str], category: str = "include") -> List[Dict]:
        """过滤标题列表"""
        active = self.db.get_active_keywords(category)
        if not active or category not in active:
            return []
        
        results = []
        for title in titles:
            result = self.match(title, categories=[category])
            if result['matched']:
                results.append({
                    "title": title,
                    "matched_keywords": [m['keyword'] for m in result['matched']],
                    "scores": {m['keyword']: result['scores'][m['keyword']] 
                               for m in result['matched']}
                })
        
        return results
    
    def get_stats(self) -> Dict:
        return self.db.keywords_count()
    
    def seed_defaults(self):
        """填充默认关键词"""
        c = self.db._get_conn()
        count = c.execute("SELECT COUNT(*) FROM keywords").fetchone()[0]
        if count > 0:
            return
        
        defaults = [
            ("智慧", "include", "exact", 1.0),
            ("智能", "include", "exact", 1.0),
            ("数字化", "include", "exact", 1.0),
            ("信息化", "include", "exact", 1.0),
            ("系统", "include", "exact", 1.0),
            ("平台", "include", "exact", 1.0),
            ("软件", "include", "exact", 1.0),
            ("服务", "include", "exact", 1.0),
            ("数据", "include", "exact", 1.0),
            ("网络", "include", "exact", 1.0),
            ("建设", "include", "exact", 1.0),
            ("改造", "include", "exact", 1.0),
            ("采购", "include", "exact", 1.0),
            ("招标", "include", "exact", 1.0),
            ("流标", "exclude", "exact", 1.0),
            ("终止", "exclude", "exact", 1.0),
            ("废标", "exclude", "exact", 1.0),
            ("智慧城市", "include", "fuzzy", 0.7),
            ("智慧园区", "include", "fuzzy", 0.7),
        ]
        
        for kw, cat, mode, th in defaults:
            self.db.add_keyword(kw, cat, mode, th)
        
        logger.info(f"[Keywords] 填充默认关键词 {len(defaults)} 个")
