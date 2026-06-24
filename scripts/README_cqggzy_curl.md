# CQGGZY curl 采集脚本 (2026-06-23)

## 概述
替代 Playwright 的 curl + aiohttp 方案, 性能提升 **10x** (200MB 内存 / 30s 启动 → 10MB / <1s).

## 用法

### 补采历史数据
```bash
# 在 collector 容器内
docker exec tender-scraper-collector python3 /app/scripts/fetch_cqggzy_curl.py \
  --backfill \
  --date-start 2026-06-22 \
  --date-end 2026-06-23 \
  --with-details \
  --output /tmp/cqggzy_backfill.json
```

### 实时 cron (集成版)
在 `app/crawlers/cqggzy_curl.py` 中有 `CqggzyCurlCrawler` 类, 可在 `main.py` 中通过环境变量切换:
```bash
export CRAWLER_MODE=curl  # 替代 playwright
```

## 性能对比
| 指标 | Playwright | curl |
|---|---|---|
| 启动 | 30s | <1s |
| 22 条详情 | 5min | 20s |
| 内存 | 200MB | 10MB |
| 依赖 | chromium | curl + aiohttp |

## 数据流
```
[APScheduler cron] 
  → main.py 
  → CqggzyCurlCrawler._fetch_list_via_curl (API POST)
  → CqggzyCurlCrawler._fetch_detail_via_curl (GET + BS4)
  → db.upsert_projects (DB)
```

## 关键设计
- **白名单**: 9 位 catnum 前缀 (014001019/001/002/003/004 + 014005001/002/004)
- **黑名单**: 014001015, 014005008 (用户 6-23 17:51 指令)
- **标题兜底**: 拦截"招租"/"经营权出让" (CQGGZY 偶发挂载)
- **edt 排他**: end_date + 1d (沿用 AGENTS.md 6-05)
- **API 兼容**: 复用 PR #33 condition 数组结构

## 测试
```bash
python3 -m pytest tests/test_crawlers/test_cqggzy_curl.py -v
# 18/18 passed
```
