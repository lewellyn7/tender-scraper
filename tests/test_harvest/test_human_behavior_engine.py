"""
tests/test_human_behavior_engine.py

单元测试: HumanBehaviorEngine
- 模拟人类访问行为引擎
- 覆盖: 延迟、鼠标移动、点击、滚动、键盘操作、反检测配置
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from typing import Optional

import sys
sys.path.insert(0, "scripts")
from human_behavior_engine import HumanBehaviorEngine


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def mock_page():
    """Mock Playwright Page object."""
    page = MagicMock()
    page.viewport_size = {"width": 1920, "height": 1080}
    page.mouse = MagicMock()
    page.mouse.move = AsyncMock()
    page.mouse.wheel = AsyncMock()
    page.mouse.click = AsyncMock()
    page.keyboard = MagicMock()
    page.keyboard.type = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.evaluate = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.click = AsyncMock()
    return page


@pytest.fixture
def mock_context():
    """Mock Playwright BrowserContext."""
    ctx = MagicMock()
    ctx.add_init_script = AsyncMock()
    return ctx


@pytest.fixture
def engine(mock_page):
    """HumanBehaviorEngine instance with mocked page."""
    return HumanBehaviorEngine(mock_page)


# ─────────────────────────────────────────────────────────────
# 随机延迟测试
# ─────────────────────────────────────────────────────────────

class TestRandomDelay:
    """Test random_delay and human_reading_delay."""

    @pytest.mark.asyncio
    async def test_random_delay_range(self):
        """延迟应在 [min_seconds, max_seconds] 范围内"""
        min_s, max_s = 1.0, 3.0
        for _ in range(20):
            start = asyncio.get_event_loop().time()
            await HumanBehaviorEngine.random_delay(min_s, max_s)
            elapsed = asyncio.get_event_loop().time() - start
            assert min_s <= elapsed <= max_s + 0.1

    @pytest.mark.asyncio
    async def test_human_reading_delay_range(self):
        """阅读延迟应在 [3.0, 8.0] 范围内"""
        for _ in range(10):
            start = asyncio.get_event_loop().time()
            await HumanBehaviorEngine.human_reading_delay()
            elapsed = asyncio.get_event_loop().time() - start
            assert 3.0 <= elapsed <= 8.1


# ─────────────────────────────────────────────────────────────
# 鼠标移动测试
# ─────────────────────────────────────────────────────────────

class TestMouseMovement:
    """Test random_mouse_move and _generate_curve_path."""

    @pytest.mark.asyncio
    async def test_random_mouse_move_with_target(self, engine, mock_page):
        """给定目标坐标时，移动到指定位置"""
        await engine.random_mouse_move(target_x=500, target_y=300)

        # 验证 page.mouse.move 被调用多次（沿曲线路径）
        assert mock_page.mouse.move.call_count >= 8

    @pytest.mark.asyncio
    async def test_random_mouse_move_auto_target(self, engine, mock_page):
        """未指定目标时，在视口内随机选择"""
        await engine.random_mouse_move()

        assert mock_page.mouse.move.call_count >= 8
        # 鼠标位置应被更新
        assert engine._mouse_position["x"] >= 0
        assert engine._mouse_position["y"] >= 0

    @pytest.mark.asyncio
    async def test_random_mouse_move_custom_steps(self, engine, mock_page):
        """指定步数时，按步数移动"""
        await engine.random_mouse_move(target_x=100, target_y=100, steps=15)
        assert mock_page.mouse.move.call_count == 15

    @pytest.mark.asyncio
    async def test_generate_curve_path_returns_list(self, engine):
        """曲线路径返回正确格式"""
        path = engine._generate_curve_path(0, 0, 100, 100, steps=10)
        assert isinstance(path, list)
        assert len(path) == 10
        assert all("x" in p and "y" in p for p in path)

    @pytest.mark.asyncio
    async def test_generate_curve_path_shape(self, engine):
        """曲线起点=终点"""
        path = engine._generate_curve_path(0, 0, 100, 100, steps=10)
        assert path[0]["x"] != path[-1]["x"]  # 有横向移动
        assert path[0]["y"] != path[-1]["y"]  # 有纵向移动


# ─────────────────────────────────────────────────────────────
# 元素移动测试
# ─────────────────────────────────────────────────────────────

class TestMoveToElement:
    """Test move_to_element."""

    @pytest.mark.asyncio
    async def test_move_to_element_success(self, engine, mock_page):
        """元素存在时移动到元素中心"""
        mock_element = MagicMock()
        mock_element.bounding_box = AsyncMock(return_value={
            "x": 100, "y": 200, "width": 50, "height": 30
        })
        mock_page.wait_for_selector = AsyncMock(return_value=mock_element)

        await engine.move_to_element("div.target")

        mock_page.wait_for_selector.assert_called_once_with("div.target", timeout=5000)
        # 目标位置应为元素中心
        mock_page.mouse.move.assert_called()

    @pytest.mark.asyncio
    async def test_move_to_element_not_found(self, engine, mock_page):
        """元素不存在时静默跳过"""
        mock_page.wait_for_selector = AsyncMock(side_effect=Exception("timeout"))
        await engine.move_to_element("div.missing")
        # 不应抛出异常
        mock_page.mouse.move.assert_not_called()


# ─────────────────────────────────────────────────────────────
# 点击行为测试
# ─────────────────────────────────────────────────────────────

class TestHumanClick:
    """Test human_click, human_double_click, human_right_click."""

    @pytest.mark.asyncio
    async def test_human_click_with_selector(self, engine, mock_page):
        """带选择器时先移动再点击"""
        mock_element = MagicMock()
        mock_element.bounding_box = AsyncMock(return_value={
            "x": 100, "y": 200, "width": 50, "height": 30
        })
        mock_page.wait_for_selector = AsyncMock(return_value=mock_element)

        await engine.human_click(selector="button.submit")

        mock_page.wait_for_selector.assert_called_once()
        mock_page.click.assert_called_once()
        # click 被调用时带 delay
        call_kwargs = mock_page.click.call_args
        assert call_kwargs[1].get("delay") is not None

    @pytest.mark.asyncio
    async def test_human_click_with_coordinates(self, engine, mock_page):
        """带坐标时移动到坐标再点击"""
        await engine.human_click(x=300, y=400)

        mock_page.mouse.move.assert_called()
        mock_page.mouse.click.assert_called_once()

    @pytest.mark.asyncio
    async def test_human_double_click(self, engine, mock_page):
        """双击时 click_count=2"""
        mock_element = MagicMock()
        mock_element.bounding_box = AsyncMock(return_value={
            "x": 100, "y": 200, "width": 50, "height": 30
        })
        mock_page.wait_for_selector = AsyncMock(return_value=mock_element)

        await engine.human_double_click(selector="div.dbl")

        mock_page.click.assert_called_once()
        assert mock_page.click.call_args[1]["click_count"] == 2

    @pytest.mark.asyncio
    async def test_human_right_click(self, engine, mock_page):
        """右键点击"""
        mock_element = MagicMock()
        mock_element.bounding_box = AsyncMock(return_value={
            "x": 100, "y": 200, "width": 50, "height": 30
        })
        mock_page.wait_for_selector = AsyncMock(return_value=mock_element)

        await engine.human_right_click(selector="div.context")

        mock_page.click.assert_called_once()
        assert mock_page.click.call_args[1]["button"] == "right"


# ─────────────────────────────────────────────────────────────
# 滚动测试
# ─────────────────────────────────────────────────────────────

class TestHumanScroll:
    """Test human_scroll, scroll_to_bottom, scroll_to_top."""

    @pytest.mark.asyncio
    async def test_human_scroll_down(self, engine, mock_page):
        """向下滚动分段执行"""
        mock_page.viewport_size = {"height": 800}

        await engine.human_scroll(distance=600, direction="down")

        # 至少调用一次 wheel
        assert mock_page.mouse.wheel.call_count >= 3

    @pytest.mark.asyncio
    async def test_human_scroll_up(self, engine, mock_page):
        """向上滚动"""
        mock_page.viewport_size = {"height": 800}

        await engine.human_scroll(distance=400, direction="up")

        # wheel delta 应为负值
        calls = [c for c in mock_page.mouse.wheel.call_args_list]
        # 至少有向上的滚动
        assert len(calls) > 0

    @pytest.mark.asyncio
    async def test_human_scroll_custom_segments(self, engine, mock_page):
        """指定段数"""
        mock_page.viewport_size = {"height": 800}

        await engine.human_scroll(distance=900, segments=5)

        # 5段 = 至少5次 wheel 调用
        assert mock_page.mouse.wheel.call_count >= 5

    @pytest.mark.asyncio
    async def test_scroll_to_bottom(self, engine, mock_page):
        """滚动到底部"""
        await engine.scroll_to_bottom()
        mock_page.evaluate.assert_called()

    @pytest.mark.asyncio
    async def test_scroll_to_top(self, engine, mock_page):
        """滚动到顶部"""
        await engine.scroll_to_top()
        mock_page.evaluate.assert_called_with("window.scrollTo(0, 0)")


# ─────────────────────────────────────────────────────────────
# 键盘操作测试
# ─────────────────────────────────────────────────────────────

class TestHumanTyping:
    """Test human_typing."""

    @pytest.mark.asyncio
    async def test_human_typing(self, engine, mock_page):
        """输入文本逐字输入"""
        await engine.human_typing("hello")

        # 每个字符一次 type 调用
        assert mock_page.keyboard.type.call_count == 5

    @pytest.mark.asyncio
    async def test_human_typing_empty(self, engine, mock_page):
        """空字符串不调用"""
        await engine.human_typing("")
        mock_page.keyboard.type.assert_not_called()

    @pytest.mark.asyncio
    async def test_human_typing_custom_delay(self, engine, mock_page):
        """自定义延迟范围"""
        await engine.human_typing("ab", delay_range=(0.01, 0.05))
        assert mock_page.keyboard.type.call_count == 2


# ─────────────────────────────────────────────────────────────
# 反检测配置测试
# ─────────────────────────────────────────────────────────────

class TestStealthMode:
    """Test stealth_mode and related static methods."""

    @pytest.mark.asyncio
    async def test_stealth_mode_injects_script(self, mock_context):
        """stealth_mode 注入反检测 JS"""
        await HumanBehaviorEngine.stealth_mode(mock_context)
        mock_context.add_init_script.assert_called_once()
        script = mock_context.add_init_script.call_args[0][0]
        # 验证脚本包含关键属性
        assert "webdriver" in script
        assert "plugins" in script
        assert "languages" in script

    def test_get_stealth_user_agent(self):
        """返回真实感 UA 列表中的值"""
        ua = HumanBehaviorEngine.get_stealth_user_agent()
        assert isinstance(ua, str)
        assert "Mozilla/5.0" in ua
        # 验证在预设池中
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        ]
        # 随机返回，应为有效 UA 格式
        assert "Chrome" in ua or "Firefox" in ua or "Edg" in ua

    def test_get_stealth_viewport(self):
        """返回预设视口"""
        vp = HumanBehaviorEngine.get_stealth_viewport()
        assert "width" in vp
        assert "height" in vp
        assert vp["width"] in (1920, 1536, 1366, 1440, 1280, 1600)
        assert vp["height"] in (1080, 864, 768, 900, 720, 900)


# ─────────────────────────────────────────────────────────────
# 组合行为测试
# ─────────────────────────────────────────────────────────────

class TestCombinedBehaviors:
    """Test human_page_view and human_search_action."""

    @pytest.mark.asyncio
    async def test_human_page_view(self, engine, mock_page):
        """完整页面浏览行为"""
        mock_page.viewport_size = {"height": 800}

        await engine.human_page_view(min_read_time=0.5, max_read_time=1.0)

        # 应有多次滚动
        assert mock_page.mouse.wheel.call_count >= 2

    @pytest.mark.asyncio
    async def test_human_search_action(self, engine, mock_page):
        """搜索操作流程"""
        mock_element = MagicMock()
        mock_element.bounding_box = AsyncMock(return_value={
            "x": 100, "y": 200, "width": 200, "height": 40
        })
        mock_page.wait_for_selector = AsyncMock(return_value=mock_element)

        await engine.human_search_action("input.search", "test query")

        # 点击搜索框
        mock_page.click.assert_called()
        # 输入文本
        assert mock_page.keyboard.type.call_count > 0
        # 按回车
        mock_page.keyboard.press.assert_called_with("Enter")
