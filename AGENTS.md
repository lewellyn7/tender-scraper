# AGENTS.md - 仓库级 Agent 协作规则

> 本文件是项目级 AGENTS.md, 位于 /home/lewellyn/tender-scraper/.
> 个人工作区规则位于 /home/lewellyn/.openclaw/workspace/AGENTS.md.

## 关键 Lesson (2026-06-17 累积)

### PR force-push 后 GitHub 自动同步

**事件:** force-push 修复分支后担心 PR 不会自动刷新 commits.

**发现:** GitHub PR 会**自动检测** force-push 并刷新 commits 列表, 不需要 close/reopen.

**规则:** force-push 修复分支后:
1. `git push origin <branch> --force-with-lease`
2. `gh pr view <id> --json commits,state` 验证 PR 已同步
3. 不需要额外操作

### rebase 后 detached HEAD 陷阱

**事件:** `git rebase --onto d86b5c7 65ee1f7d def01a88` 后新 commits 在 detached HEAD, `refs/heads/<branch>` 还指向旧 SHA. `git push --force` 报 "Everything up-to-date" 实际是空操作.

**根因:** rebase 在 detached HEAD 上执行, 完成时只更新 HEAD, 没动 branch ref.

**修复:**
```bash
git branch -f <branch> HEAD  # 强制移动 branch ref
git push origin <branch> --force
```

**规则:** rebase 后**必须** `git branch -f <branch> HEAD` 再 push, 否则 push 不会生效且不报错.

### PR Squash 合并 + Code Scanning 未启用仓库

**事件:** PR #19 合并时 Security Audit 失败, 阻塞所有 PR 合并.

**根因:** 仓库 Code scanning 未在 GitHub Settings 启用, 与代码无关.

**临时方案:** `gh pr merge <id> --squash --admin` 绕过 CI (需 main 仓库 admin).

**长期方案:** GitHub Settings → Code security → Enable Code scanning.


---

## bid_parser 实战经验 (2026-06-18)

### parse_tender_result() 4 格式适配

CQGGZY 工程招投标·中标结果公示 真实样本分 4 类:

| 类别 | 样本 | 关键特征 |
|------|------|----------|
| **A 类 (2019- 老)** | `拟 中 标 人 xxx 中标金额 (万元) 3044 工商注册号 91410726MA3X69CU1F` | 单位在 `(万元)` 括号里, 数字在后面, 一行内连续字段, 无换行 |
| **B 类 (2024+ 新)** | `中标人信息\n单位名称 xxx\n中标金额（费率、单价等） 100元` | 块状, "单位名称" 单独一行 |
| **C 类 (规范)** | `中标人：xxx 中标金额：100万元` | 经典"键:值"格式 |
| **D 类 (英文表格)** | `1 xxx 1,750,000.00 ... 3 中标人 1,663,100.00 ... 中标人名称：xxx 咨询受理联系人:...` | 表格 + 后续字段, "中标人的中标价" 不在"中标金额"字段里 |

**A 类必须 2 个独立捕获**: 名字 + 金额。 名字 regex `拟中标人[：:\s]+([^\n]+?)(?= 中标金额|工商注册号|...)` 用 non-greedy + 显式停点; 金额 regex `中标金额\s*[(（]\s*(万元|元|费率,单价等)\s*[)）]\s*([0-9.,]+?)` 把括号单位作为 hint 拼到数字后传给 parse_amount。

### noise suffix 过滤顺序很关键

新格式 `单位名称 中机中联工程有限公司 社会信用代码 9150010720288713XA 法定代表人 赵永勃`:
- **先** `_split_multi_winners` 按顿号切 → 一段
- **然后** `_strip_noise_suffix` 按顺序跑 10+ 个 regex 划断 "中标结果公示.pdf" / "社会信用代码" / "法定代表人" / "联合体牵头人" 等

**坑**: 若先 split('：') 切冒号再 strip_suffix, 中文全角冒号 `：` 切在"社会信用代码"前, 留下 "中机中联工程有限公司 社会信用代码" 段. 必须**先 strip 后 split**.

### 联合体识别

