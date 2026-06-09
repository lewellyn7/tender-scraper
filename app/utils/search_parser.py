"""关键词搜索解析工具。

支持语法（data.html 工具栏 /api/projects /api/export/{excel,csv} 共享）：
- "AI"               -> 包含 AI
- "AI 智能"           -> 包含 AI 或 智能（OR）
- "AI -音频"          -> 包含 AI 且不包含 音频
- "AI,智能,-音频"     -> 逗号 / 空格两种分隔都支持

返回 (positives: list[str], negatives: list[str])。
所有 token 转小写、去空白；负关键词 `-` 单独视为无效被忽略。
匹配大小写不敏感（调用方负责把被匹配字段也转小写）。
"""

from __future__ import annotations

import re
from typing import Tuple


def parse_keyword(raw: str | None) -> Tuple[list[str], list[str]]:
    """解析用户输入的搜索关键词。

    Args:
        raw: 原始输入字符串，可包含空格 / 逗号 / `-` 前缀的负关键词。

    Returns:
        (positives, negatives) — 均为小写字符串列表，已去重（保持原顺序）。
        空 / 纯负号 / 全空 token 都被忽略。
    """
    if not raw:
        return [], []

    # 先把负号后的空白折叠成无空白（`AI - 音频` → `AI -音频`），
    # 避免 `AI - 音频` 被切成 `AI / - / 音频` 让负号脱落
    normalized_raw = re.sub(r"-\s+", "-", raw.strip())
    # 同时按空格和逗号切分（连续分隔符合并）
    tokens = re.split(r"[\s,]+", normalized_raw)

    positives: list[str] = []
    negatives: list[str] = []
    seen_pos: set[str] = set()
    seen_neg: set[str] = set()

    for tok in tokens:
        if not tok:
            continue
        normalized = tok.lower()
        if normalized.startswith("-"):
            # 负关键词：去掉所有前导 `-`（处理 `---audio` 这种异常输入），纯负号忽略
            neg = normalized.lstrip("-").strip()
            if not neg or neg in seen_neg:
                continue
            seen_neg.add(neg)
            negatives.append(neg)
        else:
            if normalized in seen_pos:
                continue
            seen_pos.add(normalized)
            positives.append(normalized)

    return positives, negatives


def match_item(
    text_lower: str,
    positives: list[str],
    negatives: list[str],
) -> bool:
    """判断单条文本是否匹配。

    规则：
    - positives 任一命中即视为可能匹配（OR），全空视为通过；
    - negatives 任一命中即排除；
    - positives 和 negatives 至少一组非空才算有过滤意图。

    Args:
        text_lower: 已转小写的待匹配文本（title / keywords_matched 等）。
        positives: parse_keyword 返回的正向列表。
        negatives: parse_keyword 返回的负向列表。

    Returns:
        True 表示通过（保留），False 表示过滤掉。
    """
    if not positives and not negatives:
        return True
    if positives and not any(p in text_lower for p in positives):
        return False
    if negatives and any(n in text_lower for n in negatives):
        return False
    return True
