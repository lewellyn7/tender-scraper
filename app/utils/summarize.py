#!/usr/bin/env python3
"""
生成结构化 project_overview 摘要
规则基于 business_type + info_type
"""
import re
from typing import Optional, List


def clean(text: Optional[str]) -> str:
    """清洗文本：去除多余空白、换行"""
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _re_search(pattern: str, text: str):
    """正则提取，返回第一个匹配"""
    m = re.search(pattern, text)
    return m.group(1) if m else None


def _extract_summary_block(text: str, keywords: list, max_lines: int = 5) -> list:
    """从文本中提取包含关键词的段落"""
    if not text or not keywords:
        return []
    lines = []
    text_lines = text.split('\n')
    for line in text_lines:
        line = line.strip()
        if len(line) < 5:
            continue
        if any(kw in line for kw in keywords):
            cleaned = clean(line)
            if cleaned:
                lines.append(cleaned)
        if len(lines) >= max_lines:
            break
    return lines


def _extract_section(text: str, keywords: list, max_chars: int = 1500) -> str:
    """从正文中提取包含关键词的段落内容（用于 project_overview 拼接）"""
    if not text or not keywords:
        return ""
    for kw in keywords:
        idx = text.find(kw)
        if idx >= 0:
            # 从关键词位置往后取 max_chars 字符
            chunk = text[idx: idx + max_chars]
            # 清理多余空白但保留段落结构
            chunk = re.sub(r'\s+', ' ', chunk).strip()
            return chunk
    return ""


def _clean_deadline(text: str) -> str:
    """清洗截止时间：提取纯 datetime，格式 YYYY-MM-DD HH:MM
    支持格式：
      - 2026-04-28 10:30（dash 分隔）
      - 2026年4月30日11时00分（中文紧凑）
      - 2026年4月 30 日 11 时00分（中文带多余空格）
      - 为2026年4月30日（前缀后直接日期，如"为2026-04-28"）
    策略：直接用宽松合并模式匹配。
    """
    if not text:
        return ""

    # 去掉各种格式前缀（全角右括号 U+FF09 也要处理）
    text = re.sub(r'^投标截止时间[，,\s]下同[\)）]\s*', '', text)
    text = re.sub(r'^投标(?:文件)?递交截止(?:时间)?[：:]\s*', '', text)
    text = re.sub(r'^截止(?:时间)?[：:]\s*', '', text)
    text = re.sub(r'^📌\s*投标截止时间：\s*', '', text)
    text = text.strip()

    # 宽松合并模式：直接匹配含空格的日期文本
    # 允许年/月/日/时/分/秒之间有任意空格、短横线或前缀字（如"为"）
    m = re.search(
        r'(\d{4})\s*[年\-]\s*(\d{1,2})\s*[月\-]\s*(\d{1,2})\s*日?'
        r'(?:\s*(\d{1,2})\s*[时:：]\s*(\d{1,2})(?:\s*分?\s*秒?)?)?',
        text
    )
    if not m:
        return ""
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hour, minute = m.group(4), m.group(5)
    result = f"{year}-{month:02d}-{day:02d}"
    if hour and minute:
        result += f" {int(hour):02d}:{int(minute):02d}"
    return result

