# Claude Code 架构深度分析

> 分析源: https://github.com/jarmuine/claude-code (Anthropic 源码泄露版本)
> 分析时间: 2026-04-03
> 分析目标: 学习其架构设计，提升自身系统能力

---

## 📊 项目概览

### 基本信息
- **语言**: TypeScript (strict mode)
- **运行时**: Bun
- **规模**: ~1,900 文件, 512,000+ 行代码
- **UI 框架**: React + Ink (终端 UI)
- **CLI 解析**: Commander.js
- **Schema 验证**: Zod v4

### 核心目录结构
```
src/
├── main.tsx              # 入口编排 (启动优化)
├── tools.ts              # 工具注册中心
├── commands.ts           # 命令注册中心
├── Tool.ts               # 工具类型定义
├── QueryEngine.ts        # LLM 查询引擎
├── coordinator/          # 多 Agent 协调器
├── tools/                # 工具实现 (~40 个)
├── commands/             # 命令实现 (~50 个)
├── skills/               # 技能系统
├── plugins/              # 插件系统
├── services/             # 外部服务集成
├── bridge/               # IDE 桥接
└── utils/                # 工具函数
```

---

## 🏗️ 核心架构模式

### 1. 启动优化策略

**关键发现**: 将启动时间从 ~200ms 优化到 ~65ms

```typescript
// main.tsx - 侧边效应优先执行
// 1. MDM 设置预读 (并行)
startMdmRawRead()

// 2. macOS Keychain 预取 (并行)
startKeychainPrefetch()

// 3. GrowthBook 特性标志初始化 (并行)
initializeGrowthBook()

// 重模块延迟加载
const coordinatorModule = feature('COORDINATOR_MODE')
  ? require('./coordinator/coordinatorMode.js')
  : null
```

**学习点**:
- ✅ 将 IO 密集型操作（文件读取、网络请求）提前到模块导入阶段
- ✅ 使用 `feature()` 特性开关进行死代码消除
- ✅ 重模块使用动态 `require()` 延迟加载

---

### 2. 工具系统设计

#### 工具注册中心 (`tools.ts`)

```typescript
export function getAllBaseTools(): Tools {
  return [
    AgentTool,        // 子 Agent 生成
    BashTool,         // Shell 命令执行
    FileReadTool,     // 文件读取
    FileWriteTool,    // 文件写入
    FileEditTool,     // 文件编辑
    GlobTool,         // 文件搜索
    GrepTool,         // 内容搜索
    WebFetchTool,     // URL 获取
    WebSearchTool,    // Web 搜索
    SkillTool,        // 技能执行
    MCPTool,          // MCP 协议调用
    LSPTool,          // LSP 集成
    TaskCreateTool,   // 任务创建
    SendMessageTool,  // Agent 间消息
    TeamCreateTool,   // 团队 Agent 管理
    // ... 更多工具
  ]
}
```

#### 工具类型定义 (`Tool.ts`)

```typescript
export type Tool<Input = unknown, Output = unknown> = {
  name: string
  inputSchema: ToolInputJSONSchema
  
  // 权限检查
  checkPermissions?: (
    input: Input,
    context: ToolUseContext
  ) => Promise<PermissionResult>
  
  // 验证逻辑
  validateInput?: (input: unknown) => ValidationResult
  
  // 执行逻辑
  execute: (
    input: Input,
    context: ToolUseContext
  ) => Promise<ToolResult<Output>>
  
  // 进度回调
  onProgress?: ToolCallProgress<Progress>
  
  // 可见性控制
  isEnabled?: () => boolean
}
```

**学习点**:
- ✅ 每个工具自包含：schema + 权限 + 执行 + 进度
- ✅ 统一的 `ToolUseContext` 上下文注入
- ✅ 权限检查前置，而非执行时检查
- ✅ 进度回调支持实时 UI 更新

---

### 3. 命令系统设计

#### 命令注册中心 (`commands.ts`)

```typescript
// 用户可调用命令 (~50 个)
import commit from './commands/commit.js'
import review from './commands/review.js'
import mcp from './commands/mcp/index.js'
import skills from './commands/skills/index.js'
import tasks from './commands/tasks/index.js'
import memory from './commands/memory/index.js'
import doctor from './commands/doctor/index.js'
// ... 更多命令

// 特性开关控制的命令
const proactive = feature('PROACTIVE')
  ? require('./commands/proactive.js').default
  : null

const bridge = feature('BRIDGE_MODE')
  ? require('./commands/bridge/index.js').default
  : null
```

