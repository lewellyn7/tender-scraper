"""内容清洗：剥离采集页面的 UI 噪点（导航/按钮/页脚）

2026-06-05 创建：用户反馈内容摘要中含"采购公告 / 我要报名"等 UI 元素。
原 fetcher 抓详情页时漏处理 SPA 顶层 chrome（面包屑/字号/按钮）。
"""
import re

# 噪点清洗正则（按顺序执行）
NOISE_PATTERNS = [
    # 1. 面包屑（开头）：首页 > 交易信息 > 政府采购/工程建设 > [UUID]
    (re.compile(r'^\s*首页\s*[>＞]\s*交易信息\s*[>＞]\s*(?:政府采购|工程建设|土地交易|矿权交易|国企采购)?\s*[>＞]?\s*[0-9a-f-]*', re.IGNORECASE), ''),
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
    """
    if not full_content:
        return ''
    cleaned = clean_text(full_content)
    cleaned = strip_title_dup(cleaned, title)
    if not cleaned:
        return ''
    if len(cleaned) > max_len:
        return cleaned[:max_len] + '...'
    return cleaned
