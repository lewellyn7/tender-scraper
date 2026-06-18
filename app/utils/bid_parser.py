"""
bid_parser.py — 中标结果结构化解析

支持 3 类公告 + 1 类废标:
  1. 采购结果公告 (政府采购): 包号 / 供应商名称 / 中标(成交)金额
  2. 中标候选人公示 (工程招投标): 第一/第二/第三候选人 / 投标报价 / 评审得分
  3. 中标结果公示 (工程招投标): 中标人(单位) / 中标金额
  4. 废标: 整条跳过, 不写表 (用户决策 2026-06-18)

复用 summarize.py 的部分正则风格, 但本模块是"结构化提取", 不是摘要.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Optional


# ─── 废标检测 ──────────────────────────────────────────────────────────────

_ABORTED_PATTERNS = [
    r'本项目.*?(?:废标|流标)',
    r'(?:予以|决定|宣布).{0,10}(?:废标|流标)',
    r'(?:废标|流标).{0,10}公告',
    r'终止.{0,5}采购',
    r'招标失败',
    # 补充: 政府采购公告中常见的废标表述
    r'项目废标的?原因',
    r'项目终止的?原因',
    r'本次.{0,10}(?:流标|废标)',
    r'(?:合格|有效|报价).{0,10}供应商.{0,5}不足',
    r'(?:合格|有效).{0,10}投标人.{0,5}不足',
    r'废标（终止）原因',
]


def is_aborted(content: str) -> bool:
    """检测公告是否为废标/流标/终止. 命中任一 → True."""
    if not content:
        return False
    for pat in _ABORTED_PATTERNS:
        if re.search(pat, content):
            return True
    return False


# ─── 金额解析 ──────────────────────────────────────────────────────────────

def parse_amount(text: str) -> Optional[Decimal]:
    """
    把字符串金额解析为 Decimal(元).
    支持:
      '12.78元'        → 12.78
      '1234.56万元'    → 12345600.00
      '1234万元'       → 12340000.00
      '1,234.56元'     → 1234.56 (千分位)
      '￥12.78'        → 12.78
      '12.78'          → 12.78 (默认元)
    失败/空值 → None
    """
    if not text:
        return None
    s = str(text).strip()
    s = s.replace('￥', '').replace(',', '').strip()
    # 匹配: 数字 + 可选单位(元/万元/万元整)
    m = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*(万元?|元)?', s)
    if not m:
        return None
    num_str = m.group(1)
    unit = m.group(2) or '元'
    try:
        n = Decimal(num_str)
        if '万' in unit:
            n = n * Decimal(10000)
        return n.quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None


# ─── 政府采购 · 采购结果公告 ───────────────────────────────────────────────

def parse_gov_result(content: str) -> list[dict]:
    """
    政府采购·采购结果公告 解析.
    提取每个包号: package_no, winner_name (供应商名称), bid_amount, winner_score.
    整块文本通常格式:
      包号：1 供应商名称：xxx 供应商地址：xxx 中标（成交）金额：单价：12.78元
      包号：2 供应商名称：yyy 供应商地址：yyy 中标（成交）金额：单价：12.36元
      七、中标（成交）候选供应商评审得分及报价表
      包号：1 供应商名称 报价总得分 技术总得分 商务总得分 合计 排序
      xxx 28.87 51 19 98.87 1
    """
    results = []

    # 1. 主块: 包号+供应商+金额
    # 模式: 包号：N 供应商名称：xxx ... 中标（成交）金额：xxx元
    # 用更稳的 split: 按 "包号：" 切块, 每块内提取
    pkg_blocks = re.split(r'包号[：:]\s*(\d+)', content)
    # pkg_blocks 格式: ['preamble', '1', 'block_for_1', '2', 'block_for_2', ...]

    # 评分表: 合并包号 → {package_no: [(name, total_score), ...]}
    score_map: dict[str, list[tuple[str, Decimal]]] = {}

    # 找评审表区域 (标题以 "七、" 或 "中标（成交）候选供应商评审得分" 开头)
    score_section = re.search(
        r'(?:七、|中标（成交）候选供应商评审得分.*?)\n(.*?)(?:\n注[：:]|\n[一二三四五六七八九十]、|\Z)',
        content, re.DOTALL
    )
    if score_section:
        sec = score_section.group(1)
        current_pkg: Optional[str] = None
        # 按行解析:
        #   表头行: "包号：1 供应商名称 报价总得分 ... 合计 排序"
        #   公司行: "公司名 n1 n2 n3 total rank"
        for line in sec.split('\n'):
            line = line.strip()
            if not line:
                continue
            # 表头行: "包号：N" 开头, 且后面含表头关键词
            pkg_inline = re.match(r'包号[：:]\s*(\d+)', line)
            if pkg_inline:
                current_pkg = pkg_inline.group(1)
                if any(kw in line for kw in ('供应商名称', '报价总得分', '技术总得分', '合计', '排序')):
                    continue  # 是表头, 仅设置 current_pkg
                # 否则是裸 "包号：N" 行, 继续让下面匹配
            # 公司+分数行
            # name n1 n2 n3 total rank
            m = re.match(
                r'(.+?)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)\s*$',
                line
            )
            if m and current_pkg:
                name = m.group(1).strip()
                try:
                    total = Decimal(m.group(5))
                except InvalidOperation:
                    continue
                if name and not any(kw in name for kw in ('供应商名称', '报价总得分', '合计', '排序')):
                    score_map.setdefault(current_pkg, []).append((name, total))

    # 解析主块
    i = 1
    while i < len(pkg_blocks):
        pkg_no = pkg_blocks[i].strip()
        block = pkg_blocks[i + 1] if i + 1 < len(pkg_blocks) else ''
        i += 2

        # 提取供应商名称 (首个) — 非贪婪 + lookahead 限制在“供应商地址”前
        name_m = re.search(
            r'供应商名称[：:]\s*([^\n]{2,80}?)'
            r'(?=\s*(?:供应商地址|中标（成交）金额|包号|\Z))',
            block
        )
        if not name_m:
            continue
        winner_name = name_m.group(1).strip()

        # 提取中标金额
        amt_m = re.search(r'中标（成交）金额[：:]\s*([^\n]{2,80})', block)
        bid_amount = amt_m.group(1).strip() if amt_m else None

        # 优先用主块金额; 如果有 "单价" 前缀, parse_amount 还是能解析
        bid_amount_num = parse_amount(bid_amount) if bid_amount else None

        # 评分 (从 score_map 匹配)
        winner_score = None
        for name, score in score_map.get(pkg_no, []):
            if name == winner_name:
                winner_score = score
                break
        if winner_score is None and score_map.get(pkg_no):
            # 评分表里有这个包, 但名字不完全匹配 → 取第一个 (通常排第一就是中标人)
            winner_score = score_map[pkg_no][0][1]

        results.append({
            'package_no': pkg_no,
            'winner_name': winner_name,
            'winner_rank': 1,  # 政府采购结果只有成交供应商
            'bid_amount': bid_amount,
            'bid_amount_num': bid_amount_num,
            'winner_score': winner_score,
        })

    return results


# ─── 工程招投标 · 中标候选人公示 ────────────────────────────────────────────

_CANDIDATE_RANK_MAP = {
    # 单字 (group(1) 直接捕获的)
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
    # 全称 (兼容性)
    '第一': 1, '第二': 2, '第三': 3, '第四': 4, '第五': 5,
}


def parse_tender_candidate(content: str) -> list[dict]:
    """
    工程招投标·中标候选人公示 解析.
    格式:
      一、... 二、... 三、中标候选人公示内容:
      第一中标候选人：xxx公司 投标报价：1234.56万元 评审得分：98.87
      第二中标候选人：yyy公司 投标报价：1230.00万元 评审得分：95.20
    """
    results = []

    # 模式 1: 标准 — "第N中标候选人：name ... 投标报价：xxx ... 评审得分：xx"
    # 注意: 名字后面可能有 "地址" 等字段, 用非贪婪 + 行尾锚定 price/score
    for m in re.finditer(
        r'第([一二三四五]+)中标候选人[（(]?\s*(?:名称|为|：)?\s*[）)]?[：:]\s*'
        r'([^\n]{2,80}?)(?=\s*(?:地址|投标报价|评审得分|\n|$))'
        r'(.*?)(?=第[一二三四五]+中标候选人|\Z)',
        content, re.DOTALL
    ):
        cn_rank = m.group(1)
        name = m.group(2).strip()
        rest = m.group(3) or ''
        rank = _CANDIDATE_RANK_MAP.get(cn_rank)

        # 投标报价
        price_m = re.search(r'投标报价[：:]\s*([^\n]{1,80})', rest)
        bid_amount = price_m.group(1).strip() if price_m else None
        bid_amount_num = parse_amount(bid_amount) if bid_amount else None

        # 评审得分
        score_m = re.search(r'(?:评审)?得分[：:]\s*([\d.]+)', rest)
        winner_score = None
        if score_m:
            try:
                winner_score = Decimal(score_m.group(1))
            except InvalidOperation:
                pass

        if name and rank:
            results.append({
                'package_no': None,
                'winner_name': name,
                'winner_rank': rank,
                'bid_amount': bid_amount,
                'bid_amount_num': bid_amount_num,
                'winner_score': winner_score,
            })

    # 模式 2: 简化 — "中标候选人：name" (无排名, 默认 1)
    if not results:
        for m in re.finditer(
            r'(?:中标候选人|投标单位)[：:]\s*([^\n]{2,80})',
            content
        ):
            results.append({
                'package_no': None,
                'winner_name': m.group(1).strip(),
                'winner_rank': 1,
                'bid_amount': None,
                'bid_amount_num': None,
                'winner_score': None,
            })

    return results


# ─── 工程招投标 · 中标结果公示 ──────────────────────────────────────────────

def parse_tender_result(content: str) -> list[dict]:
    """
    工程招投标·中标结果公示 解析.
    格式:
      中标人(单位)名称：xxx公司
      中标金额：1234.56万元
    或:
      推荐中标候选人：xxx公司 (公示结束后变中标人)
    """
    results = []

    # 模式 1: 中标人 / 中标单位 — 兼容 "中标人(单位)名称"、"中标人单位名称"、"中标人：" 三种
    # 策略: 找 "中标人" 之后到第一个冒号/全角冒号之间的内容, 然后取冒号后的名字
    name_m = re.search(
        r'(?:中标人|中标单位)[^：:\n]{0,30}[：:]\s*([^\n]{2,80})',
        content
    )
    if name_m:
        winner_name = name_m.group(1).strip()
    else:
        # 模式 2: 推荐/确定 中标候选人 (公示后转中标)
        rec_m = re.search(
            r'(?:确定|推荐)\s*中标候选人?[：:]\s*([^\n]{2,80})',
            content
        )
        winner_name = rec_m.group(1).strip() if rec_m else None

    if not winner_name:
        return results

    amt_m = re.search(r'中标金额[：:]\s*([^\n]{1,80})', content)
    if not amt_m:
        amt_m = re.search(r'中标（成交）价[：:]\s*([^\n]{1,80})', content)
    bid_amount = amt_m.group(1).strip() if amt_m else None
    bid_amount_num = parse_amount(bid_amount) if bid_amount else None

    results.append({
        'package_no': None,
        'winner_name': winner_name,
        'winner_rank': 1,  # 中标结果只有最终中标人
        'bid_amount': bid_amount,
        'bid_amount_num': bid_amount_num,
        'winner_score': None,
    })

    return results


# ─── 主入口 ────────────────────────────────────────────────────────────────

def parse_bid_results(
    content: str,
    info_type: str,
    category: str,
    project_id: int,
    url: str,
    publish_date,
) -> list[dict]:
    """
    主解析入口.
    根据 info_type 选择对应解析器, 包装统一格式返回.
    返回 list[dict] — 每条 dict 已带 project_id / url / category / publish_date.

    废标 → 返回 [] (不入表, 用户决策 2026-06-18)

    DB 中 category 字段实际值 = info_type (零填业务分类), 所以按 info_type 路由:
      采购结果公告 → 政府采购
      中标候选人公示 / 中标结果公示 → 工程招投标
    category 参数保留传入值 (URL 路由或其他来源)
    """
    if is_aborted(content):
        return []

    if info_type == '采购结果公告':
        rows = parse_gov_result(content)
        # 政府采购是“唯一成交供应商”, winner_rank=1
    elif info_type == '中标候选人公示':
        rows = parse_tender_candidate(content)
    elif info_type == '中标结果公示':
        rows = parse_tender_result(content)
    else:
        return []

    if not rows:
        return []

    # 包装公共字段 (不修改原 rows, 避免污染)
    out = []
    for r in rows:
        out.append({
            'source': 'cqggzy',  # 默认来源
            'project_id': project_id,
            'url': url,
            'info_type': info_type,
            'category': category or '',
            'package_no': r['package_no'],
            'winner_name': r['winner_name'],
            'winner_rank': r['winner_rank'],
            'bid_amount': r['bid_amount'],
            'bid_amount_num': r['bid_amount_num'],
            'winner_score': r['winner_score'],
            'publish_date': publish_date,
        })
    return out