**命令类型**:
- **用户命令** (`/commit`, `/review`, `/mcp`)
- **系统命令** (`/doctor`, `/config`)
- **团队命令** (`/tasks`, `/agents`)
- **特性命令** (由 `feature()` 控制)

**学习点**:
- ✅ 命令与工具分离：命令是用户入口，工具是 Agent 能力
- ✅ 特性开关控制命令可见性
- ✅ 延迟加载减少启动时间

---

### 4. 多 Agent 协调系统

#### 协调器模式 (`coordinator/coordinatorMode.ts`)

```typescript
export function getCoordinatorSystemPrompt(): string {
  return `You are Claude Code, an AI assistant that orchestrates
software engineering tasks across multiple workers.

## 1. Your Role
You are a **coordinator**. Your job is to:
- Help the user achieve their goal
- Direct workers to research, implement and verify code changes
- Synthesize results and communicate with the user

## 2. Your Tools
- **AgentTool** - Spawn a new worker
- **SendMessageTool** - Continue an existing worker
- **TaskStopTool** - Stop a running worker

## 3. Worker Capabilities
Workers have access to: ${workerTools}
`
}
```

#### Worker 工具集

```typescript
const ASYNC_AGENT_ALLOWED_TOOLS = new Set([
  'Bash',
  'FileRead',
  'FileEdit',
  'Glob',
  'Grep',
  'WebFetch',
  'WebSearch',
  'Skill',
  'MCP',
  // 不包括: AgentTool, SendMessageTool, TeamCreateTool
])
```

**协调器核心原则**:
1. **层次化设计**: Coordinator → Workers → Tools
2. **工具隔离**: Workers 不能生成新 Workers
3. **消息传递**: 通过 `SendMessageTool` 继续 Worker
4. **结果聚合**: Worker 结果以 `<task-notification>` XML 返回

**学习点**:
- ✅ 分层架构防止递归生成
- ✅ 明确的职责边界：协调器调度，Workers 执行
- ✅ 结构化结果返回格式

---

### 5. 技能系统 (Skills)

#### 技能注册 (`skills/bundled/index.ts`)

```typescript
export function initBundledSkills(): void {
  registerUpdateConfigSkill()
  registerKeybindingsSkill()
  registerVerifySkill()
  registerDebugSkill()
  registerLoremIpsumSkill()
  registerSkillifySkill()
  registerRememberSkill()
  registerSimplifySkill()
  registerBatchSkill()
  registerStuckSkill()
  
  // 特性开关控制的技能
  if (feature('KAIROS') || feature('KAIROS_DREAM')) {
    const { registerDreamSkill } = require('./dream.js')
    registerDreamSkill()
  }
}
```

#### 技能执行 (`tools/SkillTool/SkillTool.ts`)

```typescript
async function executeForkedSkill(
  command: Command & { type: 'prompt' },
  context: ToolUseContext
): Promise<ToolResult<Output>> {
  // 1. 创建独立 Agent
  const agentId = createAgentId()
  
  // 2. 在隔离上下文中执行技能
  const result = await runAgent({
    agentId,
    prompt: command.prompt,
    tools: getToolsForAgent(),
    forkedContext: true
  })
  
  // 3. 返回结果
  return {
    output: result.output,
    cost: result.usage.totalCost
  }
}
```

**技能类型**:
- **Bundled Skills**: 内置技能 (`/verify`, `/debug`)
- **Custom Skills**: 用户定义 (`.claude/skills/*.md`)
- **MCP Skills**: 来自 MCP 服务器的技能

**学习点**:
- ✅ 技能在独立 Agent 中执行（隔离上下文）
- ✅ 技能 = Prompt + 元数据
- ✅ 支持用户自定义技能

---

### 6. 插件系统 (Plugins)

#### 插件加载器 (`utils/plugins/pluginLoader.ts`)

```typescript
export interface LoadedPlugin {
  id: string              // name@marketplace
  version: string
  manifest: PluginManifest
  commands: Command[]     // 插件提供的命令
  agents: AgentDefinition[] // 插件提供的 Agents
  hooks: PluginHooks      // 插件钩子
  source: PluginSource    // 来源 (marketplace/git/npm)
}
```

#### 插件目录结构

```
my-plugin/
├── plugin.json       # 元数据
├── commands/         # 自定义命令
│   ├── build.md
│   └── deploy.md
├── agents/           # 自定义 Agents
│   └── test-runner.md
└── hooks/
    └── hooks.json    # 钩子定义
```

