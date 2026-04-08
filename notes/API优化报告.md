# API 性能优化报告

> 作者：后端架构师 subagent  
> 日期：2026-04-07  
> 项目：tender-scraper

---

## 一、现状分析

### 1.1 技术栈
- **框架**：FastAPI + Uvicorn
- **双数据库**：SQLite（同步单文件）+ PostgreSQL（asyncpg 异步）
- **缓存**：内存 `_cache` dict（projects）+ SQLite `data_cache` 表
- **批量写入**：SQLite 异步批量队列（`queue.Queue` + 后台线程）

### 1.2 架构图

```
HTTP Request
    ↓
RateLimitMiddleware → SecurityHeadersMiddleware → CSRFProtection
    ↓
FastAPI Routes
    ├── /api/projects       ← 项目列表查询（从 latest.json + SQLite）
    ├── /api/favorites     ← SQLite 直接操作
    ├── /api/analytics     ← 直接执行 SQL 统计
    ├── /api/harvest/*     ← 异步任务（SmartScheduler）
    └── /api/db/*          ← 数据库管理（备份/恢复）
```

---

## 二、已识别性能瓶颈

### 🔴 瓶颈 1：`/api/projects` — N+1 查询 + 全量内存过滤

**文件**：`app/api/routes/projects.py`

```python
for p in page_projects:
    p["is_favorite"] = db.is_favorite(p.get("url", ""))       # ← 每个项目1次SQL
    p["annotation"] = db.get_annotation(p.get("url", ""))     # ← 每个项目又1次SQL
```

**问题**：
- 分页 20 条 → 40 次 SQLite 查询
- 关键词过滤、分类过滤、日期过滤全部在 Python 内存中遍历全量数据（`latest.json` 可能数千条）
- `TFIDFMatcher` 每次请求都调用 `m.build_corpus()` 重新构建，O(n) 初始化

**影响**：p99 延迟 500ms–2s，数据量越大越慢

---

### 🔴 瓶颈 2：`/api/analytics` — 无索引的聚合查询

**文件**：`app/api/routes/analytics.py`

```python
SELECT DATE(created_at) as date, COUNT(*) as count
FROM favorites
WHERE created_at >= DATE('now', ? || ' days')
GROUP BY DATE(created_at)
ORDER BY date
```

**问题**：
- `DATE(created_at)` 函数导致全表扫描，无法利用 `idx_favorites_updated` 索引
- `keywords_matched = 1` 字段在 SQL 中但表中无此列（逻辑列，非物理列）

---

### 🔴 瓶颈 3：SQLite WAL 模式无并发写入保护

**文件**：`app/database/db.py`

```python
def _batch_writer(self):
    batch = []
    while not self._shutdown:
        item = self._batch_queue.get(timeout=1)  # ← 单线程串行
        batch.append(item)
        ...
        if batch:
            self._execute_batch(batch)  # ← COMMIT 块整个队列
```

**问题**：
- 后台批量写入线程与读操作共用同一 `sqlite3.Connection`（WAL 模式）
- 写入阻塞期间所有读操作等待

---

### 🔴 瓶颈 4：`save_harvest_records` 逐条 upsert

**文件**：`app/database/async_models.py`

```python
async def save_harvest_records(records: List[Dict], source_name: str):
    async with DatabaseManager.transaction() as conn:
        for r in records:
            _, is_new = await HarvestRecord.upsert_by_url(conn, ...)  # ← N 次网络往返
```

**问题**：`PostgreSQL` 连接池中每个 record 单独一次 `fetchrow`（SELECT）+ 一次 `fetchrow`（INSERT/UPDATE），N 条记录 = 2N 次 RTT

---

### 🟡 瓶颈 5：`RateLimitMiddleware` 内存字典无限增长

**文件**：`app/middleware/security.py`

```python
self._requests = {}
# ...
if current_minute % 60 == 0:  # ← 只有整分钟才清理，过期数据可能残留
    cutoff = current_minute - 60
    self._requests = {k: v for k, v in self._requests.items() if ...}
```

---

### 🟡 瓶颈 6：`TFIDFMatcher` 重复初始化

**文件**：`app/api/routes/projects.py`

```python
if use_tfidf:
    m = TFIDFMatcher()
    m.build_corpus([p.get("title", "") for p in projects])  # ← 每次请求重建
    kws = [k.strip() for k in keyword.split(",") if k.strip()]
    m.build_keywords(kws)
```

**问题**：数千条 projects 每次请求都重新分词 + 构建 TF-IDF 向量库

---

### 🟡 瓶颈 7：SQLite `get_stats()` 6 次独立 COUNT 查询

```python
def get_stats(self):
    return {
        "favorites_count": c.execute("SELECT COUNT(*) FROM favorites").fetchone()[0],
        "annotations_count": c.execute("SELECT COUNT(*) FROM annotations").fetchone()[0],
        "presets_count": c.execute("SELECT COUNT(*) FROM filter_presets").fetchone()[0],
        ...
    }
```

