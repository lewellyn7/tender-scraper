"""TF-IDF 语义匹配模块 - 支持同义词扩展"""

import math
import re
from collections import Counter
from typing import Dict, List, Tuple

import jieba

# 同义词词库
SYNONYM_DICT = {
    "智慧": ["智能", "数字化", "信息化"],
    "智能": ["智慧", "数字化", "自动化"],
    "数字化": ["智慧", "智能", "信息化", "数智化"],
    "信息化": ["数字化", "智慧", "智能化"],
    "系统": ["平台", "软件", "应用"],
    "平台": ["系统", "软件", "应用"],
    "软件": ["系统", "平台", "应用"],
    "数据": ["信息", "资料", "数字"],
    "网络": ["互联网", "通信", "宽带"],
    "建设": ["构建", "搭建", "开发"],
    "改造": ["升级", "改建", "扩建"],
    "服务": ["服务", "运维", "运营"],
    "园区": ["工业园", "产业园", "开发区"],
    "监控": ["监测", "监视", "监管"],
    "视频": ["图像", "影像", "摄像"],
    "安全": ["安防", "保卫", "防护"],
    " LED ": ["发光二极管", "led显示屏"],
    "采购": ["购买", "购置", "招标"],
    "招标": ["采购", "投标", "竞标"],
    "工程": ["项目", "建设工程", "基建"],
}


def expand_synonyms(text: str) -> str:
    """展开同义词"""
    result = text
    for key, synonyms in SYNONYM_DICT.items():
        for syn in synonyms:
            result = result.replace(syn, key + " " + syn)
    return result


def tokenize_chinese(text: str) -> List[str]:
    """中文分词 + 预处理"""
    text = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    words = jieba.lcut(text)
    # 过滤停用词和短词
    stopwords = {
        "的",
        "了",
        "在",
        "是",
        "我",
        "有",
        "和",
        "就",
        "不",
        "人",
        "都",
        "一",
        "一个",
        "上",
        "也",
        "很",
        "到",
        "说",
        "要",
        "去",
        "你",
        "会",
        "着",
        "没有",
        "看",
        "好",
        "自己",
        "这",
        "那",
        "中",
        "大",
        "为",
        "与",
        "等",
        "其",
        "对",
        "或",
        "可",
        "更",
        "被",
        "但",
        "并",
        "从",
        "以",
        "及",
        "被",
        "有",
        "可",
        "之",
        "而",
        "于",
    }
    return [w.strip() for w in words if len(w.strip()) >= 2 and w.strip() not in stopwords]


def compute_tf(tokens: List[str]) -> Dict[str, float]:
    """计算词频 TF"""
    counter = Counter(tokens)
    total = len(tokens)
    return {word: count / total for word, count in counter.items()}


def compute_idf(corpus: List[List[str]]) -> Dict[str, float]:
    """计算逆文档频率 IDF"""
    df = {}
    n_docs = len(corpus)
    for doc in corpus:
        for word in set(doc):
            df[word] = df.get(word, 0) + 1
    return {word: math.log(n_docs / (df[word] + 1)) for word in df}


def compute_tfidf(tf: Dict[str, float], idf: Dict[str, float]) -> Dict[str, float]:
    """计算 TF-IDF 向量"""
    return {word: tf_val * idf.get(word, 0) for word, tf_val in tf.items()}


def cosine_similarity(vec1: Dict[str, float], vec2: Dict[str, float]) -> float:
    """余弦相似度"""
    common = set(vec1.keys()) & set(vec2.keys())
    if not common:
        return 0.0
    dot = sum(vec1[w] * vec2[w] for w in common)
    norm1 = math.sqrt(sum(v * v for v in vec1.values()))
    norm2 = math.sqrt(sum(v * v for v in vec2.values()))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


class TFIDFMatcher:
    """TF-IDF 语义匹配器"""

    def __init__(self, min_similarity: float = 0.15):
        self.min_similarity = min_similarity
        self.corpus: List[List[str]] = []
        self.idf: Dict[str, float] = {}
        self.keyword_docs: List[List[str]] = []
        self.keyword_idf: Dict[str, float] = {}

    def build_corpus(self, texts: List[str]):
        """构建语料库"""
        self.corpus = [tokenize_chinese(expand_synonyms(t)) for t in texts]
        self.idf = compute_idf(self.corpus)

    def build_keywords(self, keywords: List[str]):
        """构建关键词语料库 - 使用语料库的 IDF"""
        self.keyword_docs = [tokenize_chinese(expand_synonyms(kw)) for kw in keywords]
        # Use corpus IDF so keyword and text vectors are in the same space

    def match(self, text: str, keywords: List[str] = None) -> Tuple[bool, List[str], float]:
        """
        匹配文本与关键词
        返回: (是否匹配, 匹配的关键词列表, 最高相似度)
        """
        expanded = expand_synonyms(text)
        text_tokens = tokenize_chinese(expanded)
        if not text_tokens:
            return False, [], 0.0

        text_tf = compute_tf(text_tokens)
        text_tfidf = compute_tfidf(text_tf, self.idf)

        matched_kws = []
        max_sim = 0.0

        if keywords:
            kw_list = keywords
        else:
            kw_list = getattr(self, "_keywords", [])

        for i, kw in enumerate(kw_list):
            kw_expanded = expand_synonyms(kw)
            kw_tokens = tokenize_chinese(kw_expanded)
            if not kw_tokens:
                continue

            kw_tf = compute_tf(kw_tokens)
            kw_tfidf = compute_tfidf(kw_tf, self.idf)  # Use same IDF as corpus

            sim = cosine_similarity(text_tfidf, kw_tfidf)
            if sim >= self.min_similarity:
                matched_kws.append(kw)
            if sim > max_sim:
                max_sim = sim

        return len(matched_kws) > 0, matched_kws, max_sim

    def find_similar(
        self, text: str, candidates: List[str], top_n: int = 5
    ) -> List[Tuple[str, float]]:
        """查找最相似的候选文本"""
        text_tokens = tokenize_chinese(expand_synonyms(text))
        if not text_tokens:
            return []

        text_tf = compute_tf(text_tokens)
        text_tfidf = compute_tfidf(text_tf, self.idf)

        # Use corpus IDF for candidates
        results = []
        for cand in candidates:
            cand_tokens = tokenize_chinese(expand_synonyms(cand))
            if not cand_tokens:
                continue
            cand_tf = compute_tf(cand_tokens)
            cand_tfidf = compute_tfidf(cand_tf, self.idf)
            sim = cosine_similarity(text_tfidf, cand_tfidf)
            results.append((cand, sim))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_n]

    def title_similarity(self, title1: str, title2: str) -> float:
        """计算两个标题的相似度"""
        t1_tokens = tokenize_chinese(expand_synonyms(title1))
        t2_tokens = tokenize_chinese(expand_synonyms(title2))
        if not t1_tokens or not t2_tokens:
            return 0.0

        tf1 = compute_tf(t1_tokens)
        tf2 = compute_tf(t2_tokens)
        combined_corpus = [t1_tokens, t2_tokens]
        idf = compute_idf(combined_corpus)

        tfidf1 = compute_tfidf(tf1, idf)
        tfidf2 = compute_tfidf(tf2, idf)
        return cosine_similarity(tfidf1, tfidf2)
