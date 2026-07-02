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
from pathlib import Path
from typing import List, Optional

# 项目类型分类词典（启动时加载一次）
from config.project_types import get_sorted_types, PROJECT_TYPES

_SORTED_TYPES = get_sorted_types()  # [(name, [kw, ...])] by priority asc


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


# ─── 中标人名称清洗 ─────────────────────────────────────────────────────────
# 公告原文里 "中标人: X 公司 资质: ..." / "供应商名称: X 业绩: ..."
# 会把 "资质"/"业绩"/"第二中标候选人" 等附注一起抓到 winner_name 里.
# cleaned_winner_name 用于 GROUP BY + 唯一约束, 避免附注差异导致重复入库.
#
# 7-01 拓展: 覆盖工程招投标中标候选人公示中常见的 10+ 未清洗模式:
#   - "1.中标候选人的资质：..." / "1．中标候选人的资质：..." (数字+句点+中标候选人的+资质)
#   - "公司资质：..." / "公司业绩：..." (多了"公司"前缀)
#   - "资质等级：..." (没"企业"前缀)
#   - "（联合体牵头人：X）" / "（联合体：X）" / "（联合体成员：X）" (联合体模式不全)
#   - "&nbsp;" HTML 实体未清理
#   - "无 提出异议的渠道和方式" (无 + 长描述)
#   - "资质：xxx 第二中标候选人：xxx" (多 pass 累积)
#   - "，企业资质：xxx" 中文逗号 (regex 只匹配空白)
#   - "1．" 全角句点

# 截断分隔符: 空白 + 中文标点 + 数字+句点 (eg "1.中标候选人的资质")
# 用 ([0-9]+[.．]?[，；\s,;]+)? 替代纯空白, 允许 1. 2. 1． 等前缀
_CLEAN_Winner_SEP = r'(?:[0-9]+[.．]?[，；\s,;]+)?'

_CLEAN_Winner_STOP_PATTERNS = [
    # ── 资质相关 (按特异性高→低排序) ──
    _CLEAN_Winner_SEP + r'中标候选人的?资质[:：].*',     # "1.中标候选人的资质：..." / "1．中标候选人的资质：..."
    _CLEAN_Winner_SEP + r'企业资质[:：].*',             # "企业资质：..." (含中文逗号)
    _CLEAN_Winner_SEP + r'公司资质[:：].*',             # 7-01: "公司资质：..." (多了'公司'前缀)
    _CLEAN_Winner_SEP + r'资质等级[:：].*',             # 7-01: "资质等级：..." (没'企业'前缀)
    _CLEAN_Winner_SEP + r'投标资格业绩[:：].*',         # "投标资格业绩：..."
    _CLEAN_Winner_SEP + r'资质[:：].*',                 # "资质：..." (最通用, 放在最后)
    # ── 业绩相关 ──
    _CLEAN_Winner_SEP + r'公司业绩[:：].*',             # 7-01: "公司业绩：..."
    _CLEAN_Winner_SEP + r'业绩[:：].*',                 # "业绩：..."
    # ── 单位名称 ──
    _CLEAN_Winner_SEP + r'单位名称[:：].*',
    # ── 中标候选人附注 ──
    _CLEAN_Winner_SEP + r'第[一二三四五六七八九十]中标候选人.*',
    _CLEAN_Winner_SEP + r'第[一二三四五六七八九十]+中标候选人.*',
    # ── 7-01 v2: 段落分隔词 (公司名 + 关键词 + 详细描述) ──
    _CLEAN_Winner_SEP + r'中标候选人(审查|资格|评审|评|详细|基本|主要|公示|初步|排序|排名|得分|一览|情况|信息|资料).*',
    _CLEAN_Winner_SEP + r'否决投标(情况|的?|理由|原因).*',
    _CLEAN_Winner_SEP + r'比选文件规定.*',
    _CLEAN_Winner_SEP + r'招标文件规定.*',
    _CLEAN_Winner_SEP + r'初步评审.*',
    _CLEAN_Winner_SEP + r'其他详见.*',
    _CLEAN_Winner_SEP + r'详见附表.*',
    _CLEAN_Winner_SEP + r'其他资格能力.*',
    # ── 7-01 v2: 中文冒号 + 资质等级附注 ──
    r'[，；、\s,;：:]+\s*(建筑工程|市政公用|公路工程|水利水电|机电工程|装修装饰|钢结构|地基基础|施工总承包|专业承包).*',
    # ── 联合体括号 (用 [^）]* 而非 .*? 避免匹配到内层嵌套的) ──
    r'（联合体[^）]*）',                                  # 7-01: 联合体成员 / 牵头人 / 简写
    r'\(联合体[^)]*\)',                                # 7-01: 半角括号版本
    # ── "无" 开头的无效中标人 ──
    r'^无[\s，：:].*',                                  # 7-01: "无 提出异议的渠道和方式..." / "无，xxx"
    r'\s+无[\s，：:].*',                               # 7-01: "公司名 无 详细描述" (放后面截断, 避免切合法公司名)
]

