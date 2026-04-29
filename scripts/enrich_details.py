#!/usr/bin/env python3
"""补全 latest.json 中所有条目的详情页内容

用法:
    python scripts/enrich_details.py [--limit 50] [--concurrent 3]

流程:
    1. 读取 output/latest.json
    2. 过滤出 content_preview 为空的条目
    3. 并行爬取详情页（控制并发）
    4. 更新 latest.json（原地更新，仅修改空字段）
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import loguru
logger = loguru.logger
logger.remove()
logger.add(sys.stderr, level="INFO")

from app.core.browser import StealthBrowser
from app.crawlers.cqggzy import CQGGZYCrawlerV2
from app.crawlers.ccgp import CCGPCrawlerV3
from app.models.tender import TenderInfo

OUTPUT_FILE = Path("/app/output/latest.json")


def detect_source(url: str) -> str:
    """根据 URL 判断数据源"""
    if "cqggzy.com" in url:
        return "cqggzy"
    elif "ccgp-chongqing.gov.cn" in url or "ccgp.gov.cn" in url:
        return "ccgp"
    return "unknown"


async def enrich_item(browser: StealthBrowser, item: dict, semaphore: asyncio.Semaphore) -> dict:
    """为单个条目爬取详情页，补充空字段"""
    url = item.get("url", "")
    if not url:
        return item

    source = detect_source(url)
    if source == "unknown":
        return item

    async with semaphore:
        try:
            if source == "cqggzy":
                crawler = CQGGZYCrawlerV2(browser)
            elif source == "ccgp":
                crawler = CCGPCrawlerV3(browser)
            else:
                return item

            tender = TenderInfo(
                title=item.get("title", ""),
                url=url,
                category=item.get("type", "") or item.get("category", ""),
            )

            result = await crawler.fetch_detail(tender)

            # 只填充空字段，保留已有内容
            if not item.get("content_preview") and result.content_preview:
                item["content_preview"] = result.content_preview
            if not item.get("full_content") and result.full_content:
                item["full_content"] = result.full_content
            if not item.get("budget") and result.budget:
                item["budget"] = result.budget
            if not item.get("region") and result.region:
                item["region"] = result.region
            if not item.get("deadline") and result.deadline:
                item["deadline"] = result.deadline.strftime("%Y-%m-%d %H:%M") if hasattr(result.deadline, 'strftime') else str(result.deadline) if result.deadline else ""
            if not item.get("contact_name") and result.contact_info and result.contact_info.name:
                item["contact_name"] = result.contact_info.name
            if not item.get("contact_phone") and result.contact_info and result.contact_info.phone:
                item["contact_phone"] = result.contact_info.phone
            if not item.get("contact_email") and result.contact_info and result.contact_info.email:
                item["contact_email"] = result.contact_info.email
            if not item.get("project_overview") and result.project_overview:
                item["project_overview"] = result.project_overview
            if not item.get("bidder_requirements") and result.bidder_requirements:
                item["bidder_requirements"] = result.bidder_requirements
            if not item.get("submission_deadline") and result.submission_deadline:
                item["submission_deadline"] = result.submission_deadline
            if not item.get("bid_amount") and result.bid_amount:
                item["bid_amount"] = result.bid_amount
            if not item.get("business_type") and result.business_type:
                item["business_type"] = result.business_type
            if not item.get("info_type") and result.info_type:
                item["info_type"] = result.info_type

            att_count = len(result.attachments) if result.attachments else 0
            if att_count > 0:
                item["attachments_count"] = att_count
                item["attachments"] = ", ".join(a.name for a in result.attachments if a.name)

            return item

        except Exception as e:
            logger.warning(f"⚠️ 详情页采集失败: {item.get('title', '')[:30]}... {e}")
            return item


async def main(limit: int, concurrent: int):
    """主流程"""
    if not OUTPUT_FILE.exists():
        logger.error(f"文件不存在: {OUTPUT_FILE}")
        return

    # 读取现有数据
    with open(OUTPUT_FILE, encoding="utf-8") as f:
        data = json.load(f)

    projects = data.get("projects", [])
    total = len(projects)
    logger.info(f"📥 读取 {total} 条数据")

    # 找出需要补全的条目（content_preview 为空）
    needs_enrich = [p for p in projects if not p.get("content_preview") and not p.get("full_content")]
    logger.info(f"📋 需补全详情: {len(needs_enrich)} 条")

    if not needs_enrich:
        logger.info("✅ 所有条目已有内容摘要，无需补全")
        return

    # 限制处理数量
    if limit > 0:
        needs_enrich = needs_enrich[:limit]
        logger.info(f"🔍 限制处理前 {limit} 条")

    # 启动浏览器
    browser = StealthBrowser(headless=True, slow_mo=50)
    await browser.start()
    logger.info("🌐 浏览器已启动")

    try:
        semaphore = asyncio.Semaphore(concurrent)
        tasks = [enrich_item(browser, item, semaphore) for item in needs_enrich]

        done = 0
        for coro in asyncio.as_completed(tasks):
            result = await coro
            done += 1
            if done % 5 == 0:
                logger.info(f"📦 进度: {done}/{len(needs_enrich)}")

            # 更新原数据
            for orig in projects:
                if orig.get("url") == result.get("url"):
                    orig.update(result)
                    break

        # 写回 latest.json
        data["projects"] = projects
        data["enriched_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        def json_safe(obj):
            """Convert objects that can't be serialized by JSON (datetime, etc.)"""
            if hasattr(obj, 'strftime'):
                return obj.strftime("%Y-%m-%d %H:%M:%S")
            if hasattr(obj, 'to_dict'):
                return obj.to_dict()
            return str(obj)

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=json_safe)

        # 统计
        filled = sum(1 for p in projects if p.get("content_preview"))
        logger.info(f"✅ 补全完成！content_preview 已填充: {filled}/{total} 条")

    finally:
        await browser.close()
        logger.info("🌐 浏览器已关闭")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="补全 latest.json 详情页内容")
    parser.add_argument("--limit", type=int, default=0, help="限制处理条数（0=全部）")
    parser.add_argument("--concurrent", type=int, default=3, help="并发数")
    args = parser.parse_args()

    asyncio.run(main(limit=args.limit, concurrent=args.concurrent))