`单位名称 A、B、C` (顿号分隔) → 切 3 段, rank=1 全部 (联合体都 rank=1). 真正的"第一中标人"应只取牵头人 (牵头单位), 不取成员单位. **当前实现简化**: 一律 rank=1, 数据上有歧义但金额聚合正确.

### 容器内 docker cp 路径

Backfill 脚本 import 走 `app.utils.bid_parser`, 容器内 Python sys.path 含 `/app`, 所以**实际路径是 `/app/app/utils/bid_parser.py`** (不是 `/app/utils/...`!). Docker cp 时必须 cp 到正确路径, 不然模块不更新. **坑**: 早期 cp 到 `/tmp/bid_app/...` 没生效, 排查 30min.

### UPSERT savepoint 隔离

`bid_results` 表 UNIQUE(source, project_id, package_no, winner_name). 单条失败 (savepoint ROLLBACK) 不影响 batch 后续. **关键**: 用 `seen` set 内存去重避免同 batch 重复 ON CONFLICT, 数据库 UNIQUE 兜底.

### 工程招投标默认无金额

候选人公示 (第一候选人) 通常**不含报价** (`bid_amount_num=0`), 用户查"工程招投标排名" 应:
- 默认按 `info_type=中标结果公示` (最终中标人) 才看金额
- 提供 `info_type` 参数 (2026-06-18 加) 让前端按需切换
- 不要用 `total_amount=0` 当数据缺失判断 (要 COUNT(DISTINCT project_id) > 0)

### D 类英文表格暂未适配

`1,663,100.00` 在英文表格里, 需从"中标人名称:xxx" 后的"中标人的中标价" 字段提. 当前 D 类 2 条样本 (慕叶/世纪超星) 金额为 NULL, 排名靠后. **可优化**: 提取 No.X 行中标人行 紧跟的第 1 个数字作为 bid_amount.

### stopword 黑名单 (2026-06-18 加)

`winner_name = '其他'` (1 条) 误匹, 应过滤. 加到 _split_multi_winners:
```python
if not name or name in ('企业资质', '企业业绩', '其他', '无', '/', '—'):
    continue
```



### 重医附一院采集 (fahcqmu) - 2026-06-25 (PR #39)

**事件:** 新增第三方采集源 (重庆医科大学附属第一医院, fahcqmu.cn), 7 个分类 + 1667 条首次全量.

**关键发现:**

1. **翻页方式**: URL 后加 `/p/N` 路径后缀 (`base/p/1` 等同 `base`)
   - **必须带 Cookie `visited=1`**, 否则返回 1.3KB shell (与详情页不同, 详情是 1283 字节)
   - 0 items 停止 (空页 ~46KB, 无 `li > a`)
   - 总务处 (cgglczb2) /p/1-51, 信息数据处 (xxsjc1) /p/1-11
   - 各分类独立翻页, 互不影响

2. **Doc ID 编码 15 位数字** (全站共享递增序列):
   - `0101008/009` = 总务处 cggg/jggs
   - `0101415` = 其他 (qt, 总务旧分类)
   - `0101604/005/006/007` = 信息数据处 dygg/ygtjgg/cggg/cgjggs
   - org_unit 从 URL 前缀推断

3. **详情页结构统一**:
   - 首次访问返 1.3KB shell + JS `if(!document.cookie.includes('visited=1'))` reload
   - 带 Cookie 后 SSR HTML, `div.news-content` 含完整公告文本
   - `<h1>` 含标题, `<span class="time">` 含日期

4. **数据规模 vs 预测**:
   - 预测: ~202 条 (基于 page=1 visible)
   - 实际: 1667 条 (page=1 only 显示 53, 翻页后大 8x)
   - 总务处是主战场 (1465 条 = 88%)

5. **NULLIF(EXCLUDED.timestamp, '') 失败 bug** (在 ccgp 上也 pre-existing):
   - 错误: `invalid input syntax for type timestamp: ""`
   - 原因: PostgreSQL TIMESTAMP 字段与 TEXT `''` 不能直接比较
   - 修复: `CASE WHEN EXCLUDED.x IS NOT NULL THEN EXCLUDED.x ELSE table.x END`
   - 影响: upsert_projects_ccgp 同样有 bug, 待后续 PR 修复