# HTML 实体清理: 公告抓取常带 &nbsp; 等
_CLEAN_Winner_HTML_ENTITIES = {
    '&nbsp;': ' ',
    '&amp;': '&',
    '&lt;': '<',
    '&gt;': '>',
    '&quot;': '"',
    '&#39;': "'",
}

_CLEAN_Winner_MAX_LEN = 80  # 7-01 v2: 50→80, 给长公司名 + 联合体名留余量, 避免提前截断

# 已知非公司名 (清洗后判定为无效)
_CLEAN_Winner_INVALID_NAMES = frozenset([
    '无', '无。', '无,', '无;', '无；',
    '详见', '见附', '见上', '见下',
    '/', '-', '—',
])


def clean_winner_name(raw, max_passes=5):
    r"""清洗 winner_name: 截断附注 + 联合体括号 + 多 pass + HTML 实体.

    入参: 公告原文抓到的 winner_name (可能含 资质/业绩/第二中标候选人 附注)
    返回: 干净的中标人公司名; 若入参为空或无效则返回 None

    7-01 拓展:
      - 多 pass 清理 (max_passes=5): 应对 '资质:xxx 第二中标候选人:xxx' 多次截断
      - HTML 实体清理: &nbsp; → 空格
      - 中文标点支持: [，；\s,;]+ 替代 \s+ (中文逗号/分号)
      - 联合体模式扩展: （联合体成员/牵头人/简写）
      - 无效名判定: '无' / '详见' / 纯符号 → None

    示例:
      "重庆佰晟捷建筑工程有限公司 业绩：城口县2022年森林抚育项目"
        → "重庆佰晟捷建筑工程有限公司"
      "信息产业电子第十一设计研究院科技工程股份有限公司（联合体成员：中贝天丰）"
        → "信息产业电子第十一设计研究院科技工程股份有限公司"
      "某公司&nbsp; 资质：xxx 第二中标候选人：另一公司"
        → "某公司"
    """
    if not raw:
        return None
    s = str(raw)
    if not s.strip():
        return None

    # Step 1: HTML 实体清理
    for ent, rep in _CLEAN_Winner_HTML_ENTITIES.items():
        s = s.replace(ent, rep)

    # Step 2: 截断附注 (多 pass 直到稳定)
    s = s.strip()
    for _ in range(max_passes):
        prev = s
        for pat in _CLEAN_Winner_STOP_PATTERNS:
            s = re.sub(pat, '', s, count=1)
        s = s.strip()
        if s == prev:
            break

    # Step 3: 长度截断
    if len(s) > _CLEAN_Winner_MAX_LEN:
        s = s[:_CLEAN_Winner_MAX_LEN].rstrip()

    # Step 4: 无效名判定
    s = s.strip()
    if not s or s in _CLEAN_Winner_INVALID_NAMES:
        return None
    # 纯附注无公司名 (eg "资质:xxx"): 不含中文公司常见后缀
    if len(s) < 5 and not any(kw in s for kw in ['公司', '有限', '集团', '厂', '院', '所', '中心', '校', '店']):
        return None
    # 纯附注 (只有"资质:xxx"但截断后无主中标人): 检测常见附注前缀词
    if any(s.startswith(kw) for kw in ['资质：', '资质:', '业绩：', '业绩:', '项目名称：', '项目名称:']):
        return None

    # Step 4.5: 清理末尾孤立的标点/数字/右括号
    # (多 pass 截断 + 嵌套联合体会留下 1. / ， / ） 等残留)
    s = re.sub(r'[，；、,;\s]+$', '', s)
    s = re.sub(r'[\s,;，；]*\d+[.．]?$', '', s)
    s = re.sub(r'[)）]+$', '', s)
    # 7-01 v2: 清理末尾孤立修饰词 (regex 截断后留下的 ' 企业' / ' 联合体' 等)
    s = re.sub(r'\s+(企业|联合体|中标人|负责人|电话|地址)\s*$', '', s)
    s = s.strip()

    # Step 5: 最终检查
    if not s or s in _CLEAN_Winner_INVALID_NAMES:
        return None
    if len(s) < 5 and not any(kw in s for kw in ['公司', '有限', '集团', '厂', '院', '所', '中心', '校', '店']):
        return None

    return s


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
            'cleaned_winner_name': clean_winner_name(winner_name),
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

    # 模式 0 (新格式, 表格行): "第N名 公司名 数字 数字 数字" 出现在 中标候选人排序 表
    # 2026-06-22 新增: 修复 3952 条 bid_amount_num=NULL 问题 (原代码只匹旧格式)
    cn_rank_map = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
    for m in re.finditer(
        r'第([一二三四五六七八九十]+|\d+)名\s+'
        r'(\S+?(?:公司|集团|企业|联合体|事务所|院))'
        r'\s+([\d.]+)\s+[\d.]+\s+([\d.]+)',
        content
    ):
        rank_str = m.group(1)
        rank = cn_rank_map.get(rank_str, int(rank_str) if rank_str.isdigit() else 0)
        if not rank:
            continue
        try:
            score = Decimal(m.group(4))
        except (InvalidOperation, ValueError):
            score = None
        try:
            price_num = Decimal(m.group(3))
        except (InvalidOperation, ValueError):
            price_num = None
        results.append({
            'package_no': None,
            'winner_name': m.group(2).strip(),
            'winner_rank': rank,
            'bid_amount': m.group(3),  # 表里通常是元为单位 (71558384.20)
            'bid_amount_num': price_num,
            'winner_score': score,
        })

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
                'cleaned_winner_name': clean_winner_name(name),
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
                'cleaned_winner_name': clean_winner_name(m.group(1).strip()),
                'winner_rank': 1,
                'bid_amount': None,
                'bid_amount_num': None,
                'winner_score': None,
            })

    return results


