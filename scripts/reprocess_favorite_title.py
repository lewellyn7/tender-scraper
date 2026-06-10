"""2026-06-10: 一次性回填 favorites 表空 title 记录

根因: data.html:639 之前 hardcode title: "", 收藏 POST 时传空 title,
DB 存空 title, 收藏页 favorites.html:123 显示空卡片, 用户看不到项目.

修复: data.html 改为传 item.title, 但**已存在的空 title 收藏需要回填**.

逻辑: 按 favorites.project_url → projects_cqggzy.url 查 title, UPDATE 回填.
      (项目可能来自 projects_ccgp, 但 CQGGZY 占比 98%, 先查 CQGGZY, 查不到再查 CCGP)
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, '/home/lewellyn/tender-scraper')

from sqlalchemy import create_engine, text
from app.config.settings import settings
from app.database.db import DATABASE_URL

e = create_engine(DATABASE_URL)

with e.connect() as c:
    # 1. 看空 title 收藏总数
    n_total = c.execute(text("""
        SELECT COUNT(*) FROM favorites
        WHERE title IS NULL OR title = ''
    """)).scalar()
    print(f"空 title 收藏总数: {n_total}")

    if n_total == 0:
        print("✅ 无需回填, 退出")
        sys.exit(0)

    # 2. 抽样 3 条空 title 看看 url 情况
    rows = c.execute(text("""
        SELECT id, project_url, source_url FROM favorites
        WHERE title IS NULL OR title = ''
        LIMIT 3
    """)).fetchall()
    for r in rows: print(f"  id={r[0]} | url={r[1][:80]!r}")

    # 3. 回填: 从 projects_cqggzy 按 url 查 title, UPDATE favorites
    # 用 UPDATE ... FROM 一次搞定 (PostgreSQL 语法)
    result = c.execute(text("""
        UPDATE favorites f
        SET title = p.title,
            tender_type = COALESCE(NULLIF(f.tender_type, ''), p.tender_type),
            budget = COALESCE(NULLIF(f.budget, ''), p.budget),
            publish_date = COALESCE(NULLIF(f.publish_date, ''), p.publish_date),
            content_preview = COALESCE(NULLIF(f.content_preview, ''), p.content_preview, p.project_overview),
            updated_at = CURRENT_TIMESTAMP
        FROM projects_cqggzy p
        WHERE f.project_url = p.url
        AND (f.title IS NULL OR f.title = '')
        RETURNING f.id, f.title
    """))
    updated = result.fetchall()
    c.commit()
    print(f"\n✅ 从 projects_cqggzy 回填: {len(updated)} 条")
    for r in updated[:5]: print(f"  id={r[0]} | title={r[1][:50]!r}")

    # 4. 残余（projects_cqggzy 没匹配的）尝试从 projects_ccgp
    n_remain = c.execute(text("""
        SELECT COUNT(*) FROM favorites
        WHERE title IS NULL OR title = ''
    """)).scalar()
    print(f"\n残余空 title: {n_remain}")

    if n_remain > 0:
        result = c.execute(text("""
            UPDATE favorites f
            SET title = p.title,
                tender_type = COALESCE(NULLIF(f.tender_type, ''), p.tender_type),
                budget = COALESCE(NULLIF(f.budget, ''), p.budget),
                publish_date = COALESCE(NULLIF(f.publish_date, ''), p.publish_date),
                content_preview = COALESCE(NULLIF(f.content_preview, ''), p.content_preview, p.project_overview),
                updated_at = CURRENT_TIMESTAMP
            FROM projects_ccgp p
            WHERE f.project_url = p.url
            AND (f.title IS NULL OR f.title = '')
            RETURNING f.id, f.title
        """))
        updated2 = result.fetchall()
        c.commit()
        print(f"✅ 从 projects_ccgp 回填: {len(updated2)} 条")

    # 5. 最终统计
    n_final = c.execute(text("""
        SELECT COUNT(*) FROM favorites
        WHERE title IS NULL OR title = ''
    """)).scalar()
    n_total = c.execute(text("SELECT COUNT(*) FROM favorites")).scalar()
    print(f"\n📊 最终: 总 {n_total} | 仍空 title {n_final} | 覆盖率 {100*(n_total-n_final)/max(n_total,1):.1f}%")
