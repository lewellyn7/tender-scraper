"""
Playwright 浏览器核心模块 - 支持真人模拟与反爬对抗
"""
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from playwright_stealth import stealth_async
from loguru import logger
import asyncio
import random

class StealthBrowser:
    """防检测浏览器管理类"""
    
    def __init__(self, headless: bool = True, slow_mo: int = 100):
        self.headless = headless
        self.slow_mo = slow_mo
        self.playwright = None
        self.browser: Browser = None
        self.context: BrowserContext = None
        
    async def start(self):
        """启动浏览器"""
        self.playwright = await async_playwright().start()
        
        # 随机 User-Agent
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        ]
        
        # 启动浏览器
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
            ]
        )
        
        # 创建上下文
        self.context = await self.browser.new_context(
            user_agent=random.choice(user_agents),
            viewport={'width': 1920, 'height': 1080},
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
            device_scale_factor=1,
        )
        
        logger.info("✅ 防检测浏览器已启动")
        return self
    
    async def new_page(self) -> Page:
        """创建新页面并应用隐身设置"""
        if not self.context:
            raise RuntimeError("浏览器未启动，请先调用 start()")
        
        page = await self.context.new_page()
        
        # 应用 stealth 防检测
        await stealth_async(page)
        
        # 注入额外脚本隐藏自动化特征
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
        """)
        
        return page
    
    async def human_like_scroll(self, page: Page):
        """模拟真人滚动行为"""
        scroll_times = random.randint(3, 7)
        for _ in range(scroll_times):
            scroll_by = random.randint(200, 800)
            await page.evaluate(f"window.scrollBy(0, {scroll_by})")
            await asyncio.sleep(random.uniform(0.5, 1.5))
    
    async def human_like_click(self, page: Page, selector: str):
        """模拟真人点击"""
        try:
            element = await page.wait_for_selector(selector, timeout=5000)
            if element:
                # 随机延迟后点击
                await asyncio.sleep(random.uniform(0.3, 1.2))
                await element.click()
                logger.debug(f"✅ 点击: {selector}")
        except Exception as e:
            logger.warning(f"⚠️ 点击失败 {selector}: {e}")
    
    async def close(self):
        """关闭浏览器"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("🔒 浏览器已关闭")
