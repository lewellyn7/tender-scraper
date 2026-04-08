"""浏览器自动化模块"""

import asyncio
import random
from typing import List

# User-Agent 列表
USER_AGENTS: List[str] = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
]

# 反检测脚本
STEALTH_SCRIPT = """
    // 修改 webdriver 属性
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
    });
    // 修改 plugins
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
    });
    // 修改 languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['zh-CN', 'zh', 'en'],
    });
    // 隐藏 Chrome 自动化标志
    window.chrome = { runtime: {} };
"""


class StealthBrowser:
    """反检测浏览器 - 基于 Playwright"""

    def __init__(self, headless: bool = True, slow_mo: int = 0):
        self.headless = headless
        self.slow_mo = slow_mo
        self._playwright = None
        self._browser = None
        self._context = None

    async def start(self):
        """启动浏览器"""
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
        )
        self._context = await self._browser.new_context(
            user_agent=self.get_random_user_agent(),
        )

    async def new_page(self):
        """创建新页面"""
        page = await self._context.new_page()
        page = await self.stealth_page(page)
        return page

    async def close(self):
        """关闭浏览器"""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def stealth_page(self, page):
        """应用反检测措施"""
        await page.add_init_script(STEALTH_SCRIPT)
        return page

    async def random_scroll(self, page):
        """随机滚动模拟人类行为"""
        scroll_times = random.randint(3, 7)
        for _ in range(scroll_times):
            scroll_by = random.randint(200, 800)
            await page.evaluate(f"window.scrollBy(0, {scroll_by})")
            await asyncio.sleep(random.uniform(0.5, 1.5))

    async def random_mouse_move(self, page):
        """随机移动鼠标"""
        for _ in range(random.randint(3, 6)):
            x = random.randint(100, 800)
            y = random.randint(100, 600)
            await page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.3, 1.2))

    def get_random_user_agent(self) -> str:
        """获取随机 User-Agent"""
        return random.choice(USER_AGENTS)
