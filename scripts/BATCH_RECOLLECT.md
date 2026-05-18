# 分批次重新采集指南

## 背景

由于之前采集器只写入 SQLite，PostgreSQL 中的 800 条记录缺少 `full_content` 字段，导致 `project_overview` 只能基于标题生成（内容较简略）。

通过分批次重新采集，可以：
- 从数据库中读取已有 URL
- 逐批采集详情页，获取完整内容
- 自动更新 `full_content` 和 `project_overview`
- 避免并发压力过大触发反爬
- 支持中断后续采（进度持久化）

## 快速开始

### 方式一：使用 Shell 脚本（推荐）

```bash
cd ~/tender-scraper

# 采集重庆市公共资源交易网（每批 20 条，延时 5 秒）
./scripts/batch-recrawl.sh cqggzy 20 5

# 采集重庆市政府采购网（每批 10 条，延时 10 秒）
./scripts/batch-recrawl.sh ccgp 10 10

# 重试之前失败的记录
./scripts/batch-recrawl.sh cqggzy 20 5 true
```

### 方式二：直接调用 Python 脚本

```bash
cd ~/tender-scraper

# 基础用法
docker compose exec web python -m scripts.batch_recrawl_simple \
    --source cqggzy \
    --batch-size 20 \
    --delay 5

# 重试失败记录
docker compose exec web python -m scripts.batch_recrawl_simple \
    --source ccgp \
    --batch-size 10 \
    --delay 10 \
    --retry-failed

# 限制最大批次数（测试用）
docker compose exec web python -m scripts.batch_recrawl_simple \
    --source cqggzy \
    --batch-size 5 \
    --delay 3 \
    --max-batches 2
```

## 参数说明

| 参数 | 说明 | 默认值 | 示例 |
|------|------|--------|------|
| `--source` | 数据源：`cqggzy` 或 `ccgp` | 必填 | `cqggzy` |
| `--batch-size` | 每批采集数量 | 20 | `10` |
| `--delay` | 批次间延时（秒） | 5 | `10` |
| `--retry-failed` | 重试失败记录 | false | `--retry-failed` |
| `--max-batches` | 最大批次数（测试用） | 不限制 | `2` |

## 进度管理

### 进度文件
采集进度保存在 `scripts/.batch_recrawl_progress.json`

格式：
```json
{
  "cqggzy": {
    "processed": ["url1", "url2", ...],
    "failed": ["url3", ...],
    "done": false
  },
  "ccgp": {...}
}
```

### 中断后续采
脚本会自动读取进度文件，从中断处继续。

如果要重新开始：
```bash
# 删除进度文件
rm ~/tender-scraper/scripts/.batch_recrawl_progress.json

# 或者手动编辑，清空 processed 列表
```

### 查看进度
```bash
cat ~/tender-scraper/scripts/.batch_recrawl_progress.json | jq .
```

## 采集逻辑

### CQGGZY（重庆市公共资源交易网）
- 自动判断类别：URL 包含 `014005` → 政府采购，否则 → 工程建设
- 调用 `crawler.fetch_detail(url, category=...)`
- 生成 `project_overview` 基于 10 条结构化规则

### CCGP（重庆市政府采购网）
- 自动判断信息类型：
  - URL 包含 `intention` → 采购意向
  - URL 包含 `result` → 结果公告
  - 默认 → 采购公告
- 调用 `crawler.fetch_detail(url, info_type=...)`
- 生成 `project_overview` 基于 10 条结构化规则

## 输出示例

```
==========================================
🚀 分批次重新采集
==========================================
数据源：cqggzy
每批数量：20
批次延时：5 秒
==========================================

2026-05-09 23:30:00.000 | INFO     | 🚀 开始分批次采集：cqggzy
2026-05-09 23:30:01.000 | INFO     | 📊 数据库共有 800 条记录
2026-05-09 23:30:01.000 | INFO     | 📋 待采集：800 条

==================================================
📦 第 1/40 批 (20 条)
==================================================

2026-05-09 23:30:02.000 | INFO     | 🔍 https://www.cqggzy.com/xxhz/014005/...
2026-05-09 23:30:05.000 | INFO     | ✅ 某办公设备采购项目...
2026-05-09 23:30:06.000 | INFO     | 🔍 https://www.cqggzy.com/xxhz/014001/...
...

💾 进度：已处理 20 条，失败 0 条
⏱️  延时 5 秒...

==================================================
📦 第 2/40 批 (20 条)
==================================================
...
```

## 注意事项

### 1. 反爬策略
- 批次间延时建议 ≥ 5 秒
- 每批数量建议 ≤ 20
- 避免在业务高峰期采集

### 2. 失败处理
- 失败的 URL 会记录在 `failed` 列表
- 可使用 `--retry-failed` 重试
- 检查失败原因：日志中的错误信息

### 3. 数据库更新
- 使用 `upsert_projects()` 写入
- URL 重复时更新已有记录
- `full_content` 和 `project_overview` 会自动更新

### 4. 资源占用
- 采集过程在 Docker 容器内运行
- 每个批次会创建/关闭浏览器页面
- 大量采集时注意内存占用

## 验证采集结果

### 检查 full_content 填充率
```bash
cd ~/tender-scraper
docker compose exec -T web python -c "
import psycopg2
conn = psycopg2.connect('postgresql://root:root123@localhost:5435/tender_scraper')
cur = conn.cursor()
cur.execute('SELECT COUNT(*), COUNT(full_content), COUNT(CASE WHEN full_content != \"\" THEN 1 END) FROM projects_cqggzy')
r = cur.fetchone()
print(f\"projects_cqggzy: 总计 {r[0]} 条，有 full_content 的 {r[1]} 条，full_content 非空 {r[2]} 条\")
cur.execute('SELECT COUNT(*) FROM projects_ccgp')
print(f\"projects_ccgp: {cur.fetchone()[0]} 条\")
conn.close()
"
```

### 查看最新采集记录
```bash
cd ~/tender-scraper
docker compose exec -T web python -c "
import psycopg2
conn = psycopg2.connect('postgresql://root:root123@localhost:5435/tender_scraper')
cur = conn.cursor()
cur.execute(\"SELECT title, LENGTH(full_content), project_overview FROM projects_cqggzy WHERE full_content != '' ORDER BY updated_at DESC LIMIT 5\")
for r in cur.fetchall():
    print(f'{r[0][:30]}... | full_content: {r[1]} chars | overview: {r[2][:50]}...')
conn.close()
"
```

## 故障排除

### 问题：采集器启动失败
```bash
# 检查容器日志
docker compose logs web

# 检查浏览器是否正常
docker compose exec web playwright install chromium
```

### 问题：数据库连接失败
```bash
# 检查数据库容器
docker compose ps postgres

# 检查数据库日志
docker compose logs postgres
```

### 问题：进度文件损坏
```bash
# 删除后重新采集
rm ~/tender-scraper/scripts/.batch_recrawl_progress.json
```

### 问题：采集结果为空
检查：
1. URL 是否正确
2. 网络是否可达
3. 是否需要登录
4. 选择器是否变化

## 下一步

采集完成后：
1. 验证 `full_content` 填充率
2. 检查 `project_overview` 质量
3. 在数据页面查看展示效果
4. 如有问题，调整 `summarize.py` 规则

---
文档更新时间：2026-05-09
