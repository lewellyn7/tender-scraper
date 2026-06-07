#!/usr/bin/env python3
"""
历史数据回采脚本（v3 - 大 rn + 分页）
- 每次请求 rn=1000
- 翻页直到 fetched==total
- 客户端日期过滤
- upsert 去重
"""
import asyncio
import os
import sys
import json
from datetime import datetime, timedelta

sys.path.insert(0, '/app')
os.environ.setdefault('DATABASE_URL', 'postgresql://root:root123@postgres:5432/tender_scraper')

from app.core.browser import StealthBrowser
from app.crawlers.cqggzy import CQGGZYCrawlerV2
from app.database.db import Database

START_DATE = os.environ.get('START_DATE', '2026-01-01')
END_DATE = os.environ.get('END_DATE', datetime.now().strftime('%Y-%m-%d'))
RN_SIZE = int(os.environ.get('RN_SIZE', 1000))
MAX_PAGES = int(os.environ.get('MAX_PAGES', 20))  # 每分类最多翻 20 页

CATEGORY_MAP = {
    "engineering_notice": ("014001", "014001001", "工程建设"),
    "engineering_plan": ("014001", "014001002", "工程建设"),
    "engineering_qa": ("014001", "014001003", "工程建设"),
    "engineering_candidate": ("014001", "014001004", "工程建设"),
    "engineering_result": ("014001", "014001005", "工程建设"),
    "engineering_terminate": ("014001", "014001006", "工程建设"),
    "gov_purchase_notice": ("014005", "014005001", "政府采购"),
    "gov_purchase_change": ("014005", "014005002", "政府采购"),
    "gov_purchase_result": ("014005", "014005003", "政府采购"),
}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