def summarize(
    info_type: str,
    budget: str = "",
    bid_amount: str = "",
    submission_deadline: str = "",
    contact_name: str = "",
    contact_phone: str = "",
    region: str = "",
    full_content: str = "",
    business_type: str = "",
    **kwargs
) -> str:
    """
    根据 info_type 生成结构化 project_overview 摘要

    规则:
    1. 政府采购-采购公告: 投标截止时间 /n + 正文「一、项目基本情况」全部内容
    2. 工程招投标-招标公告: 投标截止时间 /n + 正文「2.项目概况与招标范围」全部内容
    3. 政府采购-答疑变更: 只清洗显示更正内容
    4. 政府采购-采购结果公告: 包号 / 供应商名称 / 中标金额
    5. 工程招投标-招标计划: 招标内容 / 招标方式 / 招标文件计划发布时间
    6. 工程招投标-答疑补遗: 只清洗显示补遗内容
    7. 工程招投标-中标候选人公示: 中标候选人名称 / 投标报价
    8. 工程招投标-中标结果公示: 中标人单位名称 / 中标金额
    9. 工程招投标-相关公告: 清洗显示具体公告内容
    10. 工程招投标-终止公告: 清洗显示具体公告内容
    """
    lines = []

    if info_type == "采购公告":
        lines = _summarize_gov_purchase_announce(
            budget, submission_deadline, full_content, business_type
        )
    elif info_type == "答疑变更":
        lines = _summarize_gov_change(full_content)
    elif info_type == "采购结果公告":
        lines = _summarize_gov_result(full_content)
    elif info_type == "招标计划":
        lines = _summarize_tender_plan(full_content)
    elif info_type == "招标公告":
        lines = _summarize_tender_announce(
            budget, submission_deadline, full_content, business_type
        )
    elif info_type == "答疑补遗":
        lines = _summarize_tender_qa(full_content)
    elif info_type == "中标候选人公示":
        lines = _summarize_tender_candidate(full_content)
    elif info_type == "中标结果公示":
        lines = _summarize_tender_result(full_content)
    elif info_type in ("相关公告", "终止公告"):
        lines = _summarize_generic(full_content)
    else:
        lines = _summarize_generic(full_content)

    return '\n'.join([l for l in lines if l]).strip()


# ─── 政府采购 ────────────────────────────────────────────────────────────────

def _summarize_gov_purchase_announce(budget, deadline, content, business_type="") -> list:
    lines = []
    # 清洗截止时间（只保留 YYYY-MM-DD HH:MM）
    raw = _re_search(
        r'(?:投标|响应|报价)截止[：:]\s*(?:投标截止时间[，\s]下同\)?[：:\s=]*)?(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}[日]?(?:\s*\d{1,2}[时:：]\d{1,2}(?:分|秒?)?)?)',
        content
    )
    if not raw:
        raw = _re_search(r'(?:四、投标文件递交|投标文件递交)[^\\n]*截止[：:]\s*(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}[日]?(?:\s*\d{1,2}[时:：]\d{1,2}(?:分|秒?)?)?)', content)
    if not raw:
        raw = _re_search(r'截止[：:]\s*(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}[日]?(?:\s*\d{1,2}[时:：]\d{1,2}(?:分|秒?)?)?)', content)
    if not raw and deadline:
        raw = deadline
    if raw:
        cleaned_dl = _clean_deadline(raw)
        if cleaned_dl:
            lines.append(f"📌 投标截止时间：{cleaned_dl}")

    if business_type == "政府采购":
        # 政府采购-采购公告：拼接「一、项目基本情况」全部内容
        section = _extract_section(content, ["一、项目基本情况", "一、项目情况", "一、项目概述", "项目基本情况"])
        if section:
            lines.append(section)
    else:
        # 其他类型兜底
        method = _re_search(r'(?:采购方式|采购组织形式)[：:]\s*(公开招标|竞争性磋商|竞争性谈判|询价采购|单一来源|邀请招标)', content)
        if not method:
            method = _re_search(r'(?:本次|该)采购[采用]?([^\n]{2,30}(?:招标|磋商|谈判|询价|单一来源))', content)
        if method:
            lines.append(f"📋 采购方式：{clean(method)}")
        if budget:
            lines.append(f"💰 最高限价：{clean(budget)}")

    if not lines:
        summary = _extract_summary_block(content, ['采购公告', '采购项目', '供应商', '资质要求', '预算'], max_lines=4)
        lines = summary if summary else ["无有效采购信息"]
    return lines


def _summarize_gov_change(content) -> list:
    """答疑变更：只显示更正内容"""
    lines = _extract_summary_block(content, ['更正', '变更', '修改', '调整'], max_lines=8)
    if not lines:
        lines = _extract_summary_block(content, ['原', '现', '调整'], max_lines=8)
    return lines if lines else [clean(content[:200])] if content else ["无更正内容"]


