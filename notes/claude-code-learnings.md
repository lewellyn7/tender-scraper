# Claude Code 源码学习笔记

## 核心设计模式

### 1. Memory 系统：文件化 + 分层
- **透明化**：所有记忆存储为 Markdown 文件
- **索引分离**：`MEMORY.md` 做索引，具体记忆分散存储
- **硬截断保护**：索引文件限制 200 行 / 25KB
- **四层分离**：Auto / Session / Agent / Team Memory

**应用到采集系统：**
```
tender-scraper/
├── memory/
│   ├── MEMORY.md           # 采集批次索引
│   ├── 2026-04-03.md       # 当日结果摘要
│   └── projects/           # 项目详情
│       ├── 项目A_智能化改造.md
│       └── 项目B_AI平台建设.md
```

### 2. Tool 协议：工程化执行
- 所有工具必须通过 `buildTool()` 构造
- **Fail-Closed 原则**：默认不安全，显式声明才能放行
- 强制规范：并发安全、只读、破坏性、权限检查

### 3. Sandbox 沙箱：四层防御
```
shouldUseSandbox() 
  → checkSandboxAutoAllow() 
  → Shell.ts 执行 
  → SandboxManager.wrapWithSandbox() 
  → cleanupAfterCommand()
```

### 4. MCP 集成：开放协议
- 统一命名：`mcp__{server}__{tool}`
- 四种传输：stdio / sse / ws / http
- 描述截断：2048 字符限制
- 超时控制：针对运行时的规避策略

---

## 可落地的改进点

### A. 采集系统架构优化
```python
# 当前：单一 main.py
# 改进：分层架构

tender-scraper/
├── app/
│   ├── core/           # 核心引擎
│   │   ├── browser.py  # 浏览器管理
│   │   └── executor.py # 执行内核（借鉴 Tool Call）
│   ├── tools/          # 工具层
│   │   ├── scraper.py  # 采集工具
│   │   ├── filter.py   # 筛选工具
│   │   └── reporter.py # 报表工具
│   ├── memory/         # 记忆层
│   │   ├── manager.py  # 记忆管理
│   │   └── recall.py   # 召回机制
│   └── sandbox/        # 沙箱层
│       └── guard.py    # 安全守护
```

### B. 工具协议化
```python
from dataclasses import dataclass
from typing import Callable, Any

@dataclass
class ScraperTool:
    """采集工具协议（借鉴 Claude Code）"""
    name: str
    description: str
    call: Callable
    
    # 安全属性（必须显式声明）
    is_concurrency_safe: bool = False
    is_read_only: bool = False
    is_destructive: bool = False
    
    # 权限检查
    def check_permissions(self, input: dict) -> dict:
        return {"behavior": "allow", "input": input}
    
    # 输入校验
    def validate_input(self, input: dict) -> bool:
        return True
```

### C. Memory 集成
```python
# 在 OpenClaw 的基础上借鉴 Claude Code 的文件化设计

# memory/MEMORY.md
"""
# 采集历史索引

## 2026-04-03
- [重庆AI平台建设](./projects/2026-04-03_AI平台.md)
- [智能化改造项目](./projects/2026-04-03_智能化.md)

## 2026-04-02
- [音视频系统采购](./projects/2026-04-02_音视频.md)
"""

# 每次采集后自动更新索引
# 保持硬截断：索引 ≤ 200 行
```

### D. 沙箱防护（可选）
```python
# 对高风险操作（如自动提交 Git）启用沙箱
def should_use_sandbox(command: str) -> bool:
    # 排除安全命令
    safe_commands = ['git status', 'git log', 'python --version']
    if command in safe_commands:
        return False
    
    # 破坏性命令强制沙箱
    if 'rm' in command or 'DELETE' in command.upper():
        return True
    
    return False
```

---

## 关键文件索引

### 架构总览
- `analysis/01-architecture-overview.md` - 六层架构详解

### Memory 系统
- `analysis/04-agent-memory.md` - 文件化记忆机制
- `src/memdir/memdir.ts` - Memory 核心实现

### Tool Call
- `analysis/04b-tool-call-implementation.md` - 执行流水线
- `src/Tool.ts` - Tool 协议定义

### MCP 集成
- `analysis/04d-mcp-implementation.md` - 协议集成
- `src/services/mcp/client.ts` - 客户端实现

### Sandbox
- `analysis/04e-sandbox-implementation.md` - 四层防御
- `src/tools/BashTool/shouldUseSandbox.ts` - 沙箱判断

---

## 下一步行动

1. **重构采集器**：应用 Tool 协议化设计
2. **集成 Memory**：实现文件化记忆索引
3. **增强安全**：为破坏性操作添加沙箱保护
4. **MCP 扩展**：为 OpenClaw 编写 MCP 服务器（可选）

---

*学习时间：2026-04-03*
*来源：liuup/claude-code-analysis*
