-- ============================================================
-- pgvector HNSW 索引创建脚本 (P0-2)
-- 目标表: vector_store (2560 维, Qwen3-Embedding-4B)
-- 创建时间: 2026-06-11
-- 关联 PR: feat/pgvector-hnsw-index
-- ============================================================

-- 1. 验证环境
SELECT
    extversion AS pgvector_version
FROM pg_extension
WHERE extname = 'vector';
-- 期望: 0.5.0+ (本环境 0.8.2)

-- 2. 验证表结构
SELECT
    column_name,
    data_type,
    character_maximum_length
FROM information_schema.columns
WHERE table_name = 'vector_store'
  AND column_name = 'embedding';
-- 期望: data_type = 'vector', dim = 2560

-- 3. 检查现有索引
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'vector_store'
ORDER BY indexname;

-- 4. 检查文档数量
SELECT COUNT(*) AS total_vectors
FROM vector_store;
-- 当前 14K 量级

-- ============================================================
-- 5. 创建 HNSW 索引（在线模式）
-- 参数说明:
--   m = 16              # 每个节点连接数（推荐 16，过大过小都影响精度）
--   ef_construction = 64 # 构建时的候选列表（推荐 64-200，越大越精确但构建慢）
--   vector_cosine_ops   # 余弦距离（适合 normalized embedding）
--
-- CONCURRENTLY: 不锁表，运行时可读可写
-- 注意: CONCURRENTLY 不能在事务中执行
-- ============================================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS vector_store_hnsw_idx
ON vector_store
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- 6. 设置运行时查询参数（建议 100，平衡精度/速度）
-- 写入 postgresql.conf 或 session 级：
-- SET hnsw.ef_search = 100;
-- 注: 应用层可在 PGVectorBackend.search() 中显式 SET

-- 7. 验证索引已创建
SELECT
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename = 'vector_store'
  AND indexname = 'vector_store_hnsw_idx';

-- 8. 性能对比测试
-- 测试 1: seq scan (无索引)
SET enable_indexscan = off;
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT id, doc_id, embedding <=> (
    SELECT embedding FROM vector_store LIMIT 1
) AS distance
FROM vector_store
ORDER BY embedding <=> (
    SELECT embedding FROM vector_store LIMIT 1
)
LIMIT 10;

-- 测试 2: HNSW index scan
SET enable_indexscan = on;
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT id, doc_id, embedding <=> (
    SELECT embedding FROM vector_store LIMIT 1
) AS distance
FROM vector_store
ORDER BY embedding <=> (
    SELECT embedding FROM vector_store LIMIT 1
)
LIMIT 10;
-- 期望: Index Scan using vector_store_hnsw_idx

-- ============================================================
-- 回滚脚本 (如需删除索引)
-- DROP INDEX CONCURRENTLY IF EXISTS vector_store_hnsw_idx;
-- ============================================================