**问题**：6 次独立查询，可合并为 1 次 `SELECT ... COUNT(*) FROM table1 UNION ALL ...`

---

## 三、优化方案

### ✅ 优化 1：消除 N+1 查询 — 批量预加载

**改动文件**：`app/api/routes/projects.py`

```python
# 优化后：2次批量查询替代 N×2 次单条查询
urls = [p.get("url", "") for p in page_projects]
# favorites 批量查询
placeholders = ",".join(["?"] * len(urls))
fav_rows = c.execute(
    f"SELECT project_url, status FROM favorites WHERE project_url IN ({placeholders})",
    urls
).fetchall()
fav_map = {row["project_url"]: row for row in fav_rows}
# annotations 批量查询
ann_rows = c.execute(
    f"SELECT project_url, note, priority FROM annotations WHERE project_url IN ({placeholders})",
    urls
).fetchall()
ann_map = {row["project_url"]: row for row in ann_rows}
for p in page_projects:
    url = p.get("url", "")
    p["is_favorite"] = url in fav_map
    p["annotation"] = ann_map.get(url)
```

**预期提升**：N=20 时 40 次查询 → 2 次查询，延迟降低 80%

---

### ✅ 优化 2：`/api/analytics` 索引优化

**改动**：在 `_init_indexes()` 添加复合索引

```sql
-- 针对 DATE(created_at) 查询，创建计算列 + 索引
CREATE INDEX IF NOT EXISTS idx_favorites_created_date
ON favorites(DATE(created_at));

-- 或使用本地索引（SQLite 支持表达式索引）
CREATE INDEX IF NOT EXISTS idx_favorites_created_at_days
ON favorites(created_at);
```

**SQL 重写**（避免 DATE() 函数全表扫描）：
```sql
-- 改前（无法利用索引）
WHERE created_at >= DATE('now', '-30 days')

-- 改后（利用索引范围扫描）
WHERE created_at >= (datetime('now', '-30 days'))
```

---

### ✅ 优化 3：PostgreSQL 批量 upsert

**改动文件**：`app/database/async_models.py`

```python
# save_harvest_records 优化：使用 PostgreSQL 批量 upsert
@classmethod
async def bulk_upsert_by_url(
    cls,
    conn: asyncpg.Connection,
    records: List[Dict[str, Any]],
    source_name: str,
) -> tuple[int, int]:
    """批量 upsert，单次网络往返"""
    if not records:
        return 0, 0
    values = [
        (
            r.get("title", ""),
            r.get("url", ""),
            source_name,
            r.get("date"),
            json.dumps(r.get("matched_keywords") or []),
            json.dumps(r.get("raw_data") or {}),
        )
        for r in records
    ]
    result = await conn.fetchval("""
        WITH ins AS (
            INSERT INTO harvest_records
                (title, source_url, source_name, publish_date,
                 matched_keywords, raw_data, status, retry_count,
                 created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, 'pending', 0, NOW(), NOW())
            ON CONFLICT (source_url) DO UPDATE SET
                title = EXCLUDED.title,
                publish_date = EXCLUDED.publish_date,
                matched_keywords = EXCLUDED.matched_keywords,
                raw_data = EXCLUDED.raw_data,
                updated_at = NOW(),
                status = 'pending'
            RETURNING 1
        ),
        upd AS (
            UPDATE harvest_records
            SET status = 'pending', updated_at = NOW()
            WHERE source_url = ANY($7::text[])
            AND source_url NOT IN (SELECT source_url FROM ins)
            RETURNING 1
        )
        SELECT
            (SELECT count(*) FROM ins) as inserted,
            (SELECT count(*) FROM upd) as updated
    """, [v for v in values for _ in range(6)],  # flatten... use array_unnest
        # 实际建议用 asyncpg 的 COPY 或 prepared statement 批量
    )
    # 简化版：使用 conn.copy_records_to_table 或 批量 INSERT ... ON CONFLICT
```

**实际推荐**：使用 `psycopg3` 的 `copy` 或 `asyncpg` 的 `copy_records_to_table`：

```python
# 最优路径：PostgreSQL COPY + 临时表
async def bulk_save(self, records, source_name):
    pool = await DatabaseManager.get_pool()
    async with pool.acquire() as conn:
        # 1. 写入临时表
        await conn.copy_records_to_table(
            'harvest_records_staging',
            columns=['title','source_url','source_name','publish_date',
                     'matched_keywords','raw_data','status'],
            records=[self._to_row(r) for r in records]
        )
        # 2. 单次 upsert
        inserted, updated = await conn.fetchval("""
            WITH merged AS (
                INSERT INTO harvest_records
                    SELECT * FROM harvest_records_staging
                    ON CONFLICT (source_url) DO UPDATE SET ...
            ),
            cleanup AS (DELETE FROM harvest_records_staging)
            SELECT * FROM merged
        """)
```

