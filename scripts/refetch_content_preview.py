#!/usr/bin/env python3
"""回填 content_preview 字段

2026-06-18 任务: 清除 6-15 之后 986 条采集数据中的干扰项:
- 项目编号: 32.7% 记录含 20 位项目编号码
- 面包屑 (工程招投标/政府采购): 29.8% 记录
- Tab 列表 (工程/政采): 17.1% 记录

策略:
1. 建备份表 _content_preview_backup (id, old_cp, new_cp, updated_at)
2. 读 full_content 非空 + scraped_at > 6-15 的记录
3. 调用 make_content_preview(full_content, title) 重生成
4. 对比 old_cp vs new_cp, 不同的写入新值 + 备份表
5. 未变的不写 (0 写入)
6. 进度日志 + 错误回滚 (单条失败不影响整体)

回滚: UPDATE projects_cqggzy SET content_preview = (SELECT old_cp FROM _content_preview_backup WHERE id = p.id)

用法:
    python scripts/refetch_content_preview.py            # 跑回填
    python scripts/refetch_content_preview.py --dry-run  # 只统计, 不写库
    python scripts/refetch_content_preview.py --limit 10 # 限制条数
"""
import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 设默认值 (如果外面没传环境变量)
os.environ.setdefault(
    'DATABASE_URL',
    'postgresql://root:root123@postgres:5432/tender_scraper'
)

import psycopg2
from psycopg2.extras import execute_batch, RealDictCursor
from loguru import logger

from app.utils.clean_noise import make_content_preview

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logger.add(LOG_DIR / "refetch_cp_{time:YYYY-MM-DD}.log", rotation="1 day", level="INFO")


BACKUP_DDL = """
CREATE TABLE IF NOT EXISTS _content_preview_backup (
    id          BIGINT NOT NULL,
    old_cp      TEXT NOT NULL,
    new_cp      TEXT NOT NULL,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS _cp_backup_updated_idx ON _content_preview_backup(updated_at);
"""


def get_connection():
    """从 DATABASE_URL 环境变量读 DB 配置"""
    url = os.environ.get('DATABASE_URL', '')
    p = urlparse(url)
    return psycopg2.connect(
        host=p.hostname or 'postgres',
        port=p.port or 5432,
        dbname=(p.path or '/tender_scraper').lstrip('/'),
        user=p.username or 'root',
        password=p.password or '',
    )


def ensure_backup_table(conn):
    """建备份表 (幂等)"""
    with conn.cursor() as cur:
        cur.execute(BACKUP_DDL)
    conn.commit()
    logger.info("✅ 备份表 _content_preview_backup 就绪")


def fetch_target_records(conn, scraped_after: str, limit: int = None):
    """读待回填记录 (有 full_content 且 scraped_at >= cutoff)
    2026-06-18 修复: 用 >= 而非 >, 不然 起始日当天记录被漏
    """
    sql = """
        SELECT id, title, full_content, content_preview
        FROM projects_cqggzy
        WHERE full_content IS NOT NULL
          AND full_content != ''
          AND scraped_at >= %s
        ORDER BY id
    """
    if limit:
        sql += f" LIMIT {limit}"
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, (scraped_after,))
        return cur.fetchall()


def regen_one(record: dict) -> str:
    """重生成单条 content_preview"""
    title = record.get('title', '') or ''
    full = record.get('full_content', '') or ''
    if not full:
        return ''
    try:
        new_cp = make_content_preview(full, title)
    except Exception as e:
        logger.error(f"id={record['id']} 重生成失败: {e}")
        return None  # 标记失败
    return new_cp


def diff_stats(old: str, new: str) -> dict:
    """对比新旧, 返回差异统计"""
    old_clean = (old or '').strip()
    new_clean = (new or '').strip()
    return {
        'changed': old_clean != new_clean,
        'old_len': len(old_clean),
        'new_len': len(new_clean),
        'delta': len(new_clean) - len(old_clean),
    }


