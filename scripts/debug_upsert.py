"""调试 upsert_projects 写入数量问题"""
import asyncio, json, sys
sys.path.insert(0, '/app')
from app.database import get_db

async def main():
    import httpx
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Content-Type': 'application/json',
        'Referer': 'https://www.cqggzy.com/jyxx/transaction_detail.html',
    }
    body = {
        'token': '', 'rn': 50,
        'condition': [{'fieldName': 'categorynum', 'equal': '014001001',
                       'notEqualList': ['014001018','004002005','014001015','014005014','014008011'],
                       'isLike': True, 'likeType': 2}],
        'time': [{'fieldName': 'webdate', 'startTime': '2026-01-01 00:00:00', 'endTime': '2026-05-31 23:59:59'}],
        'isBusiness': '1', 'noWd': True
    }

    all_records = []
    for pn in range(2):
        resp = httpx.post(
            'https://www.cqggzy.com/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew',
            headers=headers, json={**body, 'pn': pn}, timeout=15
        )
        content = json.loads(resp.json()['content'])
        result = content.get('result', {})
        records = result.get('records', [])
        print(f'pn={pn}: got {len(records)} records, totalcount={result.get("totalcount")}')
        all_records.extend(records)

    print(f'Total fetched: {len(all_records)} unique_newids={len(set(r["newid"] for r in all_records))}')

    # 构建 rows
    rows = []
    for r in all_records:
        pub_date_str = r.get('pubinwebdate', '') or ''
        pub_date = None
        if pub_date_str:
            from datetime import datetime
            try:
                pub_date = datetime.strptime(pub_date_str[:10], '%Y-%m-%d')
            except ValueError:
                pass

        infod = r.get('infod', '') or ''
        linkurl = r.get('linkurl', '') or ''
        if infod:
            url = f'https://www.cqggzy.com/xxhz/{infod}/transaction_detail.html'
        elif linkurl:
            url = 'https://www.cqggzy.com' + linkurl if linkurl.startswith('/') else linkurl
        else:
            url = ''

        rows.append({
            'url': url,
            'title': (r.get('titlenew') or r.get('title') or '')[:500],
            'info_type': '招标公告',
            'category': '工程建设',
            'business_type': '工程建设',
            'publish_date': pub_date,
            'publish_date_raw': pub_date.strftime('%Y-%m-%d') if pub_date else '',
            'content_preview': (r.get('content') or '')[:500],
            'full_content': (r.get('content') or '')[:5000],
            'budget': '', 'bid_amount': '', 'deadline': None,
            'region': r.get('infoc', '') or '重庆市',
            'industry': '',
            'tender_type': '工程建设',
            'project_overview': '', 'bidder_requirements': '',
            'submission_deadline': '', 'contact_name': '', 'contact_phone': '',
            'contact_email': '', 'attachments_count': 0, 'attachments': '[]',
            'keywords_matched': '',
            'source_url': 'https://www.cqggzy.com/jyxx/transaction_detail.html',
            'scraped_at': None, 'scraped_by': 'debug_v1',
            'contract_amount': '', 'planned_publish_date': '', 'tender_content': '',
            'opening_date': None,
        })

    print(f'Prepared {len(rows)} rows for upsert')

    db = get_db()
    db.upsert_projects(rows)

    cur = db._get_conn().conn.cursor()
    cur.execute('SELECT COUNT(*) FROM projects_cqggzy WHERE scraped_by=%s', ('debug_v1',))
    print(f'DB now has {cur.fetchone()[0]} records with scraped_by=debug_v1')

    cur.execute('SELECT url, LEFT(title,30) FROM projects_cqggzy WHERE scraped_by=%s LIMIT 5', ('debug_v1',))
    for row in cur.fetchall():
        print(f'  {row[0][:60]} | {row[1]}')

if __name__ == '__main__':
    asyncio.run(main())