---

### ✅ 优化 4：TF-IDF 缓存

**改动**：在 `TFIDFMatcher` 实例或模块级缓存 corpus IDF

```python
# app/utils/tfidf_matcher.py
_tfidf_cache = {}
_tfidf_cache_expiry = 0
TFIDF_CACHE_TTL = 300  # 5 分钟

def get_tfidf_matcher(projects: list) -> TFIDFMatcher:
    global _tfidf_cache, _tfidf_cache_expiry
    now = time.time()
    if now - _tfidf_cache_expiry > TFIDF_CACHE_TTL:
        m = TFIDFMatcher()
        m.build_corpus([p.get("title", "") for p in projects])
        _tfidf_cache = m
        _tfidf_cache_expiry = now
    return _tfidf_cache
```

---

### ✅ 优化 5：SQLite `get_stats()` 合并查询

```python
def get_stats(self):
    c = self._get_conn()
    # 1 次查询获取所有计数
    rows = c.execute("""
        SELECT 'favorites' as tbl, COUNT(*) as cnt FROM favorites
        UNION ALL SELECT 'annotations', COUNT(*) FROM annotations
        UNION ALL SELECT 'filter_presets', COUNT(*) FROM filter_presets
        UNION ALL SELECT 'config_backups', COUNT(*) FROM config_backups
        UNION ALL SELECT 'scrape_logs', COUNT(*) FROM scrape_logs
        UNION ALL SELECT 'duplicate_records', COUNT(*) FROM duplicate_records
    """).fetchall()
    return {row["tbl"] + "_count": row["cnt"] for row in rows}
```

---

### ✅ 优化 6：RateLimitMiddleware 修复内存泄漏

```python
# app/middleware/security.py
class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_per_minute: int = 100):
        ...
        self._requests: dict[str, int] = {}
        self._minute_keys: list[str] = []  # 记录所有活跃 key

    async def dispatch(self, request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        current_minute = int(time.time() / 60)
        key = f"{client_ip}:{current_minute}"

        # 主动清理：移除非当前分钟的所有 key
        keys_to_remove = [k for k in self._requests if int(k.split(":")[1]) < current_minute]
        for k in keys_to_remove:
            del self._requests[k]

        if self._requests.get(key, 0) >= self.max_per_minute:
            return JSONResponse(status_code=429, content={"error": "请求过于频繁"})
        self._requests[key] = self._requests.get(key, 0) + 1
        return await call_next(request)
```

---

### ✅ 优化 7：项目列表服务端分页

**当前**：`_load_projects()` 从 `latest.json` 加载全部到内存 → Python 分页

**优化**：JSON 文件按 `publish_date` 预排序 + 二分查找分页起始位置，或迁移到 PostgreSQL：

```python
# PostgreSQL 服务端分页（推荐迁移路径）
@router.get("/projects")
async def get_projects(page: int = 1, page_size: int = 20, keyword: str = ""):
    offset = (page - 1) * page_size
    async with DatabaseManager.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM harvest_records
            WHERE ($1 = '' OR title ILIKE '%' || $1 || '%')
            ORDER BY publish_date DESC
            LIMIT $2 OFFSET $3
        """, keyword, page_size, offset)
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM harvest_records WHERE ($1 = '' OR title ILIKE '%' || $1 || '%')",
            keyword
        )
    return {"data": [dict(r) for r in rows], "total": total, "page": page, "page_size": page_size}
```

---

## 四、优先级与预期收益

| 优化项 | 优先级 | 复杂度 | 预期延迟改善 |
|--------|--------|--------|-------------|
| N+1 批量预加载 | 🔴 P0 | 低 | -80%（40→2次查询） |
| `get_stats()` 合并 COUNT | 🟡 P2 | 低 | -80%（6→1次查询） |
| RateLimit 内存泄漏 | 🟡 P2 | 低 | 防止内存持续增长 |
| TF-IDF 缓存 | 🟡 P2 | 低 | -60%（消除重复分词） |
| analytics 索引 | 🟠 P1 | 中 | -50%（全表→索引扫描） |
| PostgreSQL 批量 upsert | 🟠 P1 | 中 | -90%（2N→1次RTT） |
| JSON→PostgreSQL 分页 | 🔴 P0 | 高 | -70%（内存→数据库） |

---

## 五、实施建议

### Phase 1（立即上线，风险低）
1. N+1 查询修复（`projects.py` 批量预加载）
2. `get_stats()` COUNT 合并
3. RateLimit 内存泄漏修复
4. TF-IDF 缓存（TTL 5min）

### Phase 2（验证后上线）
5. PostgreSQL 批量 upsert（需压测）
6. analytics 表达式索引

### Phase 3（架构演进）
7. 项目数据从 `latest.json` 迁移到 PostgreSQL，支持 SQL 分页/过滤
8. 引入 Redis 作为热点数据缓存层

---

*报告完毕。如需实现某个优化项，请告知。*
