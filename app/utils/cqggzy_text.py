"""
CQGGZY 详情页文本清洗工具。

清洗目标：
  1) 移除 nav/header/footer 噪音（"APP下载"、"首页"、"注册 登录" 等页面装饰）
  2) 移除 inline CSS 噪音（".preview-wrap h4{...}" 这种 style block）
  3) 定位真正正文起点："一、" "项目编号：" "项目名称：" "采购人：" 等
  4) 移除尾部噪音（"请点击..." "请到原网址..." "点击前往"）

抽取策略（双保险）：
  - 优先抓 <div class="app-detail ...">（纯正文容器，1370 bytes）
  - fallback 到 <div class="detail-wrapper"> + clean_cqggzy_text 裁 nav
"""
import re
from html.parser import HTMLParser

# 正文起点 markers (按优先级)
_CONTENT_START_MARKERS = [
    re.compile(r'[一二三四五六七八九十]+、'),          # 一、二、三、等章节
    re.compile(r'项目编号\s*[：:]'),
    re.compile(r'项目名称\s*[：:]'),
    re.compile(r'采购人\s*[：:]'),
    re.compile(r'招标人\s*[：:]'),
    re.compile(r'中标人\s*[：:]'),
    re.compile(r'第一中标候选人\s*[：:]'),
]

# Nav/header 关键词 (用于检测 cp 是否以 nav 开头)
_NAV_KEYWORDS = (
    'APP下载', '用户手册', '交易监督网', '加入收藏', '注册 登录',
    '首页 资讯动态', '信息汇总', '产权交易', '工程招投标',
    '采购公告 单一来源', '答疑补遗', '中标候选人公示',
    '重庆公共资源APP', '渝产权APP', '公众号', '人民法院诉讼资产网',
)

# 尾部噪音 patterns
_TAIL_NOISE_PATTERNS = [
    re.compile(r'请到原网址[^\n]*'),
    re.compile(r'请点击[^\n]*'),
    re.compile(r'点击前往[^\n]*'),
    re.compile(r'请到[^\n]*?下载附件[^\n]*'),
]


def _strip_css_noise(text: str) -> str:
    """移除 inline CSS block.

    处理形式:
      - .cls{ prop: val }                (class selector)
      - .cls1.cls2{ prop: val }          (multi-class)
      - .cls element{ prop: val }        (descendant selector, e.g. ".preview-wrap h4")
      - .cls, .cls2{ prop: val }         (grouped, 简化版只处理前者)
    """
    # 1) multi-class + descendant selector: .x .y{...} / .x.y{...}
    text = re.sub(r'\.[\w-]+(?:\s+[\w-]+)*\s*\{[^{}]*\}', '', text)
    # 2) 兜底: 任何 .{...} 形式 (允许 selector 含空格)
    text = re.sub(r'\.[^{}]+\{[^{}]*\}', '', text)
    return text


def _strip_tail_noise(text: str) -> str:
    """移除尾部"请点击..."等噪音."""
    for pat in _TAIL_NOISE_PATTERNS:
        text = pat.sub('', text)
    return text.rstrip()


def find_content_start(text: str) -> int:
    """找正文起点位置. 返回 text 中的 offset, 找不到返回 len(text)."""
    earliest = len(text)
    for marker in _CONTENT_START_MARKERS:
        m = marker.search(text)
        if m and m.start() < earliest:
            earliest = m.start()
    return earliest


def looks_like_nav(text: str) -> bool:
    """检测文本是否以 nav 开头."""
    head = (text or '')[:200]
    return any(kw in head for kw in _NAV_KEYWORDS)


def clean_cqggzy_text(raw_text: str, *, hard_truncate_to: int | None = None) -> str:
    """
    清洗 CQGGZY 详情页文本.

    Args:
        raw_text: 原始文本 (可能含 nav + CSS 噪音)
        hard_truncate_to: 清洗后截断到 N 字符 (None = 不截断)

    Returns:
        清洗后的纯正文文本
    """
    if not raw_text:
        return raw_text or ''

    text = raw_text

    # 1) strip CSS block
    text = _strip_css_noise(text)

    # 2) 如果含 nav, 定位正文起点
    if looks_like_nav(text):
        start = find_content_start(text)
        if start < len(text):
            text = text[start:]

    # 3) strip tail noise
    text = _strip_tail_noise(text)

    # 4) 合并多余空白
    text = re.sub(r'\s+', ' ', text).strip()

    if hard_truncate_to and len(text) > hard_truncate_to:
        text = text[:hard_truncate_to]

    return text


# ---------------- HTML 抽取 ----------------

class _DetailDivExtractor(HTMLParser):
    """提取 <div class="app-detail..."> 内容（精确正文容器）."""

    def __init__(self):
        super().__init__()
        self._div_stack = []
        self._capture_target = None  # None = not capturing; else = depth when to stop
        self._capture_buf = []
        self._result = ''

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        if tag != 'div':
            return
        cls = attr_dict.get('class', '') or ''
        self._div_stack.append(cls)
        # 抓 app-detail (class 含 'app-detail')
        if 'app-detail' in cls and self._capture_target is None:
            self._capture_target = len(self._div_stack)
            self._capture_buf = []

    def handle_data(self, data):
        if self._capture_target is not None:
            self._capture_buf.append(data)

    def handle_endtag(self, tag):
        if tag != 'div':
            return
        if self._div_stack:
            self._div_stack.pop()
        if self._capture_target is not None and len(self._div_stack) < self._capture_target:
            self._result = ''.join(self._capture_buf)
            self._capture_target = None
            self._capture_buf = []

    def result(self):
        return self._result


def extract_cqggzy_detail(html: str) -> str:
    """
    从 CQGGZY 详情页 HTML 中抽取正文.

    优先抽 <div class="app-detail..."> 内容（纯正文）;
    fallback 到 detail-wrapper 容器 + clean_cqggzy_text 裁 nav.

    Args:
        html: 详情页 HTML

    Returns:
        清洗后的纯正文文本
    """
    if not html:
        return ''

    # 1) 优先抽 app-detail div
    parser = _DetailDivExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    raw = parser.result()

    if raw:
        # app-detail 内容还可能含 CSS 噪音, 过一遍 clean
        text = re.sub(r'<[^>]+>', ' ', raw)
        text = re.sub(r'\s+', ' ', text).strip()
        return clean_cqggzy_text(text)

    # 2) fallback: detail-wrapper
    m = re.search(r'<div[^>]*class="[^"]*detail-wrapper[^"]*"[^>]*>(.*?)(?=<footer|<script)', html, re.S)
    if m:
        text = re.sub(r'<[^>]+>', ' ', m.group(1))
        text = re.sub(r'\s+', ' ', text).strip()
        return clean_cqggzy_text(text)

    return ''