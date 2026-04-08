# 🔍 代码审查报告 - tender-scraper
**审查时间**: 2026-04-07 20:54 GMT+8
**审查范围**: 完整项目代码
**综合评分**: 6.5/10

---

## 1. 代码风格

### ✅ 做得好的
- 有 `pyproject.toml` 配置 black/isort/ruff，格式规范有章可循
- 日志使用 `loguru`，输出格式统一
- 有 `.pre-commit-config.yaml`，CI 规范化初步到位
- 模块划分较清晰（crawlers/services/database/repositories）

### ⚠️ 问题
| 问题 | 数量 | 示例 |
|------|------|------|
| 未使用 import (F401) | 25+ | `harvest_api.py` 单独文件 9 个未使用 import |
| 模块级 import 不在顶部 (E402) | 1 | `harvest_api.py` |
| 未定义名称 (F821) | 4 | `SmartScheduler`, `CrawlTask`, `BehaviorFingerprint` |
| 未使用局部变量 (F841) | 4 | 多处 `e`, `url`, `row` 赋值未用 |

**ruff check 输出**：39 个 lint 错误，主要是未使用 import 和未定义名称。

**核心问题**：`harvest_api.py` 有条件导入（`if TYPE_CHECKING` 应该用但没有），导致大量 F401。

### 🚨 高危风格问题
1. **ccgp_crawler.py / cqggzy_crawler.py** 仍使用 `logger.info(f"✅ ...")` 和 `logger.warning(f"⚠️ ...")` — emoji 日志不适合结构化日志系统
2. **cqggzy_crawler.py** 多个 `except Exception as e: pass` — 吞掉错误，用户完全不知道发生了什么

---

## 2. 错误处理

### 🚨 严重问题

**❌ 入口文件引用不存在的模块 — 程序根本无法运行！**

```python
# harvest_main.py:57
from scripts.async_chongqing_procurement_refactored import ChongqingProcurementRefactored
#                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# scripts/ 目录根本不存在！

# harvest_main.py:72
crawler_cls = _get_crawler_class("ChongqingProcurementRefactored")
# 调用时会失败 ImportError
```

`harvest_main.py` 导入了不存在的 `scripts/async_chongqing_procurement_refactored.py`，这是一个**致命阻塞性 bug** — 运行 `python harvest_main.py run ...` 会直接崩溃。

**类似问题存在于 `main.py:57`**：
```python
from scripts.async_chongqing_procurement_refactored import ChongqingProcurementRefactored
```

### ⚠️ 一般性问题
1. **cqggzy_crawler.py**: 多处 `except Exception as e: pass` 和 `except Exception as e: logger.warning(...)`，错误被静默吞噬
2. **exception_handler.py**: 架构设计良好，但 `__main__` 块中的 `demo()` 是同步调用而非异步，可能误导用户
3. **ccgp_crawler.py**: `except Exception as e: logger.debug(...)` — debug 级别在生产环境看不到
4. **harvest_main.py**: 所有命令（`cmd_run`, `cmd_schedule` 等）catch 住异常后仅 log，调用方没有错误状态码，CLI 行为不一致

---

## 3. 性能问题

### ✅ 做得好的
- **cqggzy_crawler.py**: URL 去重用 `Set[str]` + `asyncio.Lock`，并行采集用 `asyncio.Semaphore(concurrency=5)`，设计合理
- **cqggzy_crawler.py**: `asyncio.gather` 并行采集多个列表/详情页
- **ccgp_crawler.py**: `asyncio.sleep(2)` 在 `networkidle` 后再次等待，不必要但无害

### ⚠️ 潜在问题
1. **browser.py**: `StealthBrowser` 是类而非单例，但 `_playwright`/`_browser`/`_context` 实例变量无锁保护 — 多线程/协程共享同一实例时可能出问题
2. **db.py**: 单例模式 `_instance` 用 `threading.Lock`，但 `sqlite3` 的 `check_same_thread=False` 削弱了线程隔离，高并发下可能有竞争
3. **db.py**: WAL 模式配置了，但 `_batch_writer` 用 `queue.Queue()` + `threading.Thread`，batch size 和 flush 逻辑需确认是否真的生效
4. **anti_detect.py**: `FingerprintProfile.generate()` 每次调用创建新的 `np.random.default_rng(seed)`，在高频调用场景下可能重复 seed

---

## 4. 测试覆盖

### 测试文件统计
```
tests/test_harvest/test_anti_detect.py        702 行
tests/test_harvest/test_integration.py       573 行
tests/test_harvest/test_security_utils.py    559 行
tests/test_harvest/test_human_behavior_engine.py  374 行
tests/test_db/test_database.py                 65 行
tests/test_api/test_security.py               32 行
tests/test_utils/test_security.py             31 行
```
**总计**: 2,374 行测试代码，17 个测试文件

