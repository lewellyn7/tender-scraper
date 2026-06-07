"""数据过滤与关键词匹配模块 - 增强版 V2"""

import difflib
import math
import re
from typing import Any, Dict, List

from loguru import logger


# 2026-06-02 用户分类标准
CATEGORY_NUM_TO_INFO_TYPE = {
    '014001019': '招标计划',
    '014001001': '招标公告',
    '014001002': '答疑补遗',
    '014001003': '中标候选人公示',
    '014001004': '中标结果公示',
    '014001021': '终止公告',
    '014005001': '采购公告',
    '014005002': '变更公告',
    '014005004': '采购结果公告',
}


def _classify_info_type_by_url(url: str) -> str:
    """从 URL 提取 categoryNum 前 9 位 -> info_type"""
    if not url:
        return ''
    m = re.search(r'categoryNum=(\d+)', url or '')
    if not m:
        return ''
    prefix9 = m.group(1)[:9]
    return CATEGORY_NUM_TO_INFO_TYPE.get(prefix9, '')


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
        full_content = self._get_field(item, "full_content", "")
        if not content_preview:
            if full_content and len(full_content) > 10:
                content_preview = full_content[:300].strip() + ("..." if len(full_content) > 300 else "")
            # 2026-06-05 修复：不在这里用 title 填充摘要。列表 API 不返回 content，
            # 如用 title 填充会导致内容摘要列始终是标题，不符合预期。
            # 正确做法是空着，等详情补采后写入。
        budget = self._get_field(item, "budget", "")
        deadline = self._fmt_date(self._get_field(item, "deadline"))
        region = self._get_field(item, "region", "")
        tender_type = self._get_field(item, "tender_type", "")
        keywords_matched = self._fmt_kw(self._get_field(item, "keywords_matched", []))
        scraped_at = self._fmt_date(self._get_field(item, "scraped_at"))
        scraped_by = self._get_field(item, "scraped_by", "tender-scraper v3.2")
        business_type = self._get_field(item, "business_type", "")
        info_type = self._get_field(item, "info_type", "")
        # 2026-06-02 fallback: 如果 item.info_type 为空，从 URL 提取
        if not info_type:
            _url = self._get_field(item, "url") or self._get_field(item, "source_url", "")
            info_type = _classify_info_type_by_url(_url)
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
            "full_content": full_content,
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


