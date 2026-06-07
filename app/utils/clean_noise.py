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
