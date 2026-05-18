#!/usr/bin/env python3
"""重庆政府采购网 - requests 替代方案（绕过 Playwright Timeout）"""
import asyncio
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, '/home/lewellyn/tender-scraper')

import requests
from bs4 import BeautifulSoup
from app.utils.report import ReportGenerator

KEYWORDS = ["智能化", "音视频", "AI", "人工智能", "智能体", "大模型"]
OUTPUT_DIR = "/home/lewellyn/.openclaw/workspace/logs/procurement"
os.makedirs(OUTPUT_DIR, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Connection': 'keep-alive',
}

def matches_keywords(title: str) -> bool:
    t = title.lower()
    for kw in KEYWORDS:
        if kw.lower() in t:
            return True
    return False

def collect_page(url: str, info_type: str) -> list:
    """采集单个页面，返回匹配今日+关键词的项目"""
    today = datetime.now().strftime("%Y-%m-%d")
    today_short = datetime.now().strftime("%Y%m%d")
    results = []
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 尝试多种选择器（新版页面结构）
        items = soup.select('.block-item, .list-item, .notice-item, .item')
        if not items:
            items = soup.find_all('div', class_=lambda c: c and ('item' in c.lower() or 'notice' in c.lower()))
        
        print(f"  [{info_type}] 找到 {len(items)} 个元素")
        
        for item in items:
            title_elem = item.select_one('.item-title, .title, .notice-title, a')
            title = (title_elem.get_text(strip=True) if title_elem else '').strip()
            
            # 尝试提取日期
            date_elem = item.select_one('.date, .time, .style__DateCol, [class*=date]')
            date = ''
            if date_elem:
                date = date_elem.get_text(strip=True)
            else:
                # 从整个item文本中查找日期格式
                import re
                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', item.get_text())
                if date_match:
                    date = date_match.group(1)
            
            if not title:
                continue
            
            # 过滤：今日且关键词匹配
            if (today not in date and today_short not in date):
                continue
            
            matched_kw = [kw for kw in KEYWORDS if kw.lower() in title.lower()]
            if not matched_kw:
                continue
            
            # 提取链接
            link = item.select_one('a')
            href = ''
            if link and link.get('href'):
                href = link['href']
                if href.startswith('/'):
                    href = 'https://www.ccgp-chongqing.gov.cn' + href
                elif not href.startswith('http'):
                    href = 'https://www.ccgp-chongqing.gov.cn/' + href
            
            results.append({
                'title': title,
                'url': href,
                'business_type': '政府采购',
                'info_type': info_type,
                'publish_date': date,
                'publish_date_raw': date,
                'source_url': url,
                'tender_type': info_type,
                'budget': '',
                'project_overview': title,
                'contact_name': '',
                'contact_phone': '',
                'keywords_matched': matched_kw,
            })
            print(f"    ✅ {matched_kw[0]} | {title[:50]}")
            
    except Exception as e:
        print(f"  ❌ [{info_type}] 采集失败: {e}")
    
    return results

async def main():
    today = datetime.now().strftime("%Y-%m-%d")
    today_short = datetime.now().strftime("%Y%m%d")
    print(f"📅 采集日期: {today}")
    print(f"🔑 关键词: {KEYWORDS}")
    print()
    
    all_results = []
    
    # 新版 URL（来自 quick_ccgp.py）
    for info_type, path in [
        ("采购公告", "info-notice/notice-list"),
        ("采购意向", "info-notice/intention-list"),
        ("结果公告", "info-notice/result-list"),
    ]:
        url = f"https://www.ccgp-chongqing.gov.cn/{path}"
        print(f"📋 采集 [{info_type}]...")
        results = collect_page(url, info_type)
        all_results.extend(results)
    
    print(f"\n📥 关键词匹配: {len(all_results)} 条")
    
    # 生成 Excel
    excel_path = ""
    if all_results:
        rg = ReportGenerator(OUTPUT_DIR)
        excel_path = rg.generate_excel(all_results, f"ccgp_procurement_{today_short}")
        print(f"✅ Excel: {excel_path}")
    else:
        print("⚠️ 今日无匹配数据")
    
    # 保存 JSON
    data_path = os.path.join(OUTPUT_DIR, "ccgp_latest.json")
    output_data = {
        "total": len(all_results),
        "filtered": len(all_results),
        "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "matched_projects": all_results,
    }
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"📊 JSON: {data_path}")
    
    print("\n" + "="*60)
    if all_results:
        for r in all_results:
            print(f"【{r['info_type']}】{r['title'][:60]}")
            print(f"  日期: {r['publish_date']} | 关键词: {r['keywords_matched']}")
    else:
        print("今日无符合关键词的采购信息")
    print("="*60)
    
    return len(all_results)

if __name__ == "__main__":
    count = asyncio.run(main())
    sys.exit(0)