def _summarize_gov_result(content) -> list:
    """采购结果公告：包号 / 供应商名称 / 中标金额"""
    lines = []
    blocks = re.findall(r'(?:包号|标的|品目)[：:]\s*([^\n]{1,100})', content)
    for b in blocks[:5]:
        if clean(b):
            lines.append(f"📦 {clean(b)}")

    suppliers = re.findall(r'(?:中标|成交)供应商[：:]\s*([^\n]{2,80})', content)
    for s in suppliers[:5]:
        if clean(s):
            lines.append(f"🏢 {clean(s)}")

    amounts = re.findall(r'(?:中标|成交|合同)金额[：:]\s*([^\n]{1,80})', content)
    for a in amounts[:5]:
        if clean(a):
            lines.append(f"💵 {clean(a)}")

    if not lines:
        lines = _extract_summary_block(content, ['中标', '成交', '候选', '金额'], max_lines=5)
    return lines if lines else [clean(content[:200])] if content else ["无结果信息"]


# ─── 工程招投标 ────────────────────────────────────────────────────────────────

def _summarize_tender_plan(content) -> list:
    """招标计划：招标内容 / 招标方式 / 招标文件计划发布时间"""
    lines = []

    tenderee = _re_search(r'招标(?:法人|人|单位)[（(]?\s*盖章[）)]?[：:]\s*([^\n]{2,80})', content)
    if not tenderee:
        tenderee = _re_search(r'招标(?:人|单位)[：:]\s*([^\n]{2,80})', content)
    if tenderee:
        lines.append(f"🏗️ 招标人：{clean(tenderee)}")

    items = re.findall(r'(?:招标项目名称|项目名称)[：:]\s*([^\n]{2,100})', content)
    for item in items[:3]:
        if clean(item):
            lines.append(f"📋 {clean(item)}")

    method = _re_search(r'招标方式[：:]\s*([^\n]{2,30})', content)
    if method:
        lines.append(f"⚙️ 招标方式：{clean(method)}")

    ptime = _re_search(r'招标文件计划发布时间[：:]\s*([^\n]{2,50})', content)
    if ptime:
        lines.append(f"📅 {clean(ptime)}")

    if not lines:
        lines = _extract_summary_block(content, ['招标计划', '招标项目', '招标人', '计划发布'], max_lines=6)
    return lines if lines else [clean(content[:200])] if content else ["无招标计划信息"]


def _summarize_tender_announce(budget, deadline, content, business_type="") -> list:
    lines = []
    # 从正文「6.投标文件递交」节提取截止时间
    raw = _re_search(
        r'(?:6\.投标文件递交)[^\\n]*?(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}[日]?(?:\s*\d{1,2}[时:：]\d{1,2}(?:分|秒?)?)?)',
        content
    )
    if not raw:
        raw = _re_search(
            r'(?:投标截止时间[，,\s]下同\)[：:\s=]*|投标文件递交截止[：:]\s*|截止时间[：:]\s*)?(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}[日]?(?:\s*\d{1,2}[时:：]\d{1,2}(?:分|秒?)?)?)',
            content
        )
    if not raw and deadline:
        raw = deadline
    if raw:
        cleaned_dl = _clean_deadline(raw)
        if cleaned_dl:
            lines.append(f"📌 投标截止时间：{cleaned_dl}")

    if business_type == "工程建设":
        # 工程招投标-招标公告：拼接「2.项目概况与招标范围」全部内容
        section = _extract_section(content, ["2.项目概况与招标范围", "二、项目概况与招标范围", "2.项目概况", "二、项目概况", "项目概况与招标范围"])
        if section:
            lines.append(section)
    else:
        # 其他类型兜底
        if budget:
            lines.append(f"💰 最高限价：{clean(budget)}")
        scope = _re_search(r'招标范围[：:]\s*([^\n]{10,300})', content)
        if scope:
            lines.append(f"🎯 招标范围：{clean(scope)[:200]}")

    if not lines:
        lines = _extract_summary_block(content, ['招标公告', '招标项目', '投标文件', '资质要求', '工期', '评标'], max_lines=5)
    return lines if lines else ["无有效招标信息"]


