"""内容清洗：剥离采集页面的 UI 噪点（导航/按钮/页脚）

2026-06-05 创建：用户反馈内容摘要中含"采购公告 / 我要报名"等 UI 元素。
原 fetcher 抓详情页时漏处理 SPA 顶层 chrome（面包屑/字号/按钮）。
"""
import re

# 噪点清洗正则（按顺序执行）
NOISE_PATTERNS = [
    # 1. 面包屑（开头）：首页 > 交易信息 > 政府采购/工程招投标/工程建设 > [项目标题] + 下一节起始
    # 2026-06-18 修复: 加 "工程招投标" + 改结尾 [0-9a-f-]* → [^\n]+? + 明确停点 (附件/项目/采购公告/招标公告/一、/本采购/本招标/采购人/年份)
    # 避免贪婪: 以具体内容 marker 作为停点, 不会吃掉真实正文.
    (re.compile(r'^\s*首页\s*[>＞]\s*交易信息\s*[>＞]\s*(?:政府采购|工程招投标|工程建设|土地交易|矿权交易|国企采购)\s*[>＞][^\n]+?(?=\s+附件\d|\s+一、|\s+本招标|\s+本采购|\s+采购人|\s+项目信息|\s+项目编号|\s+项目编码|\s+招标公告|\s+采购公告|\s+\d{4}年|\s+（\d{4}|\s+\(\d{4}|$)', re.IGNORECASE), ''),
    # 1b. 面包屑 (中段, 如 "项目编号:XXX 首页 > 交易信息 > ...")
    (re.compile(r'\s*首页\s*[>＞]\s*交易信息\s*[>＞]\s*(?:政府采购|工程招投标|工程建设|土地交易|矿权交易|国企采购)\s*[>＞][^\n]+?(?=\s+附件\d|\s+一、|\s+本招标|\s+本采购|\s+采购人|\s+项目信息|\s+项目编号|\s+项目编码|\s+招标公告|\s+采购公告|\s+\d{4}年|\s+（\d{4}|\s+\(\d{4}|$)', re.IGNORECASE), ''),
    # 2. APP下载 / 公众号 / 用户手册 等顶部 chrome
    (re.compile(r'^\s*APP\s*下载[^\n]*?当前位置[：:]\s*[^\n]*', re.IGNORECASE | re.DOTALL), ''),
    (re.compile(r'^\s*APP\s*下载[^\n]*', re.IGNORECASE), ''),
    # 3. 信息时间：XXXX-XX-XX 字段
    (re.compile(r'信息时间[：:]\s*[\d\-]*\s*', re.IGNORECASE), ''),
    # 4. 字号: 小 中 大 控件
    (re.compile(r'字号[：:]\s*小\s*中\s*大\s*', re.IGNORECASE), ''),
    # 5. 按钮文字
    (re.compile(r'(?:我要)?打印\s*', re.IGNORECASE), ''),
    (re.compile(r'关闭\s*', re.IGNORECASE), ''),
    (re.compile(r'加入收藏\s*', re.IGNORECASE), ''),
    (re.compile(r'(?:立即|我要)报名\s*', re.IGNORECASE), ''),
    (re.compile(r'附件下载\s*', re.IGNORECASE), ''),
    # 6. 尾部 chrome
    (re.compile(r'主办单位[：:][^\n]*?(?=主办单位|承办单位|技术支持|建议反馈|版权所有|$)', re.IGNORECASE | re.DOTALL), ''),
    (re.compile(r'承办单位[：:][^\n]*', re.IGNORECASE), ''),
    (re.compile(r'(?:技术支持|建议反馈)[：:][^\n]*', re.IGNORECASE), ''),
    (re.compile(r'版权所有[^\n]*', re.IGNORECASE), ''),
    (re.compile(r'国家部委网站[^\n]*', re.IGNORECASE | re.DOTALL), ''),
    # 7. "暂无内容" / "未找到" 标记
    (re.compile(r'暂无内容|没有找到|未找到相关|页面不存在|内容已被删除', re.IGNORECASE), ''),
    # 8. 顶部平台名称 (精确字面量，避免贪婪匹配整行)
    (re.compile(r'^\s*重庆市公共资源交易网[_\-]重庆市公共资源交易中心\s*', re.IGNORECASE), ''),
    # 9. "您当前的位置：..." 面包屑 (变体：到 我要报名 / 我要打印 / 【 / 项目概况 停止)
    (re.compile(r'^\s*您当前的位置[：:]\s*首页\s*[>＞]\s*[^\n]*?(?=我要报名|我要打印|【|项目概况|$)', re.IGNORECASE), ''),
    (re.compile(r'^\s*您当前的位置[：:][^\n]*?(?=我要报名|【|项目概况|$)', re.IGNORECASE), ''),
    # 10. 字号控件 (顺序不限，匹配【字号 ...】)
    (re.compile(r'【\s*字号\s*[大小中\s]+?\s*】\s*', re.IGNORECASE), ''),
    # 11. 投标保函按钮 (到 项目概况/项目内容 停止)
    (re.compile(r'本项目保证金支持电子投标保函形式[^\n]*?(?=项目概况|项目内容|$)', re.IGNORECASE), ''),
    # 12. 【】开头占位符链 (2026-06-15 调研: 4126 条 cp 开头有 "【】" / "【】【 】【 】" 等 SPA 空容器 div 残留)
    #     例子: "【】一、项目号：FLQ26B00001" / "【】【 】【 】 一、项目号：NCQ26B00001"
    #     变体多 (含空格 / 多个连续), 用循环 sub 干净
    (re.compile(r'^(?:\s*【\s*】\s*)+', re.MULTILINE), ''),
    # 13. 页脚备案号 (2026-06-15 调研: 809 条 cp = "渝公网安备 50019002503055 号" / "<数字>_渝公网安备..." 等)
    #     鲁棒: "渝公网安备" 后跟任意数字 + "号"
    (re.compile(r'^\s*[\d_]+\s*渝公网安备\s*\d+\s*号\s*', re.MULTILINE), ''),
    (re.compile(r'^\s*渝公网安备\s*\d+\s*号\s*', re.MULTILINE), ''),
    # 14. "信息时间:..." 变体 (规则 3 只匹配"信息时间: "，漏了"信息时间 2024-05-20" 头有 "信息时间" 但接日期)
    #     原规则: r'信息时间[：:]\s*[\d\-]*\s*'  // 漏了无冒号 / 有横杠变体
    (re.compile(r'^\s*信息时间\s*[\d\-：:]*\s*', re.MULTILINE), ''),
    # 15. 项目编号:XXXX (2026-06-18 调研: 323/986=32.7% 记录含 20 位项目编号码)
    #     模式: "项目编号：50024220260520001010101" (20 位数字) / 出现在行首或中段 / 可重复
    #     不吃尾随 \s*: 让后面的 Tab 列表仍有前导空格可被规则 17 匹到 (否则 Tab list 变行首, \s+ 无法匹)
    (re.compile(r'\s*项目编号[：:]\s*\d{10,}', re.IGNORECASE), ''),
    # 16. 项目编码:XXXX (政采类少量, "项目编码：5001232025...")
    (re.compile(r'\s*项目编码[：:]\s*[A-Z0-9]{6,}', re.IGNORECASE), ''),
    # 17. 工程类 Tab 列表 (2026-06-18 调研: 169/986=17.1% 记录含此 tab 列表)
    #     字符串必须全段匹配, 几乎不误伤. 出现在中段 (项目编号 / 面包屑 之后) 或行首 (被规则 15 吃后).
    #     (?:^|\s+) 允许行首匹配, 避免被规则 15 (项目编号 \s* 吃前空格) 后 Tab list 变行首无法匹配
    (re.compile(r'(?:^|\s+)招标公告\s+邀标信息\s+答疑补遗\s+中标候选人公示\s+中标结果公告\s+合同签订基本信息公示\s+合同变更基本信息公示\s+相关公告\s+终止公告', re.IGNORECASE), ''),
    # 18. 政采类 Tab 列表
    (re.compile(r'(?:^|\s+)采购公告\s+单一来源公示\s+答疑变更\s+采购结果公告', re.IGNORECASE), ''),
]

