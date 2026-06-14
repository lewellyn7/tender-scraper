"""Startup 安全断言 — P0-3
=========================================

**目的**：在生产环境（`ENV=production`）禁止 `DEPLOYMENT_MODE=self` 启动。

**为什么需要这个模块**：
- `app/config/settings.py:_validate_production_safety()` 已经在 import 时检查
- 这里提供一个**显式 startup hook**，作为 defense-in-depth 兜底
- 启动时**显式调用**比"依赖导入时副作用"更明确、更可测、更可观测

**使用方式**：
```python
# main.py / web_server.py 入口
from app.core.safety_guard import check_production_safety

if __name__ == "__main__":
    check_production_safety()  # ← 显式 startup hook
    main()
```

**失败行为**：直接抛 `RuntimeError`，进程退出码 1。
**成功行为**：无返回值，print 一行 OK 提示到 stderr。
"""
from __future__ import annotations

import os
import sys
from typing import Literal


def check_production_safety() -> None:
    """P0-3: production 环境 startup 安全断言

    Raises:
        RuntimeError: ENV=production 且 DEPLOYMENT_MODE=self 时
    """
    env = os.getenv("ENV", "development").lower()
    mode = os.getenv("DEPLOYMENT_MODE", "team").lower()

    if env == "production" and mode == "self":
        msg = (
            "\n"
            "=" * 70 + "\n"
            "🚨 STARTUP BLOCKED: DEPLOYMENT_MODE=self 在 production 环境被禁\n"
            "=" * 70 + "\n"
            "原因: self 模式依赖 admin-fallback 永真、所有 API 端点对未认证用户开放。\n"
            "      production 环境严禁此模式。\n"
            "\n"
            "修复: 改 DEPLOYMENT_MODE=team 并配置身份认证 (JWT/SSO)。\n"
            "      或: 确认这是 dev 环境，把 ENV 设为 development。\n"
            "=" * 70
        )
        # stderr 输出，CRITICAL 级别
        print(msg, file=sys.stderr)
        raise RuntimeError("DEPLOYMENT_MODE=self forbidden in production")

    # 成功路径 — 静默或 DEBUG 级别
    if env in ("development", "staging", "production") and mode in ("self", "team"):
        # 仅在显式 DEBUG 模式打印（避免日志噪音）
        if os.getenv("SAFETY_GUARD_VERBOSE") == "1":
            print(f"✅ Startup safety check passed: ENV={env}, DEPLOYMENT_MODE={mode}", file=sys.stderr)
    else:
        # 未知 env / mode 组合 — 不阻塞，但警告
        print(
            f"⚠️  Unknown ENV/mode combination: ENV={env!r}, DEPLOYMENT_MODE={mode!r}. "
            f"Expected ENV ∈ {{development,staging,production}}, mode ∈ {{self,team}}",
            file=sys.stderr
        )


def is_production() -> bool:
    """便捷判断: 当前是否在 production 环境"""
    return os.getenv("ENV", "development").lower() == "production"


def get_deployment_mode() -> Literal["self", "team", "unknown"]:
    """便捷获取: 当前部署模式"""
    mode = os.getenv("DEPLOYMENT_MODE", "team").lower()
    if mode in ("self", "team"):
        return mode  # type: ignore[return-value]
    return "unknown"
