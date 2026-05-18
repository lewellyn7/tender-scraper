#!/usr/bin/env python3
"""
分批次重新采集脚本（简化版）

用法:
    cd ~/tender-scraper
    # 采集 cqggzy，每批 20 条，延时 5 秒
    docker compose exec web python -m scripts.batch_recrawl_simple --source cqggzy --batch-size 20 --delay 5
    
    # 采集 ccgp，重试失败记录
    docker compose exec web python -m scripts.batch_recrawl_simple --source ccgp --retry-failed
"""
import asyncio
import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict
from loguru import logger

from app.crawlers.cqggzy import CQGGZYCrawlerV2
from app.crawlers.ccgp import CCGPCrawlerV3
from app.database.db import upsert_projects

PROGRESS_FILE = Path(__file__).parent / ".batch_recrawl_progress.json"

def load_progress(source: str) -> Dict:
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get(source, {"processed": [], "failed": [], "done": False})
        except:
            pass
    return {"processed": [], "failed": [], "done": False}

def save_progress(source: str, progress: Dict):
    data = {}
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            pass
    data[source] = progress
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info(f"💾 进度：已处理 {len(progress['processed'])} 条，失败 {len(progress['failed'])} 条")

async def main():
    parser = argparse.ArgumentParser(description="分批次重新采集")
    parser.add_argument("--source", choices=["cqggzy", "ccgp"], required=True)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--delay", type=int, default=5)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--max-batches", type=int, default=None)
    args = parser.parse_args()
    
    logger.info(f"🚀 开始分批次采集：{args.source}")
    
    # 从数据库获取 URL 列表
    import psycopg2
    conn = psycopg2.connect("postgresql://root:root123@localhost:5435/tender_scraper")
    cur = conn.cursor()
    table = "projects_cqggzy" if args.source == "cqggzy" else "projects_ccgp"
    cur.execute(f"SELECT url FROM {table}")
    all_urls = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    
    logger.info(f"📊 数据库共有 {len(all_urls)} 条记录")
    
    # 加载进度
    progress = load_progress(args.source)
    processed_set = set(progress.get("processed", []))
    failed_set = set(progress.get("failed", []))
    
    if not args.retry_failed:
        urls_to_process = [u for u in all_urls if u not in processed_set and u not in failed_set]
    else:
        # 重试失败的
        urls_to_process = [u for u in all_urls if u in failed_set]
        logger.info(f"🔄 将重试 {len(urls_to_process)} 条失败记录")
    
    if not urls_to_process:
        logger.info("✅ 无需采集")
        return
    
    logger.info(f"📋 待采集：{len(urls_to_process)} 条")
    
    # 分批
    batch_size = args.batch_size
    batches = [urls_to_process[i:i+batch_size] for i in range(0, len(urls_to_process), batch_size)]
    
    # 创建采集器
    crawler = CQGGZYCrawlerV2() if args.source == "cqggzy" else CCGPCrawlerV3()
    
    batch_count = 0
    for batch_urls in batches:
        if args.max_batches and batch_count >= args.max_batches:
            break
        
        batch_count += 1
        logger.info(f"\n{'='*50}")
        logger.info(f"📦 第 {batch_count}/{len(batches)} 批 ({len(batch_urls)} 条)")
        logger.info(f"{'='*50}\n")
        
        # 采集该批次
        for url in batch_urls:
            try:
                logger.info(f"🔍 {url[:80]}...")
                
                # 调用采集
                if args.source == "cqggzy":
                    category = "gov_purchase" if "014005" in url else "engineering"
                    result = await crawler.fetch_detail(url, category=category)
                else:
                    info_type = "采购公告"
                    if "intention" in url:
                        info_type = "采购意向"
                    elif "result" in url:
                        info_type = "结果公告"
                    result = await crawler.fetch_detail(url, info_type=info_type)
                
                if result and result.title:
                    # 写入数据库
                    row = {
                        "title": result.title,
                        "url": result.url,
                        "business_type": getattr(result, 'category', None) or getattr(result, 'business_type', None),
                        "info_type": getattr(result, 'info_type', None),
                        "project_no": getattr(result, 'project_no', ''),
                        "project_name": getattr(result, 'project_name', ''),
                        "budget": getattr(result, 'budget', ''),
                        "deadline": getattr(result, 'deadline', ''),
                        "contact_info": getattr(result, 'contact_info', ''),
                        "full_content": getattr(result, 'full_content', ''),
                        "project_overview": getattr(result, 'project_overview', ''),
                        "published_at": getattr(result, 'published_at', None),
                        "created_at": datetime.now(),
                        "updated_at": datetime.now(),
                    }
                    upsert_projects([row])
                    processed_set.add(url)
                    logger.info(f"✅ {result.title[:40]}...")
                else:
                    logger.warning(f"⚠️ 无数据")
                    failed_set.add(url)
                    
            except Exception as e:
                logger.error(f"❌ 失败：{e}")
                failed_set.add(url)
        
        # 保存进度
        progress["processed"] = list(processed_set)
        progress["failed"] = list(failed_set)
        save_progress(args.source, progress)
        
        # 延时
        if batch_count < len(batches):
            logger.info(f"⏱️  延时 {args.delay} 秒...")
            await asyncio.sleep(args.delay)
    
    await crawler.close()
    logger.info(f"\n✅ 完成！成功：{len(processed_set)}, 失败：{len(failed_set)}")

if __name__ == "__main__":
    asyncio.run(main())
