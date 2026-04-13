"""爬虫执行器 - 基于Playwright的通用网页数据提取"""

import json
import re
import time
from typing import Any
from urllib.parse import urljoin, urlparse
from loguru import logger

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class CrawlExecutor:
    """通用爬虫执行器"""

    def __init__(self, config: dict):
        """
        config: {
            "name": "网站名",
            "base_url": "https://...",
            "list_selector": ".item",
            "item_rules": {
                "title": {"selector": ".title", "attr": "text"},
                "url": {"selector": "a", "attr": "href"},
                "date": {"selector": ".date", "attr": "text"},
                "budget": {"selector": ".money", "attr": "text"}
            },
            "pagination_type": "next_button | page_param | scroll | none",
            "pagination_selector": ".next",
            "pagination_param": "?page={n}",
            "cookies": "",
            "headers": {}
        }
        """
        self.config = config
        self.results = []

    def extract_field(self, el, rule: dict) -> str:
        """从一个元素中提取字段"""
        selector = rule.get("selector", "")
        attr = rule.get("attr", "text")
        try:
            if attr == "text":
                return el.query_selector(selector).inner_text().strip() if el.query_selector(selector) else ""
            elif attr == "href":
                href = el.query_selector(selector).get_attribute("href") or ""
                return urljoin(self.config["base_url"], href)
            else:
                return el.query_selector(selector).get_attribute(attr) or ""
        except Exception:
            return ""

    def extract_item(self, item_el, rules: dict) -> dict:
        """从单个列表项提取所有字段"""
        item = {}
        for field, rule in rules.items():
            item[field] = self.extract_field(item_el, rule)
        # 补全 URL
        if "url" not in item or not item["url"]:
            item["url"] = ""
        return item

    def apply_filters(self, items: list) -> list:
        """应用关键词过滤"""
        keyword = self.config.get("filter_keyword", "").strip()
        if not keyword:
            return items
        kw_lower = keyword.lower()
        return [it for it in items if kw_lower in (it.get("title", "") + it.get("url", "")).lower()]

    def crawl_page(self, page, url: str) -> list:
        """爬取单个页面，返回列表项"""
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)  # 等待动态内容加载
        except PlaywrightTimeout:
            logger.warning(f"页面加载超时: {url}")
            return []
        except Exception as e:
            logger.error(f"页面加载失败 {url}: {e}")
            return []

        selector = self.config.get("list_selector", "")
        if not selector:
            logger.warning("未设置 list_selector")
            return []

        try:
            items = page.query_selector_all(selector)
        except Exception:
            return []

        rules = json.loads(self.config.get("item_rules", "{}"))
        results = [self.extract_item(el, rules) for el in items]
        return [r for r in results if r.get("title") or r.get("url")]

    def crawl(self, timeout: int = 15) -> dict:
        """
        执行爬取，返回结果摘要
        {
            "items_found": int,
            "items_new": int,
            "results": list
        }
        """
        if not PLAYWRIGHT_AVAILABLE:
            return {"error": "Playwright未安装: pip install playwright && playwright install"}

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )

            # 设置 cookies
            cookies_str = self.config.get("cookies", "").strip()
            if cookies_str:
                try:
                    cookies = json.loads(cookies_str) if cookies_str.startswith("[") else [{"name": k.strip(), "value": v.strip()} for k, v in (pair.split("=") for pair in cookies_str.split(";"))]
                    context.add_cookies(cookies)
                except Exception as e:
                    logger.warning(f"Cookie设置失败: {e}")

            page = context.new_page()
            all_items = []
            page_num = 1
            max_pages = self.config.get("max_pages", 10)

            while page_num <= max_pages:
                # 构建 URL
                base = self.config["base_url"]
                pag_type = self.config.get("pagination_type", "none")

                if pag_type == "page_param":
                    param = self.config.get("pagination_param", "")
                    url = re.sub(r"\{[nNpP]\}\}|\{page\}", str(page_num), base + ("?" + param if "?" not in base else "&" + param.lstrip("?")))
                    if page_num == 1 and "{" not in param:
                        url = base
                elif pag_type == "next_button" and page_num > 1:
                    try:
                        next_sel = self.config.get("pagination_selector", "")
                        next_btn = page.query_selector(next_sel)
                        if not next_btn:
                            break
                        next_href = next_btn.get_attribute("href")
                        if not next_href:
                            break
                        url = urljoin(base, next_href)
                    except Exception:
                        break
                elif page_num > 1:
                    break  # 没有更多分页

                if page_num == 1:
                    url = base

                items = self.crawl_page(page, url)
                if not items:
                    break

                all_items.extend(items)
                logger.info(f"第{page_num}页: 获得{len(items)}条")
                page_num += 1

            browser.close()

        all_items = self.apply_filters(all_items)
        return {
            "items_found": len(all_items),
            "results": all_items
        }
