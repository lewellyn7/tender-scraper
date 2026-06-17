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

