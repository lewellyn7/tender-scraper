"""招投标采集系统 - 主入口 V3
更新：集成 SmartScheduler 动态优先级调度，替代手动 asyncio.gather
"""
import asyncio
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loguru import logger

from app.core.browser import StealthBrowser
from app.core.harvest.smart_scheduler import CrawlTask, SmartScheduler, TaskStatus
from app.core.session_memory import SessionMemory, SessionMemoryConfig
from app.crawlers.cqggzy import CQGGZYCrawlerV2
from app.services.vector_store import get_vector_store
from app.utils.filter import TenderFilter
from app.utils.report import ReportGenerator
from config.settings import settings

# 配置日志
logger.add(sys.stderr, format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}", level="INFO", colorize=False)


def _build_vector_text(p: dict) -> str:
    """构建用于向量化的文本（拼接多字段，控制长度）"""
    parts = [
        p.get("title", ""),
        p.get("type", ""),
        p.get("business_type", ""),
        p.get("info_type", ""),
        p.get("project_overview", ""),
        p.get("bidder_requirements", ""),
    ]
    # content_preview 含实际内容摘要，补充向量语义（尤其是 project_overview 为空时）
    content_preview = p.get("content_preview", "") or ""
    if content_preview:
        parts.append(content_preview[:500])
    text = " | ".join(x for x in parts if x)
    # MiniLM max_tokens=256, 约1000 tokens，截断至2000字符
    return text[:2000] if text else p.get("title", "")


def _upsert_to_vector_store(projects: list):
    """将采集结果批量入库向量库（失败不影响主流程）"""
    try:
        docs = [
            {
                "id": f"tender_{p.get('publish_date', 'unknown')}_{i}",
                "text": _build_vector_text(p),
                "metadata": {
                    "url": p.get("url"),
                    "title": p.get("title"),
                    "type": p.get("type"),
                    "budget": p.get("budget"),
                    "deadline": p.get("deadline"),
                    "region": p.get("region"),
                    "publish_date": p.get("publish_date"),
                    "keywords_matched": p.get("keywords_matched"),
                }
            }
            for i, p in enumerate(projects)
        ]
        vs = get_vector_store()
        result = vs.upsert_documents(docs)
        logger.info(f"向量入库: {result['inserted']} 条，backend={result['backend']}")
    except Exception as e:
        logger.warning(f"向量入库失败（不影响主流程）: {e}")


def _build_crawl_task(item, index: int) -> CrawlTask:
    """将 TenderInfo 映射为 CrawlTask（用于 SmartScheduler）"""
    source = "cqggzy"
    if hasattr(item, "source_url") and item.source_url:
        if "ccgp" in item.source_url:
            source = "ccgp"
        elif "ggzy" in item.source_url:
            source = "cqggzy"

    # 静态优先级：预算越高优先级越高（归一化到 1-10）
    priority_static = 5
    if hasattr(item, "budget") and item.budget:
        try:
            budget_str = item.budget.replace("万元", "").replace("元", "").replace(",", "").strip()
            budget_val = float(budget_str)
            priority_static = min(10, max(1, int(budget_val / 500)))  # 每500万1分，上限10
        except (ValueError, AttributeError):
            pass

    return CrawlTask(
        task_id=f"detail_{index}_{item.url[:40]}",
        source=source,
        url=item.url,
        info_type=getattr(item, "info_type", "招标公告"),
        region="重庆",
        deadline=getattr(item, "deadline", None),
        keywords=getattr(item, "keywords_matched", []),
        priority_static=priority_static,
    )