**Schema 决策 (projects_fahcqmu):**
- 与 projects_ccgp 同构 (37 cols)
- 加 `org_unit` 字段 (信息数据处 / 总务处 / 其他)
- 加索引: url, publish_date, info_type, org_unit, business_type
- business_type = '医院采购' (新枚举)

**采集策略 (run_fahcqmu_collection):**
- 独立函数, 不修改现有 CQGGZY pipeline
- 7 类并行翻页 (`asyncio.gather`)
- 详情并发 5 (防反爬)
- 列表 → 关键词过滤 (复用 TenderFilter) → 详情 → upsert → JSON+Excel
- 启用方式: `python harvest_main.py run --source fahcqmu`

**教训:**
- 调研阶段: 单一列表页只能看到 page=1 数据, 必须找到分页机制才能评估真实规模
- Cookie 反爬在 SSR 站点上表现为 shell 重定向, 必须带正确 cookie 才能解析
- "已存在" 的 NULLIF 模式在 TIMESTAMP 类型上不通用, TEXT 才行



## CQGGZY URL 后缀 + cp/fc 同源 (2026-07-21, PR #87 + #88)

### Bug 1: `_1` 后缀错链 (PR #87)

**事件:** 2026-07-21 用户报 YCQ26B00018 (采购更正公告) 详情页是空壳 113KB, 0 匹配.

**根因:** 采集器对所有 014005 类目都自动给裸 infoid 加 `_1` 后缀, 但实际上 `_1/_2/_3/_4/_5` 只有 **014005004 (采购结果公告)** 才是合法的多版本修订; **014005001 (采购公告) / 014005002 (变更公告)** 加 `_1` 会指向空壳.

**修复:**
```python
if (infoid and '_' not in infoid and infoid.isdigit()
    and raw_catnum.startswith('014005004')):
    infoid = f'{infoid}_1'
```

**规则:** API 返回的 infoid 格式**因类目而异**——加后缀前**必须**确认该类目允许多版本 (实际抓一个样本链接验证). 不能"所有 014005 都加 `_1`" 这种一刀切假设. commit `45f55db` 当时"修 25,861 URLs" 实则破了 138 条记录, 因为没核对类目差异.

### Bug 2: cp 与 fc 提取路径分歧 (PR #88)

**事件:** 2026-07-21 用户报 DZQ26B00010 cp 是 nav, fc 是正文.

**根因:** 详情阶段 cp = `make_content_preview(<body> 前 500 字符)` 但 fc = `<div class="app-detail">` 抽的真正文. **两个字段走了不同的提取路径**, 结果不一致.

**修复:**
```python
# 旧
tender.content_preview = make_content_preview(full, tender.title)
# 新 (cqggzy.py:622/729/754, cqggzy_curl.py:295/342/351/361)
tender.content_preview = clean_cqggzy_text(full, hard_truncate_to=500)
```

**规则:** 数据库里**相关字段必须同源同路径**. 若 A 字段从 X 路径提取, B 字段也从 X 路径提取, 不能再各自跑独立抽取. CQGGZY 这里的 cp/fc、name/code、publish_date/publish_date_raw 都要遵循这条.

### 部署教训: PR merge ≠ 容器代码更新 (关键!)

**事件:** PR #87 merge 后 47 秒, 用户报 CQS26B00891 仍未修复. 排查发现 web 容器跑的是 7-15 镜像烤进去的旧代码 (容器内 cqggzy.py mtime `2026-07-14 11:39`, 新守卫 `raw_catnum.startswith('014005004')` **根本不存在**). 同时 16:00 定时 cron 用旧代码写了 71 条新错链 (scraped_at 在 16:00:06~16:01:43).

**根因:** merge 只更新了 main 仓库代码, **容器里没动**. CI 重建镜像需要 push 触发, PR 上 Build & Push Image SKIPPED, merge 后才触发, 但用户期望是 merge 后立刻可用.

