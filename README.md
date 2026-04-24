# 重庆市招投标智能采集系统

自动采集重庆市政府采购网 (ccgp-chongqing.gov.cn) 和公共资源交易网 (cqggzy.com) 的招投标信息，支持语义检索、智能筛选、资质匹配和 Telegram 通知推送。

## 功能特点

### 采集能力
- ✅ **双源采集**: 重庆市政府采购网 + 重庆市公共资源交易网
- ✅ **三类信息**: 采购意向 / 采购公告 / 结果公告
- ✅ **内容摘要**: LLM 自动生成结构化摘要
- ✅ **关键词过滤**: exact / fuzzy / partial 三种匹配模式
- ✅ **反检测规避**: TLS 指纹、Canvas 噪声、WebGL 随机化、人类行为模拟
- ✅ **智能调度**: 5 因子动态优先级 (来源可信度、截止时间、历史成功率、请求间隔、关键词匹配)

### AI 能力
- ✅ **语义向量检索**: pgvector + vLLM Qwen3-Embedding-4B (2560 维 → HNSW 索引)
- ✅ **RAG 对话**: 基于采集历史的项目咨询
- ✅ **质量评估**: 投标人资质与招标要求智能匹配
- ✅ **T-3 截标提醒**: 截标日期临近时自动推送通知

### 工程能力
- ✅ **定时采集**: APScheduler (08:00 / 12:00 / 18:00)
- ✅ **分布式调度**: Redis Pub/Sub 解耦 Scheduler 与 Collector
- ✅ **Redis 去重**: URL 7 天 TTL 缓存，防重复采集
- ✅ **Docker 生产部署**: Web + Redis + PostgreSQL + Scheduler 四服务分离
- ✅ **监控告警**: Prometheus + Grafana + Alertmanager
- ✅ **审计日志**: 采集开始/成功/失败完整记录

---

## 快速部署

### 环境要求
- Docker + Docker Compose
- PostgreSQL 16 + pgvector 扩展
- Redis 7
- Python 3.12 (本地开发)

### 生产部署

```bash
# 1. 配置密钥
cp secrets/README.md secrets/.env
# 编辑 secrets/ 目录下的密钥文件

# 2. 启动服务
docker compose -f docker-compose.prod.yml up -d

# 3. 检查状态
curl http://localhost:8002/health
```

### 开发部署

```bash
# 1. 安装依赖
pip install -r requirements.txt
playwright install chromium

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入实际值

# 3. 启动服务
docker compose up -d postgres redis
python web_server.py
```

---

## 配置说明

### 环境变量 (.env / secrets/.env)

| 变量 | 说明 | 示例 |
|------|------|------|
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql://root:pass@postgres:5432/tender_scraper` |
| `REDIS_URL` | Redis 连接串 | `redis://:password@redis:6379/0` |
| `VLLM_EMBEDDING_URL` | vLLM Embedding API | `http://host.docker.internal:8000/v1/embeddings` |
| `EMBEDDING_MODEL` | Embedding 模型 | `Qwen/Qwen3-Embedding-4B` |
| `NVIDIA_API_KEY` | NVIDIA API Key | `nvapi-...` |
| `DEFAULT_ADMIN_PASSWORD` | 管理员密码 | (必填，无默认值) |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | `8770725035:AAE3...` |
| `TELEGRAM_CHAT_ID` | 通知接收者 ID | `612092563` |

### 采集关键词

通过 Web UI 管理 (路径: `/settings` → 关键词维护):
- **精确匹配 (exact)**: 子串包含即匹配
- **模糊匹配 (fuzzy)**: SequenceMatcher 相似度 ≥ 0.8
- **部分匹配 (partial)**: 短词优先前缀/片段匹配

默认关键词 (19 个): 智能化、数字化、信息化、人工智能、AI、智慧城市、智慧政务、数据治理、物联网、5G、区块链、云计算、大数据、数字孪生、工业互联网、智慧园区、智慧交通、智慧医疗、智慧教育

---

## 项目结构