**插件发现源**:
1. **Marketplace**: `plugin@marketplace` 格式
2. **Git 仓库**: 直接从 Git 加载
3. **NPM**: 通过 Marketplace 索引

**学习点**:
- ✅ 插件市场机制（集中索引 + 分布式存储）
- ✅ 插件沙箱（命令/Agents/Hooks 分离）
- ✅ 版本管理（Git SHA/Semver）

---

### 7. MCP (Model Context Protocol) 集成

#### MCP 客户端 (`services/mcp/client.ts`)

```typescript
export async function connectMCPServers(
  configs: McpServerConfig[]
): Promise<MCPServerConnection[]> {
  return Promise.all(configs.map(async config => {
    // 1. 创建传输层
    const transport = config.transport === 'stdio'
      ? new StdioClientTransport(config.command)
      : new SSEClientTransport(config.url)
    
    // 2. 初始化客户端
    const client = new Client({ name: 'claude-code' }, {
      capabilities: { tools: true, prompts: true }
    })
    
    // 3. 连接
    await client.connect(transport)
    
    // 4. 发现工具
    const tools = await client.listTools()
    
    return { client, tools, config }
  }))
}
```

**MCP 能力**:
- **Tools**: 外部工具调用
- **Prompts**: 技能/命令模板
- **Resources**: 资源读取
- **Elicitations**: 用户交互

**学习点**:
- ✅ MCP 是 Agent 工具扩展的标准协议
- ✅ 支持多种传输层 (stdio, SSE, HTTP)
- ✅ 自动发现工具和提示

---

### 8. 查询引擎 (QueryEngine)

#### 核心架构 (`QueryEngine.ts`)

```typescript
export class QueryEngine {
  private messages: Message[]
  private fileCache: FileStateCache
  private usage: Usage
  private abortController: AbortController
  
  async submitMessage(input: string): Promise<Message[]> {
    // 1. 处理用户输入
    const userMessage = await processUserInput(input, this.context)
    
    // 2. 构建 System Prompt
    const systemPrompt = await this.buildSystemPrompt()
    
    // 3. 调用 LLM API (流式)
    const stream = await query({
      messages: [...this.messages, userMessage],
      system: systemPrompt,
      tools: this.tools,
      model: this.model
    })
    
    // 4. 处理流式响应
    for await (const event of stream) {
      if (event.type === 'content_block_start') {
        // 工具调用开始
      } else if (event.type === 'content_block_delta') {
        // 增量内容
      } else if (event.type === 'message_stop') {
        // 消息结束
      }
    }
    
    // 5. 执行工具调用
    const toolResults = await this.executeToolCalls(toolCalls)
    
    // 6. 递归直到无工具调用
    if (toolResults.length > 0) {
      return this.submitMessage(toolResults)
    }
  }
}
```

**关键特性**:
- **流式处理**: 实时响应
- **工具循环**: 自动处理工具调用
- **预算控制**: Token 和成本限制
- **中断支持**: AbortController

**学习点**:
- ✅ 流式 API + 工具循环的标准模式
- ✅ 消息不可变，每次返回新数组
- ✅ System Prompt 动态构建

---

### 9. 权限系统

#### 权限模式 (`utils/permissions/permissionSetup.ts`)

```typescript
type PermissionMode =
  | 'default'      // 每次询问
  | 'plan'         // 计划模式
  | 'auto'         // 自动模式（有安全检查）
  | 'bypass'       // 绕过权限（危险）

// 危险命令检测
export function isDangerousBashPermission(
  toolName: string,
  ruleContent: string | undefined
): boolean {
  if (toolName !== 'Bash') return false
  
  // Tool-level allow
  if (!ruleContent) return true
  
  // 检查危险模式
  const DANGEROUS_PATTERNS = [
    'python', 'node', 'bash', 'sh',
    'curl', 'wget', 'eval'
  ]
  
  for (const pattern of DANGEROUS_PATTERNS) {
    if (ruleContent.match(new RegExp(`^${pattern}[:*]?`))) {
      return true
    }
  }
  
  return false
}
```

**权限规则来源**:
1. **CLI 参数**: `--allowedTools`
2. **配置文件**: `.claude/settings.json`
3. **运行时决策**: 用户交互

**学习点**:
- ✅ 多级权限模式
- ✅ 危险模式黑名单
- ✅ 规则继承和覆盖

---

### 10. 特性开关系统