**修复流程 (PR merge 后立即执行):**
```bash
# 1. merge
git checkout main && git pull --ff-only
# 2. 立即 hot-patch 容器 (临时方案)
docker cp app/crawlers/<x>.py tender-scraper-web:/app/app/crawlers/<x>.py
docker cp app/utils/<y>.py tender-scraper-web:/app/app/utils/<y>.py
docker restart tender-scraper-web
# 3. 验证: 容器代码 mtime 必须反映新 commit 时间
docker exec tender-scraper-web stat -c '%y' /app/app/crawlers/<x>.py
# 4. 等 CI 重建镜像 (Build & Push Image run, 长线方案)
```

**规则:** 合并 ≠ 生效. **merge 后必须**单独验证容器代码 mtime 反映新 commit. 在 CI 镜像重建期间, 用 docker cp hot-patch 覆盖; 否则定时 cron 会用旧代码继续写脏数据.

### nav 三层防护 (clean_cqggzy_text)

**事件:** 即便抽到 `<div class="app-detail">`, 仍可能有 `<style>` CSS block / nav app menu / 尾部"免责声明" / "国家部委网站" 噪音.

**根因:** 单层正则容易漏场景. CQGGZY 页面 nav 关键词 10+ 个 ("APP下载" / "重庆公共资源APP" / "渝产权APP" / "公众号" / "人民法院诉讼资产网" / "首页 资讯动态" / "您当前的位置" / "交易信息" / "工程招投标" / "采购公告" / ...).

**三层防护 (app/utils/cqggzy_text.py):**
1. **抽取层**: 优先 `<div class="app-detail">` (纯正文容器, 1370 bytes) — 最稳
2. **fallback 层**: `<div class="detail-wrapper">` + `clean_cqggzy_text` (regex 找正文 marker)
3. **清洗层**: `_strip_css_noise` (去 `<style>` block) + `_strip_tail_noise` (去"免责声明...") + `_strip_nav_app_menu` (去 nav 关键词)

**规则:** 不要单靠一层防护. 多层组合, 互为兜底. 新增 nav 关键词时**先看真实页面**, 别凭空想象关键词.

### 站点撤回检测 (backfill 必做)

**事件:** backfill 偶遇 2 条 404 "暂无内容" (大足区城市管理局食堂食材采购 / 重庆体彩全渠道内容制作), 返回 113KB 空壳.

**根因:** 业主已撤回公告但 URL 还存在. 详情页成空壳但状态码 200, 抓详情脚本不能判空.

**修复:** 抓详情页时检查 "404 暂无内容" / "页面不存在" / "已撤回" / "公告已删除" 等关键词, 遇到时**清空 cp 和 fc** (而不是保留空白或错误信息), 标记数据为"已被业主撤回".

**SQL 模式:**
```sql
UPDATE projects_cqggzy SET content_preview=NULL, full_content=NULL, updated_at=NOW()
WHERE id IN (...) AND (content_preview LIKE '%404 暂无内容%' OR ...);
```

**规则:** 抓详情脚本必须区分"抓失败" (网络问题) 和"业主撤回" (合法状态). 前者重试, 后者清空. 不要把撤回数据当成"空"——前端展示时也要区分这两种空.

---

## Watchdog 静默期跨日边界 (2026-07-22, commit c62c793)

### Bug: 静默期"点态"判断在跨日边界失效
- **现象**: 21:00 成功采集后到次日 08:04 (静默期结束 4min 后) watchdog 巡检,
  `last_crawl_age=11.1h` > 2.5h 阈值 → 误报 (count=447, status=ok, failures=0).
- **根因**: 现有 `_is_quiet_hour()` 是**点态**判断, 只防"当前在静默期内".
  跨日静默边界 (08:00 静默期刚结束) 立即告警, 而新 cron 还没跑起来.
- **用户拍板 (2026-07-22 08:53):** "晚上 8 点到第二天 8 点不算采集错误"

### 修复: 静默期"窗口态"二次抑制
不只看 `last_crawl_age` 总时长, 而计算 "上次采集到现在的累积活跃期小时数".

