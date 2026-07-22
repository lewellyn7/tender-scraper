"""部署版本校验 (2026-07-22 加入)

痛点 (用户拍板 2026-07-22 12:44 + 12:45):
  PR #87 (e1a484c) 改了 cqggzy.py / cqggzy_curl.py 的 _1 守卫 (2026-07-21),
  但 collector 容器镜像还是 2026-07-15 建的 (PR merge 前 6 天).
  容器跑旧代码 (无条件补 _1) → 24500+ 错版 URL 写入 DB → 用户点击链接
  看到空壳, 数据采不到. 教训: PR merge ≠ 容器代码更新 (AGENTS.md 已记).

设计:
  - 启动时 + watchdog 定时检查关键文件是否含最新修复的"代码指纹"
  - 不含 → WARNING 日志 + Telegram 告警 (不 fatal, 避免重启失败)
  - 含 → 静默通过

添加新检查:
  - 在 REQUIRED_PATTERNS 加 (file, pattern, issue_url) 三元组
  - pattern 用字符串 (精确子串匹配) 或 re.compile() (regex)
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Tuple, Union

# (file_path_relative_to_app, pattern_or_regex, issue_pr, description)
REQUIRED_PATTERNS: List[Tuple[str, Union[str, "re.Pattern[str]"], str, str]] = [
    (
        "crawlers/cqggzy.py",
        "raw_catnum.startswith('014005004')",
        "PR #87 (e1a484c)",
        "infoid _N 守卫: 仅 014005004 加 _1, 其他不加 (防 _1 URL 空壳)",
    ),
    (
        "crawlers/cqggzy_curl.py",
        "raw_catnum.startswith('014005004')",
        "PR #87 (e1a484c)",
        "curl 路径 infoid _N 守卫: 同上",
    ),
]


def _check_file(rel_path: str, pattern: Union[str, "re.Pattern[str]"]) -> bool:
    """检查单个文件是否含 pattern. 字符串用 substring, re.Pattern 用 regex."""
    base = Path(__file__).resolve().parent.parent  # app/
    fpath = base / rel_path
    if not fpath.exists():
        return False
    try:
        content = fpath.read_text(encoding="utf-8")
    except Exception:
        return False
    if isinstance(pattern, str):
        return pattern in content
    return bool(pattern.search(content))


def check_crawler_version() -> Tuple[bool, List[str]]:
    """校验所有 REQUIRED_PATTERNS 是否在代码里.

    Returns:
        (ok, missing_descriptions): ok=True 全部含, ok=False 缺.
        missing_descriptions 是缺失项的人类可读描述列表.
    """
    missing: List[str] = []
    for rel_path, pattern, pr, desc in REQUIRED_PATTERNS:
        if not _check_file(rel_path, pattern):
            missing.append(f"  - {rel_path} [{pr}]: {desc}")
    return (len(missing) == 0, missing)


def warn_if_stale() -> None:
    """启动时调用: 缺守卫就 WARNING 日志 + Telegram 告警 (不 fatal)."""
    from loguru import logger

    ok, missing = check_crawler_version()
    if ok:
        logger.debug("[DeployCheck] ✅ 所有爬虫代码指纹匹配最新修复")
        return
    msg = "[DeployCheck] ⚠️ 部署版本落后! 缺以下修复:\n" + "\n".join(missing)
    msg += (
        "\n\n→ 这通常是 docker 镜像未重建 (git 有 PR 但容器跑旧代码).\n"
        "→ 解决: docker compose build --no-cache collector && docker compose up -d collector"
    )
    logger.warning(msg)
    # 发 Telegram 告警 (best-effort)
    try:
        from app.utils.alerts import send_alert
        send_alert(
            level="warning",
            title="部署版本落后 (爬虫代码未含最新 PR 修复)",
            body=msg,
            source="deploy-check",
        )
    except Exception as e:
        logger.debug(f"[DeployCheck] send_alert failed (non-fatal): {e}")


if __name__ == "__main__":
    # 手动诊断: python -m app.utils.deployment_check
    ok, missing = check_crawler_version()
    if ok:
        print("✅ 所有爬虫代码指纹匹配最新修复")
    else:
        print("⚠️ 部署版本落后, 缺以下修复:")
        for m in missing:
            print(m)
        print("\n→ docker compose build --no-cache collector && docker compose up -d collector")
    raise SystemExit(0 if ok else 1)