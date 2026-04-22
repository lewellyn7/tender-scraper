#!/usr/bin/env python3
"""
将 vector_store (2560 维) 的向量切片到 1024 维 (取前 1024 个分量)
写入 vector_store_1024 表
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
import psycopg2.extras
import json
import ast
from loguru import logger

# 移除 loguru 文件处理器
import loguru
loguru.logger.remove()
logger.add(sys.stderr, level="INFO")

def main():
    # 1. 连接数据库 (Docker Compose 网络)
    conn = psycopg2.connect("postgresql://root:root123@postgres:5432/tender_scraper")
    cur = conn.cursor()
    
    # 2. 读取所有 2560 维向量
    logger.info("Reading 2560-dim vectors from vector_store...")
    cur.execute("SELECT doc_id, text, metadata, embedding FROM vector_store")
    rows = cur.fetchall()
    total = len(rows)
    logger.info(f"Found {total} vectors")
    
    if total == 0:
        logger.info("No vectors to migrate")
        return
    
    # 3. 插入新表 (简单切片：取前 1024 维)
    logger.info("Inserting into vector_store_1024 (slice first 1024 dims)...")
    for i, (doc_id, text, metadata, embedding_str) in enumerate(rows):
        # embedding 是字符串，需要解析
        embedding = ast.literal_eval(embedding_str)
        # 切片到 1024 维
        emb_1024 = embedding[:1024]
        # 转为 pgvector 的字符串格式 (不带空格)
        emb_str = '[' + ','.join(str(v) for v in emb_1024) + ']'
        
        cur.execute(f"""
            INSERT INTO vector_store_1024 (doc_id, text, metadata, embedding)
            VALUES (%s, %s, %s, %s::vector(1024))
            ON CONFLICT (doc_id) DO UPDATE SET
                text=excluded.text,
                metadata=excluded.metadata,
                embedding=excluded.embedding
        """, (doc_id, text, psycopg2.extras.Json(metadata) if metadata else '{}', emb_str))
        
        if (i + 1) % 20 == 0:
            logger.info(f"  Processed {i+1}/{total}")
    
    conn.commit()
    cur.close()
    conn.close()
    
    logger.info(f"✅ Migration complete: {total} vectors migrated to vector_store_1024 (1024-dim slice)")

if __name__ == "__main__":
    main()