```
tender-scraper/
├── main.py                      # 采集任务主入口 (asyncio.run(run_collection()))
├── web_server.py                 # FastAPI Web 服务入口
├── scheduler.py                  # APScheduler 调度器入口 (独立容器)
│
├── app/
│   ├── api/
│   │   ├── routes.py             # 页面渲染路由 (/dashboard, /data, /settings...)
│   │   ├── harvest_api.py         # 采集系统 REST API (/crawl, /status, /results)
│   │   ├── routes/                # 分模块 REST API (20+ 路由)
│   │   │   ├── projects.py        # 项目 CRUD
│   │   │   ├── favorites.py        # 收藏
│   │   │   ├── stats.py           # 统计
│   │   │   ├── search.py          # 搜索
│   │   │   ├── chat.py            # AI 对话 (RAG)
│   │   │   ├── vector_search.py   # 向量语义检索
│   │   │   ├── quality.py         # 质量评估
│   │   │   ├── tasks.py           # 任务管理
│   │   │   └── keywords.py        # 关键词维护
│   │   ├── dependencies.py        # 路由依赖注入 (认证)
│   │   └── metrics.py             # Prometheus 中间件 + /metrics 端点
│   │
│   ├── core/
│   │   ├── browser.py            # StealthBrowser (Playwright 封装，反检测)
│   │   ├── harvest/
│   │   │   ├── smart_scheduler.py # 5 因子动态优先级调度器
│   │   │   ├── anti_detect/       # TLS 指纹、Canvas、WebGL、DNS
│   │   │   └── human_behavior_engine.py  # 人类行为模拟
│   │   └── session_memory.py      # LLM 上下文窗口管理
│   │
│   ├── crawlers/
│   │   ├── base.py               # BaseCrawler (通用字段提取、URL 去重、重试)
│   │   ├── ccgp.py               # 中国政府采购网爬虫
│   │   ├── cqggzy.py             # 重庆公共资源交易网爬虫
│   │   └── async_base.py         # AsyncHumanCrawlerBase (异步版本)
│   │
│   ├── database/
│   │   ├── db.py                 # DatabaseManager (asyncpg 连接池 + SQLite 降级)
│   │   ├── async_models.py        # HarvestRecord ORM (asyncpg)
│   │   └── repositories/          # Repository 模式 (favorite, project, annotation...)
│   │
│   ├── services/
│   │   ├── llm_service.py         # LLM 摘要/分类 (vLLM HTTP API)
│   │   ├── vector_store.py         # 向量存储 (pgvector + HNSW 索引)
│   │   ├── keywords_service.py    # 关键词 CRUD + 模糊匹配
│   │   ├── qualification_matcher.py # 投标人资质匹配
│   │   ├── quality_evaluation.py   # 质量评估
│   │   ├── recommendation_service.py # 推荐服务
│   │   └── health_monitor.py       # 系统健康检查
│   │
│   ├── models/
│   │   ├── tender.py              # TenderInfo (25 字段)
│   │   └── schemas.py              # Pydantic 模型 (User, Project, Login...)
│   │
│   ├── middleware/
│   │   └── security.py             # HTTPS 强制、安全头、请求日志、限流
│   │
│   ├── security/
│   │   └── audit.py               # 审计日志 (crawl_started/completed/failed)
│   │
│   └── templates/                  # Jinja2 HTML 模板 (dashboard, data, settings...)
│
├── services/
│   └── ragflow_service.py          # RAGFlow API 客户端
│
├── scripts/
│   ├── init_pg.sql                # PostgreSQL 建表脚本 (16 表 + pgvector)
│   ├── migrate_chroma_to_pg.py     # ChromaDB → pgvector 数据迁移
│   ├── migrate_1024_pca.py         # 2560 维 → 1024 维切片迁移
│   ├── backfill_vectors.py         # 批量向量入库
│   └── backup.sh                   # 数据库备份脚本
│
├── config/
│   └── settings.py                 # Pydantic Settings 配置
│
├── docker-compose.yml              # 开发环境配置
├── docker-compose.prod.yml         # 生产环境配置
├── Dockerfile                      # 多阶段构建 (Builder → Base → Runtime)
└── monitoring/                      # Prometheus + Grafana 配置
    ├── prometheus/
    │   ├── prometheus.yml
    │   └── rules/tender-scraper.yml
    ├── grafana/
    │   └── provisioning/
    └── alertmanager/
        └── alertmanager.yml
```

---

## API 参考

### 采集 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/crawl` | 触发采集任务 |
| `GET` | `/status/{task_id}` | 查询任务状态 |
| `GET` | `/results/{task_id}` | 获取采集结果 |
| `GET` | `/stats` | 统计信息 |

