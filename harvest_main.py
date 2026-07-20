#!/usr/bin/env python3
"""采集任务统一入口 — 支持多站点采集

用法:
    python harvest_main.py run --source cqggzy --keywords 智能化:AI --days 7
    python harvest_main.py run --source ccgp --info-type 采购公告
    python harvest_main.py run --source fahcqmu
    python harvest_main.py run --source all
    python harvest_main.py list-sources

支持的 --source:
    cqggzy  — 重庆市公共资源交易网（政府采购 + 工程建设）
    ccgp    — 重庆市政府采购网（采购意向/公告/结果公告）
    fahcqmu — 重庆医科大学附属第一医院 (信息数据处 + 总务处 + 其他)
    all     — 同时采集以上所有站点
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loguru import logger

from app.core.browser import StealthBrowser
from app.crawlers.ccgp import CCGPCrawlerV3
from app.crawlers.cqggzy import CQGGZYCrawlerV2
from app.utils.filter import TenderFilter
from app.utils.report import ReportGenerator

# ─── 日志配置 ────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logger.add(LOG_DIR / "harvest.log", rotation="1 day", retention="7 days", level="INFO")

# ─── 默认配置 ────────────────────────────────────────────────
DEFAULT_KEYWORDS = ["智能化", "AI", "人工智能", "智能体", "大模型", "智慧", "数字化", "信息化", "音视频"]
DEFAULT_EXCLUDE = ["流标", "终止", "废标", "中标公告", "成交公告", "结果公告"]
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


# ─── 采集器工厂 ──────────────────────────────────────────────

def make_crawler(source: str, browser: StealthBrowser):
    """根据 source 名称创建对应爬虫实例"""
    factories = {
        "cqggzy": CQGGZYCrawlerV2,
        "ccgp": CCGPCrawlerV3,
    }
    if source not in factories:
        raise ValueError(f"未知数据源: {source}，可用: {list(factories.keys())}")
    return factories[source](browser)


# ─── 采集流程 ────────────────────────────────────────────────

async def run_cqggzy(keywords, exclude_kw, days, headless, slow_mo):
    """采集重庆市公共资源交易网"""
    browser = None
    try:
        browser = StealthBrowser(headless=headless, slow_mo=slow_mo)
        await browser.start()
        crawler = CQGGZYCrawlerV2(browser)
        all_items = []

        for category in ["gov_purchase", "engineering"]:
            label = "政府采购" if category == "gov_purchase" else "工程建设"
            logger.info(f"📋 开始采集 [{label}]...")
            items = await crawler.fetch_lists_parallel(category=category, pages=list(range(1, 4)))
            all_items.extend(items)
            logger.info(f"  获取 {len(items)} 条")

        return await _process_results(browser, crawler, all_items, keywords, exclude_kw, "cqggzy")
    finally:
        if browser:
            await browser.close()


async def run_ccgp(info_type, keywords, exclude_kw, headless, slow_mo):
    """采集重庆市政府采购网"""
    browser = None
    try:
        browser = StealthBrowser(headless=headless, slow_mo=slow_mo)
        await browser.start()
        crawler = CCGPCrawlerV3(browser)
        all_items = []

        info_types = [info_type] if info_type else ["采购意向", "采购公告", "结果公告"]
        for itype in info_types:
            logger.info(f"📋 开始采集 [{itype}]...")
            items = await crawler.fetch_list(info_type=itype, page_num=1)
            all_items.extend(items)
            logger.info(f"  获取 {len(items)} 条")

        return await _process_results(browser, crawler, all_items, keywords, exclude_kw, "ccgp")
    finally:
        if browser:
            await browser.close()


async def run_fahcqmu(keywords, exclude_kw):
    """采集重医附一院 (信息数据处 + 总务处 + 其他).

    2026-06-25 新增 (PR #39). 不需 Playwright (Curl 模式).
    """
    from app.core.harvest.pipeline import run_fahcqmu_collection
    # 直接调用独立函数, 复用 TenderFilter (settings.KEYWORDS)
    result = await run_fahcqmu_collection(detail_limit=300)
    # 2026-07-21 修: run_fahcqmu_collection 不返回 source 字段, 而 cqggzy/ccgp 的
    # _process_results 都会返回 {"source": ...}, exit handler (line 225) 统一依赖
    # result["source"]. 补齐 shape, 避免 KeyError (非致命但污染 exit log).
    if result is None:
        return None
    result.setdefault("source", "fahcqmu")
    return result


async def _process_results(browser, crawler, all_items, keywords, exclude_kw, source):
    """通用结果处理：过滤 → 详情采集 → 报表生成"""
    logger.info(f"📥 总计获取：{len(all_items)} 条")

    if not all_items:
        logger.warning("⚠️ 未采集到任何数据")
        return None

    # 关键词过滤
    flt = TenderFilter(keywords=keywords, exclude_keywords=exclude_kw)
    matched = []
    for item in all_items:
        if flt._contains_exclude(item.title.lower()):
            item.keywords_matched = []
            continue
        mk = flt.check_keywords(item.title)
        item.keywords_matched = mk
        if mk:
            matched.append(item)

    logger.info(f"✅ 关键词匹配：{len(matched)}/{len(all_items)} 条")

    # 详情页采集（全部匹配项，限制并发 3）
    if matched:
        logger.info(f"📄 开始采集详情页（{len(matched)} 条）...")
        # 使用基类通用批量采集方法
        matched = await crawler.fetch_details_batch(
            matched, max_concurrent=3
        )

    # 标准化输出
    standardized = [flt.extract_project_info(item) for item in matched]

    # 生成报表
    rgen = ReportGenerator(str(OUTPUT_DIR))
    excel_path = rgen.generate_excel(standardized, f"{source}_tender") if standardized else ""

    summary = rgen.generate_summary(standardized) if standardized else "无匹配数据"

    # 持久化 JSON
    data_path = OUTPUT_DIR / f"{source}_latest.json"
    output_data = {
        "source": source,
        "total": len(all_items),
        "filtered": len(matched),
        "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "matched_projects": standardized,
    }
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    logger.info(f"\n{summary}")
    logger.info("=" * 60)
    logger.info(f"✅ 采集完成：{len(matched)}/{len(all_items)} 条匹配")
    logger.info(f"📊 Excel：{excel_path}")
    logger.info(f"📊 JSON：{data_path}")
    logger.info("=" * 60)

    return {
        "source": source,
        "total": len(all_items),
        "filtered": len(matched),
        "excel_path": excel_path,
        "data_path": str(data_path),
        "summary": summary,
        "matched_projects": standardized,
    }


# ─── CLI 命令 ────────────────────────────────────────────────

def cmd_run(args):
    """执行采集任务"""
    keywords = args.keywords.split(":") if args.keywords else DEFAULT_KEYWORDS
    exclude_kw = args.exclude.split(":") if args.exclude else DEFAULT_EXCLUDE

    logger.info("=" * 60)
    logger.info(f"🚀 采集任务启动 | source={args.source} | keywords={keywords}")
    logger.info("=" * 60)

    async def do_run():
        if args.source == "all":
            results = []
            for src in ["cqggzy", "ccgp", "fahcqmu"]:
                logger.info(f"\n{'='*40} 站点: {src} {'='*40}")
                if src == "cqggzy":
                    r = await run_cqggzy(keywords, exclude_kw, args.days, not args.visible, args.slow_mo)
                elif src == "ccgp":
                    r = await run_ccgp(args.info_type, keywords, exclude_kw, not args.visible, args.slow_mo)
                elif src == "fahcqmu":
                    r = await run_fahcqmu(keywords, exclude_kw)
                else:
                    continue
                if r:
                    results.append(r)
            return results
        elif args.source == "cqggzy":
            return await run_cqggzy(keywords, exclude_kw, args.days, not args.visible, args.slow_mo)
        elif args.source == "ccgp":
            return await run_ccgp(args.info_type, keywords, exclude_kw, not args.visible, args.slow_mo)
        elif args.source == "fahcqmu":
            return await run_fahcqmu(keywords, exclude_kw)
        else:
            raise ValueError(f"未知source: {args.source}")

    result = asyncio.run(do_run())

    if result:
        src = result[0]["source"] if isinstance(result, list) else result["source"]
        total = sum(r["total"] for r in result) if isinstance(result, list) else result["total"]
        filtered = sum(r["filtered"] for r in result) if isinstance(result, list) else result["filtered"]
        print(f"\n✅ {src} 采集完成：{filtered}/{total} 条匹配")
    else:
        print("\n⚠️ 未采集到数据")


def cmd_list_sources(args):
    """列出可用数据源"""
    sources = [
        ("cqggzy", "重庆市公共资源交易网", ["政府采购", "工程建设"]),
        ("ccgp", "重庆市政府采购网", ["采购意向", "采购公告", "结果公告"]),
        ("fahcqmu", "重庆医科大学附属第一医院", ["阳光推介", "调研", "采购公告", "采购结果", "其他"]),
    ]
    print("\n可用数据源:")
    for name, desc, categories in sources:
        print(f"  {name:10} — {desc}")
        print(f"             类型: {', '.join(categories)}")
    print()


# ─── 主入口 ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="招投标信息采集系统")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_run = subparsers.add_parser("run", help="运行采集任务")
    p_run.add_argument("--source", default="cqggzy", help="数据源: cqggzy | ccgp | fahcqmu | all")
    p_run.add_argument("--keywords", default="", help="关键词，冒号分隔")
    p_run.add_argument("--exclude", default="", help="排除词，冒号分隔")
    p_run.add_argument("--days", type=int, default=7, help="采集最近N天")
    p_run.add_argument("--info-type", default="", help="采购信息类型（ccgp专用）")
    p_run.add_argument("--visible", action="store_true", help="显示浏览器窗口")
    p_run.add_argument("--slow-mo", type=int, default=100, help="浏览器减速ms")
    p_run.set_defaults(func=cmd_run)

    p_list = subparsers.add_parser("list-sources", help="列出可用数据源")
    p_list.set_defaults(func=cmd_list_sources)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
