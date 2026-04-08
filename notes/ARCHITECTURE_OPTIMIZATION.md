# 架构优化报告 — 2026-04-07

## 问题诊断

### 1. 爬虫继承体系断裂 ⚠️ HIGH
**现象：** `BaseCrawler` 定义了抽象方法 `fetch_list/fetch_detail`，但 `CQGGZYCrawlerV2` 和 `CCGPCrawlerV3` 均未继承它，而是各自实现了完整逻辑。

**影响：**
- 约 150 行 `_extract_contact_info`、`_extract_attachments`、`_parse_date` 在两个爬虫中完全重复
- URL 去重、批量采集等通用能力无法复用
- 后续维护需要改两处

**根因：** `CQGGZYCrawlerV2` 和 `CCGPCrawlerV3` 最初独立开发，之后才创建 `BaseCrawler`，但迁移未完成。

### 2. 入口文件碎片化 ⚠️ MEDIUM
**现象：** 4 个入口点功能高度重叠：
- `main.py` — CLI（使用 `HumanCrawlerBase`）
- `harvest_main.py` — asyncio 脚本（使用 `CQGGZYCrawlerV2`，导入了不存在的 `scripts/async_chongqing_procurement_refactored`）
- `ccgp_main.py` — asyncio 脚本（使用 `CCGPCrawlerV3`）
- `web_server.py` — FastAPI 服务

**影响：** 逻辑分散，无法统一调度；`harvest_main.py` 实际无法运行（导入错误）。

### 3. TenderFilter 双重实现 ⚠️ MEDIUM
**现象：** `extract_project_info` 对 `TenderInfo` 对象和 `dict` 各写了一套完整字段映射逻辑（约 80 行几乎相同的代码）。

### 4. ReportGenerator 字段映射错误 ⚠️ MEDIUM
**现象：** `field_mapping` 字典的 key 是中文列名，但 DataFrame 列是英文字段名，导致 rename 失效。

### 5. 配置体系分散 ⚠️ LOW
**现象：** 两套配置系统并存：
- `config/settings.py` — Pydantic `BaseSettings`
- `app/core/harvest/config.py` — dataclass `SystemConfig`

`main.py` 使用后者，`harvest_main.py` 使用前者。

### 6. 两套浏览器管理 ⚠️ LOW
**现象：**
- `StealthBrowser` — 独立管理 Playwright，方法较少
- `HumanCrawlerBase` — 完整包装，内置人类行为引擎

`BaseCrawler` 使用 `StealthBrowser`，`main.py` 的 SmartScheduler 使用 `HumanCrawlerBase`。

---

## 优化实施

### ✅ 已完成

#### 1. 重构 `BaseCrawler` — 成为真正的基类
**文件：** `app/crawlers/base.py`

新增通用方法：
- `_extract_contact_info()` — 通用联系人提取
- `_extract_attachments()` — 通用附件提取
- `_extract_field()` / `_extract_field_by_kw()` — 通用字段提取
- `_parse_date()` / `_parse_datetime()` — 通用日期解析
- `_extract_budget()` / `_extract_deadline()` / `_extract_bid_amount()` — 通用金额/截止时间
- `_mark_visited()` — 线程安全 URL 去重
- `fetch_details_batch()` — 信号量控制并发批量采集
- `_fetch_with_retry()` — 指数退避重试

#### 2. 重构 `CQGGZYCrawlerV2` — 继承 BaseCrawler
**文件：** `app/crawlers/cqggzy.py`

- 继承 `BaseCrawler`
- 删除约 120 行重复代码（联系人、附件、日期解析、预算/截止时间提取）
- 复用基类 `_extract_contact_info`、`_extract_attachments`、`_parse_date` 等
- 保留站点特有逻辑：`_extract_region`、`_extract_business_type`、`_extract_info_type`

#### 3. 重构 `CCGPCrawlerV3` — 继承 BaseCrawler
**文件：** `app/crawlers/ccgp.py`

- 继承 `BaseCrawler`
- 删除约 100 行重复代码
- 复用基类联系人、附件、日期解析、金额提取
- 保留站点特有逻辑：信息类型专用字段提取（采购意向/公告/结果公告）

#### 4. 重构 `TenderFilter.extract_project_info` — 统一字段提取
**文件：** `app/utils/filter.py`

- 提取 `_get_title()`、`_get_field()`、`_get_contact()`、`_get_attachments()`、`_fmt_date()`、`_fmt_kw()` 等辅助方法
- `extract_project_info()` 从 ~100 行重复代码压缩为 ~30 行统一调用
- 22 个字段输出（比之前多 4 个新字段）

#### 5. 修复 `ReportGenerator` 字段映射
**文件：** `app/utils/report.py`

- 正确建立英文字段名 → 中文列名映射 `COLUMN_RENAME`
- 优先列顺序标准化
- `generate_summary()` 重构简化

#### 6. 统一入口 `harvest_main.py`
**文件：** `harvest_main.py`

- 替换 `harvest_main.py` 和 `ccgp_main.py` 的重复逻辑
- 单一入口支持 `--source cqggzy|ccgp|all`
- `_process_results()` 统一：过滤 → 详情采集 → 报表生成 → JSON 持久化
- 使用 `BaseCrawler.fetch_details_batch()` 替代手动 asyncio.gather

---

## 架构现状（优化后）

```
                    ┌─────────────────────────────────────────┐
                    │           harvest_main.py               │
                    │     (统一入口: --source cqggzy|ccgp|all) │
                    └──────────────────┬──────────────────────┘
                                       │
           ┌───────────────────────────┼───────────────────────────┐
           │                           │                           │
    ┌──────▼──────┐          ┌───────▼───────┐          ┌────────▼────────┐
    │  cqggzy.py  │          │   ccgp.py      │          │   main.py       │
    │ (BaseCrawler│◄────────│  (BaseCrawler) │          │ (SmartScheduler │
    │  继承)      │  复用    │    继承)       │          │  + CLI)         │
    └──────┬──────┘          └───────┬───────┘          └────────┬────────┘
           │                         │
           │    ┌─────────────────────┤
           │    │  app/crawlers/base.py  │
           │    │  - URL 去重             │
           │    │  - 联系人提取            │
           │    │  - 附件提取              │
           │    │  - 日期/金额解析         │
           │    │  - 批量采集（信号量）    │
           │    │  - 指数退避重试          │
           │    └─────────────────────────┘
           │
    app/core/browser.py (StealthBrowser)
    app/utils/filter.py  (TenderFilter V2)
    app/utils/report.py   (ReportGenerator V2)
    app/models/tender.py  (TenderInfo dataclass)
```

---

## 待优化项

### 中期
1. **`app/core/harvest/` 模块清理** — `anti_detect.py`(57KB)、`smart_scheduler.py`、`exception_handler.py` 等是否被实际使用需确认
2. **`harvest_api.py` 清理** — 该文件内容为 tangent API 代码，导入不存在的模块，需确认是否废弃
3. **配置统一** — 选定一套配置系统（推荐 `app/core/harvest/config.py` 的 dataclass 方案），废弃 `config/settings.py`
4. **`api_server.py` 与 `web_server.py` 合并** — 两套 FastAPI 服务，职责重叠

### 长期
1. **`HumanCrawlerBase` vs `BaseCrawler``StealthBrowser`** — 统一为单一爬虫基类
2. **站点插件化** — 新增站点只需添加爬虫类文件，注册即可，无需修改入口
3. **数据库 ORM 统一** — 确认 `app/database/db.py` 与 `app/database/async_models.py` 的关系，合并为一套

---

*优化完成：2026-04-07 | 优化人：架构重构 subagent*
