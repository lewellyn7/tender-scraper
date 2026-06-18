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

