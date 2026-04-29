#!/usr/bin/env python3
"""重庆政府采购网采集脚本 - 临时执行版（解决日志权限问题）"""

import asyncio
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loguru import logger

from app.core.browser import StealthBrowser
from app.crawlers.ccgp import CCGPCrawlerV3
from app.utils.filter import TenderFilter
from app.utils.report import ReportGenerator

OUTPUT_DIR = "/home/lewellyn/.openclaw/workspace/logs/procurement"

# 专用关键词
KEYWORDS = ["智能化", "音视频", "AI", "人工智能", "智能体", "大模型"]
EXCLUDE_KEYWORDS = ["流标", "终止", "废标", "中标公告", "成交公告", "结果公告"]

# 不写本地日志，只输出到 stderr
logger.add(sys.stderr, format="{time:HH:mm:ss} | {level} | {message}", level="INFO")


async def run_collection():
    logger.info("=" * 60)
    logger.info("🚀 重庆政府采购网采集任务")
    logger.info(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')} (下午场)")
    logger.info("=" * 60)

    browser = None
    try:
        browser = StealthBrowser(headless=True, slow_mo=100)
        await browser.start()
        crawler = CCGPCrawlerV3(browser)
        crawler._visited_urls.clear()

        all_items = []

        for info_type in ["采购意向", "采购公告"]:
            logger.info(f"📋 采集 [{info_type}]...")
            items = await crawler.fetch_list(info_type=info_type, page_num=1)
            logger.info(f"   获取 {len(items)} 条")
            all_items.extend(items)

        logger.info(f"📥 总计：{len(all_items)} 条")

        if not all_items:
            logger.warning("⚠️ 未获取到数据")
            return None

        filter_engine = TenderFilter(keywords=KEYWORDS, exclude_keywords=EXCLUDE_KEYWORDS)
        filtered = []
        for item in all_items:
            title = item.title if hasattr(item, "title") else str(item)
            if filter_engine.check_keywords(title):
                matched = filter_engine.get_matched_keywords(title) if hasattr(filter_engine, 'get_matched_keywords') else filter_engine.check_keywords(title)

                filtered.append({
                    "title": title,
                    "url": item.url if hasattr(item, "url") else "",
                    "publish_date": item.publish_date if hasattr(item, "publish_date") else "",
                    "info_type": item.info_type if hasattr(item, "info_type") else "",
                    "type": item.type if hasattr(item, "type") else "",
                    "budget": item.budget if hasattr(item, "budget") else "",
                    "region": "重庆",
                    "keywords_matched": matched,
                    "source": "重庆政府采购网",
                })

        logger.info(f"🔍 关键词过滤后：{len(filtered)} 条")

        if filtered:
            report_gen = ReportGenerator(output_dir=OUTPUT_DIR)
            excel_path = report_gen.generate_excel(
                filtered,
                f"重庆采购_{datetime.now().strftime('%Y%m%d_%H%M')}"
            )
            logger.info(f"✅ Excel 已生成：{excel_path}")

            # 推送
            try:
                from app.services.notification import NotificationService
                notifier = NotificationService()
                notifier.send_procurement_report(excel_path, len(filtered))
                logger.info("📤 已推送至用户")
            except Exception as e:
                logger.warning(f"推送失败（不影响主流程）: {e}")
        else:
            logger.info("📭 今日无匹配关键词的采购公告")

        return filtered

    finally:
        if browser:
            await browser.close()


if __name__ == "__main__":
    result = asyncio.run(run_collection())
    sys.exit(0 if result is not None else 1)