### ✅ 做得好的
- 反检测模块有专项测试（anti_detect, human_behavior_engine）
- 集成测试覆盖较完整（test_integration.py 573行）
- 有 conftest.py 提供 fixture

### 🚨 严重问题
1. **harvest_main.py / main.py 的 CLI 命令完全没有测试** — `cmd_run`, `cmd_schedule`, `cmd_db_migrate` 均无单元/集成测试
2. **crawlers/ccgp.py 和 crawlers/cqggzy.py 完全没有单元测试** — 采集器是核心逻辑
3. **API routes 没有测试** — `routes.py` 的页面渲染函数、API 端点均无测试
4. **覆盖率不明** — 没有 `pytest --cov` 配置，无法量化

---

## 5. 文档完整性

### ✅ 做得好的
- `README.md` 有基本使用说明
- `ARCHITECTURE.md` 有系统架构图
- `CODE_QUALITY_CRITIQUE.md` 有详细代码批判
- `pyproject.toml` + `.pre-commit-config.yaml` 规范文档齐全

### 🚨 严重问题
1. **文档过时** — `README.md` 提到的目录结构（`app/crawlers/cqggzy_crawler.py`）与实际不符，实际是 `app/crawlers/cqggzy.py`
2. **入口无法运行** — 没有文档说明 `harvest_main.py` vs `main.py` vs `ccgp_main.py` 的关系和选择
3. **harvest_main.py 引用了不存在的脚本** — 没有任何警告或说明
4. **archive/old_versions/** 目录有旧代码，但没有说明为何保留和与新代码的差异

---

## 6. 关键阻塞性 Bug

| 优先级 | 问题 | 影响 |
|--------|------|------|
| 🔴 致命 | `harvest_main.py` / `main.py` 导入不存在的 `scripts/async_chongqing_procurement_refactored.py` | **程序无法启动** |
| 🔴 致命 | `harvest_main.py:cmd_run()` 调用 `_run_crawler()` 但 `_get_crawler_class()` 永远 raise `ImportError` | **所有 run 命令崩溃** |
| 🟠 高 | `cqggzy_crawler.py` 的 `asyncio.sleep(0.3 + random.random()*0.5)` 在高频采集时仍是瓶颈 | 采集速度受限 |
| 🟡 中 | `ccgp_crawler.py` 和 `cqggzy_crawler.py` 选择器降级逻辑重复 | 维护成本高 |

---

## 7. 已知问题修复状态

| 问题 | 报告时间 | 状态 |
|------|----------|------|
| routes.py 424行上帝文件 | 2026-04-05 | ⚠️ 部分解决（有 routes/routes/ 子目录，但主 routes.py 仍119行） |
| db.py 795行上帝文件 | 2026-04-05 | ⚠️ 部分解决（有 repositories/ 目录，但 db.py 仍915行） |
| bare `except:` | 2026-04-05 | ⚠️ 部分改善，但仍存在多处 |
| 贫血模型无 Service 层 | 2026-04-05 | ❌ 未解决（`project_service.py` 仅1个简单服务） |

---

## 8. 改进建议

### 立即修复（阻塞）
1. **创建或删除** `scripts/async_chongqing_procurement_refactored.py` — 如果不需要则修改 `harvest_main.py`
2. **统一入口** — 明确 `main.py` / `harvest_main.py` / `ccgp_main.py` 各自职责
3. 清理 `harvest_api.py` 的 9 个未使用 import

### 短期优化（1-2周）
1. 为 `ccgp_crawler.py` 和 `cqggzy_crawler.py` 添加单元测试
2. 为 `harvest_main.py` CLI 命令添加测试
3. 统一选择器降级逻辑到基类
4. 给 `StealthBrowser` 增加实例锁或改为上下文管理器

### 中期改进（1个月）
1. 继续拆分 `db.py`（仍915行）→ 迁移到 repository 模式
2. 添加 pytest-cov 配置，设定覆盖率目标 > 60%
3. 更新 README.md 的目录结构
4. 给所有 API 端点补充集成测试

---

## 📊 总结

| 维度 | 评分 | 说明 |
|------|------|------|
| 代码风格 | 7/10 | 规范有章，但lint错误39个 |
| 错误处理 | 5/10 | 有exception_handler，但入口有致命bug |
| 性能 | 7/10 | asyncio并行设计好，但细节有竞争风险 |
| 测试覆盖 | 5/10 | 测试代码总量不少，但核心爬虫无测 |
| 文档 | 5/10 | 有批判文档，但入口无法运行 |

**最大问题**：项目有两个断开的入口（`harvest_main.py` 和 `main.py` 都引用不存在的 `scripts/` 模块），这表明重构过程中有重大变更未完成。