def _summarize_tender_qa(content) -> list:
    """答疑补遗：只显示补遗/答疑内容"""
    lines = _extract_summary_block(content, ['补遗', '答疑', '变更', '澄清', '修改', '问：', '答：'], max_lines=8)
    if not lines:
        lines = _extract_summary_block(content, ['问：', '答：', '补充', '调整'], max_lines=8)
    return lines if lines else [clean(content[:200])] if content else ["无补遗内容"]


def _summarize_tender_candidate(content) -> list:
    lines = []
    names = re.findall(
        r'(?:第一|第二|第三)?\s*中标候选人[（(]?\s*名称\s*[）)]?[：:]\s*([^\n]{2,80})',
        content
    )
    if not names:
        names = re.findall(r'(?:中标候选人|投标单位)[：:]\s*([^\n]{2,80})', content)
    for n in names[:5]:
        if clean(n):
            lines.append(f"🏢 {clean(n)}")

    prices = re.findall(r'(?:投标报价|报价)[：:]\s*([^\n]{1,80})', content)
    for p in prices[:5]:
        if clean(p):
            lines.append(f"💵 {clean(p)}")

    if not lines:
        lines = _extract_summary_block(content, ['中标候选', '报价', '投标', '候选人'], max_lines=5)
    return lines if lines else [clean(content[:200])] if content else ["无候选人信息"]


def _summarize_tender_result(content) -> list:
    lines = []
    names = re.findall(r'(?:中标人|中标单位)[：:]\s*([^\n]{2,80})', content)
    if not names:
        names = re.findall(r'(?:确定|推荐)\s*中标候选人?\s*[：:]\s*([^\n]{2,80})', content)
    for n in names[:3]:
        if clean(n):
            lines.append(f"🏢 {clean(n)}")

    amounts = re.findall(r'(?:中标|合同)(?:金额|价)[：:]\s*([^\n]{1,80})', content)
    for a in amounts[:3]:
        if clean(a):
            lines.append(f"💵 {clean(a)}")

    if not lines:
        lines = _extract_summary_block(content, ['中标', '结果', '成交', '金额'], max_lines=5)
    return lines if lines else [clean(content[:200])] if content else ["无结果信息"]


def _summarize_generic(content) -> list:
    """相关公告 / 终止公告：通用清洗"""
    lines = _extract_summary_block(content, ['公告', '通知', '说明', '公示', '结果'], max_lines=6)
    return lines if lines else [clean(content[:200])] if content else ["无有效信息"]


if __name__ == "__main__":
    # 测试
    test_content_gov = """
    一、采购项目名称：智慧林业信息化系统
    一、项目基本情况
    本次采购内容包括硬件设备采购、软件系统开发、云服务租赁等。
    采购预算：人民币50万元（含税）
    采购方式：竞争性磋商
    四、投标文件递交
    投标文件递交截止时间：2026年5月18日 14:30
    五、其他说明
    联系人：刘老师 023-12345678
    """
    print("=== 政府采购-采购公告测试 ===")
    result = _summarize_gov_purchase_announce("50万元", "", test_content_gov, "政府采购")
    print('\n'.join(result))
    print()

    test_content_engineering = """
    1.项目名称：城区道路改造工程
    2.项目概况与招标范围
    本项目主要包括道路基层处理、沥青混凝土面层铺装、排水管网改造等。
    招标范围：施工图纸范围内的全部工程
    最高限价：100万元
    6.投标文件递交
    投标文件递交截止时间：2026年5月20日 10:00
    评标办法：综合评估法
    """
    print("=== 工程招投标-招标公告测试 ===")
    result = _summarize_tender_announce("100万元", "", test_content_engineering, "工程建设")
    print('\n'.join(result))