```python
# app/scheduler.py 新增 (2026-07-22)
def _effective_active_age_h(last_crawl_iso, now=None):
    """从 last_crawl_at 按整点切片扫描, 累计非静默期时长."""
    ...
```

**job_watchdog_check() 二次抑制**: 累积活跃期 ≤ 阈值 → 不告警 (静默期吃掉了大部分时间, 不算停滞).

### 关键洞察: 时态判断 ≠ 窗口判断
- **点态**: 现在是否在静默期 → 够防大部分场景 (已实现)
- **窗口态**: 跨静默边界 (08:00 / 20:00) 必须用累积活跃期 → **新加**

**同样的模式适用于其他周期性静默场景**: 周末 / 节假日 / 维护窗口 / 站点维护. 一律要用窗口态判断.

### Edge cases 处理
- 静默期未启用 → 返回 None, 回退到原始 age 判断 (等同禁用)
- `last_crawl_iso` 解析失败 → 返回 None, 回退到原始 age 判断 (防 bug 漏报)
- `last_dt >= now` (未来时间, 时钟漂移) → 0.0
- last_dt 本身在静默期内 → 按整点切片计算照样正确

### Hot-patch 流程 (标准 5 步)
1. 改本地 `app/scheduler.py`
2. `docker cp app/scheduler.py tender-scraper-scheduler:/app/app/scheduler.py`
3. `docker restart tender-scraper-scheduler`
4. 容器内手动跑 `python -c "from app.scheduler import job_watchdog_check; job_watchdog_check()"`
   确认 DEBUG 输出 `[Watchdog] ✅ collector 健康` 不告警
5. `git add app/scheduler.py && git commit && git push origin main`

**注意**: 容器内 Python 进程已加载旧版 `scheduler.py` 到内存, **必须 restart 才会生效**, 单 `docker cp` 不够.

### 测试场景 (10/10 pass)
| 场景 | last → now | 期望 | 结果 |
|---|---|---|---|
| 1. 跨夜静默边界 | 21:00 → 08:04 (11.07h 总, 0.07h 活跃) | 抑制 | ✅ |
| 2. 白天连续停滞 | 09:00 → 13:00 (4h 全活跃) | 告警 | ✅ |
| 3. 跨夜活跃期不够 | 19:00 → 08:30 次日 (1.5h 活跃) | 抑制 | ✅ |
| 4. 跨夜真停滞 | 19:00 → 13:00 次日 (6h 活跃) | 告警 | ✅ |
| 5. 全静默期内 | 23:00 → 02:00 (0h 活跃) | 拦截 | ✅ |
| 6. 静默期刚启动 | 21:00 → 21:30 (0h 活跃) | 拦截 | ✅ |
| 7. 刚成功无停滞 | last == now | 不告警 | ✅ |
| 8. 刚出静默 2h | 08:00 → 10:00 (2h < 阈值) | 抑制 | ✅ |
| 9. 跨夜真停滞边缘 | 19:30 → 11:00 次日 (3.5h 活跃) | 告警 | ✅ |
| 10. 跨夜临界 | 19:55 → 09:00 次日 (1.08h 活跃) | 抑制 | ✅ |

### 教训总结
> **周期性的"不做事"窗口** (静默期/周末/节假日) 用 watchdog 监控时, 一定要做"窗口态"判断, 不要只看"点态". 否则每个周期边界都会误报一次. 修正成本 = 误报次数 × 用户信任损失.

---

## PR merge ≠ 容器代码更新: 部署校验强制 (2026-07-22, commit b5d957b)

### Bug: PR #87 代码进了 git 但 collector 容器未重建
- **现象**: 用户拍板 2026-07-22 12:44 + 12:45: '还有很多项目 因为增加了 _1导致无法采集到数据 或者链接点击后无法跳转到正确页面'
- **根因**: PR #87 (e1a484c, 2026-07-21 16:24:47) 加了 `raw_catnum.startswith('014005004')` 守卫 (只有采购结果公告加 `_1`),
  **但 collector 容器镜像构建于 2026-07-15T09:18:20Z (PR merge **之前 6 天**)**, 跑的是旧代码 (无条件补 `_1`).
  7 类白名单 (014001001/002/003/004/019 + 014005001/002) 全部错版 `_1` URL 写入 DB (~24500 条).