# 空详情页标记
EMPTY_MARKERS = ['暂无内容', '没有找到', '未找到相关', '页面不存在', '内容已被删除']


def clean_text(text: str) -> str:
    """清洗一段文本中的 UI 噪点"""
    if not text:
        return ''
    s = text
    for pat, repl in NOISE_PATTERNS:
        s = pat.sub(repl, s)
    s = re.sub(r'[\s\u3000]+', ' ', s).strip()
    return s


def is_empty_page(text: str) -> bool:
    """检测整页是"无内容"状态 — 详情页只有 chrome 时返回 True"""
    if not text:
        return True
    for m in EMPTY_MARKERS:
        if m in text:
            return True
    cleaned = clean_text(text)
    return len(cleaned) < 30


def _norm_for_dup(s: str) -> str:
    """规范化用于去重比较: 去空白 + 标点差异"""
    if not s:
        return ""
    s = re.sub(r"\s+", "", s)
    s = s.replace(" ", "")
    return s


def strip_title_dup(text: str, title: str, max_strip_lines: int = 10) -> str:
    """2026-06-08 修复 (Bug 2.1): 详情页 .epoint-article-content 含 <h1>title</h1> + 表格,
    inner_text() 把 title 也抓进来, 导致 content_preview 开头 = title 重复。

    关键: 真实数据中, inner_text 输出的 full_content 是"单行" (HTML 标签被 strip),
    title 重复以 "title + title + ..." 形式出现, 用 \\n split 失效.
    需支持:
    1. 多行形式: 连续 1-2 行 == title (用 \\n 分割)
    2. 单行形式: 连续 N 次以 title 开头 (用 startswith)

    行为:
    - 跳过开头所有与 title 完全相等的行 (连空行)
    - 单行内连续以 title 开头, 全部剥
    - 容忍 title 出现在中间 (不删, 用户可能想看)
    - title 为空 / text 为空 → 原样返回

    Example:
        text='<h1>title</h1>\\ntitle\\n项目编号：xxx' → '项目编号：xxx'
        text='title title 项目编号：xxx' → '项目编号：xxx' (单行 startswith)
    """
    if not text or not title:
        return text or ""
    title = title.strip()
    norm_title = _norm_for_dup(title)
    if not norm_title:
        return text

    out = text
    stripped = 0

    # 阶段 1: 多行形式 — 连续 N 行 = title
    lines = out.split('\n')
    out_lines = []
    started = False
    for i, line in enumerate(lines):
        if i >= max_strip_lines:
            break
        norm_line = _norm_for_dup(line)
        if not norm_line:
            if not started:  # 开头空行保留
                out_lines.append(line)
                continue
            else:
                continue  # 中间空行剥
        if not started and (norm_line == norm_title or norm_title in norm_line or norm_line in norm_title):
            stripped += 1
            continue
        # 遇到非 title 行
        out_lines.append(line)
        started = True
        out_lines.extend(lines[i + 1:])
        break

    if out_lines:
        out = "\n".join(out_lines)

    # 阶段 2: 单行形式 — 连续 N 次以 title 开头 (inner_text 把所有内容合并到一行)
    while True:
        norm_out = _norm_for_dup(out[:500])  # 只看前 500 字符
        if not norm_out.startswith(norm_title):
            break
        if not out.startswith(title):
            # 边界: 规范化后等但原始不同 (可能含额外空格), 强制剥
            out = out.lstrip()
            if not out.startswith(title):
                break
        out = out[len(title):].lstrip()
        stripped += 1
        if stripped > 20:  # 安全保护
            break

    if stripped == 0:
        return text

    return out.strip()


