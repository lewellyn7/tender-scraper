#!/usr/bin/env python3
"""回填历史数据到 projects + project_records 关联表

从 projects_cqggzy (11437) + projects_ccgp (58) 提取已有数据
调用 db._sync_projects_link() 写入关联表

不触发通知（避免 1.1 万条历史消息轰炸）。
"""

import asyncio
import os
import sys
from pathlib import Path

# 让脚本能导入 app.*
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from app.database import get_db
from app.utils.project_linker import (
    extract_project_no,
    normalize_project_name,
)


def _row_to_dict(row_tuple, columns: list) -> dict:
    """psycopg2 row tuple → dict（用列名做 key）"""
    return {col: row_tuple[i] for i, col in enumerate(columns)}


def _normalize_row(r: dict) -> dict:
    """统一字段：publish_date 转 str，None 字段填空串"""
    out = dict(r)
    pub = out.get("publish_date")
    if pub and not isinstance(pub, str):
        try:
            out["publish_date"] = pub.strftime("%Y-%m-%d")
        except Exception:
            out["publish_date"] = str(pub) if pub else ""
    elif pub is None:
        out["publish_date"] = ""
    return out


def _fetch_all(db, table: str, columns: list) -> list:
    """分页拉取整张表，避免一次性 OOM"""
    rows = []
    page_size = 1000
    offset = 0
    c = db._get_conn()
    while True:
        cur = c.execute(
            f"SELECT {','.join(columns)} FROM {table} ORDER BY id LIMIT %s OFFSET %s",
            (page_size, offset),
        )
        batch = cur.fetchall()
        if not batch:
            break
        for r in batch:
            rows.append(_row_to_dict(r, columns))
        offset += page_size
        if len(batch) < page_size:
            break
    return rows


async def backfill():
    db = get_db()

    # columns to fetch per table (业务列不全相同)
    cols_by_table = {
        "projects_cqggzy": [
            "url", "title", "info_type", "business_type", "tender_type",
            "publish_date", "budget", "region", "industry", "project_no",
            "content_preview", "full_content",
        ],
        "projects_ccgp": [
            "url", "title", "info_type", "tender_type",
            "publish_date", "budget", "region", "industry", "project_no",
            "content_preview", "full_content",
        ],
    }

    summary = {}

    for table, common_cols in cols_by_table.items():
        logger.info(f"📥 拉取 {table} 全部记录...")
        rows = _fetch_all(db, table, common_cols)
        logger.info(f"   {table} 拉取到 {len(rows)} 条")

        # 规范化
        rows = [_normalize_row(r) for r in rows]

        # 注入缺失字段
        for r in rows:
            if not r.get("project_no"):
                # 从 title/content 提取
                pno = extract_project_no(
                    r.get("title", "") or "",
                    r.get("content_preview", "") or "",
                )
                r["project_no"] = pno or ""
            if not r.get("region"):
                r["region"] = ""

        # 调用同步函数（写 projects + project_records，不触发通知）
        logger.info(f"🔗 {table} → projects + project_records 同步开始...")
        # 临时关闭通知 hook（直接调底层，不走 add_project_record 末尾的 hook）
        synced = await _sync_without_notify(db, rows, source_table=table)
        summary[table] = synced
        logger.info(f"   {table} 同步完成：{synced} 条")

    # 汇总
    logger.info("\n" + "=" * 60)
    logger.info("📊 回填汇总")
    for t, n in summary.items():
        logger.info(f"  {t}: {n} 条")
    logger.info("=" * 60)

    # 验证
    c = db._get_conn()
    n_projects = c.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    n_records = c.execute("SELECT COUNT(*) FROM project_records").fetchone()[0]
    logger.info(f"  projects 表: {n_projects} 行")
    logger.info(f"  project_records 表: {n_records} 行")


async def _sync_without_notify(db, rows: list, source_table: str) -> int:
    """同步项目到 projects + project_records，不触发通知 hook。

    模仿 _sync_projects_link 但跳过 add_project_record 末尾的通知调用。
    """
    synced = 0
    for r in rows:
        url = r.get("url", "")
        title = r.get("title", "")
        if not url or not title:
            continue

        try:
            project_name = normalize_project_name(title)
            project_no = r.get("project_no", "") or ""

            project_id = db.upsert_project(
                project_name=project_name,
                project_name_raw=title,
                project_no=project_no,
                business_type=r.get("business_type", "") or r.get("tender_type", ""),
                region=r.get("region", "") or "",
                industry=r.get("industry", "") or "",
                budget=r.get("budget", "") or "",
            )
            if project_id <= 0:
                continue

            # 调 add_project_record 但绕开通知 hook
            # 临时把 hook 置空
            original_hook = db._try_trigger_favorite_notification
            db._try_trigger_favorite_notification = lambda *a, **kw: None
            try:
                db.add_project_record(
                    project_id=project_id,
                    record_url=url,
                    record_type=r.get("info_type", "") or "",
                    title=title,
                    publish_date=r.get("publish_date", "") or "",
                    budget=r.get("budget", "") or "",
                )
            finally:
                db._try_trigger_favorite_notification = original_hook

            synced += 1
            if synced % 500 == 0:
                logger.info(f"   {source_table}: 已同步 {synced} 条")
        except Exception as e:
            logger.debug(f"  单条失败: {url}: {e}")
            continue

    return synced


if __name__ == "__main__":
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | {message}",
        level="INFO",
    )
    asyncio.run(backfill())