def backfill(scraped_after: str = '2026-06-15', limit: int = None, dry_run: bool = False):
    """主回填流程"""
    conn = get_connection()
    try:
        ensure_backup_table(conn)

        records = fetch_target_records(conn, scraped_after, limit=limit)
        total = len(records)
        logger.info(f"📋 找到 {total} 条候选 (scraped_at >= {scraped_after}{', limit=' + str(limit) if limit else ''})")

        changed_count = 0
        unchanged_count = 0
        failed_count = 0
        old_pn_count = 0
        old_bc_count = 0
        old_tab_count = 0
        new_pn_count = 0
        new_bc_count = 0
        new_tab_count = 0

        for i, r in enumerate(records, 1):
            old_cp = r.get('content_preview') or ''
            new_cp = regen_one(r)

            if new_cp is None:
                failed_count += 1
                continue

            stats = diff_stats(old_cp, new_cp)
            if not stats['changed']:
                unchanged_count += 1
                continue

            # 统计污染项消除
            if '项目编号' in old_cp: old_pn_count += 1
            if '首页 >' in old_cp or '首页＞' in old_cp: old_bc_count += 1
            if '招标公告 邀标信息' in old_cp or '采购公告 单一来源' in old_cp: old_tab_count += 1
            if '项目编号' in new_cp: new_pn_count += 1
            if '首页 >' in new_cp or '首页＞' in new_cp: new_bc_count += 1
            if '招标公告 邀标信息' in new_cp or '采购公告 单一来源' in new_cp: new_tab_count += 1

            changed_count += 1

            if not dry_run:
                with conn.cursor() as cur:
                    # 备份旧值
                    cur.execute("""
                        INSERT INTO _content_preview_backup (id, old_cp, new_cp)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            old_cp = EXCLUDED.old_cp,
                            new_cp = EXCLUDED.new_cp,
                            updated_at = CURRENT_TIMESTAMP
                    """, (r['id'], old_cp, new_cp))
                    # 更新主表
                    cur.execute("""
                        UPDATE projects_cqggzy
                        SET content_preview = %s
                        WHERE id = %s
                    """, (new_cp, r['id']))

            if i % 100 == 0 or i == total:
                logger.info(f"  [{i}/{total}] 变={changed_count} 不变={unchanged_count} 失败={failed_count} | "
                            f"旧:pn={old_pn_count} bc={old_bc_count} tab={old_tab_count} | "
                            f"新:pn={new_pn_count} bc={new_bc_count} tab={new_tab_count}")

        if not dry_run:
            conn.commit()
            logger.info(f"✅ 已提交 {changed_count} 条变更到 DB + 备份表")
        else:
            logger.info(f"[DRY-RUN] 将变更 {changed_count} 条, 备份 {changed_count} 条")

        # 总结
        logger.info("=" * 60)
        logger.info("📊 回填总结")
        logger.info(f"  总数:       {total}")
        logger.info(f"  变:         {changed_count}")
        logger.info(f"  不变:       {unchanged_count}")
        logger.info(f"  失败:       {failed_count}")
        logger.info(f"  旧 含 项目编号:    {old_pn_count} → 新 {new_pn_count} (净除 {old_pn_count - new_pn_count})")
        logger.info(f"  旧 含 面包屑:      {old_bc_count} → 新 {new_bc_count} (净除 {old_bc_count - new_bc_count})")
        logger.info(f"  旧 含 Tab 列表:    {old_tab_count} → 新 {new_tab_count} (净除 {old_tab_count - new_tab_count})")

    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="回填 content_preview 字段 (清除 6-15 之后的 3 种污染项)")
    parser.add_argument("--after", default="2026-06-15", help="scraped_at 起始时间 (含当日, 默认 2026-06-15)")
    parser.add_argument("--limit", type=int, default=None, help="限制条数 (测试用)")
    parser.add_argument("--dry-run", action="store_true", help="只统计, 不写库")
    args = parser.parse_args()

    # >= 包含起始日 (修正: 之前用 > 漏了 6-15 当天 235 条)
    backfill(scraped_after=args.after, limit=args.limit, dry_run=args.dry_run)
