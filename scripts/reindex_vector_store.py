"""
重新索引 vector_store 表（修复 6-5 向量库 URL 过期问题）

背景：
- 2026-06-01 修复 UUID 字段（syscollectguid → infoid）后，project URL 从
  https://www.cqggzy.com/xxhz/.../<date>/<uuid>.html
  改为
  https://www.cqggzy.com/trade/<category>/<uuid>?categoryNum=<num>
- 向量库 metadata.url 还是旧格式，导致 vector search 召回的 URL 0 匹配项目库
- 临时方案：在 API 层检测 vector URL 不匹配项目库时回退到 title+content 简单匹配
- 本脚本：清空向量库并用当前 URL 重新索引

用法:
  P=$(grep "^DB_PASSWORD=" ~/tender-scraper/.env | cut -d= -f2)
  docker exec -e "DBPASS=$P" -e "DBURL=postgresql://root:${P}@postgres:5432/tender_scraper" \\
    tender-scraper-web python3 /app/scripts/reindex_vector_store.py [--limit N] [--batch 50]
"""
import os
import sys
import time
import argparse
import psycopg2

sys.path.insert(0, "/app")

from app.services.vector_store import get_vector_store


def fetch_projects(conn, limit=None, offset=0):
    """从 projects_cqggzy 拉取需要向量化的项目。"""
    cur = conn.cursor()
    sql = """
        SELECT
            id, url, title, content_preview, full_content,
            publish_date, info_type
        FROM projects_cqggzy
        WHERE title IS NOT NULL AND title != ''
        ORDER BY publish_date DESC NULLS LAST
    """
    if limit:
        sql += f" LIMIT {int(limit)} OFFSET {int(offset)}"
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def truncate_vector_store(conn):
    """清空 vector_store 表。"""
    cur = conn.cursor()
    # pgvector 表名 vector_store, 先看 schema
    cur.execute("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_name = 'vector_store'
    """)
    rows = cur.fetchall()
    if not rows:
        print("⚠️  vector_store 表不存在，跳过清空")
        return
    schema, name = rows[0]
    full = f'"{schema}"."{name}"'
    print(f"🗑  清空 {full}")
    cur.execute(f"TRUNCATE TABLE {full}")
    conn.commit()


def build_doc(project: dict) -> dict:
    """从 project 记录构造 vector doc。"""
    title = project.get("title") or ""
    preview = project.get("content_preview") or ""
    full = (project.get("full_content") or "")[:500]
    # 总长控制在 1000 字符以内（避免 vLLM batch 400）
    text = f"{title}\n{preview}\n{full}".strip()[:1000]

    doc_id = f"tender_{project['id']}"
    metadata = {
        "url": project["url"],
        "title": title[:200],
        "publish_date": str(project.get("publish_date") or ""),
        "info_type": project.get("info_type") or "",
        "source": "cqggzy",
        "project_id": project["id"],
    }
    return {"id": doc_id, "text": text, "metadata": metadata}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="最多索引多少条（默认全部）")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--batch", type=int, default=50, help="每批多少条")
    ap.add_argument("--no-truncate", action="store_true", help="不清空向量库（增量更新）")
    args = ap.parse_args()

    dburl = os.environ.get("DBURL")
    if not dburl:
        print("❌ DBURL env var required")
        sys.exit(1)

    conn = psycopg2.connect(dburl)
    vs = get_vector_store()

    if not args.no_truncate:
        truncate_vector_store(conn)

    projects = fetch_projects(conn, limit=args.limit, offset=args.offset)
    total = len(projects)
    print(f"📚 准备索引 {total} 条")

    if total == 0:
        print("✅ 无可索引项目，退出")
        return

    inserted = 0
    failed = 0
    t_start = time.time()
    for i in range(0, total, args.batch):
        batch = projects[i:i + args.batch]
        docs = [build_doc(p) for p in batch]
        try:
            result = vs.upsert_documents(docs)
            inserted += result.get("inserted", len(docs))
            elapsed = time.time() - t_start
            rate = inserted / elapsed if elapsed > 0 else 0
            eta = (total - inserted) / rate if rate > 0 else 0
            print(
                f"  [{inserted:>5}/{total}]  "
                f"+{len(docs):<3}  "
                f"elapsed={elapsed:.0f}s  "
                f"rate={rate:.1f}/s  "
                f"ETA={eta:.0f}s"
            )
        except Exception as e:
            failed += len(docs)
            print(f"  ❌ 批次 {i} 失败: {e}")
            continue

    elapsed = time.time() - t_start
    print(f"\n🎉 完成: inserted={inserted} failed={failed} elapsed={elapsed:.0f}s")
    print(f"📊 新向量库 size: {vs.stats()['total_vectors']}")


if __name__ == "__main__":
    main()