# ─── 工程招投标 · 中标结果公示 ──────────────────────────────────────────────

# 中标公告后面常见的补足/附件文本 (不是公司名, 需要划断)
_NOISE_SUFFIX_PATTERNS = [
    r'\s+中标结果公示\.pdf.*$',  # 附件 PDF 名
    r'\s+申请履约保函.*$',
    r'\s+低价风险担保保函.*$',
    r'\s+社会信用代码\s*[:：]?\s*[A-Z0-9]{15,30}.*$',  # 联合体成员的信用代码 (15-30 字符)
    r'\s+法定代表人[：:].*$',
    r'\s+招标代理.*$',
    r'\s+电话[：:].*$',
    r'\s+联系[人]?[:：].*$',
    r'\s+咨询受理联系人[：:].*$',
    r'\s+联系电话[：:].*$',
    r'\s+开标时间.*$',
    r'\s+招标人：.*$',
    r'\s+工商注册号.*$',
    r'\s+组织机构.*$',
    r'\s+投诉受理部门.*$',
    r'\s*[(（]联合体(?:牵头人|成员(?:单位)?)?[)）]?.*$',  # "（联合体牵头人）" / "（联合体成员单位"
]


def _strip_noise_suffix(name: str) -> str:
    """去掉公司名后的 PDF/信用代码/法人/电话等噪声"""
    if not name:
        return name
    for pat in _NOISE_SUFFIX_PATTERNS:
        name = re.sub(pat, '', name)
    return name.strip()


