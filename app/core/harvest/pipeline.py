"""P0-4: 采集主流程 — 从 main.py 拆出
=========================================

负责:
- run_collection: 完整采集任务 (列表 → 详情 → 向量化 → 写 DB → 报表)

原 main.py:119-569 (451 行)
本模块是 PURE LIFT (纯搬移) — 行为 100% 等价, 仅调整 imports.

依赖:
- app.core.harvest.vectorize: _upsert_to_vector_store
- app.core.harvest.scheduler: _build_crawl_task
- app.core.harvest.smart_scheduler: SmartScheduler
- app.crawlers.cqggzy: CQGGZYCrawlerV2
- app.crawlers.ccgp: CCGPCrawlerV3 (默认停采)
- app.core.session_memory: SessionMemory
- app.core.browser: StealthBrowser
- app.utils.filter: TenderFilter
- app.utils.report: ReportGenerator
- app.services.vector_store: get_vector_store_indexed
"""
import asyncio
import json
import os
import time
from datetime import datetime, timedelta

from loguru import logger

from app.core.browser import StealthBrowser
from app.core.harvest.scheduler import _build_crawl_task
from app.core.harvest.smart_scheduler import CrawlTask, SmartScheduler, TaskStatus
from app.core.harvest.vectorize import _upsert_to_vector_store
from app.core.session_memory import SessionMemory, SessionMemoryConfig
from app.crawlers.ccgp import CCGPCrawlerV3
from app.crawlers.cqggzy import CQGGZYCrawlerV2
from app.crawlers.cqggzy_curl import CqggzyCurlCrawler  # 2026-06-24: CRAWLER_MODE=curl
from app.crawlers.fahcqmu import (
    FahcqmuCrawler, CATEGORIES as FAHC_CATEGORIES,
    tender_to_db_row as fahc_tender_to_db_row,
    collect_org_unit as fahc_collect_org_unit,
)
from app.database.db import get_db
from app.services.vector_store import get_vector_store_indexed
from app.utils.filter import TenderFilter
from app.utils.report import ReportGenerator
from config.settings import settings



# 采集源开关（2026-06-02 决策，与原 main.py 一致）
ENABLE_CCGP = False  # 设为 True 重新启用 CCGP 采集（需先修复 XHR 端点问题）
# 2026-06-25: 重医附一院开关 (默认开启, 如需停采置 False)
ENABLE_FAHCQMU = True


# ── 以下代码 100% 等价于 main.py:119-569，仅 imports 调整 ──────────────