async def run_collection():
    """执行一次完整的数据采集任务"""
    logger.info("=" * 60)
    logger.info("🚀 开始执行招投标信息采集任务 V3 (SmartScheduler)")
    logger.info(f"📡 目标网站: {settings.TARGET_URL}")
    logger.info("=" * 60)

    # 初始化 Session Memory
    session_memory = SessionMemory(SessionMemoryConfig(max_tokens=128000, compact_threshold=0.80))

    browser = None
    try:
        # 1. 启动浏览器
        browser = StealthBrowser(headless=settings.HEADLESS, slow_mo=settings.SLOW_MO)
        await browser.start()

        # 2. 创建采集器 V2
        crawler = CQGGZYCrawlerV2(browser)

        # 3. 采集数据 (列表页，并行两路)
        all_items = []

        logger.info("📋 开始采集政府采购公告 + 工程招投标（并行）...")
        gov_items, eng_items = await asyncio.gather(
            crawler.fetch_list(category="gov_purchase"),
            crawler.fetch_list(category="engineering"),
        )
        all_items.extend(gov_items)
        all_items.extend(eng_items)

        logger.info(f"📥 列表页数据总计：{len(all_items)} 条（政府采购 {len(gov_items)} 条，工程招投标 {len(eng_items)} 条）")

        if not all_items:
            logger.warning("⚠️ 未采集到任何数据")
            return None

        # 4. 关键词过滤
        filter_engine = TenderFilter(
            keywords=settings.KEYWORDS,
            exclude_keywords=settings.EXCLUDE_KEYWORDS
        )

        matched_items = []
        for item in all_items:
            if filter_engine._contains_exclude(item.title):
                item.keywords_matched = []
                continue
            matched_keywords = filter_engine.check_keywords(item.title)
            item.keywords_matched = matched_keywords
            if matched_keywords:
                matched_items.append(item)

        logger.info(f"✅ 匹配关键词的项目：{len(matched_items)}/{len(all_items)} 条")

        # 5. 使用 SmartScheduler 并行采集详情页
        detail_limit = min(10, len(matched_items))
        detail_items = matched_items[:detail_limit]

        if detail_items:
            logger.info(f"📄 使用 SmartScheduler 并行采集 {len(detail_items)} 个详情页...")

            # 构建 CrawlTask 列表
            crawl_tasks = [_build_crawl_task(item, i) for i, item in enumerate(detail_items)]

            # URL → TenderInfo 映射（用于 crawler_fn 回查）
            task_item_map = {task.url: item for task, item in zip(crawl_tasks, detail_items)}
            # task_id → TenderInfo 映射
            task_id_item_map = {task.task_id: item for task, item in zip(crawl_tasks, detail_items)}

            # 创建 SmartScheduler（最大并发 3，避免触发反爬）
            scheduler = SmartScheduler(max_concurrent=settings.DETAIL_MAX_CONCURRENT)

            # 注册全部任务（按动态优先级排序）
            priorities = await scheduler.register_batch(crawl_tasks)
            logger.info(f"  优先级范围：{max(priorities):.4f} ~ {min(priorities):.4f}")

            # 定义 crawler 函数：SmartScheduler 调用此函数处理每个任务
            async def crawler_fn(task: CrawlTask) -> bool:
                item = task_id_item_map.get(task.task_id)
                if item is None:
                    return False
                try:
                    detail_item = await crawler.fetch_detail(item)
                    # 更新原始 matched_items 中的对应项
                    for mi in matched_items:
                        if mi.url == detail_item.url:
                            # 复制详情字段
                            mi.full_content = detail_item.full_content
                            mi.content_preview = detail_item.content_preview
                            mi.budget = detail_item.budget
                            mi.deadline = detail_item.deadline
                            mi.contact_info = detail_item.contact_info
                            mi.attachments = detail_item.attachments
                            break
                    # 同时更新 all_items
                    for ai in all_items:
                        if ai.url == detail_item.url:
                            ai.full_content = detail_item.full_content
                            ai.content_preview = detail_item.content_preview
                            ai.budget = detail_item.budget
                            ai.deadline = detail_item.deadline
                            ai.contact_info = detail_item.contact_info
                            ai.attachments = detail_item.attachments
                            break
                    return True
                except Exception as e:
                    logger.warning(f"  ⚠️ 详情采集失败 [{task.task_id}]: {e}")
                    return False

            # 执行调度（自动控制并发 + 自适应间隔）
            results = await scheduler.schedule(crawler_fn)
            succeeded = results.get("succeeded", 0)
            failed = results.get("failed", 0)
            skipped = results.get("skipped", 0)
            logger.info(f"  ✅ 详情采集完成：成功 {succeeded} / 失败 {failed} / 跳过 {skipped}")

        # 6. 生成标准化数据
        standardized_all = []
        standardized_matched = []

        for item in all_items:
            std = filter_engine.extract_project_info(item)
            standardized_all.append(std)
            if item.keywords_matched:
                standardized_matched.append(std)

        # 7. 生成报表 (仅匹配项)
        report_gen = ReportGenerator(settings.OUTPUT_DIR)
        excel_path = ""

        if standardized_matched:
            excel_path = report_gen.generate_excel(
                standardized_matched,
                filename_prefix="chongqing_tender_v3"
            )

        # 8. 生成摘要
        summary = report_gen.generate_summary(standardized_matched)
        logger.info("\n" + summary)

        # 9. 持久化数据到 JSON
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

        # 10. 向量库入库（语义检索基础设施）
        if standardized_matched:
            _upsert_to_vector_store(standardized_matched)

        # 11. 截标日期 T-3 提醒检查
        try:
            from app.utils.notifications import get_notif_manager
            nm = get_notif_manager()
            sent = await nm.check_deadline_alerts(days=3)
            if sent:
                logger.info(f"📬 截标提醒已发送 {len(sent)} 条")
        except Exception as e:
            logger.warning(f"截标提醒检查失败（不影响采集）: {e}")

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
