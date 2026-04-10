"""
HumanBehaviorEngine - 模拟人类访问行为引擎
用于反爬虫检测绕过，模拟真实用户的鼠标移动、点击和滚动行为
"""

import asyncio
import math
import random
from typing import List, Optional, Tuple

from playwright.async_api import BrowserContext, Page


class HumanBehaviorEngine:
    """人类行为模拟引擎"""

    def __init__(self, page: Page):
        self.page = page
        self._mouse_position = {"x": 0, "y": 0}

    # ==================== 随机延迟 ====================

    @staticmethod
    async def random_delay(min_seconds: float = 1.0, max_seconds: float = 5.0) -> None:
        """随机等待一段时间，模拟人类思考/阅读"""
        delay = random.uniform(min_seconds, max_seconds)
        await asyncio.sleep(delay)

    @staticmethod
    async def human_reading_delay() -> None:
        """模拟阅读页面内容的延迟 [3-8秒]"""
        await HumanBehaviorEngine.random_delay(3.0, 8.0)

    # ==================== 鼠标移动 ====================

    async def random_mouse_move(
        self,
        target_x: Optional[int] = None,
        target_y: Optional[int] = None,
        steps: Optional[int] = None
    ) -> None:
        """
        生成随机曲线路径移动鼠标，模拟人类操作

        Args:
            target_x: 目标X坐标（如果为None则在当前视口内随机）
            target_y: 目标Y坐标（如果为None则在当前视口内随机）
            steps: 移动步数（默认随机8-20步）
        """
        viewport = self.page.viewport_size
        if viewport is None:
            viewport = {"width": 1920, "height": 1080}

        # 如果未指定目标，在视口内随机选择
        if target_x is None:
            target_x = random.randint(50, viewport["width"] - 50)
        if target_y is None:
            target_y = random.randint(50, viewport["height"] - 50)

        # 计算步数
        if steps is None:
            dx = target_x - self._mouse_position["x"]
            dy = target_y - self._mouse_position["y"]
            distance = math.sqrt(dx * dx + dy * dy)
            steps = max(8, min(20, int(distance / 30)))
            steps = random.randint(steps, steps + 5)

        # 生成贝塞尔曲线路径点
        path_points = self._generate_curve_path(
            self._mouse_position["x"], self._mouse_position["y"],
            target_x, target_y,
            steps
        )

        # 沿路径移动鼠标
        for point in path_points:
            # 添加随机偏移（模拟手抖）
            jitter_x = random.uniform(-2, 2)
            jitter_y = random.uniform(-2, 2)
            await self.page.mouse.move(point["x"] + jitter_x, point["y"] + jitter_y)

            # 随机延迟（移动越快越不自然）
            move_delay = random.uniform(0.01, 0.05)
            await asyncio.sleep(move_delay)

        # 更新位置
        self._mouse_position = {"x": target_x, "y": target_y}

    def _generate_curve_path(
        self,
        start_x: float, start_y: float,
        end_x: float, end_y: float,
        steps: int
    ) -> List[dict]:
        """生成带随机抖动的曲线路径"""
        path = []
        # 控制点偏移（使路径弯曲）
        ctrl_x = random.uniform(-100, 100)
        ctrl_y = random.uniform(-100, 100)

        for i in range(steps):
            t = i / (steps - 1) if steps > 1 else 0

            # 二次贝塞尔曲线 + 随机噪声
            x = (1 - t) ** 2 * start_x + 2 * (1 - t) * t * (start_x + ctrl_x) + t ** 2 * end_x
            y = (1 - t) ** 2 * start_y + 2 * (1 - t) * t * (start_y + ctrl_y) + t ** 2 * end_y

            # 添加额外的随机抖动
            noise_x = random.uniform(-5, 5)
            noise_y = random.uniform(-5, 5)

            path.append({"x": x + noise_x, "y": y + noise_y})

        return path

    async def move_to_element(self, selector: str) -> None:
        """将鼠标移动到指定元素"""
        try:
            element = await self.page.wait_for_selector(selector, timeout=5000)
            if element:
                box = await element.bounding_box()
                if box:
                    target_x = box["x"] + box["width"] / 2
                    target_y = box["y"] + box["height"] / 2
                    await self.random_mouse_move(int(target_x), int(target_y))
        except Exception:
            pass

    # ==================== 人类点击 ====================

    async def human_click(
        self,
        selector: Optional[str] = None,
        x: Optional[int] = None,
        y: Optional[int] = None,
        button: str = "left",
        click_count: int = 1
    ) -> None:
        """
        模拟人类点击行为

        Args:
            selector: 元素选择器（优先使用）
            x, y: 坐标（如果selector为None）
            button: 鼠标按钮
            click_count: 点击次数
        """
        # 如果有selector，先移动到元素
        if selector:
            await self.move_to_element(selector)
            await self.random_delay(0.1, 0.3)  # 移动后短暂停顿
        elif x is not None and y is not None:
            # 直接移动到坐标
            await self.random_mouse_move(x, y)
            await self.random_delay(0.1, 0.3)

        # 执行点击
        if selector:
            await self.page.click(selector, button=button, click_count=click_count, delay=random.uniform(50, 150))
        else:
            await self.page.mouse.click(x or 0, y or 0, button=button)

        # 点击后延迟
        await self.random_delay(0.2, 0.5)

    async def human_double_click(
        self,
        selector: Optional[str] = None,
        x: Optional[int] = None,
        y: Optional[int] = None
    ) -> None:
        """模拟人类双击行为"""
        await self.human_click(selector=selector, x=x, y=y, click_count=2)

    async def human_right_click(
        self,
        selector: Optional[str] = None,
        x: Optional[int] = None,
        y: Optional[int] = None
    ) -> None:
        """模拟人类右键点击行为"""
        await self.human_click(selector=selector, x=x, y=y, button="right")

    # ==================== 页面滚动 ====================

    async def human_scroll(
        self,
        distance: Optional[int] = None,
        direction: str = "down",
        segment_size: int = 300,
        segments: Optional[int] = None
    ) -> None:
        """
        分段滚动页面，模拟人类滚动行为

        Args:
            distance: 滚动距离（像素），None表示滚动一整屏
            direction: 滚动方向 "up" 或 "down"
            segment_size: 每段滚动的大小
            segments: 段数（默认随机3-8段）
        """
        viewport_height = self.page.viewport_size["height"] if self.page.viewport_size else 800

        if distance is None:
            distance = viewport_height

        if segments is None:
            segments = max(3, min(8, abs(distance) // segment_size))
            segments = random.randint(segments, segments + 3)

        # 随机每段大小
        total_scrolled = 0
        for i in range(segments):
            # 添加随机抖动到每段大小
            if i == segments - 1:
                # 最后一段滚动到剩余距离
                segment = distance - total_scrolled
            else:
                jitter = random.uniform(0.7, 1.3)
                segment = int(segment_size * jitter * (1 if direction == "down" else -1))

            # 执行滚动
            if direction == "up":
                segment = -abs(segment)
            else:
                segment = abs(segment)

            await self.page.mouse.wheel(0, segment)
            total_scrolled += segment

            # 段间随机延迟（模拟阅读停顿）
            delay = random.uniform(0.3, 1.0)
            await asyncio.sleep(delay)

    async def scroll_to_bottom(self, step_pause: float = 0.5) -> None:
        """滚动到页面底部"""
        await self.page.evaluate("""
            async () => {
                await new Promise((resolve) => {
                    let totalHeight = 0;
                    const distance = 100;
                    const timer = setInterval(() => {
                        const scrollHeight = document.body.scrollHeight;
                        window.scrollBy(0, distance);
                        totalHeight += distance;
                        if (totalHeight >= scrollHeight - window.innerHeight) {
                            clearInterval(timer);
                            resolve();
                        }
                    }, 100);
                });
            }
        """)
        await asyncio.sleep(step_pause)

    async def scroll_to_top(self) -> None:
        """滚动到页面顶部"""
        await self.page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.3)

    # ==================== 键盘操作 ====================

    async def human_typing(self, text: str, delay_range: Tuple[float, float] = (0.05, 0.15)) -> None:
        """
        模拟人类打字行为

        Args:
            text: 要输入的文本
            delay_range: 每个字符之间的延迟范围（秒）
        """
        for char in text:
            await self.page.keyboard.type(char, delay=random.uniform(*delay_range))
            # 随机添加更长的停顿（模拟思考）
            if random.random() < 0.1:
                await asyncio.sleep(random.uniform(0.2, 0.5))

    # ==================== 反检测配置 ====================

    @staticmethod
    async def stealth_mode(context: BrowserContext) -> None:
        """
        配置反检测设置，隐藏自动化特征

        Args:
            context: Playwright浏览器上下文
        """
        # 注入反检测脚本
        await context.add_init_script("""
            // 隐藏 webdriver 属性
            Object.defineProperty(navigator, 'webdriver', {
                get: () => false,
                configurable: true
            });

            // 伪造 plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
                configurable: true
            });

            // 伪造 languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['zh-CN', 'zh', 'en-US', 'en'],
                configurable: true
            });

            // 修改 canvas 指纹（添加随机噪声）
            const originalGetContext = HTMLCanvasElement.prototype.getContext;
            HTMLCanvasElement.prototype.getContext = function(type, attributes) {
                const context = originalGetContext.call(this, type, attributes);
                if (type === '2d') {
                    const originalFillText = context.fillText;
                    context.fillText = function(...args) {
                        // 添加微小的随机偏移
                        if (Math.random() > 0.5) {
                            args[1] += Math.random() * 0.5;
                            args[2] += Math.random() * 0.5;
                        }
                        return originalFillText.apply(this, args);
                    };
                }
                return context;
            };

            // 拦截可能的检测
            const originalFetch = window.fetch;
            window.fetch = function(...args) {
                return originalFetch.apply(this, args);
            };
        """)

    @staticmethod
    def get_stealth_user_agent() -> str:
        """返回真实感强的 User-Agent"""
        user_agents = [
            # Chrome on Windows
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            # Chrome on Mac
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            # Firefox on Windows
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
            # Firefox on Mac
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0",
            # Edge on Windows
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
            # Safari on Mac
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
            # Chrome on Linux
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            # Mobile Chrome on Android
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
            "Mozilla/5.0 (Linux; Android 13; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
            # Mobile Safari on iOS
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
        ]
        return random.choice(user_agents)

    @staticmethod
    def get_stealth_viewport() -> dict:
        """返回真实感强的视口大小"""
        viewports = [
            {"width": 1920, "height": 1080},
            {"width": 1536, "height": 864},
            {"width": 1366, "height": 768},
            {"width": 1440, "height": 900},
            {"width": 1280, "height": 720},
            {"width": 1600, "height": 900},
        ]
        return random.choice(viewports)

    # ==================== 组合行为 ====================

    async def human_page_view(self, min_read_time: float = 5.0, max_read_time: float = 15.0) -> None:
        """
        模拟完整的人类页面浏览行为

        Args:
            min_read_time: 最小阅读时间（秒）
            max_read_time: 最大阅读时间（秒）
        """
        # 随机滚动浏览页面
        await self.human_scroll(
            distance=random.randint(300, 800),
            direction="down",
            segment_size=random.randint(200, 400)
        )

        # 阅读停顿
        await self.human_reading_delay()

        # 可能回滚一点再继续
        if random.random() > 0.5:
            await self.human_scroll(
                distance=random.randint(100, 300),
                direction="up",
                segment_size=200
            )
            await self.random_delay(1, 3)

            # 继续向下
            await self.human_scroll(
                distance=random.randint(200, 500),
                direction="down",
                segment_size=300
            )

        # 阅读时间
        await asyncio.sleep(random.uniform(min_read_time, max_read_time))

    async def human_search_action(self, search_box_selector: str, query: str) -> None:
        """
        模拟人类搜索操作

        Args:
            search_box_selector: 搜索框选择器
            query: 搜索关键词
        """
        # 点击搜索框
        await self.human_click(search_box_selector)
        await self.random_delay(0.3, 0.8)

        # 输入搜索词
        await self.human_typing(query)
        await self.random_delay(0.2, 0.5)

        # 按回车搜索
        await self.page.keyboard.press("Enter")
        await self.human_reading_delay()
