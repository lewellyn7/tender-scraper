#!/usr/bin/env python3
"""ChromaDB → pgvector 数据迁移脚本

用法:
    python scripts/migrate_chroma_to_pg.py [--limit 100]

从 ChromaDB (./data/chromadb) 读取 tender_documents collection，
提取所有向量数据，写入 PostgreSQL vector_store 表。
"""
import argparse
import json
import sys, os, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Env
os.environ["DATABASE_URL"] = "postgresql://root:root123@localhost:5435/tender_scraper"
os.environ["VECTOR_STORE_BACKEND"] = "chromadb"  # 强制 ChromaDB 后端读取

from loguru import logger

# ── Silence loguru ────────────────────────────────────────
import loguru
loguru.logger.remove()

logger.add(sys.stderr, level="INFO")


def _text_for_doc(metadata: dict, text: str = "") -> str:
    """从 metadata 构造 pgvector text 字段"""
    parts = []
    for key in ("title", "source", "source_name", "tender_type", "budget", "url"):
        v = metadata.get(key) or ""
        if v:
            parts.append(f"{key}: {v}")
    if text:
        parts.append(f"text: {text[:300]}")
    return " | ".join(parts) if parts else text[:300]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="最多迁移 N 条 (0=全部)")
    parser.add_argument("--dry-run", action="store_true", help="仅预览")
    args = parser.parse_args()

    # 1. 读取 ChromaDB
    logger.info("[migrate] Connecting to ChromaDB...")
    import chromadb
    client = chromadb.PersistentClient(path="./data/chromadb")
    coll = client.get_or_create_collection("tender_documents")
    total = coll.count()
    logger.info(f"[migrate] ChromaDB tender_documents: {total} vectors")
    if total == 0:
        logger.info("Nothing to migrate, done.")
        return

    # 2. 读取所有数据
    all_ids = coll.get()["ids"]
    if args.limit > 0:
        all_ids = all_ids[: args.limit]

    batch_size = 50
    migrated = 0
    errors = 0

    for i in range(0, len(all_ids), batch_size):
        batch_ids = all_ids[i : i + batch_size]
        try:
            result = coll.get(ids=batch_ids, include=["embeddings", "metadatas", "documents"])
            ids_list = result["ids"]
            emb_list = result["embeddings"]
            meta_list = result["metadatas"]

            docs = []
            for doc_id, emb, meta, doc_text in zip(
                ids_list, emb_list, meta_list, result.get("documents", [])
            ):
                if not emb:
                    continue
                text = _text_for_doc(meta or {}, doc_text or "")
                docs.append(
                    {
                        "id": doc_id,
                        "text": text,
                        "metadata": meta or {},
                        "embedding": emb,
                    }
                )

            if not docs:
                continue

            if args.dry_run:
                logger.info(f"[dry-run] Would migrate {len(docs)} docs: {[d['id'] for d in docs]}")
                continue

            # 3. 直接用 psycopg2 写入 pgvector（不依赖 app 模块）
            import psycopg2.extras
            pg_conn = psycopg2.connect(
                "postgresql://root:root123@postgres:5432/tender_scraper"
            )
            cur = pg_conn.cursor()
            for doc_id, emb, meta in zip(
                ids_list, emb_list, meta_list
            ):
                if not emb:
                    continue
                text = _text_for_doc(meta or {}, "")
                cur.execute(
                    "INSERT INTO vector_store (doc_id, text, metadata, embedding) "
                    "VALUES (%s, %s, %s, %s::vector) "
                    "ON CONFLICT (doc_id) DO UPDATE SET "
                    "text=excluded.text, metadata=excluded.metadata, embedding=excluded.embedding",
                    (doc_id, text, json.dumps(meta or {}), emb),
                )
            pg_conn.commit()
            cur.close()
            pg_conn.close()
            migrated += len(ids_list)
            logger.info(f"[migrate] upserted {len(ids_list)} docs (total: {migrated}/{total})")

        except Exception as e:
            logger.error(f"[migrate] Batch error at offset {i}: {e}")
            errors += 1

    logger.info(
        f"[migrate] Done. migrated={migrated}, errors={errors}, "
        f"total_chroma={total}"
    )


if __name__ == "__main__":
    main()
