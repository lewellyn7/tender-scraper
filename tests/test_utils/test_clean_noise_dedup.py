"""2026-06-08 Bug 2.1 修复: strip_title_dup + make_content_preview 单测

场景:
- 详情页 .epoint-article-content 含 <h1>title</h1> + 表格, content_preview 开头 = title
- 列表 API 解析 raw_content 也可能含 title
- filter.py fallback 也要去 title 重复
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.utils.clean_noise import strip_title_dup, make_content_preview, clean_text


class TestStripTitleDup:
    """strip_title_dup(text, title)"""

    def test_strips_title_at_start(self):
        """title 在开头 → 完全去掉"""
        text = "华洋 厂保障性住房项目配售服务答疑补遗文件\n华洋 厂保障性住房项目配售服务答疑补遗文件\n项目编号：50010620260601025020101"
        title = "华洋 厂保障性住房项目配售服务答疑补遗文件"
        out = strip_title_dup(text, title)
        assert out.startswith("项目编号"), f"expected strip, got: {out[:80]}"
        assert title not in out.split("\n")[0], "first line should not be title"

    def test_strips_consecutive_title_lines(self):
        """连续多行 title 全部去掉"""
        text = "彭水县双创项目\n彭水县双创项目\n彭水县双创项目\n项目编号：xxx\n项目法人：yyy"
        title = "彭水县双创项目"
        out = strip_title_dup(text, title)
        assert out.startswith("项目编号"), f"got: {out[:80]}"
        assert not out.startswith(title), f"should not start with title"

    def test_strips_single_line_consecutive_title(self):
        """单行内连续 2 个 title 重复 (inner_text 产生), 全部去掉

        2026-06-08 Bug 2.1 二次发现: 真实 full_content 是单行
        (HTML 标签被 strip 后 inner_text 合并), title 重复以
        'title title' 形式出现, 原来的按 \\n split 失效.
        需支持 startswith 连续剥.
        """
        text = "巫山县官渡中学计算机教室设施设备采购(WSX26A00223)采购更正公告 巫山县官渡中学计算机教室设施设备采购(WSX26A00223)采购更正公告 项目编号：WSX26A00223_130117562645086240"
        title = "巫山县官渡中学计算机教室设施设备采购(WSX26A00223)采购更正公告"
        out = strip_title_dup(text, title)
        assert not out.startswith(title), f"got: {out[:80]}"
        assert out.startswith("项目编号"), f"got: {out[:80]}"

    def test_strips_single_line_3_titles(self):
        """单行内连续 3 个 title 重复, 全部去掉"""
        text = "TITLE TITLE TITLE 项目编号：xxx"
        title = "TITLE"
        out = strip_title_dup(text, title)
        assert not out.startswith("TITLE"), f"should strip all 3, got: {out[:80]}"
        assert out.startswith("项目编号")

    def test_preserves_title_in_middle(self):
        """title 在中间 (非开头) → 保留 (可能是用户想看的)"""
        text = "项目编号：xxx\n标题：彭水县双创项目\n项目法人：yyy"
        title = "彭水县双创项目"
        out = strip_title_dup(text, title)
        assert "彭水县双创项目" in out
        assert out.startswith("项目编号")

    def test_skips_blank_lines_after_title(self):
        """title 后有空行也跳过"""
        text = "标题文字\n\n\n项目编号：xxx"
        title = "标题文字"
        out = strip_title_dup(text, title)
        assert out.startswith("项目编号"), f"got: {out!r}"

    def test_no_dup_returns_unchanged(self):
        """text 开头无 title → 不动"""
        text = "项目编号：xxx\n项目法人：yyy"
        title = "完全不相关标题"
        out = strip_title_dup(text, title)
        assert out == text

    def test_empty_inputs(self):
        """空输入 / 空 title → 不动"""
        assert strip_title_dup("", "title") == ""
        assert strip_title_dup("text", "") == "text"
        assert strip_title_dup("text", "  ") == "text"

    def test_real_594901_sample(self):
        """真实 594901 数据样本"""
        text = """彭水县人武部建设项目（环境绿化部分）招标计划表
彭水县人武部建设项目（环境绿化部分）招标计划表
项目名称        彭水县人武部建设项目（环境绿化部分）
招标法人或招标人名称（盖章）    彭水县城市建设投资有限责任公司"""
        title = "彭水县人武部建设项目（环境绿化部分）招标计划表"
        out = strip_title_dup(text, title)
        # 前 2 行 title 被剥
        assert out.startswith("项目名称"), f"got: {out[:60]}"
        # 不应该再以 title 开头
        assert not out.startswith(title), f"title should be stripped"


class TestMakeContentPreview:
    """make_content_preview(full_content, title, max_len)"""

    def test_with_title_dup_truncated(self):
        """有 title 重复 + 超长 → 截断 + 去重"""
        full = "标题\n" + "标题\n" + "项目编号：xxx\n" + "x" * 1000
        title = "标题"
        out = make_content_preview(full, title, max_len=500)
        # 不应该以 title 开头
        assert not out.startswith("标题"), f"got: {out[:60]}"
        # 应该在 500 字符左右
        assert len(out) <= 503, f"len={len(out)}"

    def test_short_no_truncate(self):
        """短文本不截断"""
        full = "标题\n项目编号：xxx"
        title = "标题"
        out = make_content_preview(full, title, max_len=500)
        assert out == "项目编号：xxx"
        assert "..." not in out

    def test_empty_full_content(self):
        """空 full_content → 空 preview"""
        assert make_content_preview("", "title") == ""
        assert make_content_preview(None, "title") == ""

    def test_no_dup_just_truncate(self):
        """无 title 重复 → 单纯截断"""
        full = "x" * 1000
        out = make_content_preview(full, "完全不相关", max_len=500)
        assert out.endswith("...")
        assert len(out) == 503

    def test_max_len_custom(self):
        """自定义 max_len"""
        full = "标题\n" + "x" * 200
        out = make_content_preview(full, "标题", max_len=100)
        assert len(out) <= 103  # 100 + "..."


class TestCleanNoiseRegression:
    """回归: clean_text 行为不变 (没被我破坏)"""

    def test_clean_text_still_works(self):
        text = "首页 > 交易信息 > 工程建设 > abc-uuid\n项目编号：xxx"
        cleaned = clean_text(text)
        # 面包屑被剥
        assert "首页" not in cleaned
        assert "项目编号" in cleaned


class TestP1FallbackPath:
    """2026-06-08 验证: P1 写库路径 main.py:355 在 detail_item.content_preview 为空时
    必须用 make_content_preview(fallback) 而不是 raw full_content[:300]
    """

    def test_p1_fallback_strips_title(self):
        """模拟 cqggzy 主路径: tender.full_content 设了但 content_preview 没设
        → P1 写库走 fallback → make_content_preview
        """
        full = "标题文字\n标题文字\n项目编号：xxx\n主要内容"
        title = "标题文字"
        # 模拟 P1: content_preview 兜底走 make_content_preview
        content_preview_from_fetcher = None
        from app.utils.clean_noise import make_content_preview
        preview = content_preview_from_fetcher or make_content_preview(full, title)
        assert not preview.startswith("标题"), f"P1 fallback should strip, got: {preview[:60]}"
        assert preview.startswith("项目编号"), f"got: {preview[:60]}"
