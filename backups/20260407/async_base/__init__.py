"""
async_crawler_base.py - 基于 Playwright 的异步爬虫基类
集成人类行为模拟引擎，支持反检测和浏览器指纹
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Callable
from playwright.async_api import async_playwright, Page, BrowserContext, Browser
from human_behavior_engine import HumanBehaviorEngine


logger = logging.getLogger(__name__)


class HumanCrawlerBase(ABC):
    """
    人类行为模拟爬虫基类

    使用 Playwright + HumanBehaviorEngine 实现：
    - 模拟真实浏览器访问
    - 人类行为反检测
    - 浏览器指纹随机化
    """

    def __init__(
        self,
        headless: bool = True,
        stealth: bool = True,
        user_agent: Optional[str] = None,
        viewport: Optional[Dict[str, int]] = None,
        proxy: Optional[str] = None,
        timeout: int = 30000,
        slow_mo: int = 0,
    ):
        """
        初始化爬虫

        Args:
            headless: 是否无头模式运行
            stealth: 是否启用反检测模式
            user_agent: 指定User-Agent（None则随机）
            viewport: 视口大小（None则随机）
            proxy: 代理地址，格式: http://user:pass@host:port
            timeout: 默认超时时间（毫秒）
            slow_mo: 操作间隔（毫秒），用于调试
        """
        self.headless = headless
        self.stealth = stealth
        self.user_agent = user_agent or HumanBehaviorEngine.get_stealth_user_agent()
        self.viewport = viewport or HumanBehaviorEngine.get_stealth_viewport()
        self.proxy = proxy
        self.timeout = timeout
        self.slow_mo = slow_mo

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._behavior: Optional[HumanBehaviorEngine] = None

    # ==================== 生命周期管理 ====================

    async def __aenter__(self):
        await self.launch()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def launch(self) -> None:
        """启动浏览器"""
        self._playwright = await async_playwright().start()

        # 启动浏览器
        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-accelerated-2d-canvas",
            "--no-first-run",
            "--no-zygote",
            "--disable-gpu",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
        ]

        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
            args=browser_args,
        )

        # 创建上下文
        context_options = {
            "user_agent": self.user_agent,
            "viewport": self.viewport,
            "ignore_https_errors": True,
            "java_script_enabled": True,
        }

        if self.proxy:
            context_options["proxy"] = {"server": self.proxy}

        if self.stealth:
            # 使用临时context进行stealth注入
            temp_context = await self._browser.new_context(**context_options)
            await HumanBehaviorEngine.stealth_mode(temp_context)
            self._context = temp_context
        else:
            self._context = await self._browser.new_context(**context_options)

        # 创建页面
        self._page = await self._context.new_page()
        self._behavior = HumanBehaviorEngine(self._page)

        # 设置默认超时
        self._page.set_default_timeout(self.timeout)

        logger.info(
            f"浏览器已启动: headless={self.headless}, stealth={self.stealth}, "
            f"viewport={self.viewport}"
        )

    async def close(self) -> None:
        """关闭浏览器"""
        if self._page:
            await self._page.close()
            self._page = None
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self._behavior = None
        logger.info("浏览器已关闭")

    # ==================== 页面操作 ====================

    @property
    def page(self) -> Page:
        """获取当前页面"""
        if self._page is None:
            raise RuntimeError("浏览器未启动，请先调用 launch() 或使用 async with")
        return self._page

    @property
    def behavior(self) -> HumanBehaviorEngine:
        """获取行为引擎"""
        if self._behavior is None:
            raise RuntimeError("浏览器未启动，请先调用 launch() 或使用 async with")
        return self._behavior

    async def new_page(self) -> Page:
        """创建新页面"""
        page = await self._context.new_page()
        return page

    async def switch_to_page(self, page: Page) -> None:
        """切换到指定页面"""
        self._page = page
        self._behavior = HumanBehaviorEngine(page)

    # ==================== 人类行为封装 ====================

    async def human_get(self, url: str, wait_until: str = "domcontentloaded") -> None:
        """
        模拟人类访问页面

        Args:
            url: 目标URL
            wait_until: 等待策略
        """
        # 随机延迟模拟思考
        await self.behavior.random_delay(0.5, 2.0)

        # 导航并等待
        await self.page.goto(url, wait_until=wait_until, timeout=self.timeout)

        # 页面加载后随机浏览
        await self.behavior.human_page_view(min_read_time=2.0, max_read_time=5.0)

    async def human_click(self, selector: str, **kwargs) -> None:
        """模拟人类点击元素"""
        await self.behavior.human_click(selector, **kwargs)

    async def human_scroll(
        self,
        distance: Optional[int] = None,
        direction: str = "down",
        **kwargs
    ) -> None:
        """模拟人类滚动页面"""
        await self.behavior.human_scroll(distance=distance, direction=direction, **kwargs)

    async def human_type(self, selector: str, text: str, **kwargs) -> None:
        """模拟人类输入文本"""
        await self.behavior.human_click(selector)  # 先点击
        await self.behavior.human_typing(text, **kwargs)

    async def human_search(self, selector: str, query: str) -> None:
        """模拟人类搜索操作"""
        await self.behavior.human_search_action(selector, query)

    # ==================== 等待条件 ====================

    async def wait_for_selector(self, selector: str, timeout: Optional[int] = None) -> Any:
        """等待元素出现"""
        return await self.page.wait_for_selector(selector, timeout=timeout or self.timeout)

    async def wait_for_load_state(self, state: str = "networkidle") -> None:
        """等待页面加载状态"""
        await self.page.wait_for_load_state(state)

    async def wait_for_function(self, func: str, *args, **kwargs) -> Any:
        """等待JavaScript函数返回真值"""
        return await self.page.wait_for_function(func, *args, **kwargs)

    # ==================== 数据提取 ====================

    async def extract_content(
        self,
        selector: Optional[str] = None,
        attribute: Optional[str] = None,
        many: bool = False
    ) -> Any:
        """
        提取页面内容

        Args:
            selector: 元素选择器
            attribute: 要提取的属性（None则提取文本）
            many: 是否提取多个元素
        """
        if selector is None:
            return await self.page.content()

        if many:
            elements = await self.page.query_selector_all(selector)
            results = []
            for el in elements:
                if attribute:
                    results.append(await el.get_attribute(attribute))
                else:
                    results.append(await el.text_content())
            return results
        else:
            el = await self.page.query_selector(selector)
            if el is None:
                return None
            if attribute:
                return await el.get_attribute(attribute)
            return await el.text_content()

    async def evaluate(self, expression: str, *args, **kwargs) -> Any:
        """在页面上下文执行JavaScript"""
        return await self.page.evaluate(expression, *args, **kwargs)

    async def extract_table(self, selector: str) -> List[Dict[str, Any]]:
        """
        提取表格数据为字典列表

        Args:
            selector: 表格选择器

        Returns:
            [{col1: val1, col2: val2, ...}, ...]
        """
        script = f"""
            async () => {{
                const table = document.querySelector('{selector}');
                if (!table) return null;

                const headers = Array.from(table.querySelectorAll('th')).map(h => h.textContent.trim());
                const rows = Array.from(table.querySelectorAll('tr')).slice(1);

                return rows.map(row => {{
                    const cells = Array.from(row.querySelectorAll('td'));
                    const obj = {{}};
                    headers.forEach((h, i) => {{
                        obj[h] = cells[i] ? cells[i].textContent.trim() : '';
                    }});
                    return obj;
                }});
            }}
        """
        return await self.page.evaluate(script)

    # ==================== 截图与保存 ====================

    async def screenshot(
        self,
        path: Optional[str] = None,
        full_page: bool = False,
        **kwargs
    ) -> bytes:
        """页面截图"""
        return await self.page.screenshot(path=path, full_page=full_page, **kwargs)

    async def save_html(self, path: str) -> None:
        """保存页面HTML"""
        content = await self.page.content()
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    # ==================== Cookie管理 ====================

    async def get_cookies(self, urls: Optional[List[str]] = None) -> List[Dict]:
        """获取Cookie"""
        return await self._context.cookies(urls)

    async def set_cookies(self, cookies: List[Dict]) -> None:
        """设置Cookie"""
        await self._context.add_cookies(cookies)

    async def clear_cookies(self) -> None:
        """清除所有Cookie"""
        await self._context.clear_cookies()

    # ==================== 钩子方法（供子类实现） ====================

    async def on_page_loaded(self, page: Page) -> None:
        """
        页面加载后的回调，可被子类重写

        Args:
            page: 加载完成的页面
        """
        pass

    async def before_close(self) -> None:
        """关闭前的回调，可被子类重写"""
        pass

    # ==================== 抽象方法（子类必须实现） ====================

    @abstractmethod
    async def parse(self, page: Page) -> Any:
        """
        解析页面的抽象方法，子类必须实现

        Args:
            page: Playwright Page对象

        Returns:
            解析结果
        """
        pass

    # ==================== 便捷的页面刷新 ====================

    async def refresh(self, human_behavior: bool = True) -> None:
        """
        刷新页面

        Args:
            human_behavior: 是否模拟人类行为
        """
        if human_behavior:
            await self.behavior.random_delay(1.0, 3.0)
        await self.page.reload()
        if human_behavior:
            await self.behavior.human_page_view(min_read_time=1.0, max_read_time=3.0)

    async def back(self, human_behavior: bool = True) -> None:
        """返回上一页"""
        if human_behavior:
            await self.behavior.random_delay(1.0, 2.0)
        await self.page.go_back()
        if human_behavior:
            await self.behavior.human_page_view(min_read_time=1.0, max_read_time=3.0)

    async def forward(self, human_behavior: bool = True) -> None:
        """前进到下一页"""
        if human_behavior:
            await self.behavior.random_delay(1.0, 2.0)
        await self.page.go_forward()
        if human_behavior:
            await self.behavior.human_page_view(min_read_time=1.0, max_read_time=3.0)
