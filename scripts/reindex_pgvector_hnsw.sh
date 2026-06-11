#!/bin/bash
# ============================================================
# pgvector HNSW 索引创建脚本 (P0-2)
# 创建时间: 2026-06-11
# 关联 PR: feat/pgvector-hnsw-index
#
# 用法:
#   ./scripts/reindex_pgvector_hnsw.sh [--dry-run]
#
# 前置条件:
#   1. docker compose 已运行 (容器 tender-scraper-postgres)
#   2. 已备份 vector_store 表
#   3. 业务低峰时段 (建议 14:00-16:00 或 02:00-04:00)
#
# 风险:
#   🟢 低 — HNSW 是 pgvector 0.5+ 标准索引
#   ⚠️ 构建期间 CPU 占用高，可能短暂影响查询延迟
# ============================================================
set -e

cd "$(dirname "$0")/.."

# 解析参数
DRY_RUN=false
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=true
fi

# 加载 .env
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# 校验容器运行
if ! docker ps --format "{{.Names}}" | grep -q "tender-scraper-postgres"; then
    echo "❌ tender-scraper-postgres 容器未运行"
    exit 1
fi

PG="docker exec tender-scraper-postgres psql -U root -d tender_scraper"
SQL_FILE="scripts/create_hnsw_index_vector_store.sql"

echo "=== pgvector HNSW 索引创建 ==="
echo "目标: tender-scraper-postgres / tender_scraper"
echo "表: vector_store (2560 维)"
echo "模式: $([ "$DRY_RUN" = true ] && echo 'DRY-RUN' || echo 'EXECUTE')"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo "🔍 DRY-RUN: 打印 SQL 不执行"
    cat "$SQL_FILE"
    exit 0
fi

# 1. 验证 pgvector 版本
echo "🔍 1. 验证 pgvector 版本"
$PG -t -c "SELECT extversion FROM pg_extension WHERE extname='vector';"

# 2. 检查现有向量数
echo ""
echo "🔍 2. 当前 vector_store 行数"
$PG -t -c "SELECT COUNT(*) FROM vector_store;"

# 3. 备份表结构
echo ""
echo "🔍 3. 备份表结构"
mkdir -p .pre-qual-feature/p0-prep-2026-06-11
docker exec tender-scraper-postgres pg_dump -U root -d tender_scraper -t vector_store --schema-only \
    > .pre-qual-feature/p0-prep-2026-06-11/vector_store_schema_pre_hnsw.sql
echo "已保存到 .pre-qual-feature/p0-prep-2026-06-11/vector_store_schema_pre_hnsw.sql"

# 4. 执行 HNSW 创建
echo ""
echo "🚀 4. 创建 HNSW 索引 (可能耗时 5-15 分钟)"
echo "开始时间: $(date)"
START_TS=$(date +%s)
$PG -c "CREATE INDEX CONCURRENTLY IF NOT EXISTS vector_store_hnsw_idx ON vector_store USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);" 2>&1
END_TS=$(date +%s)
echo "结束时间: $(date)"
echo "耗时: $((END_TS - START_TS)) 秒"

# 5. 验证索引
echo ""
echo "🔍 5. 验证索引"
$PG -c "\d vector_store" 2>&1 | grep -E "hnsw|Indexes" || echo "⚠️ 索引未找到"

# 6. 性能测试
echo ""
echo "🔍 6. 性能测试 (HNSW Index Scan)"
$PG -c "SET hnsw.ef_search = 100; EXPLAIN (ANALYZE, BUFFERS) SELECT id, doc_id, embedding <=> (SELECT embedding FROM vector_store LIMIT 1) AS distance FROM vector_store ORDER BY embedding <=> (SELECT embedding FROM vector_store LIMIT 1) LIMIT 10;" 2>&1

echo ""
echo "✅ HNSW 索引创建完成"
echo ""
echo "回滚命令 (如需):"
echo "  docker exec tender-scraper-postgres psql -U root -d tender_scraper -c 'DROP INDEX CONCURRENTLY IF EXISTS vector_store_hnsw_idx;'"