def _split_multi_winners(raw: str) -> list[str]:
    """
    多个公司用 '、' / ',' / ';' 隔开 → 返回清洗后的名字列表.
    过滤掉企业资质/业绩/PDF附件这类噪声.
    """
    if not raw:
        return []
    # 先去除后缀噪声 (PDF/社会信用代码/法人/电话) — 这些可能以空格跟在名字后面
    raw = _strip_noise_suffix(raw)
    # 再按 顿号/逗号/分号 切 (优先顿号)
    parts = re.split(r'[、,;]', raw)
    out = []
    for p in parts:
        name = p.strip()
        if not name:
            continue
        # 过滤填充语: "企业资质：xxx" / "企业业绩：xxx" 经常跟在公司名后面
        if '：' in name:
            name = name.split('：', 1)[0].strip()
        if ':' in name:
            name = name.split(':', 1)[0].strip()
        # 过滤纯填充语
        if not name or name in ('企业资质', '企业业绩'):
            continue
        # 过滤太长 (>50) 的 — 多半是吃到下一段
        if len(name) > 50:
            name = name[:50].strip()
        if not name:
            continue
        # stopword 黑名单 (2026-06-18 加): 过滤无意义名字
        if name in _STOPWORDS:
            continue
        out.append(name)
    return out


# 招标公告中常见但不是公司名的无意义填充词
_STOPWORDS = frozenset([
    '其他', '无', '/', '—', '-', '上述', '同上', '以上',
    '企业资质', '企业业绩', '详见附件', '详见附表', '详见', '见附件',
    '投标报价', '评标价', '中标价', '招标人', '招标代理',
    '万元', '元', 'CNY', 'RMB',
])