async def run_collection():
    """执行一次完整的数据采集任务"""
    logger.info("=" * 60)
    logger.info("🚀 开始执行招投标信息采集任务 V3 (SmartScheduler)")
    logger.info(f"📡 目标网站: {settings.TARGET_URL}")
    logger.info("=" * 60)

    # 初始化 Session Memory
    session_memory = SessionMemory(SessionMemoryConfig(max_tokens=128000, compact_threshold=0.80))

    browser = None
    crawler = None  # 2026-06-24: 提前定义避免 finally 中未定义警告
    use_curl = os.getenv("CRAWLER_MODE", "playwright").lower() == "curl"
    try:
        logger.info(f"🔧 CRAWLER_MODE: {'curl (10x 加速)' if use_curl else 'playwright (默认)'}")
        if use_curl:
            # curl 模式: 无 browser, 直接用 CqggzyCurlCrawler
            crawler = CqggzyCurlCrawler(browser=None)
            ccgp_crawler = None
        else:
            # 1. 启动浏览器
            browser = StealthBrowser(headless=settings.HEADLESS, slow_mo=settings.SLOW_MO)
            await browser.start()

            # 2. 创建采集器 V2
            crawler = CQGGZYCrawlerV2(browser)
            # CCGP 采集器：仅在 ENABLE_CCGP=True 时创建（默认停采，2026-06-02 决策）
            ccgp_crawler = CCGPCrawlerV3(browser) if ENABLE_CCGP else None

        # 采集数据（9 个分类，并行）
        # 2026-06-18 修复：URL date=today + 列表 start_date=today（之前 date=3m URL 与 7d POST API 范围不一致）
        # 2026-06-05 修复：CQGGZY API 的 edt 是排他的（不含当天），end_date 需 +1 天才能采集当天数据
        today = datetime.now()
        start_date = today  # 今日模式：仅采集今天发布/更新的项目
        end_date = today + timedelta(days=1)
        all_items = []
        categories = [
            "engineering_notice",     # 招标公告
            "engineering_plan",       # 招标计划
            "engineering_qa",         # 答疑补遗
            "engineering_candidate",   # 中标候选人公示
            "engineering_result",    # 中标结果公示
            "engineering_terminate", # 终止公告
            "gov_purchase_notice",   # 采购公告
            "gov_purchase_change",    # 变更公告
            "gov_purchase_result",   # 采购结果公告
        ]

        logger.info(f"📋 开始采集 CQGGZY 9 个分类...")
        # 2026-06-03 修复：分页采集直到 API 返回 < 50 条（原代码只采第 1 页，丢失 50+ 之后的数据）
        async def _fetch_all_pages(category: str) -> list:
            items_all: list = []
            seen_urls: set = set()  # 2026-06-08 Bug 1 修复：跨 page 去重，list API 在多个 page 返回可能包含同一 url
            for page_num in range(1, 21):  # 最多 20 页（1000 条）安全保护
                items = await crawler.fetch_list(
                    category=category, page_num=page_num,
                    start_date=start_date, end_date=end_date,
                )
                for it in items:
                    url = getattr(it, "url", "") if not isinstance(it, dict) else it.get("url", "")
                    if url and url in seen_urls:
                        continue
                    if url:
                        seen_urls.add(url)
                    items_all.append(it)
                if len(items) < 50:
                    break
            return items_all

        tasks = [_fetch_all_pages(c) for c in categories]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for c, r in zip(categories, results):
            if isinstance(r, list):
                all_items.extend(r)
                logger.info(f"  {c}: {len(r)} 条")
            elif isinstance(r, Exception):
                logger.warning(f"  {c}: 采集异常 {r}")
        logger.info(f"📥 列表页数据总计：{len(all_items)} 条")

        # 过滤掉 CCGP-chongqing（仅保留 CQGGZY）
        # 2026-06-02 决策：CCGP 不再进行采集，下方为双重保险
        # 1. 列表页 categories 中不包含 CCGP URL（已实现）
        # 2. 即便混入 CCGP 链接也过滤掉（防止外部数据源）
        all_items = [
            item for item in all_items
            if not (hasattr(item, 'source_url') and item.source_url and 'ccgp' in item.source_url)
        ]
        logger.info(f"📥 列表页数据（过滤CCGP后）：{len(all_items)} 条")

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

        # 5. 使用 SmartScheduler 并行采集详情页（来源均衡采样）
        # 2026-06-02 决策：CCGP 停采后此处只处理 CQGGZY，不再有 CCGP 任务
        # 2026-06-03 决策：扩大 detail_limit 30→100，确保大部分匹配项目有正文（列表 API 不再返回 content）
        # 2026-06-05 决策：再扩大到 300，覆盖 3684 匹配项目中的绝大部分（每周期 16min）
        detail_limit = min(300, len(matched_items))
        # 2026-06-08 Bug 1 修复：detail_items[:300] 是按列表 API newid 顺序取的，
        # 列表 API 的 newid 排序 ≠ publish_date 排序，导致 6-8 的新数据都在 [1013-7965] 位置、
        # 从未进入前 300 个 SmartScheduler 任务。需要先按 publish_date 预排序全部 matched_items，
        # 再截前 detail_limit 个。
        def _sort_key(item):
            pd = getattr(item, "publish_date", None)
            if pd is None:
                return (1, 0)  # 未知日期 → 降序底
            return (0, -pd.timestamp())  # 有日期 → 按时间降序（负值倒置）

        # 来源均衡 + publish_date 降序（仅计算一遍）
        from collections import defaultdict
        all_sorted = sorted(matched_items, key=_sort_key)
        by_source = defaultdict(list)
        for item in all_sorted:
            src = "ccgp" if (hasattr(item, "source_url") and "ccgp" in (item.source_url or "")) else "cqggzy"
            by_source[src].append(item)
        sources = list(by_source.keys())
        max_per_source = max(5, detail_limit // len(sources)) if sources else detail_limit
        # 轮询：首次从每源取 1 个，再从每源取下一个，... 直到每源达到 max_per_source
        detail_items = []
        ptrs = {src: 0 for src in sources}
        taken = {src: 0 for src in sources}
        while len(detail_items) < detail_limit:
            progressed = False
            for src in sources:
                if taken[src] >= max_per_source:
                    continue
                if ptrs[src] >= len(by_source[src]):
                    continue
                detail_items.append(by_source[src][ptrs[src]])
                ptrs[src] += 1
                taken[src] += 1
                progressed = True
                if len(detail_items) >= detail_limit:
                    break
            if not progressed:
                break
        logger.info(
            f"  📊 预排序+来源均衡：matched_items ({len(matched_items)}) → 按 publish_date 降序后取前 {len(detail_items)}"
        )

        if detail_items:
            logger.info(f"📄 使用 SmartScheduler 并行采集 {len(detail_items)} 个详情页...")

            # 2026-06-08 Bug 1-C 修复: 24h 漏采回放
            # 1. SELECT 最近 7 天发布 且 content_preview 为空 且 本轮未采集的 URL
            # 2. 插入 detail_items 头部 (高优先级) + 去重
            # 3. 避免: 每次重抓会导致调度变慢, 只选 (今天 0 点后发布 + 空 content)
            try:
                from sqlalchemy import text as sa_text, create_engine
                from app.database.db import DATABASE_URL
                tmp_engine = create_engine(DATABASE_URL)
                with tmp_engine.connect() as conn:
                    pending = conn.execute(sa_text("""
                        SELECT id, url, title, publish_date
                        FROM projects_cqggzy
                        WHERE publish_date >= CURRENT_DATE - INTERVAL '7 days'
                          AND (content_preview IS NULL OR length(content_preview) = 0)
                          AND url NOT IN (
                            SELECT url FROM projects_cqggzy
                            WHERE scraped_at > NOW() - INTERVAL '24 hours'
                              AND length(content_preview) > 0
                          )
                        ORDER BY publish_date DESC
                        LIMIT 50
                    """)).fetchall()
                tmp_engine.dispose()
                if pending:
                    existing_urls = {it.url for it in detail_items}
                    new_reprocess = []
                    from app.models.tender import TenderInfo
                    for r in pending:
                        pid, url, title, pd = r[0], r[1], r[2], r[3]
                        if url in existing_urls:
                            continue
                        ti = TenderInfo(
                            url=url,
                            title=title or "",
                            publish_date=pd,
                            source_url="",
                        )
                        new_reprocess.append(ti)
                        existing_urls.add(url)
                    if new_reprocess:
                        logger.info(
                            f"  🔁 24h 漏采回放: 添加 {len(new_reprocess)} 条待补采"
                        )
                        # 插到头部 (优先调)
                        detail_items = new_reprocess + list(detail_items)
            except Exception as e:
                logger.warning(f"  ⚠️ 24h 漏采回放查询失败: {e}")
            # DEBUG: 看预排序后前 5 个 task 的 publish_date + 后 5 个的 publish_date
            for i in [0, 1, 2, 3, 4, -5, -4, -3, -2, -1]:
                it = detail_items[i]
                pd = getattr(it, "publish_date", None)
                logger.info(
                    f"    [DEBUG] detail_items[{i}] publish_date={pd} title={it.title[:30]}"
                )

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
                # 2026-06-12 P2 优化: 招标计划表跳过详情 fetch
                # 原因: 招标计划表 CQGGZY 上没有详情正文 (页面直接显示计划表, 无 SPA 详情页),
                #   抓详情纯浪费 5-8s/条, 11883 条 × 5s = 16.5h 周期
                # 答疑补遗 / 终止公告: 有详情正文, **保留 fetch**
                # 改: 列表阶段已采集的字段足够, 跳过 fetch
                _title = (item.title or "").strip()
                if _title.endswith("招标计划表"):
                    logger.debug(f"  跳过详情 fetch (招标计划表): {_title[:30]}")
                    return True
                # 根据来源选择采集器
                # 2026-06-02：CCGP 停采后 ccgp_crawler=None，理论上不会调用（任务已被过滤）
                # 加 None check 双重保险
                if task.source == "ccgp":
                    if ccgp_crawler is None:
                        logger.warning(f"⚠️ CCGP 任务 {task.task_id} 被跳过（CCGP 采集已停用，ENABLE_CCGP=False）")
                        return False
                    detail_crawler = ccgp_crawler
                else:
                    detail_crawler = crawler
                # 记录采集指标（HealthMonitor）
                t0 = time.monotonic()
                try:
                    detail_item = await detail_crawler.fetch_detail(item)
                    # 更新原始 matched_items 中的对应项（按 URL 而非对象引用）
                    for mi in matched_items:
                        if mi.url == item.url:  # 用原始 URL 匹配（task.item_map 已建立）
                            mi.full_content = detail_item.full_content
                            mi.content_preview = detail_item.content_preview
                            mi.budget = detail_item.budget
                            mi.deadline = detail_item.deadline
                            mi.contact_info = detail_item.contact_info
                            mi.attachments = detail_item.attachments
                            # 2026-06-09 修复: 详情阶段透传 project_no, 否则 Bug 1 修复无效
                            mi.project_no = detail_item.project_no
                            break
                    # 同时更新 all_items
                    for ai in all_items:
                        if ai.url == item.url:
                            ai.full_content = detail_item.full_content
                            ai.content_preview = detail_item.content_preview
                            ai.budget = detail_item.budget
                            ai.deadline = detail_item.deadline
                            ai.contact_info = detail_item.contact_info
                            ai.attachments = detail_item.attachments
                            # 2026-06-09 修复: 详情阶段透传 project_no
                            ai.project_no = detail_item.project_no
                            break
                    # 2026-06-08 P1 修复: 详情成功立即写 DB, 避免 SIGTERM 丢掉全部 detail
                    # (旧代码依赖 main.py:426 在 schedule 结束后一次性 upsert, 进程被杀则丢失)
                    # 2026-06-12 P0 修复: 详情阶段写 6 字段 (full_content / content_preview /
                    #   info_type / publish_date / project_no / keywords_matched)
                    # 修复 6-10 19:53 类型 BUG: 当时只写 full_content+content_preview, 导致
                    #   info_type/publish_date/project_no 仍空, 关键词未匹配
                    if detail_item.full_content or detail_item.info_type or detail_item.publish_date or detail_item.project_no:
                        try:
                            from app.database.db import get_db
                            from app.utils.clean_noise import make_content_preview
                            from app.services.keywords_service import KeywordsService
                            preview = detail_item.content_preview or make_content_preview(
                                detail_item.full_content or detail_item.title,
                                detail_item.title
                            )
                            # 跑关键词匹配 (取 matched include, exclude 命中则清空)
                            kw_str = ""
                            if detail_item.full_content or detail_item.title:
                                text = (detail_item.title or "") + " " + (detail_item.full_content or "")
                                match_result = KeywordsService().match(text)
                                if match_result:
                                    include = match_result.get("include", [])
                                    exclude = match_result.get("exclude", [])
                                    # exclude 命中 → 整条不匹配
                                    if not exclude and include:
                                        kw_str = ", ".join([k["keyword"] for k in include])
                            # publish_date 转字符串 (DetailItem 是 date / datetime 混合)
                            pd_str = ""
                            if detail_item.publish_date:
                                pd_str = detail_item.publish_date.strftime("%Y-%m-%d") if hasattr(detail_item.publish_date, "strftime") else str(detail_item.publish_date)
                            get_db().update_detail_fields(item.url, {
                                "full_content": detail_item.full_content,
                                "content_preview": preview,
                                "info_type": detail_item.info_type,
                                "publish_date": pd_str,
                                "project_no": detail_item.project_no,
                                "keywords_matched": kw_str,
                            })
                        except Exception as db_e:
                            logger.warning(f"  ⚠️ 详情写 DB 失败 [{task.task_id}]: {db_e}")
                    # 记录成功
                    try:
                        from app.services.health_monitor import get_health_monitor
                        latency_ms = (time.monotonic() - t0) * 1000
                        get_health_monitor().record_crawl_ok(latency_ms)
                    except Exception:
                        pass
                    return True
                except Exception as e:
                    logger.warning(f"  ⚠️ 详情采集失败 [{task.task_id}]: {e}")
                    try:
                        latency_ms = (time.monotonic() - t0) * 1000
                        get_health_monitor().record_crawl_fail(latency_ms)
                    except Exception:
                        pass
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

        # 11. 写入 PostgreSQL（projects_cqggzy 表）
        try:
            db = get_db()
            db.upsert_projects(standardized_all)
            logger.info(f"📦 PostgreSQL 写入：{len(standardized_all)} 条")
        except Exception as e:
            logger.error(f"PostgreSQL 写入失败: {e}")

        # 11.5 中标结果解析入库（为政府采购 / 工程招投标 排名分析提供数据基础）
        # 2026-06-18 新增: 增量解析本次采集的中标类公告, 写入 bid_results 表
        try:
            from app.utils.bid_parser import parse_bid_results
            import psycopg2
            cur = db._get_conn().cursor()
            # 取本次采集（近 1 小时）中标类项目, 拼带 project_id 的 bid_results rows
            cur.execute("""
                SELECT id, url, info_type, full_content, publish_date
                FROM projects_cqggzy
                WHERE info_type IN ('采购结果公告', '中标候选人公示', '中标结果公示')
                  AND full_content IS NOT NULL
                  AND LENGTH(full_content) > 100
                  AND scraped_at > NOW() - INTERVAL '2 hour'
            """)
            bid_rows = []
            for proj_id, url, info_type, full_content, pub_date in cur.fetchall():
                parsed = parse_bid_results(
                    content=full_content,
                    info_type=info_type,
                    category='',
                    project_id=proj_id,
                    url=url,
                    publish_date=pub_date,
                )
                bid_rows.extend(parsed)
            if bid_rows:
                written = db.upsert_bid_results(bid_rows)
                logger.info(f"🏆 中标结果解析入库: {written} 条 (解析 {len(bid_rows)} 行)")
            cur.close()
        except Exception as e:
            logger.warning(f"中标结果解析入库失败（不影响采集）: {e}")

        # 12. 截标日期 T-3 提醒检查
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
        # 2026-06-24: curl 模式关闭 aiohttp session
        if use_curl and crawler is not None:
            try:
                await crawler.close()
            except Exception:
                pass





# ============================================================================
# 2026-06-25: 重医附一院采集 (PR #39 feat/fahcqmu-crawler)
# ============================================================================
# 独立函数, 不影响 CQGGZY pipeline. 触发方式:
#   - 环境变量: FAHCQMU_RUN=1 python -m main
#   - 或: python -c "import asyncio; from app.core.harvest.pipeline import run_fahcqmu_collection; asyncio.run(run_fahcqmu_collection())"
# 调度: 建议 21:00 cron 单独跑, 与 CQGGZY 错开
# ============================================================================

async def run_fahcqmu_collection(detail_limit: int = 300):
    """执行重医附一院采集任务.

    流程:
    1. 创建 aiohttp session + FahcqmuCrawler
    2. fetch_all_lists() — 7 类并行翻页
    3. 关键词过滤 (复用 TenderFilter)
    4. fetch_details_parallel() — 并发详情 (detail_limit 上限, 默认 300)
    5. upsert_projects_fahcqmu() — 批量写库
    6. 生成报表 (复用 ReportGenerator)
    7. 写 latest.json (独立 fahcqmu_latest.json, 不覆盖 cqggzy 的)

    Args:
        detail_limit: 详情采集上限 (默认 300, 与 CQGGZY 一致)

    Returns:
        dict: {total, filtered, excel_path, data_path, summary, projects, matched_projects}
        或 None (失败)
    """
    if not ENABLE_FAHCQMU:
        logger.warning("⚠️ ENABLE_FAHCQMU=False, 跳过 fahcqmu 采集")
        return None

    logger.info("=" * 60)
    logger.info("🏥 重医附一院采集 (PR #39)")
    logger.info(f"   7 个分类: {[c.description for c in FAHC_CATEGORIES]}")
    logger.info("=" * 60)

    crawler = None
    try:
        # 1. 创建 crawler (内部创建 aiohttp session, Cookie visited=1 已设)
        crawler = FahcqmuCrawler(delay=0.3, max_pages=100)
        async with crawler:
            # 2. 列表阶段 (并行 7 类)
            logger.info("📋 阶段 1/4: 列表采集 (/p/N 翻页)")
            all_items = await crawler.fetch_all_lists()
            logger.info(f"📥 列表合计 (去重后): {len(all_items)} 条")

            if not all_items:
                logger.warning("⚠️ 未采集到任何数据, 跳过详情阶段")
                return {
                    'total': 0, 'filtered': 0,
                    'excel_path': '', 'data_path': '',
                    'summary': '本次未采集到任何数据',
                    'projects': [], 'matched_projects': []
                }

            # 3. 关键词过滤 (复用 TenderFilter, 与 CQGGZY 一致)
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
            logger.info(f"✅ 关键词匹配: {len(matched_items)}/{len(all_items)} 条")

            # 4. 详情阶段 (并发, 限 detail_limit)
            actual_detail_limit = min(detail_limit, len(matched_items) if matched_items else len(all_items))
            if matched_items:
                detail_targets = matched_items[:actual_detail_limit]
            else:
                # 没匹配也采前 N 条详情 (回填用, 避免空白期)
                detail_targets = all_items[:actual_detail_limit]

            if detail_targets:
                logger.info(f"📄 阶段 2/4: 详情采集 ({len(detail_targets)} 条, 并发 5)")
                # 按 publish_date 降序排 (新数据优先)
                def _sort_key(item):
                    pd = getattr(item, "publish_date", None)
                    if pd is None:
                        return (1, 0)
                    try:
                        ts = pd.timestamp() if hasattr(pd, "timestamp") else 0
                    except Exception:
                        ts = 0
                    return (0, -ts)
                detail_targets = sorted(detail_targets, key=_sort_key)
                detailed = await crawler.fetch_details_parallel(detail_targets, concurrency=5)
                ok = sum(1 for it in detailed if it.full_content)
                logger.info(f"  ✅ 详情完成: {ok}/{len(detailed)} 有正文")

                # 把详情写回 all_items / matched_items (by URL)
                url_to_detailed = {it.url: it for it in detailed}
                for lst in (all_items, matched_items):
                    for it in lst:
                        if it.url in url_to_detailed:
                            d = url_to_detailed[it.url]
                            it.full_content = d.full_content
                            it.content_preview = d.content_preview
                            it.publish_date = d.publish_date or it.publish_date
                            it.publish_date_raw = d.publish_date_raw or it.publish_date_raw

            # 5. 持久化到 PostgreSQL (projects_fahcqmu)
            logger.info("📦 阶段 3/4: PostgreSQL upsert (projects_fahcqmu)")
            try:
                db = get_db()
                rows = []
                for item in all_items:
                    org_unit = fahc_collect_org_unit(item)
                    rows.append(fahc_tender_to_db_row(item, org_unit))
                if rows:
                    db.upsert_projects_fahcqmu(rows)
                    logger.info(f"  ✅ upsert: {len(rows)} 条")
            except Exception as e:
                logger.error(f"  ❌ PostgreSQL 写入失败: {e}")
                import traceback; traceback.print_exc()

            # 6. 生成报表 (复用 ReportGenerator, 写独立文件)
            logger.info("📊 阶段 4/4: 报表 + JSON 持久化")
            standardized_all = []
            standardized_matched = []
            for item in all_items:
                std = filter_engine.extract_project_info(item)
                std["org_unit"] = fahc_collect_org_unit(item)  # 加 org_unit 到输出
                std["info_type"] = item.info_type
                std["business_type"] = item.business_type or "医院采购"
                standardized_all.append(std)
                if item.keywords_matched:
                    standardized_matched.append(std)

            report_gen = ReportGenerator(settings.OUTPUT_DIR)
            excel_path = ""
            if standardized_matched:
                excel_path = report_gen.generate_excel(
                    standardized_matched,
                    filename_prefix="fahcqmu_tender_v1"
                )

            summary = report_gen.generate_summary(standardized_matched)
            logger.info("\n" + summary)

            # 7. 独立 JSON 文件 (不覆盖 cqggzy 的 latest.json)
            data_path = os.path.join(settings.OUTPUT_DIR, "fahcqmu_latest.json")
            output_data = {
                "total": len(all_items),
                "filtered": len(matched_items),
                "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": "fahcqmu",
                "projects": standardized_all,
                "matched_projects": standardized_matched,
                "categories": {
                    cat.info_type: sum(1 for it in all_items if it.info_type == cat.info_type)
                    for cat in FAHC_CATEGORIES
                },
                "org_units": {
                    "信息数据处": sum(1 for it in all_items if fahc_collect_org_unit(it) == "信息数据处"),
                    "总务处":     sum(1 for it in all_items if fahc_collect_org_unit(it) == "总务处"),
                    "其他":       sum(1 for it in all_items if fahc_collect_org_unit(it) == "其他"),
                },
            }
            with open(data_path, "w", encoding="utf-8") as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ 数据已持久化: {data_path}")

            logger.info("=" * 60)
            logger.info("✅ fahcqmu 采集任务完成")
            logger.info(f"📊 报表文件: {excel_path}")
            logger.info(f"📊 数据文件: {data_path}")
            logger.info("=" * 60)

            return {
                'total': len(all_items),
                'filtered': len(matched_items),
                'excel_path': excel_path,
                'data_path': data_path,
                'summary': summary,
                'projects': standardized_all,
                'matched_projects': standardized_matched,
            }

    except Exception as e:
        logger.error(f"❌ fahcqmu 采集任务失败: {e}")
        import traceback; traceback.print_exc()
        return None
