""" 重庆市公共资源交易网专用采集器
目标网站：https://www.cqggzy.com/
"""
import asyncio
import re
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger

from app.core.browser import StealthBrowser


class CQGGZYCrawler:
    """重庆市公共资源交易网采集器"""

    BASE_URL = "https://www.cqggzy.com"

    # 政府采购公告列表页
    GOV_PURCHASE_URL = "https://www.cqggzy.com/xxhz/014005/order.html"

    # 工程招投标列表页
    ENGINEERING_URL = "https://www.cqggzy.com/xxhz/014001/bidding.html"

    def __init__(self, browser: StealthBrowser):
        self.browser = browser
        self.results = []

    async def fetch_gov_purchase_list(self, page_num: int = 1) -> List[Dict]:
        """获取政府采购公告列表"""
        results = []
        try:
            page = await self.browser.new_page()

            # 对于第一页，直接访问列表页
            url = self.GOV_PURCHASE_URL
            logger.info(f"📑 正在采集政府采购公告列表 第{page_num}页: {url}")

            await page.goto(url, wait_until="networkidle", timeout=60000)

            # 等待列表加载
            await asyncio.sleep(3)

            # 提取列表项
            items = await page.query_selector_all('ul li')

            for item in items:
                try:
                    # 获取链接和标题
                    link_elem = await item.query_selector('a')
                    if not link_elem:
                        continue

                    href = await link_elem.get_attribute('href')
                    title = await link_elem.text_content()

                    # 过滤无效链接
                    if not href or not title:
                        continue
                    if href.startswith('javascript'):
                        continue
                    if len(title.strip()) < 10:
                        continue

                    # 获取日期
                    date_elem = await item.query_selector('[class*="date"], span')
                    date_text = ""
                    if date_elem:
                        date_text = await date_elem.text_content()

                    # 解析日期
                    publish_date = self._parse_date(date_text)

                    # 构建完整链接
                    full_link = href if href.startswith('http') else f"{self.BASE_URL}{href}"

                    results.append({
                        'title': title.strip(),
                        'link': full_link,
                        'publish_date': publish_date,
                        'type': '政府采购公告',
                        'raw_date': date_text.strip() if date_text else ''
                    })

                except Exception as e:
                    logger.warning(f"⚠️ 提取单条数据失败：{e}")
                    continue

            logger.info(f"✅ 采集到 {len(results)} 条政府采购公告")
            return results

        except Exception as e:
            logger.error(f"❌ 政府采购公告列表采集失败：{e}")
            return results
        finally:
            await page.close()

    async def fetch_engineering_list(self, page_num: int = 1) -> List[Dict]:
        """获取工程招投标列表"""
        results = []
        try:
            page = await self.browser.new_page()

            url = self.ENGINEERING_URL
            logger.info(f"📑 正在采集工程招投标列表 第{page_num}页: {url}")

            await page.goto(url, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(3)

            items = await page.query_selector_all('ul li')

            for item in items:
                try:
                    link_elem = await item.query_selector('a')
                    if not link_elem:
                        continue

                    href = await link_elem.get_attribute('href')
                    title = await link_elem.text_content()

                    if not href or not title:
                        continue
                    if href.startswith('javascript'):
                        continue
                    if len(title.strip()) < 10:
                        continue

                    date_elem = await item.query_selector('[class*="date"], span')
                    date_text = ""
                    if date_elem:
                        date_text = await date_elem.text_content()

                    publish_date = self._parse_date(date_text)
                    full_link = href if href.startswith('http') else f"{self.BASE_URL}{href}"

                    results.append({
                        'title': title.strip(),
                        'link': full_link,
                        'publish_date': publish_date,
                        'type': '工程招投标',
                        'raw_date': date_text.strip() if date_text else ''
                    })

                except Exception as e:
                    logger.warning(f"⚠️ 提取单条数据失败：{e}")
                    continue

            logger.info(f"✅ 采集到 {len(results)} 条工程招投标信息")
            return results

        except Exception as e:
            logger.error(f"❌ 工程招投标列表采集失败：{e}")
            return results
        finally:
            await page.close()

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """解析日期字符串"""
        if not date_str:
            return None

        # 清理日期字符串
        date_str = re.sub(r'[\[\]]', '', date_str).strip()

        # 尝试多种日期格式
        date_formats = [
            '%Y-%m-%d',
            '%Y/%m/%d',
            '%Y年%m月%d日',
            '%Y-%m-%d %H:%M:%S',
        ]

        for fmt in date_formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        # 尝试提取 YYYY-MM-DD 格式
        match = re.search(r'(\d{4}-\d{2}-\d{2})', date_str)
        if match:
            try:
                return datetime.strptime(match.group(1), '%Y-%m-%d')
            except:
                pass

        logger.warning(f"⚠️ 日期解析失败：{date_str}")
        return None

    async def close(self):
        """关闭浏览器"""
        await self.browser.close()
