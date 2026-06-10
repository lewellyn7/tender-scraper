"""2026-06-10: 一次性回填无 project_no 的 projects_cqggzy 记录

根因: CQGGZY 详情页项目编号在第 2 个 <h1> 标签里 (e.g.
  <h1>title</h1>
  <h1>项目编号：CQS26C00816_130117562645086249</h1>
), 但采集器 _fetch_detail_page 的 selectors 列表没覆盖 h1, 导致内容丢失,
project_no 提取失败 (85.2% 覆盖率).

修复:
1. app/crawlers/cqggzy.py: 抓正文前 eval_on_selector_all('h1', ...) 拼到 content
2. app/utils/project_linker.py: 加 '项目号：' 规则 + 逗号分隔 + 下划线后缀

本脚本用 requests 抓 HTML (Nuxt SSR, 不需要 headless browser),
解析 <h1> 块, 重新跑 extract_project_no, upsert 写回.
比 headless browser 快 10-100 倍, 适合 1786 条回填.

行为:
1. SELECT projects_cqggzy WHERE project_no IS NULL OR project_no = ''
2. 对每条: requests.get → BS4 找 h1 → 拼 h1_block + content_preview
   → extract_project_no(title, h1_block + content)
3. 构造 row dict (含 scraped_at) → upsert_projects([row])
4. 限速 1.0s/req, 默认全量, --limit N 可限数
"""
import argparse
import re
import os
import sys
import time
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

# 容器内 / 本地运行兼容
sys.path.insert(0, '/app')
sys.path.insert(0, '.')

from sqlalchemy import create_engine, text

from app.config.settings import settings
from app.database.db import Database, DATABASE_URL
from app.utils.project_linker import extract_project_no


HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
}


def fetch_h1_block(url: str, timeout: int = int(os.environ.get('REPROCESS_TIMEOUT', '15'))) -> Optional[str]:
    """用 requests 抓 HTML, 提取所有 <h1> 文本拼接.

    失败/超时/无 h1 → 返回 None.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        h1s = [h.get_text(strip=True) for h in soup.find_all('h1')]
        h1s = [h for h in h1s if h]
        if h1s:
            return '\n'.join(h1s)
    except Exception as e:
        print(f"  ⚠️  抓取失败 {url[:70]}: {type(e).__name__}: {e}")
    return None


def main():
    parser = argparse.ArgumentParser(description='回填无 project_no 的 projects_cqggzy')
    parser.add_argument('--limit', type=int, default=0, help='限制处理条数 (0=全量)')
    parser.add_argument('--sleep', type=float, default=1.0, help='每条 sleep 秒数 (默认 1.0)')
    parser.add_argument('--url-pattern', type=str, default='', help='只处理匹配正则的 URL')
    parser.add_argument('--dry-run', action='store_true', help='只打印不写库')
    args = parser.parse_args()

    engine = create_engine(DATABASE_URL)
    db = Database() if not args.dry_run else None

    # 1. 选所有无 pno 记录
    where = "(project_no IS NULL OR project_no = '')"
    # 2026-06-10: 排除"招标计划表" —— 按用户观察无项目编号 (合法空)
    where += " AND title NOT LIKE '%招标计划表%'"
    if args.url_pattern:
        where += f" AND url ~ '{args.url_pattern}'"

    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, url, title, content_preview
            FROM projects_cqggzy
            WHERE {where}
            ORDER BY id
        """)).fetchall()

    if args.limit > 0:
        rows = rows[:args.limit]

    print(f"📥 待处理 {len(rows)} 条 {'(dry-run, 不写库)' if args.dry_run else ''}")
    if not rows:
        return

    # 2. 逐条处理
    success = 0
    still_empty = 0
    fetch_fail = 0
    upsert_fail = 0
    t_start = time.time()

    for i, (rid, url, title, content_preview) in enumerate(rows, 1):
        elapsed = time.time() - t_start
        print(f"\n[{i}/{len(rows)}] {url[:80]}... (累计 {elapsed:.0f}s)")

        # 抓 H1 块
        h1_block = fetch_h1_block(url)
        if not h1_block:
            fetch_fail += 1
            time.sleep(args.sleep)
            continue

        # 拼接 (H1 块在前面, 优先匹配)
        text_content = (h1_block + '\n' + (content_preview or '')).strip()

        # 提取 project_no
        new_pno = extract_project_no(title or '', text_content)
        if not new_pno:
            print(f"  ❌ 未提取 (H1: {h1_block[:80]!r})")
            still_empty += 1
            time.sleep(args.sleep)
            continue

        print(f"  ✅ {new_pno}")

        # upsert
        if args.dry_run:
            success += 1
            time.sleep(args.sleep)
            continue

        try:
            row = {
                'url': url,
                'title': title or '',
                'project_no': new_pno,
                'scraped_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            }
            db.upsert_projects([row])
            success += 1
        except Exception as e:
            print(f"  ⚠️  upsert 失败: {e}")
            upsert_fail += 1

        time.sleep(args.sleep)

    # 3. 总结
    elapsed = time.time() - t_start
    print()
    print("=" * 60)
    print(f"📊 回填完成: 耗时 {elapsed:.0f}s ({len(rows)/max(elapsed,1):.2f} 条/s)")
    print(f"   ✅ 成功: {success}")
    print(f"   ❌ 仍空: {still_empty} (页面无项目编号或 h1 缺失)")
    print(f"   ⚠️  抓取失败: {fetch_fail}")
    print(f"   ⚠️  upsert 失败: {upsert_fail}")
    print(f"   总计: {len(rows)}")


if __name__ == '__main__':
    main()
