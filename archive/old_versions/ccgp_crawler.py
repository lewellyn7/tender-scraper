"""
重庆市政府采购网专用采集器
目标网站：https://www.ccgp-chongqing.gov.cn/
"""
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger

from app.core.browser import StealthBrowser


class CCGPCrawler:
    """重庆市政府采购网采集器"""

    BASE_URL = "https://www.ccgp-chongqing.gov.cn"
    # 采购公告列表页 URL 模板
    NOTICE_LIST_URL = "https://www.ccgp-chongqing.gov.cn/gkw/web/portal/notice/list"
    # 采购意向列表页 URL 模板
    INTENTION_LIST_URL = "https://www.ccgp-chongqing.gov.cn/gkw/web/portal/intention/list"

    def __init__(self, browser: StealthBrowser):
        self.browser = browser
        self.results = []

    async def fetch_notice_list(self, page_num: int = 1) -> List[Dict]:
        """获取采购公告列表"""
        results = []

        try:
            page = await self.browser.new_page()

            # 构建列表页 URL (假设分页参数为 page)
            url = f"{self.NOTICE_LIST_URL}?page={page_num}"
            logger.info(f"📑 正在采集采购公告列表 第{page_num}页: {url}")

            await page.goto(url, wait_until="networkidle", timeout=30000)

            # 等待列表加载
            await page.wait_for_selector('.notice-item', timeout=10000)

            # 提取列表项
            items = await page.query_selector_all('.notice-item')

            for item in items:
                try:
                    title_elem = await item.query_selector('.notice-title')
                    date_elem = await item.query_selector('.notice-date')
                    link_elem = await item.query_selector('a')

                    if title_elem and link_elem:
                        title = await title_elem.text_content()
                        link = await link_elem.get_attribute('href')
                        date_text = await date_elem.text_content() if date_elem else ""

                        # 解析日期
                        publish_date = self._parse_date(date_text)

                        results.append({
                            'title': title.strip() if title else '',
                            'link': link if link.startswith('http') else f"{self.BASE_URL}{link}",
                            'publish_date': publish_date,
                            'type': '采购公告',
                            'raw_date': date_text
                        })
                except Exception as e:
                    logger.warning(f"⚠️ 提取单条数据失败：{e}")
                    continue

            logger.info(f"✅ 采集到 {len(results)} 条采购公告")
            return results

        except Exception as e:
            logger.error(f"❌ 采购公告列表采集失败：{e}")
            return results
        finally:
            await page.close()

    async def fetch_intention_list(self, page_num: int = 1) -> List[Dict]:
        """获取采购意向列表"""
        results = []

        try:
            page = await self.browser.new_page()

            url = f"{self.INTENTION_LIST_URL}?page={page_num}"
            logger.info(f"📑 正在采集采购意向列表 第{page_num}页: {url}")

            await page.goto(url, wait_until="networkidle", timeout=30000)

            # 等待列表加载
            await page.wait_for_selector('.notice-item', timeout=10000)

            items = await page.query_selector_all('.notice-item')

            for item in items:
                try:
                    title_elem = await item.query_selector('.notice-title')
                    date_elem = await item.query_selector('.notice-date')
                    link_elem = await item.query_selector('a')

                    if title_elem and link_elem:
                        title = await title_elem.text_content()
                        link = await link_elem.get_attribute('href')
                        date_text = await date_elem.text_content() if date_elem else ""

                        publish_date = self._parse_date(date_text)

                        results.append({
                            'title': title.strip() if title else '',
                            'link': link if link.startswith('http') else f"{self.BASE_URL}{link}",
                            'publish_date': publish_date,
                            'type': '采购意向',
                            'raw_date': date_text
                        })
                except Exception as e:
                    logger.warning(f"⚠️ 提取单条数据失败：{e}")
                    continue

            logger.info(f"✅ 采集到 {len(results)} 条采购意向")
            return results

        except Exception as e:
            logger.error(f"❌ 采购意向列表采集失败：{e}")
            return results
        finally:
            await page.close()

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """解析日期字符串"""
        if not date_str:
            return None

        # 尝试多种日期格式
        date_formats = [
            '%Y-%m-%d',
            '%Y/%m/%d',
            '%Y年%m月%d日',
            '%m月%d日',
            '%Y-%m-%d %H:%M:%S'
        ]

        for fmt in date_formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue

        logger.warning(f"⚠️ 日期解析失败：{date_str}")
        return None

    async def close(self):
        """关闭浏览器"""
        await self.browser.close()
