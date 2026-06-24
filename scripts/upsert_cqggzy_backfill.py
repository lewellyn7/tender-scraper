#!/usr/bin/env python3
"""把 curl 采集的 JSON upsert 到 DB"""
import json
import sys
import os
sys.path.insert(0, '/app')

from datetime import datetime
from app.database.db import Database
from app.utils.filter import TenderFilter
from app.crawlers.base import TenderInfo
from app.utils.clean_noise import make_content_preview
import re

def main():
    json_path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/cqggzy_backfill_2026_06_22_23.json'
    with open(json_path) as f:
        items = json.load(f)
    print(f"读入 {len(items)} 条")

    # 8 大类白名单 (6 位)
    info_type_map = {
        '014001019': '招标计划', '014001001': '招标公告',
        '014001002': '答疑补遗', '014001003': '中标候选人',
        '014001004': '中标结果', '014005001': '采购公告',
        '014005002': '变更公告', '014005004': '采购结果',
    }
    cat_blacklist = {'014001015', '014005008'}

    db = Database()
    rows = []
    skipped_blacklist = 0
    skipped_noinfo = 0
    for item in items:
        title = item.get('title', '').strip()
        url = item.get('url', '')
        catnum = item.get('category', '')
        pub_date = item.get('publish_date', '')
        fc = item.get('full_content', '')
        cp = item.get('content_preview', '')
        pn = item.get('project_no', '')

        if not title or not url:
            continue

        # 6 位大类
        cat6 = catnum[:6] if len(catnum) >= 6 else catnum
        # 黑名单 (2026-06-23 17:51 指令)
        if cat6 in cat_blacklist or catnum in cat_blacklist:
            skipped_blacklist += 1
            continue
        # 8 大类白名单
        if cat6 not in info_type_map:
            skipped_noinfo += 1
            continue

        info_type = info_type_map.get(cat6, '')
        if cat6.startswith('014001'):
            business_type = '工程招投标'
        elif cat6.startswith('014005'):
            business_type = '政府采购'
        else:
            business_type = ''

        rows.append({
            'title': title,
            'url': url,
            'category': cat6,
            'info_type': info_type,
            'business_type': business_type,
            'publish_date': pub_date,
            'publish_date_raw': pub_date,
            'content_preview': cp[:300] if cp else '',
            'full_content': fc,
            'project_no': pn,
            'scraped_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'scraped_by': 'tender-scraper curl backfill',
        })

    print(f"白名单通过 {len(rows)} 条 (skip 黑名单 {skipped_blacklist}, 跳过非白名单 {skipped_noinfo})")

    # 9 大类才 upsert
    if rows:
        written = db.upsert_projects(rows)
        print(f"✅ 写入: {written} 条")

if __name__ == '__main__':
    main()