async def fetch_one_category(browser, crawler, category, start_dt, end_dt):
    """单分类分页拉取（直到 fetched==total）"""
    trade_id, cat_num, tender_type = CATEGORY_MAP[category]
    page = await browser.new_page()
    all_results = []
    total = None
    
    try:
        # 访问 list 页面建立 context
        url = f"https://www.cqggzy.com/trade/{trade_id}?pageNum=1&date=3m&categoryNum={cat_num}"
        await page.goto(url, wait_until="networkidle", timeout=60000)
        await crawler._smart_wait()
        
        from app.crawlers.cqggzy import TenderInfo
        
        for pn in range(0, MAX_PAGES * RN_SIZE, RN_SIZE):
            payload = {
                "token": "", "pn": pn // RN_SIZE, "rn": RN_SIZE,
                "sdt": start_dt.strftime('%Y-%m-%d'),
                "edt": end_dt.strftime('%Y-%m-%d'),
                "wd": "", "inc_wd": "", "exc_wd": "",
                "fields": "", "sort": '{"istop":"0","ordernum":"0","newid":"1"}',
                "ssort": "", "cl": 10000, "terminal": "", "highlights": "",
                "unionCondition": [], "accuracy": "", "noParticiple": "1", "noWd": True,
                "condition": [{"fieldName": "categorynum", "equal": cat_num, "isLike": True, "likeType": 2}]
            }
            payload_json = json.dumps(payload, ensure_ascii=False)
            api_response = await page.evaluate("""async (pj) => {
                const resp = await fetch('/api/v2/search-engine-page', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: pj
                });
                return await resp.json();
            }""", payload_json)
            content = json.loads(api_response.get('content', '{}'))
            records = content.get('result', {}).get('records', [])
            if total is None:
                total = content.get('result', {}).get('totalcount', 0)
            
            if not records:
                break
            
            # 客户端日期过滤 + 转 TenderInfo
            page_results = []
            for item in records:
                title = item.get('title', '').strip()
                if len(title) < 5:
                    continue
                
                infodate = item.get('infodate', '') or item.get('webdate', '') or ''
                pub_date = None
                if infodate and len(infodate) >= 10:
                    try:
                        pub_date = datetime.strptime(infodate[:19], '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        pass
                
                if pub_date and (pub_date < start_dt or pub_date > end_dt):
                    continue
                
                infoid = item.get('infoid', '') or item.get('syscollectguid', '')
                raw_catnum = item.get('categorynum', '') or cat_num
                full_url = f"https://www.cqggzy.com/trade/{trade_id}/{infoid}?categoryNum={raw_catnum}" if infoid else f"https://www.cqggzy.com/trade/{trade_id}?infoId={item.get('infoid', '')}"
                
                tender = TenderInfo(
                    title=title,
                    url=full_url,
                    category=tender_type,
                    source_url=full_url,
                    publish_date_raw=infodate,
                    tender_type=tender_type,
                    scraped_by="backfill_v3",
                )
                if pub_date:
                    tender.publish_date = pub_date

                # info_type 从 categorynum 分类
                raw_catnum = item.get('categorynum', '') or ''
                tender.info_type = INFO_TYPE_MAP.get(raw_catnum[:9], '')

                raw_content = item.get('content', '') or ''
                if raw_content:
                    import re as re_module
                    clean = re_module.sub(r'<[^>]+>', '', raw_content)
                    clean = re_module.sub(r'\s+', ' ', clean).strip()
                    tender.full_content = clean

                page_results.append(tender)
            
            all_results.extend(page_results)
            log(f"  {category} pn={pn//RN_SIZE}: +{len(page_results)} (累计 {len(all_results)}/{total})")
            
            # 终止条件
            if len(records) < RN_SIZE:
                break
            if total and len(all_results) >= total:
                break
        
        log(f"  {category} 完成: total={total}, in_range={len(all_results)}")
        return all_results
    except Exception as e:
        log(f"  {category}: 异常 {e}")
        return all_results
    finally:
        await page.close()


async def main():
    start_dt = datetime.strptime(START_DATE, '%Y-%m-%d')
    end_dt = datetime.strptime(END_DATE, '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
    log(f"📅 回采日期范围: {start_dt.date()} ~ {end_dt.date()}")
    log(f"📋 分类: {len(CATEGORY_MAP)} 个, 单页 {RN_SIZE}, 最多 {MAX_PAGES} 页")

    browser = None
    db = None
    try:
        browser = StealthBrowser(headless=True, slow_mo=0)
        await browser.start()
        db = Database()
        crawler = CQGGZYCrawlerV2(browser)

        all_items = []
        for category in CATEGORY_MAP.keys():
            items = await fetch_one_category(browser, crawler, category, start_dt, end_dt)
            all_items.extend(items)

        log(f"\n📊 总计: {len(all_items)} 条")

        if all_items:
            standardized = []
            for item in all_items:
                try:
                    std = {
                        "url": item.url,
                        "title": item.title or "",
                        "publish_date": item.publish_date.date() if item.publish_date else None,
                        "category": item.tender_type or "",
                        "source": "cqggzy",
                        "tender_type": item.tender_type or "",
                        "info_type": getattr(item, 'info_type', '') or classify_by_url(item.url),
                        "budget": getattr(item, 'budget', None),
                        "deadline": getattr(item, 'deadline', None),
                        "content_preview": (item.content_preview or "")[:500],
                        "full_content": item.full_content or "",
                    }
                    standardized.append(std)
                except Exception:
                    continue
            
            seen = set()
            unique = []
            for s in standardized:
                if s["url"] in seen:
                    continue
                seen.add(s["url"])
                unique.append(s)
            log(f"📥 去重后: {len(unique)} 条")
            
            db.upsert_projects(unique)
            log(f"✅ upsert 完成")

            from collections import Counter
            date_counter = Counter()
            for s in unique:
                if s.get("publish_date"):
                    date_counter[s["publish_date"]] += 1
            log(f"\n📅 覆盖日期（按天）:")
            for d in sorted(date_counter.keys()):
                log(f"  {d}: +{date_counter[d]} 条")
    finally:
        if browser:
            await browser.close()
        if db:
            db.close()


if __name__ == "__main__":
    asyncio.run(main())
