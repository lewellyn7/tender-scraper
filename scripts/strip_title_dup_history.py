"""2026-06-08 Bug 2.1 数据层修复: 一次性重处理 projects_cqggzy.content_preview
去掉开头的 title 重复行

使用:
  cd /home/lewellyn/tender-scraper
  python scripts/strip_title_dup_history.py [--dry-run] [--batch-size=200]

行为:
- 扫描 projects_cqggzy 表所有 content_preview 起始 = title 的记录
- 用 full_content + make_content_preview 重生成 content_preview
- 默认 dry-run (只 SELECT 不 UPDATE)
- 加 --apply 真正更新
- 加 --limit=1000 限制更新条数 (防失控)

依赖:
- 已部署 strip_title_dup / make_content_preview 到 app/utils/clean_noise.py
- PostgreSQL 连接通过环境变量 DATABASE_URL

预期: 6-8 数据 10/24 有 content_preview 中 9/10 首行 = title
       (id=594901 等), 这条 SQL 会重生成这些 content_preview
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text
from app.config.settings import settings
from app.database.db import DATABASE_URL
from app.utils.clean_noise import make_content_preview


def main():
    parser = argparse.ArgumentParser(description="重处理 content_preview 去掉 title 重复")
    parser.add_argument("--apply", action="store_true", help="真正更新 DB (默认 dry-run)")
    parser.add_argument("--limit", type=int, default=0, help="最多更新 N 条 (0=无限制)")
    parser.add_argument("--batch-size", type=int, default=200, help="每批更新条数")
    parser.add_argument("--days", type=int, default=7, help="只看最近 N 天的数据 (默认 7)")
    args = parser.parse_args()

    engine = create_engine(DATABASE_URL)

    # 1. 扫描: SELECT 所有 content_preview 起始 = title 的记录
    # 用 LEFT(full_content, 200) 检查: 完整内容 1-2 行 == title
    scan_sql = text("""
        SELECT id, url, title,
               LEFT(content_preview, 200) AS preview_head,
               LEFT(full_content, 500) AS full_head,
               LENGTH(content_preview) AS preview_len,
               LENGTH(full_content) AS full_len
        FROM projects_cqggzy
        WHERE publish_date >= CURRENT_DATE - (:days || ' days')::INTERVAL
          AND full_content IS NOT NULL
          AND LENGTH(full_content) > 50
          AND (
            -- content_preview 前 100 字符 = title 的前 100 字符 (起始匹配)
            LEFT(content_preview, 100) = LEFT(title, 100)
            -- 或者 content_preview 含 title 完整重复 (前 200 字符出现 2 次 title)
            OR content_preview LIKE '%' || LEFT(title, 50) || '%' || LEFT(title, 50) || '%'
          )
        ORDER BY publish_date DESC, id DESC
    """)

    with engine.connect() as conn:
        rows = conn.execute(scan_sql, {"days": args.days}).fetchall()

    print(f"📊 扫描到 {len(rows)} 条 content_preview 可能含 title 重复的记录")
    if args.limit > 0:
        rows = rows[:args.limit]
        print(f"   (限 LIMIT {args.limit}, 实际处理 {len(rows)} 条)")

    if not rows:
        print("✅ 无需处理")
        return

    # 2. 逐条重生成 content_preview
    updates = []
    skipped = 0
    for r in rows:
        rid, url, title, preview_head, full_head, pl, fl = r
        # 重新生成
        new_preview = make_content_preview(full_head or "", title or "", max_len=500)
        if not new_preview:
            skipped += 1
            continue
        if new_preview == preview_head:
            skipped += 1
            continue
        updates.append((rid, new_preview))

    print(f"📝 待更新: {len(updates)} 条, 跳过: {skipped} 条 (已无重复 或 重生成失败)")

    if not args.apply:
        print("💡 当前为 dry-run 模式, 加 --apply 真正更新 DB")
        print(f"\n示例 (前 5 条):")
        for rid, np in updates[:5]:
            print(f"  id={rid}: new_preview={np[:80]!r}")
        return

    # 3. 批量 UPDATE
    if not updates:
        print("✅ 无需更新")
        return

    print(f"⏳ 批量更新 {len(updates)} 条 (batch={args.batch_size})...")
    with engine.begin() as conn:
        for i in range(0, len(updates), args.batch_size):
            batch = updates[i:i + args.batch_size]
            for rid, np in batch:
                conn.execute(
                    text("UPDATE projects_cqggzy SET content_preview = :p WHERE id = :i"),
                    {"p": np, "i": rid}
                )
            print(f"  ✅ 批次 {i//args.batch_size + 1}/{(len(updates) + args.batch_size - 1)//args.batch_size} 完成 ({len(batch)} 条)")

    print(f"✅ 全部更新完成: {len(updates)} 条")


if __name__ == "__main__":
    main()
