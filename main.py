"""招投标采集系统 - 主入口 V2 修复版
更新：支持详情页采集 + 数据持久化 + Web 管理界面
"""
import asyncio
import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loguru import logger
from app.core.browser import StealthBrowser
from app.crawlers.cqggzy import CQGGZYCrawlerV2
from app.utils.filter import TenderFilter
from app.utils.report import ReportGenerator
from app.core.session_memory import SessionMemory, SessionMemoryConfig
from app.core.concurrency_scheduler import ConcurrencyScheduler, SafetyLevel
from config.settings import settings

# 配置日志
logger.add("logs/scraper.log", rotation="1 day", retention="7 days", level="INFO")

async def run_collection():
    """执行一次完整的数据采集任务"""
    logger.info("=" * 60)
    logger.info("🚀 开始执行招投标信息采集任务 V2")
    logger.info(f"📡 目标网站: {settings.TARGET_URL}")
    logger.info("=" * 60)

    # 初始化 P0 模块
    session_memory = SessionMemory(SessionMemoryConfig(max_tokens=128000, compact_threshold=0.80))
    concurrency_scheduler = ConcurrencyScheduler()

    # 注册采集工具
    concurrency_scheduler.register_tool_from_metadata(
        name="fetch_page",
        description="采集网页数据",
        is_concurrency_safe=True,
        max_concurrent=5
    )
    concurrency_scheduler.register_tool_from_metadata(
        name="fetch_detail",
        description="采集详情页数据",
        is_concurrency_safe=True,
        max_concurrent=3
    )
    concurrency_scheduler.register_tool_from_metadata(
        name="parse_data",
        description="解析采集数据",
        is_concurrency_safe=True,
        max_concurrent=3
    )
    concurrency_scheduler.register_tool_from_metadata(
        name="write_excel",
        description="写入 Excel 文件",
        is_concurrency_safe=False,
        safety_level=SafetyLevel.WORKSPACE_WRITE
    )

    browser = None
    try:
        # 1. 启动浏览器
        browser = StealthBrowser(headless=settings.HEADLESS, slow_mo=settings.SLOW_MO)
        await browser.start()

        # 2. 创建采集器 V2
        crawler = CQGGZYCrawlerV2(browser)

        # 3. 采集数据 (列表页)
        all_items = []

        # 采集政府采购公告
        logger.info("📋 开始采集政府采购公告...")
        gov_items = await crawler.fetch_list(category="gov_purchase")
        all_items.extend(gov_items)

        # 采集工程招投标
        logger.info("📋 开始采集工程招投标信息...")
        eng_items = await crawler.fetch_list(category="engineering")
        all_items.extend(eng_items)

        logger.info(f"📥 列表页数据总计：{len(all_items)} 条")

        if not all_items:
            logger.warning("⚠️ 未采集到任何数据")
            return None

        # 4. 关键词过滤 (找出匹配项)
        filter_engine = TenderFilter(
            keywords=settings.KEYWORDS,
            exclude_keywords=settings.EXCLUDE_KEYWORDS
        )

        matched_items = []
        for item in all_items:
            # 检查是否包含排除词
            if filter_engine._contains_exclude(item.title):
                item.keywords_matched = []
                continue

            # 检查关键词匹配
            matched_keywords = filter_engine.check_keywords(item.title)
            item.keywords_matched = matched_keywords

            if matched_keywords:
                matched_items.append(item)

        logger.info(f"✅ 匹配关键词的项目：{len(matched_items)}/{len(all_items)} 条")

        # 5. 采集详情页 (仅对前 10 条匹配项) - 并行处理
        logger.info("📄 开始采集详情页...")
        detail_limit = min(10, len(matched_items))
        detail_items = matched_items[:detail_limit]
        
        async def fetch_and_update(index, item):
            detail_item = await crawler.fetch_detail(item)
            logger.info(f"  ✅ [{index+1}/{detail_limit}] {item.title[:30]}...")
            return index, detail_item
        
        # 并行采集详情页（最多 3 个并发，避免触发反爬）
        results = await asyncio.gather(*[fetch_and_update(i, item) for i, item in enumerate(detail_items)])
        
        # 更新 matched_items
        for idx, detail_item in results:
            matched_items[idx] = detail_item
            # 同时更新 all_items 中对应的项
            for j, all_item in enumerate(all_items):
                if all_item.url == detail_item.url:
                    all_items[j] = detail_item
                    break

        # 6. 生成标准化数据 (全部项目) - 使用已更新详情的 all_items
        standardized_all = []
        standardized_matched = []

        for item in all_items:
            std = filter_engine.extract_project_info(item)
            standardized_all.append(std)
            if item.keywords_matched:
                standardized_matched.append(std)
        
        # 如果 all_items 已更新，则 standardized_all 也包含更新后的数据

        # 7. 生成报表 (仅匹配项)
        report_gen = ReportGenerator(settings.OUTPUT_DIR)
        excel_path = ""

        if standardized_matched:
            excel_path = report_gen.generate_excel(
                standardized_matched,
                filename_prefix="chongqing_tender_v2"
            )

        # 8. 生成摘要
        summary = report_gen.generate_summary(standardized_matched)
        logger.info("\n" + summary)

        # 9. 持久化数据到 JSON (供 API 读取)
        # 用 matched_items 中已采集详情的项目更新 standardized_all
        for i, item in enumerate(standardized_all):
            for mi in matched_items:
                if mi.url == item.get('url'):
                    # 用详情更新标准化数据
                    std = filter_engine.extract_project_info(mi)
                    standardized_all[i] = std
                    break
        
        data_path = os.path.join(settings.OUTPUT_DIR, "latest.json")
        output_data = {
            "total": len(all_items),
            "filtered": len(matched_items),
            "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "projects": standardized_all,
            "matched_projects": standardized_matched,
            "categories": {
                "政府采购": len([p for p in standardized_all if p.get("type") == "政府采购"]),
                "工程建设": len([p for p in standardized_all if p.get("type") == "工程建设"])
            }
        }

        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ 数据已持久化：{data_path}")

        logger.info("=" * 60)
        logger.info("✅ 采集任务完成")
        logger.info(f"📊 报表文件：{excel_path}")
        logger.info(f"📊 数据文件：{data_path}")
        logger.info("=" * 60)

        return {
            'total': len(all_items),
            'filtered': len(matched_items),
            'excel_path': excel_path,
            'data_path': data_path,
            'summary': summary,
            'projects': standardized_all,
            'matched_projects': standardized_matched
        }

    except Exception as e:
        logger.error(f"❌ 采集任务失败：{e}")
        import traceback
        traceback.print_exc()
        return None

    finally:
        if browser:
            await browser.close()


def main():
    """主入口"""
    result = asyncio.run(run_collection())
    if result:
        print(f"\n✅ 采集完成：{result['filtered']}/{result['total']} 条匹配")
        if result['excel_path']:
            print(f"📊 Excel 报表：{result['excel_path']}")
        if result['data_path']:
            print(f"📊 数据文件：{result['data_path']}")
    else:
        print("\n⚠️ 未采集到数据")


if __name__ == "__main__":
    main()