def parse_tender_result(content: str) -> list[dict]:
    """
    工程招投标·中标结果公示 解析.
    支持 3 种格式 (真实 244 条样本分布):
      A 类 (老 2019-):  拟 中 标 人 xxx  +  中标金额 (万元) 3044
      B 类 (新 2024+):  中标人信息\n单位名称 xxx  +  中标金额（费率、单价等） 1180000.00元
      C 类 (老规范):   中标人(单位)名称：xxx  +  中标金额：xxx 万元
    """
    if not content:
        return []
    results = []

    # === 名字提取 (按优先级) ===
    winner_names: list[str] = []

    # 模式 1 (A 类, 老): "拟 中 标 人" 中间允许空格 + 名字到行尾/段落
    # 样本: "拟 中 标 人 河南坤宇市政园林工程有限公司 中标金额 (万元) 3044 工商注册号 91410726..."
    # 重要: 用非贪婪 + 显式停点 (中标金额/工商注册号/组织机构/投诉受理), 避免匹到信用代码段
    m1 = re.search(
        r'拟\s*中\s*标\s*人[：:\s]+([^\n]+?)(?=\s*(?:中标金额|工商注册号|组织机构|投诉受理|招标人|社会信用代码|法定代表人|$))',
        content
    )
    if m1:
        names = _split_multi_winners(m1.group(1))
        if names:
            winner_names = names

    # 模式 2 (B 类, 新): "中标人信息\n单位名称 xxx" 块状格式
    if not winner_names:
        m2 = re.search(r'中标人信息[^\n]*\n\s*单位名称\s*([^\n]+)', content)
        if m2:
            names = _split_multi_winners(m2.group(1))
            if names:
                winner_names = names

    # 模式 3 (C 类, 规范): "中标人(单位)名称：xxx" 或 "中标人：xxx" / "中标人名称：xxx"
    if not winner_names:
        m3 = re.search(
            r'(?:中标人|中标单位)(?:\(?单位\)?名称|名称)?[：:]\s*([^\n]{2,80})',
            content
        )
        if m3:
            names = _split_multi_winners(m3.group(1))
            if names:
                winner_names = names

    # 模式 4 (转换): 推荐/确定 中标候选人
    if not winner_names:
        m4 = re.search(
            r'(?:确定|推荐)\s*中标候选人?[：:]\s*([^\n]{2,80})',
            content
        )
        if m4:
            names = _split_multi_winners(m4.group(1))
            if names:
                winner_names = names

    if not winner_names:
        return results

    # === 金额提取 (按优先级) ===
    amt_text = None
    # 模式 1 (A 类, 老): "中标金额 (万元) 3044" — 单位在括号, 数字在后面
    # 重要: 必须保留括号单位标识, 传给 parse_amount 才会被识别为万元
    amt_m = re.search(
        r'中标金额\s*[(（]\s*((?:万元|元)|费率[、,]?单价(?:等)?)\s*[)）]\s*([0-9.,]+?)(?=\s|$|元|万)',
        content
    )
    if amt_m:
        unit_in_paren = amt_m.group(1)
        if '万元' in unit_in_paren:
            unit_hint = '万元'
        else:
            unit_hint = '元'
        amt_text = amt_m.group(2).strip() + unit_hint
    if not amt_text:
        # 模式 2 (B 类, 新): "中标金额（费率、单价等） 1180000.00元" / "中标金额：1180000.00元"
        # 或 "中标金额 1180000.00元，其中：..." (无括号)
        # 金额后可以接 "元," / "元，" / "元其中" 等说明文字
        amt_m = re.search(r'中标金额[（(][^）)]*[)）]?\s*([0-9.,]+?)\s*(?:元|万元)', content)
        if amt_m:
            unit_m = re.search(r'(?:元|万元)\s*$', amt_m.group(0))
            unit = '万元' if unit_m and '万' in unit_m.group(0) else '元'
            amt_text = amt_m.group(1).strip() + unit
        if not amt_text:
            # 2b: 简单 "中标金额：100万" / "中标金额 100万" 无括号也无括号补充
            amt_m = re.search(r'中标金额[：:]?\s*([0-9.,]+\s*(?:元|万元))', content)
            if amt_m:
                amt_text = amt_m.group(1).strip()
    if not amt_text:
        # 模式 3 (规范): "中标金额：xxx万元" / "中标金额：xxx元"
        amt_m = re.search(r'中标金额[：:]\s*([^\n]{1,80})', content)
        if amt_m:
            amt_text = amt_m.group(1).strip()
    if not amt_text:
        # 备选: "中标（成交）价" / "中标价"
        amt_m = re.search(r'中标[（(]成交[)）]价[：:]\s*([^\n]{1,80})', content)
        if amt_m:
            amt_text = amt_m.group(1).strip()
    if not amt_text and winner_names:
        # 模式 D: 英文+中文混合格式 (ADB 世行项目, 4 条样本 2026-06-18)
        # 表格列: 序号 投标人名称 开标价 评标价 拒标理由 中标人的中标价 合同范围
        # 中标人行最后一列数字 = 中标价 (合同价值)
        # 样本: "1 中电智安科技有限公司 19,549,995.10 17,533,270.00 无 19,549,995.10 合同范围包括：..."
        winner = winner_names[0]  # D 类无联合体, 取首个
        name_escaped = re.escape(winner)
        row_m = re.search(
            rf'\d+\s+{name_escaped}\s+(.+?)(?=\s*(?:合同范围|中标人名称|中标结果公示\.pdf|申请履约|低价风险|联系[人]?[:：]|咨询受理|$))',
            content,
        )
        if row_m:
            # 提取行内所有数字, 最后一个 = 中标人的中标价
            nums = re.findall(r'[\d,]+\.\d+|[\d,]+', row_m.group(1))
            if nums:
                amt_text = nums[-1].replace(',', '') + '元'

    bid_amount_num = parse_amount(amt_text) if amt_text else None

    for idx, name in enumerate(winner_names):
        results.append({
            'package_no': str(idx + 1) if len(winner_names) > 1 else None,
            'winner_name': name,
            'cleaned_winner_name': clean_winner_name(name),
            'winner_rank': 1,  # 中标结果只有最终中标人 (多公司 = 联合体, 都 rank=1)
            'bid_amount': amt_text,
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
    title: str = "",  # 2026-06-20 新增: 用于项目类型分类
) -> list[dict]:
    """
    主解析入口.
    根据 info_type 选择对应解析器, 包装统一格式返回.
    返回 list[dict] — 每条 dict 已带 project_id / url / category / publish_date / project_types.

    废标 → 返回 [] (不入表, 用户决策 2026-06-18)

    DB 中 category 字段实际值 = info_type (零填业务分类), 所以按 info_type 路由:
      采购结果公告 → 政府采购
      中标候选人公示 / 中标结果公示 → 工程招投标
    category 参数保留传入值 (URL 路由或其他来源)

    project_types 字段 (2026-06-20 新增): classify_project_type(title, content) 填充
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

    # 项目类型分类 (一次性计算, 所有 row 共享同一结果)
    project_types = classify_project_type(title or "", content)

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
            # 2026-06-27 修复：主入口包装时漏了 cleaned_winner_name (PR #41 加了字段
            # 但 parse_bid_results 重写 dict 时没复制, 导致回填 101 行 cleaned 全为 NULL)
            'cleaned_winner_name': r.get('cleaned_winner_name'),
            'winner_rank': r['winner_rank'],
            'bid_amount': r['bid_amount'],
            'bid_amount_num': r['bid_amount_num'],
            'winner_score': r['winner_score'],
            'publish_date': publish_date,
            'title': title,  # 保留供下钻展示
            'project_types': project_types,  # 2026-06-20 新增
        })
    return out

# ─── 项目类型分类 (2026-06-20 新增) ────────────────────────────────────────

def classify_project_type(title: str, content: str = "") -> List[str]:
    """根据 title + content 头部匹配项目类型。

    Returns:
        类型列表 (按 priority 升序)；无匹配 → ['其他']。
        多标签：可同时命中多个类型，如"老旧小区智能化改造"
        → ['老旧小区改造', '智能化'] (智能化被 neg 剔除后)
        或"智慧化老旧小区改造平台建设" → ['老旧小区改造']

    Args:
        title: 项目标题（必传，>90% 类型信息在此）
        content: 项目正文（可选，只看前 500 字避免噪声）

    匹配逻辑 (2026-06-20 16:55 增强):
      1) 任一正向关键词命中 → 加入候选
      2) 对每个候选：任一负向关键词命中 → 剔除 ("以负向为主" 否决权)
      3) 剩余按 priority 升序返回；空 → ['其他']

    Notes:
        - 修改 config/project_types.py 后需重启服务
        - 测试可通过 monkeypatch _SORTED_TYPES 覆盖
    """
    # 2026-06-22 改造: 返回 [] 而非 ['其他']
    # 用户指令: 信息类型为其他的重新分类 = 按 info_type 替代 project_types
    # bid_parser 不再产生 '其他' 兜底, 未命中任何分类时返回空列表
    if not title:
        return []

    # 拼接文本：title 全文 + content 前 500 字
    text = title
    if content:
        text = text + "\n" + (content[:500] if isinstance(content, str) else "")

    types = []
    for name, cfg in _SORTED_TYPES:
        # 2026-06-20 16:55: cfg 改为 dict {keywords: [...], neg: [...]}
        # 向后兼容：若 cfg 是 list（旧版格式），直接作为 keywords
        if isinstance(cfg, list):
            keywords = cfg
            neg_keywords: List[str] = []
        else:
            keywords = cfg.get("keywords", [])
            neg_keywords = cfg.get("neg", [])

        if not keywords:  # 跳过"其他"兜底
            continue

        # 第一轮：正关键词命中
        if not any(kw in text for kw in keywords):
            continue

        # 第二轮：负向关键词命中则剔除该类型
        if neg_keywords and any(neg in text for neg in neg_keywords):
            continue

        types.append(name)

    return types  # 2026-06-22 改造: 无匹配返回 [] 而非 ['其他']


def annotate_project_types(rows: list[dict]) -> list[dict]:
    """为 parse_* 输出的 rows 批量追加 project_types 字段（不动原 dict）。"""
    annotated = []
    for r in rows:
        annotated.append({
            **r,
            "project_types": classify_project_type(r.get("title", ""), r.get("content", "")),
        })
    return annotated


def reload_project_types() -> None:
    """测试用：强制重载词典（修改 config/project_types.py 后调用）。"""
    global _SORTED_TYPES
    import importlib
    import config.project_types as _mod
    importlib.reload(_mod)
    _SORTED_TYPES = _mod.get_sorted_types()
