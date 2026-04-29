#!/usr/bin/env python3
"""Minimal test for enrich_details.py"""
import sys
sys.path.insert(0, '/app')
import asyncio
from app.core.browser import StealthBrowser
from app.crawlers.cqggzy import CQGGZYCrawlerV2
from app.models.tender import TenderInfo
from pathlib import Path
import json

print("STEP 1: imports OK", flush=True)

async def run():
    OUTPUT_FILE = Path("/app/output/latest.json")
    with open(OUTPUT_FILE) as f:
        data = json.load(f)
    projects = data.get("projects", [])
    need = sum(1 for p in projects if not p.get("content_preview"))
    print(f"STEP 2: Total={len(projects)}, need_enrich={need}", flush=True)

    browser = StealthBrowser(headless=True, slow_mo=10)
    await browser.start()
    print("STEP 3: browser started", flush=True)

    crawler = CQGGZYCrawlerV2(browser)
    # Test with first item that needs enrichment
    test_item = next((p for p in projects if not p.get("content_preview")), None)
    if test_item:
        print(f"STEP 4: Testing with: {test_item.get('title','')[:40]}", flush=True)
        tender = TenderInfo(
            title=test_item.get("title", ""),
            url=test_item.get("url", ""),
            category=test_item.get("type", ""),
        )
        result = await crawler.fetch_detail(tender)
        print(f"STEP 5: detail fetched, content_preview={repr(result.content_preview[:50] if result.content_preview else '')}", flush=True)
        print(f"  budget={result.budget}, region={result.region}", flush=True)

    await browser.close()
    print("STEP 6: done", flush=True)
    return True

result = asyncio.run(run())
print(f"RESULT: {result}", flush=True)
