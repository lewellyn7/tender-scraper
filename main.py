"""
招投标采集系统 - 主入口
"""
import asyncio
from datetime import datetime, timedelta
from loguru import logger
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.browser import StealthBrowser
from app.crawlers.ccgp_crawler import CCGPCrawler
from app.utils.filter import TenderFilter
from app.utils.report import ReportGenerator
from config.settings import settings

async def run_collection():
    """执行一次完整的数据采集任务"""
    logger.info("=" * 50)
    logger.info("🚀 开始执行招投标信息采集任务")
    logger.info("=" * 50)
    
    browser = None
    try:
        # 1. 启动浏览器
        browser = StealthBrowser(
            headless=settings.HEADLESS,
            slow_mo=settings.SLOW_MO
        )
        await browser.start()
        
        # 2. 创建采集器
        crawler = CCGPCrawler(browser)
        
        # 3. 采集数据 (先测试 1 页)
        all_items = []
        
        # 采集采购公告
        notices = await crawler.fetch_notice_list(page_num=1)
        all_items.extend(notices)
        
        # 采集采购意向
        intentions = await crawler.fetch_intention_list(page_num=1)
        all_items.extend(intentions)
        
        logger.info(f"📥 原始数据总计：{len(all_items)} 条")
        
        if not all_items:
            logger.warning("⚠️ 未采集到任何数据")
            return None
        
        # 4. 过滤数据
        filter_engine = TenderFilter(
            keywords=settings.KEYWORDS,
            exclude_keywords=settings.EXCLUDE_KEYWORDS
        )
        
        filtered_items = filter_engine.filter_by_keywords(all_items)
        
        if not filtered_items:
            logger.info("✅ 无匹配关键词的项目")
            return None
        
        # 5. 生成报表
        report_gen = ReportGenerator(settings.OUTPUT_DIR)
        
        # 提取标准化信息
        standardized = [filter_engine.extract_project_info(item) for item in filtered_items]
        
        # 生成 Excel
        excel_path = report_gen.generate_excel(standardized, filename_prefix="chongqing_tender")
        
        # 生成摘要
        summary = report_gen.generate_summary(standardized)
        logger.info("\n" + summary)
        
        logger.info("=" * 50)
        logger.info("✅ 采集任务完成")
        logger.info("=" * 50)
        
        return {
            'total': len(all_items),
            'filtered': len(filtered_items),
            'excel_path': excel_path,
            'summary': summary,
            'projects': standardized
        }
        
    except Exception as e:
        logger.error(f"❌ 采集任务失败：{e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        if browser:
            await browser.close()

if __name__ == "__main__":
    # 本地测试运行
    result = asyncio.run(run_collection())
    
    if result:
        print(f"\n✅ 采集完成：{result['filtered']}/{result['total']} 条")
        if result['excel_path']:
            print(f"📊 报表文件：{result['excel_path']}")