### 业务 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET/POST` | `/api/projects` | 项目 CRUD |
| `GET/POST` | `/api/favorites` | 收藏管理 |
| `GET` | `/api/search` | 全文搜索 |
| `GET` | `/api/vector/search` | 语义向量检索 |
| `POST` | `/api/chat` | AI RAG 对话 |
| `GET/POST` | `/api/keywords` | 关键词管理 |
| `GET/POST` | `/api/presets` | 筛选预设 |
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/metrics` | Prometheus 指标 |

### 页面路由

| 路径 | 说明 |
|------|------|
| `/` | 仪表盘 |
| `/content` | 采集数据列表 |
| `/settings` | 系统设置 |
| `/favorites` | 收藏夹 |
| `/analytics` | 数据分析 |
| `/logs` | 审计日志 |

---

## 数据模型

### TenderInfo (25 字段)

| 分类 | 字段 |
|------|------|
| 核心 | `title`, `url`, `category`, `publish_date` |
| 来源 | `source_url`, `source_name` |
| 业务 | `business_type`, `info_type` |
| 内容 | `content_preview` (300字), `full_content`, `attachments`, `contact_info` |
| 金额 | `budget`, `bid_amount` |
| 时间 | `deadline`, `opening_date` |
| 地区/行业 | `region`, `industry`, `tender_type` |
| 工程专用 | `project_overview`, `bidder_requirements`, `submission_deadline/submission_location` |
| 元数据 | `keywords_matched`, `scraped_at`, `scraped_by` |

### 数据库表

- `harvest_records` — 采集记录
- `users` — 用户 (ADMIN / EDITOR / VIEWER)
- `projects` — 项目 (PENDING / MATCHED / REJECTED / ARCHIVED)
- `favorites` / `annotations` / `keywords` — 业务扩展表
- `bidder_qualifications` — 投标人资质
- `filter_presets` / `logs` / `duplicates` / `cache` / `backup` — 系统表
- `vector_store` — 向量存储 (2560 维，原始数据)
- `vector_store_1024` — 向量存储 (1024 维，HNSW 索引)

---

## 监控告警

### Prometheus 指标

- `tender_scraper_http_requests_total` — HTTP 请求计数
- `tender_scraper_http_request_duration_seconds` — 请求延迟
- `tender_scraper_harvest_records_total` — 采集记录数
- `tender_scraper_quality_score` — 质量评分

### 告警规则

| 告警 | 条件 | 严重度 |
|------|------|--------|
| `WebServiceDown` | `up{job="tender-scraper-web"} == 0` 持续 1m | critical |
| `HighHarvestFailureRate` | 采集失败率 > 10% 持续 5m | warning |
| `QualificationExpiringSoon` | 资质 7 天内到期 | warning |

### Grafana Dashboard

- `tender-scraper-overview.json` — 系统总览
- `tender-scraper-qualifications.json` — 资质管理

---

## 安全

### 已修复的安全问题 (2026-04-19)

| ID | 问题 | 修复方案 |
|----|------|----------|
| H-1 | 时序攻击 | `hmac.compare_digest` |
| H-2 | CSRF 绕过 | 匿名 POST 请求已拒绝 |
| H-3 | 临时文件权限 | `tempfile.mkdtemp(mode=0o700)` |
| H-4 | traceback 泄露 | `logger.exception()` 替代 |
| H-5 | 未授权 API 访问 | `Depends(get_current_user)` 全覆盖 |

### 认证机制

- Session Token 认证 (Cookie 或 `X-Session-Token` Header)
- 双模式部署: 自用模式 (免登录) / 团队模式 (完整认证)

---

## 更新日志

### 2026-04-24
- ✅ 凭证硬化: `DEFAULT_ADMIN_PASSWORD` 移除默认值，生产强制显式配置
- ✅ pgvector HNSW 索引: 新增 `VectorStoreServiceIndexed`，自动切片 2560→1024 维
- ✅ 调度器解耦: Redis Pub/Sub (Scheduler → Collector Worker)

### 2026-04-22
- ✅ PostgreSQL 全量迁移: ChromaDB → pgvector (59 条向量)
- ✅ Docker Secrets 生产配置: `secrets/` 目录完整配置

### 2026-04-21
- ✅ Scheduler Bug 修复: 删除 `app/config.py` (遮蔽 `config/settings` 模块)
- ✅ 多字段查重: 5 维度加权评分算法

### 2026-04-19
- ✅ Redis 去重集成: URL 7 天 TTL 缓存
- ✅ 安全审计: 5 项 High 漏洞全部修复
- ✅ 向量入库自动化: `_upsert_to_vector_store()` 集成到采集流程

### 2026-04-09
- ✅ 测试套件修复: 262/262 通过
- ✅ Alpine.js → 原生 JavaScript 重构
- ✅ Docker 部署优化

---

## License

MIT
