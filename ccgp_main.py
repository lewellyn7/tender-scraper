#!/usr/bin/env python3
"""重庆政府采购网采集脚本 - 专门针对 ccgp-chongqing.gov.cn"""

import asyncio
import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loguru import logger
from app.core.browser import StealthBrowser
from app.crawlers.ccgp import CCGPCrawlerV3
from app.utils.filter import TenderFilter
from app.utils.report import ReportGenerator
from config.settings import settings

OUTPUT_DIR = "/home/lewellyn/.openclaw/workspace/logs/procurement"

# 专用关键词
KEYWORDS = ["智能化", "音视频", "AI", "人工智能", "智能体", "大模型"]
EXCLUDE_KEYWORDS = ["流标", "终止", "废标", "中标公告", "成交公告", "结果公告"]

logger.add("logs/ccgp_scraper.log", rotation="1 day", retention="7 days", level="INFO")


async def run_collection():
    """执行采购网采集任务"""
    logger.info("=" * 60)
    logger.info("🚀 开始执行重庆政府采购网采集任务")
    logger.info(f"📡 目标网站: https://www.ccgp-chongqing.gov.cn")
    logger.info(f"📅 执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    logger.info("=" * 60)

    browser = None
    try:
        browser = StealthBrowser(headless=True, slow_mo=100)
        await browser.start()

        crawler = CCGPCrawlerV3(browser)
        all_items = []

        # 采集三类信息
        for info_type in ["采购意向", "采购公告", "结果公告"]:
            logger.info(f"\n📋 开始采集 [{info_type}]...")
            items = await crawler.fetch_list(info_type=info_type, page_num=1)
            logger.info(f"  获取 {len(items)} 条")
            all_items.extend(items)

        logger.info(f"\n📥 总计获取：{len(all_items)} 条")

        if not all_items:
            logger.warning("⚠️ 未采集到任何数据")
            return None

        # 关键词过滤
        filter_engine = TenderFilter(keywords=KEYWORDS, exclude_keywords=EXCLUDE_KEYWORDS)
        matched_items = []

        for item in all_items:
            if filter_engine._contains_exclude(item.title):
                item.keywords_matched = []
                continue
            matched_kw = filter_engine.check_keywords(item.title)
            item.keywords_matched = matched_kw
            if matched_kw:
                matched_items.append(item)

        logger.info(f"✅ 关键词匹配：{len(matched_items)}/{len(all_items)} 条")

        # 生成报表
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        report_gen = ReportGenerator(OUTPUT_DIR)

        standardized = []
        for item in matched_items:
            std = filter_engine.extract_project_info(item)
            standardized.append(std)

        excel_path = ""
        if standardized:
            excel_path = report_gen.generate_excel(standardized, filename_prefix="ccgp_procurement")

        summary = report_gen.generate_summary(standardized) if standardized else "无匹配数据"

        # 保存 JSON
        data_path = os.path.join(OUTPUT_DIR, "ccgp_latest.json")
        output_data = {
            "total": len(all_items),
            "filtered": len(matched_items),
            "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "matched_projects": standardized,
        }
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)

        logger.info("\n" + summary)
        logger.info("=" * 60)
        logger.info("✅ 采集完成")
        logger.info(f"📊 Excel：{excel_path}")
        logger.info(f"📊 JSON：{data_path}")
        logger.info("=" * 60)

        return {
            "total": len(all_items),
            "filtered": len(matched_items),
            "excel_path": excel_path,
            "data_path": data_path,
            "summary": summary,
            "matched_projects": standardized,
        }

    except Exception as e:
        logger.error(f"❌ 采集失败：{e}")
        import traceback
        traceback.print_exc()
        return None

    finally:
        if browser:
            await browser.close()


def main():
    result = asyncio.run(run_collection())
    if result:
        print(f"\n✅ 采集完成：{result['filtered']}/{result['total']} 条匹配")
        if result['excel_path']:
            print(f"📊 Excel：{result['excel_path']}")
        if result['data_path']:
            print(f"📊 JSON：{result['data_path']}")
    else:
        print("\n⚠️ 未采集到数据")


if __name__ == "__main__":
    main()