class SemanticTenderFilter:
    """基于 Embedding 语义相似度的招投标过滤器

    使用 vLLM Qwen3-Embedding-4B 将关键词和项目标题转为向量，
    计算余弦相似度。支持与 TenderFilter 组合使用（AND 逻辑）。
    """

    DEFAULT_THRESHOLD = 0.60  # 语义相似度阈值（Qwen3-Embedding 经验值）
    MAX_BATCH = 32            # 每批处理条数（vLLM 限制）

    def __init__(
        self,
        keywords: List[str],
        threshold: float = DEFAULT_THRESHOLD,
        min_keywords_semantic: int = 1,  # 至少 N 个关键词语义匹配（0=全部AND）
    ):
        self.keywords = [kw.strip() for kw in keywords if kw.strip()]
        self.threshold = max(0.0, min(1.0, threshold))
        self.min_keywords_semantic = min_keywords_semantic
        self._kw_embeddings: List[List[float]] = []
        self._ready = False

    async def ainit(self):
        """异步初始化：批量获取所有关键词的 embedding（只调用一次）"""
        if not self.keywords:
            self._ready = True
            return
        try:
            import asyncio
            from app.services.vector_store import encode_texts
            all_embs = []
            loop = asyncio.get_running_loop()
            for i in range(0, len(self.keywords), self.MAX_BATCH):
                batch = self.keywords[i : i + self.MAX_BATCH]
                embs = await loop.run_in_executor(None, encode_texts, batch)
                if embs:
                    all_embs.extend(embs)
                else:
                    logger.warning(f"[SemanticFilter] embedding batch {i} returned empty")
            self._kw_embeddings = all_embs
            self._ready = True
            logger.info(f"[SemanticFilter] 初始化完成，{len(self._kw_embeddings)}/{len(self.keywords)} 关键词已向量化 (vLLM Qwen3-Embedding-4B)")
        except Exception as e:
            logger.error(f"[SemanticFilter] 初始化失败: {e}")
            self._kw_embeddings = []
            self._ready = True

    def _cosine_sim(self, a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    async def get_title_embeddings(self, titles: List[str]) -> List[List[float]]:
        """批量获取标题 embedding（vLLM Qwen3-Embedding-4B）"""
        try:
            import asyncio
            from app.services.vector_store import encode_texts
            all_embs = []
            loop = asyncio.get_running_loop()
            for i in range(0, len(titles), self.MAX_BATCH):
                batch = titles[i : i + self.MAX_BATCH]
                embs = await loop.run_in_executor(None, encode_texts, batch)
                all_embs.extend(embs if embs else [None] * len(batch))
            return all_embs
        except Exception as e:
            logger.error(f"[SemanticFilter] batch title embedding failed: {e}")
            return [None] * len(titles)

    async def match_title(self, title: str) -> tuple:
        """
        判断单条标题是否语义匹配任意关键词。
        Returns: (是否匹配, 最高相似度, 匹配上的关键词列表)
        """
        if not self._ready or not self._kw_embeddings:
            return False, 0.0, []
        title_embs = await self.get_title_embeddings([title])
        title_emb = title_embs[0] if title_embs else None
        if not title_emb:
            return False, 0.0, []

        matched_kws = []
        max_sim = 0.0
        for kw, emb in zip(self.keywords, self._kw_embeddings):
            sim = self._cosine_sim(title_emb, emb)
            if sim >= self.threshold:
                matched_kws.append(kw)
            if sim > max_sim:
                max_sim = sim
        if self.min_keywords_semantic > 0 and len(matched_kws) < self.min_keywords_semantic:
            return False, max_sim, matched_kws
        return len(matched_kws) > 0, max_sim, matched_kws

    async def filter_items(self, items: List[Any]) -> List[Dict]:
        """
        语义过滤项目列表。
        每个 item 支持 TenderInfo 对象或字典。
        返回匹配项列表，每项附加 semantic_score 和 semantic_matched_kws 字段。
        """
        if not self._ready:
            await self.ainit()
        if not self.keywords or not items:
            return []

        titles = [self._get_title(it) for it in items]
        title_embs = await self.get_title_embeddings(titles)

        results = []
        for item, title_emb in zip(items, title_embs):
            if not title_emb:
                continue
            matched_kws = []
            max_sim = 0.0
            for kw, kw_emb in zip(self.keywords, self._kw_embeddings):
                sim = self._cosine_sim(title_emb, kw_emb)
                if sim >= self.threshold:
                    matched_kws.append(kw)
                if sim > max_sim:
                    max_sim = sim
            if self.min_keywords_semantic > 0 and len(matched_kws) < self.min_keywords_semantic:
                continue
            if matched_kws:
                item_dict = dict(item) if isinstance(item, dict) else {}
                if not isinstance(item, dict):
                    for f in ["title", "url", "budget", "deadline", "publish_date", "tender_type", "source_url"]:
                        item_dict[f] = getattr(item, f, None) or ""
                item_dict["semantic_score"] = round(max_sim, 3)
                item_dict["semantic_matched_kws"] = matched_kws
                results.append(item_dict)

        logger.info(f"[SemanticFilter] 语义过滤: {len(items)} -> {len(results)} 条匹配")
        return results

    @staticmethod
    def _get_title(item: Any) -> str:
        if hasattr(item, "title"):
            return item.title
        return item.get("title", "") if isinstance(item, dict) else ""
