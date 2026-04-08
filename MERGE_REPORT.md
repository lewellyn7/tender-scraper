# MERGE_REPORT.md — OpenClaw 采集系统合并报告

**合并日期:** 2026-04-07
**源目录:** `~/.openclaw/workspace/scripts/`
**目标目录:** `~/tender-scraper/`

---

## 1. 合并概述

将 OpenClaw workspace 中独立开发的采集系统模块（异步爬虫基类、人类行为引擎、反检测、智能调度器、异常处理、数据库模型、缓存管理、API 服务、配置管理）合并到 `tender-scraper` 项目中。

---

## 2. 文件映射表

| 源文件 | 目标位置 | 说明 |
|---|---|---|
| `async_crawler_base.py` | `app/crawlers/async_base/__init__.py` | 异步爬虫基类 `HumanCrawlerBase` |
| `human_behavior_engine.py` | `app/core/harvest/human_behavior_engine.py` | 人类行为模拟引擎 |
| `anti_detect.py` | `app/core/harvest/anti_detect.py` | 反机器人检测规避 |
| `smart_scheduler.py` | `app/core/harvest/smart_scheduler.py` | 智能调度器 |
| `exception_handler.py` | `app/core/harvest/exception_handler.py` | 异常状态机 |
| `db_models.py` | `app/database/async_models.py` | PostgreSQL asyncpg 模型 |
| `cache_manager.py` | `app/core/harvest/cache_manager.py` | Redis 缓存 + 分布式锁 |
| `api_server.py` | `app/api/harvest_api.py` | FastAPI 采集服务 |
| `main.py` | `harvest_main.py` | CLI 统一入口 |
| `config.py` | `app/core/harvest/config.py` | 配置管理 |

### 测试文件

| 源文件 | 目标位置 |
|---|---|
| `tests/test_anti_detect.py` | `tests/test_harvest/test_anti_detect.py` |
| `tests/test_human_behavior_engine.py` | `tests/test_harvest/test_human_behavior_engine.py` |
| `tests/test_integration.py` | `tests/test_harvest/test_integration.py` |
| `tests/test_security_utils.py` | `tests/test_harvest/test_security_utils.py` |

---

## 3. 新增依赖 (requirements.txt)

```diff
+ asyncpg==0.29.0       # 异步 PostgreSQL (asyncpg)
+ redis[hiredis]==5.0.6  # 异步 Redis
+ numpy==1.26.4          # 智能调度器数值计算
+ python-dotenv==1.0.1   # 环境变量加载
```

---

## 4. 目录结构（合并后）

```
tender-scraper/
├── harvest_main.py              # NEW — CLI 统一入口
├── app/
│   ├── api/
│   │   ├── harvest_api.py       # NEW — FastAPI 采集服务
│   │   └── routes.py / ...
│   ├── core/
│   │   ├── harvest/              # NEW — 采集系统核心模块
│   │   │   ├── __init__.py
│   │   │   ├── anti_detect.py
│   │   │   ├── cache_manager.py
│   │   │   ├── config.py
│   │   │   ├── exception_handler.py
│   │   │   ├── human_behavior_engine.py
│   │   │   └── smart_scheduler.py
│   │   ├── browser.py
│   │   ├── concurrency_scheduler.py
│   │   └── ...
│   ├── crawlers/
│   │   ├── async_base/           # NEW — 异步爬虫
│   │   │   └── __init__.py (HumanCrawlerBase)
│   │   ├── base.py
│   │   ├── ccgp.py
│   │   └── cqggzy.py
│   ├── database/
│   │   ├── async_models.py       # NEW — asyncpg 数据模型
│   │   ├── db.py
│   │   └── repositories/
│   └── ...
└── tests/
    └── test_harvest/             # NEW
        ├── test_anti_detect.py
        ├── test_human_behavior_engine.py
        ├── test_integration.py
        └── test_security_utils.py
```

---

## 5. 关键模块说明

### 5.1 `app.crawlers.async_base.HumanCrawlerBase`
- 基于 Playwright 异步爬虫基类
- 集成 `HumanBehaviorEngine` 人类行为模拟
- 支持浏览器指纹随机化、反检测、代理轮换

### 5.2 `app.core.harvest.anti_detect`
- `FingerprintProfile`: 浏览器/WebGL/Canvas/TLS/DNS 指纹管理
- `AntiDetectManager`: 综合反检测策略管理器
- 支持 UA 池、视口随机化、Canvas 噪声注入

### 5.3 `app.core.harvest.smart_scheduler`
- `DynamicPriorityEngine`: 5因子动态优先级（紧急度/时效性/历史成功率/稳定性/热点加权）
- `AdaptiveIntervalManager`: 自适应采集间隔（基于成功率动态调整）
- `SmartScheduler`: 完整调度器，支持任务队列、优先级、重试策略

### 5.4 `app.core.harvest.exception_handler`
- `AnomalyClassifier`: 异常模式分类（429频率限制/403封禁/5xx错误/解析错误等）
- `ExceptionStateMachine`: 异常状态自动恢复状态机（退避/切换代理/重试/告警）

### 5.5 `app.core.harvest.cache_manager`
- `RedisManager`: 异步 Redis 连接池
- `CacheManager`: 采集结果缓存（TTL 支持）
- `TokenBucket`: 分布式限速
- `DistributedLock`: 分布式锁

### 5.6 `app.database.async_models`
- `DatabaseManager`: asyncpg 连接池管理
- `HarvestRecord`: 采集记录数据模型
- 支持 PostgreSQL 事务和 CRUD 操作

### 5.7 `app.api.harvest_api`
- FastAPI 服务，集成调度器 + 爬虫基类
- 端点: `POST /crawl`, `GET /status/{task_id}`, `GET /results/{task_id}`, `GET /stats`

---

## 6. 已知依赖关系

- `harvest_api.py` 依赖 `app.core.harvest.smart_scheduler` 和 `app.crawlers.async_base`
- `harvest_main.py` 依赖 `app.core.harvest.*` 和 `app.database.async_models`
- `HumanCrawlerBase` 依赖 `HumanBehaviorEngine`（同模块）
- `smart_scheduler` 依赖 `numpy`
- `db_models` 依赖 `asyncpg`
- `cache_manager` 依赖 `redis[hiredis]`

---

## 7. 注意事项

1. **迁移后需安装新依赖:** `pip install -r requirements.txt`
2. **数据库迁移:** `async_models.py` 中的 `DatabaseManager` 需要 PostgreSQL，可通过 `harvest_main.py db-migrate` 初始化表
3. **Redis 依赖:** `cache_manager` 需要 Redis 服务运行
4. **Playwright 浏览器:** 首次运行需执行 `playwright install --with-deps chromium`
5. **CLI 入口:** 使用 `python harvest_main.py --help` 查看可用命令
6. **测试:** 运行 `pytest tests/test_harvest/` 验证各模块