- **用户反馈**: '不是需要补 `_1` 而是正确链接没有 `_1`' - 明确说明代码加错了, 不是 URL 应该带 `_1`.

### 验证流程 (复现用)
```bash
# 1. 看哪些容器是新代码 (PR #87 守卫存在)
for c in tender-scraper-collector tender-scraper-web tender-scraper-scheduler; do
  docker exec $c grep -c "raw_catnum.startswith..014005004.." \
    /app/app/crawlers/cqggzy.py 2>/dev/null
done
# 期望: collector ≥ 1, web ≥ 1, scheduler ≥ 1 (实际: collector=0, web=1, scheduler=0)

# 2. 看镜像构建时间 vs PR merge 时间
docker inspect tender-scraper-collector --format '{{.Created}}'
git log -1 --format='%ai' e1a484c
# 镜像早于 PR → 必然跑旧代码
```

### 修复 (5 步流程)
1. **本地代码已正确** (git HEAD 含 PR #87 守卫)
2. **备份容器旧代码**: `docker exec $c cp /app/app/.../cqggzy.py /app/.../cqggzy.py.bak-$(date +%Y%m%d)`
3. **docker cp 新代码**: `docker cp app/crawlers/cqggzy.py $c:/app/app/crawlers/cqggzy.py`
4. **restart 容器** (Python 进程内存里的旧代码必须 reload): `docker restart $c`
5. **验证**: 进容器手动 grep + 看 health endpoint

### 部署校验 (commit b5d957b, 防再发生)
- `app/utils/deployment_check.py`: REQUIRED_PATTERNS 列表, 每项 (file, pattern, pr, desc)
  - 当前含 PR #87 的 `raw_catnum.startswith('014005004')` x2 (cqggzy.py + cqggzy_curl.py)
  - 加新检查: 在列表里追加三元组
- `app/scheduler.py` 集成:
  - 模块启动钩子: `if __name__` 前调 `warn_if_stale()`
  - `job_deploy_check_daily()` 函数: 每天 9:00 检查
  - cron: `CronTrigger(minute='0', hour='9', tz='Asia/Shanghai')`
- 缺指纹行为: WARNING 日志 + Telegram 告警 (best-effort, 不 fatal, 避免重启失败)

### DB 现状 (2026-07-22 12:55)
- 错版 `_1` URL 量化 (按 URL 里 categoryNum):
  - 014005001 (采购公告): 16623 条带 `_1` ❌ → 已剥
  - 014005002 (变更公告): 7864 条带 `_1` ❌ → 已剥
  - 014005004 (采购结果公告): 16810 条带 `_1` ✅ (保留, API 真实返 _N)
  - **剥完后剩 `_N` URL 全是 014005004 (正确)**
- backfill 脚本: `scripts/backfill_cqggzy_url_strip_2026-07-22.py`
  - LIMIT=20 collector 测试: 75% 成功率 (15/20)
  - 失败 5 条都是 selector 不匹配 (UUID/HTML 路径历史不可抓项目)
  - **不接受全量 5h 后台跑** - 让自然 cron 覆盖 (PR #88 修了 'cp 从 fc 计算', 新采集不会再有 cp 空)

### 教训总结 (3 条铁律)
1. **PR merge 后必须** `docker compose build --no-cache $service && docker compose up -d $service`. **不能依赖 CI 自动重建** - CI 流程缺失/不稳定.
2. **新增爬虫修复必须同时加部署校验指纹** - 在 `deployment_check.py` 的 `REQUIRED_PATTERNS` 追加 (file, pattern, pr, desc), 不加 = 允许下次重犯.
3. **历史 cp/fc 空 ≠ 本次 bug 受害者** - 用 URL 是否带 `_N` + 是否数字 infoid 区分. 数字 infoid 是本次 bug 直接受害者, UUID/HTML 路径是历史不可抓 (不在本次修复范围).
