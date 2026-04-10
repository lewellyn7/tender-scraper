"""TextSummarizer - 文本摘要器
支持：抽取式摘要（TextRank 简化版）、关键句抽取
"""

import re
from typing import List, Tuple


class TextSummarizer:
    """文本摘要生成器（抽取式）"""

    def __init__(self):
        # 关键句指示词
        self.key_indicators = [
            "本项目", "该项目", "招标人", "采购人", "预算", "最高限价",
            "采购内容", "采购需求", "采购范围", "合同估算", "资金来源",
            "投标人", "供应商", "资质要求", "报名时间", "截止时间", "开标时间",
            "交货期", "服务期", "交付", "中标人", "成交供应商",
        ]

    def split_sentences(self, text: str) -> List[str]:
        """分句"""
        # 按中英文标点分句
        sentences = re.split(r'[。！？；\n]+', text)
        return [s.strip() for s in sentences if s.strip() and len(s) > 10]

    def score_sentences(self, sentences: List[str], top_k: int = 5) -> List[Tuple[str, float]]:
        """句子评分（基于位置 + 关键词命中 + 长度惩罚）"""
        scored = []
        total = len(sentences)

        for i, sent in enumerate(sentences):
            score = 0.0

            # 位置分数：首句、末句加权
            if i == 0:
                score += 2.0
            elif i == total - 1:
                score += 1.5
            elif i < 3:
                score += 1.0

            # 关键词命中
            indicator_hits = sum(1 for kw in self.key_indicators if kw in sent)
            score += indicator_hits * 0.5

            # 长度惩罚：过短或过长句子减分
            length = len(sent)
            if length < 20:
                score -= 1.0
            elif length > 200:
                score -= 0.5

            # 数字命中（金额、日期）
            number_count = len(re.findall(r'[\d,.%％]+', sent))
            score += min(number_count * 0.1, 1.0)

            scored.append((sent, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def summarize(self, text: str, max_sentences: int = 3) -> str:
        """生成摘要（指定句数）"""
        if not text or len(text) < 50:
            return text

        sentences = self.split_sentences(text)
        if len(sentences) <= max_sentences:
            return "。".join(sentences) + "。" if sentences else text[:200]

        top = self.score_sentences(sentences, top_k=max_sentences)
        # 按原文顺序排序
        order = {sent: i for i, sent in enumerate(sentences)}
        top.sort(key=lambda x: order[x[0]])

        return "。".join(s for s, _ in top) + "。"

    def extract_budget(self, text: str) -> str:
        """抽取预算金额"""
        patterns = [
            r'预算[：:：]?\s*([\d,，.]+)\s*(?:万元|元|万)',
            r'最高限价[：:：]?\s*([\d,，.]+)\s*(?:万元|元|万)',
            r'合同估算[：:：]?\s*([\d,，.]+)\s*(?:万元|元|万)',
            r'采购预算[：:：]?\s*([\d,，.]+)\s*(?:万元|元|万)',
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return m.group(0)
        return ""

    def extract_deadline(self, text: str) -> str:
        """抽取截止时间"""
        patterns = [
            r'截止[时分]?[：:：]?\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?(?:\s*\d{1,2}[时:：]\d{1,2})?)',
            r'报名截止[时分]?[：:：]?\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?(?:\s*\d{1,2}[时:：]\d{1,2})?)',
            r'开标[时分]?[：:：]?\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?(?:\s*\d{1,2}[时:：]\d{1,2})?)',
            r'响应[时分]?[：:：]?\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?(?:\s*\d{1,2}[时:：]\d{1,2})?)',
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return m.group(1)
        return ""

    def extract_contact(self, text: str) -> str:
        """抽取联系方式"""
        patterns = [
            r'联系人[：:：]?\s*([^\s，。,，]+)',
            r'电话[：:：]?\s*([\d\-–]{7,})',
            r'手机[：:：]?\s*([1][3-9]\d{9})',
            r'邮箱[：:：]?\s*([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)',
        ]
        parts = []
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                parts.append(m.group(0))
        return "；".join(parts) if parts else ""