def make_content_preview(full_content: str, title: str, max_len: int = 500) -> str:
    """2026-06-08 新增: 生成 content_preview 统一入口
    1. clean_text 剥 UI 噪点 (面包屑/按钮等)
    2. strip_title_dup 去掉 title 重复
    3. 截断到 max_len + '...'
    4. 2026-06-29 新增: 兑底提取附件名+日期 (答疑补遗类)
    """
    if not full_content:
        return ''
    cleaned = clean_text(full_content)
    cleaned = strip_title_dup(cleaned, title)
    if not cleaned:
        # 兑底: 从 fc 提取附件名 + 日期 (答疑补遗等附件类内容)
        cleaned = _fallback_extract_metadata(full_content)
        if not cleaned:
            return ''
    if len(cleaned) > max_len:
        return cleaned[:max_len] + '...'
    return cleaned


def _fallback_extract_metadata(fc: str) -> str:
    """2026-06-29 新增: 从 fc 提取附件名 + 日期 (main make_content_preview 兑底)

    适用于答疑补遗/补遗公告等以附件为主的项目 - 主要内容在附件中, 页面仅含标题+日期+附件名.
    返回格式: "包含 N 个版本 (YYYY-MM-DD~YYYY-MM-DD) | 附件: name1.pdf, name2.pdf"
    """
    if not fc:
        return ''
    # 提取附件名 (.pdf/.doc/.docx/.rar/.zip/.xlsx/.xls/.csv)
    files = re.findall(r'[\w一-鿿（）()【】\[\]_-]+\.(?:pdf|doc|docx|rar|zip|xlsx|xls|csv|7z|tar|gz)\b', fc)
    # 提取日期
    dates = re.findall(r'\d{4}-\d{2}-\d{2}', fc)
    parts = []
    if dates:
        unique_dates = sorted(set(dates))
        if len(unique_dates) == 1:
            parts.append(f"包含 {len(dates)} 个版本 ({unique_dates[0]})")
        else:
            parts.append(f"包含 {len(dates)} 个版本 ({unique_dates[0]}~{unique_dates[-1]})")
    if files:
        seen = []
        for f in files:
            if f not in seen:
                seen.append(f)
        parts.append(f"附件: {', '.join(seen[:3])}" + (" 等" if len(seen) > 3 else ""))
    return ' | '.join(parts)