#### GrowthBook 集成 (`services/analytics/growthbook.ts`)

```typescript
export function feature(name: string): boolean {
  return getFeatureValue_CACHED_MAY_BE_STALE(name) === true
}

// 使用示例
if (feature('COORDINATOR_MODE')) {
  const module = require('./coordinator/coordinatorMode.js')
  // ...
}

// 构建时死代码消除
import { feature } from 'bun:bundle'
const coordinatorModule = feature('COORDINATOR_MODE')
  ? require('./coordinator/coordinatorMode.js')
  : null
```

**特性开关类别**:
- **PROACTIVE**: 主动模式
- **KAIROS**: 助手模式
- **BRIDGE_MODE**: IDE 桥接
- **DAEMON**: 守护进程
- **VOICE_MODE**: 语音输入
- **AGENT_TRIGGERS**: Agent 触发器

**学习点**:
- ✅ 特性开关 = 运行时特性 + 构建时优化
- ✅ GrowthBook 用于远程配置
- ✅ Bun 的 `feature()` 实现死代码消除

---

## 🎯 架构精髓总结

### 1. **分层设计**

```
┌─────────────────────────────────────┐
│          User Interface             │
│  (React + Ink Terminal UI)          │
├─────────────────────────────────────┤
│        Command Layer                │
│  (/commit, /review, /mcp...)        │
├─────────────────────────────────────┤
│      Query Engine                   │
│  (Message Processing + Tool Loop)   │
├─────────────────────────────────────┤
│     Coordinator (Optional)          │
│  (Multi-Agent Orchestration)        │
├─────────────────────────────────────┤
│       Agent Layer                   │
│  (SkillTool + AgentTool)            │
├─────────────────────────────────────┤
│        Tool Layer                   │
│  (Bash, File, Web, MCP...)          │
├─────────────────────────────────────┤
│    External Services                │
│  (API, MCP Servers, LSP...)         │
└─────────────────────────────────────┘
```

### 2. **核心设计原则**

| 原则 | 实现 |
|------|------|
| **模块化** | 每个工具/命令自包含 |
| **可扩展** | 插件系统 + MCP 协议 |
| **安全性** | 权限检查前置 + 危险模式检测 |
| **性能** | 启动优化 + 特性开关消除 |
| **可观测** | Telemetry + Analytics |

### 3. **关键模式**

#### 模式 1: 工具注册中心

```typescript
// 集中注册 + 条件加载
export function getAllBaseTools(): Tools {
  return [
    AgentTool,
    BashTool,
    // ...
    ...(feature('PROACTIVE') ? [SleepTool] : []),
    ...(feature('AGENT_TRIGGERS') ? cronTools : [])
  ]
}
```

#### 模式 2: 延迟加载

```typescript
// 避免循环依赖 + 减少启动时间
const getTeamCreateTool = () =>
  require('./tools/TeamCreateTool/TeamCreateTool.js').TeamCreateTool
```

#### 模式 3: 权限装饰器

```typescript
// 权限检查在执行前
async execute(input, context) {
  const permission = await this.checkPermissions(input, context)
  if (permission.result === 'denied') {
    return { error: 'Permission denied' }
  }
  // ... 实际执行
}
```

#### 模式 4: 上下文注入

```typescript
type ToolUseContext = {
  getAppState: () => AppState
  canUseTool: CanUseToolFn
  mcpClients: MCPServerConnection[]
  abortController: AbortController
  // ... 统一注入
}
```

---

## 💡 对 OpenClaw 的启示

### 1. 工具系统改进

**当前问题**: 工具定义分散，缺乏统一类型

**改进方案**:
```typescript
// 定义统一工具类型
type OpenClawTool<Input, Output> = {
  name: string
  description: string
  inputSchema: z.ZodType<Input>
  outputSchema?: z.ZodType<Output>
  
  checkPermissions?: (input: Input) => Promise<PermissionResult>
  execute: (input: Input, context: ToolContext) => Promise<Output>
  onProgress?: (progress: ToolProgress) => void
}

// 工具注册中心
class ToolRegistry {
  private tools = new Map<string, OpenClawTool>()
  
  register(tool: OpenClawTool) {
    this.tools.set(tool.name, tool)
  }
  
  getToolSchema(): ToolInputJSONSchema[] {
    return Array.from(this.tools.values()).map(t => ({
      name: t.name,
      description: t.description,
      input_schema: zodToJsonSchema(t.inputSchema)
    }))
  }
}
```

