-- ============================================================
-- 向量数据库初始化脚本 (pgvector)
-- 用于创建 vector 扩展和 vectors 表
-- ============================================================

-- 1. 启用 pgvector 扩展
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. 创建 vectors 表
-- embedding: 1024维向量 (NVIDIA NIM embed-qa_4 模型输出维度)
-- tender_id: 关联的 tender 记录 ID (可选)
-- text: 原始文本内容
-- metadata: JSONB 存储附加属性 (来源、发布时间等)
CREATE TABLE IF NOT EXISTS vectors (
    id              BIGSERIAL PRIMARY KEY,
    tender_id       BIGINT REFERENCES harvest_records(id) ON DELETE CASCADE,
    embedding       VECTOR(1024) NOT NULL,
    text            TEXT NOT NULL,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. 创建索引 (HNSW 索引，检索性能更好)
CREATE INDEX IF NOT EXISTS idx_vectors_embedding_hnsw
    ON vectors USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 4. 创建 tender_id 索引 (加速按标书ID查询)
CREATE INDEX IF NOT EXISTS idx_vectors_tender_id
    ON vectors(tender_id) WHERE tender_id IS NOT NULL;

-- 5. 创建 text 全文索引 (辅助检索)
CREATE INDEX IF NOT EXISTS idx_vectors_text_fts
    ON vectors USING gin (to_tsvector('simple', text));

COMMENT ON TABLE vectors IS '招投标文本向量存储表';
COMMENT ON COLUMN vectors.embedding IS '1024维向量 (NVIDIA NIM embed-qa_4 或 sentence-transformers paraphrase-multilingual-MiniLM-L12-v2)';
COMMENT ON COLUMN vectors.metadata IS '附加元数据: source, publish_date, budget, tender_type 等';