### 2. 技能系统改进

**当前问题**: 技能只是简单 prompt，缺乏隔离

**改进方案**:
```typescript
// 技能在独立 Agent 中执行
class SkillExecutor {
  async executeSkill(skill: Skill, input: string) {
    // 1. 创建隔离上下文
    const forkedContext = this.createForkedContext()
    
    // 2. 运行 Agent
    const result = await this.runAgent({
      prompt: skill.prompt + '\n\n' + input,
      tools: this.getToolsForSkill(skill),
      context: forkedContext
    })
    
    // 3. 返回结果
    return result.output
  }
}
```

### 3. 多 Agent 协调

**当前问题**: 缺乏多 Agent 协调能力

**改进方案**:
```typescript
// 协调器模式
class Coordinator {
  private workers = new Map<AgentId, Worker>()
  
  async spawnWorker(task: string): Promise<AgentId> {
    const agentId = createAgentId()
    const worker = await this.agentTool.execute({
      prompt: task,
      agentId
    })
    this.workers.set(agentId, worker)
    return agentId
  }
  
  async sendMessage(agentId: AgentId, message: string) {
    const worker = this.workers.get(agentId)
    return this.sendMessageTool.execute({
      to: agentId,
      message
    })
  }
}
```

### 4. 启动优化

**当前问题**: 启动时间未优化

**改进方案**:
```typescript
// 预加载关键资源
async function optimizeStartup() {
  // 1. 并行预读配置
  const [config, credentials, featureFlags] = await Promise.all([
    readConfig(),
    readCredentials(),
    fetchFeatureFlags()
  ])
  
  // 2. 延迟加载重模块
  const heavyModule = await import('./heavy-module')
  
  return { config, credentials, featureFlags }
}
```

### 5. 权限系统改进

**当前问题**: 权限检查不够精细

**改进方案**:
```typescript
// 权限规则系统
type PermissionRule = {
  tool: string
  pattern?: string  // e.g., "python:*"
  decision: 'allow' | 'deny'
  source: 'cli' | 'config' | 'runtime'
}

class PermissionManager {
  private rules: PermissionRule[] = []
  
  checkPermission(tool: string, input: any): PermissionResult {
    // 1. 检查危险模式
    if (this.isDangerous(tool, input)) {
      return { result: 'denied', reason: 'Dangerous pattern' }
    }
    
    // 2. 应用规则
    const rule = this.findMatchingRule(tool, input)
    if (rule) {
      return { result: rule.decision }
    }
    
    // 3. 默认询问用户
    return { result: 'pending', askUser: true }
  }
}
```

---

## 📈 优先级建议

### 高优先级 (立即实施)

1. **统一工具类型定义** - 提升类型安全
2. **工具注册中心** - 集中管理
3. **权限前置检查** - 提升安全性
4. **上下文注入模式** - 统一依赖传递

### 中优先级 (短期实施)

5. **技能隔离执行** - 在独立 Agent 中执行
6. **启动优化** - 并行预读 + 延迟加载
7. **权限规则系统** - 精细化控制

### 低优先级 (长期规划)

8. **多 Agent 协调** - Coordinator 模式
9. **插件市场** - Marketplace 机制
10. **MCP 协议支持** - 标准化工具扩展

---

## 🎓 学习心得

### 1. 架构设计

- **模块化 > 单体**: 每个功能自包含
- **分层 > 扁平**: 清晰的职责边界
- **协议 > 实现**: MCP 是好例子

### 2. 性能优化

- **并行 > 串行**: 启动优化关键
- **延迟 > 预先**: 重模块延迟加载
- **消除 > 条件**: 死代码消除更彻底

### 3. 安全设计

- **前置 > 后置**: 权限检查在执行前
- **白名单 > 黑名单**: 明确允许而非禁止
- **隔离 > 共享**: 技能/Agent 隔离执行

### 4. 扩展性

- **插件 > 硬编码**: 用户可扩展
- **协议 > API**: MCP 是标准
- **配置 > 代码**: 特性开关远程控制

---

## 📚 参考资料

- [Claude Code 源码](https://github.com/jarmuine/claude-code)
- [Model Context Protocol](https://modelcontextprotocol.io)
- [Bun Feature Flags](https://bun.sh/docs/runtime/bundle)
- [GrowthBook](https://growthbook.io)
- [Ink - React for CLI](https://github.com/vadimdemedes/ink)

---

*分析完成时间: 2026-04-03 07:40*
*分析者: 贾维斯*
