# Claude Code 提示词工程深度解析

> 源码分析: Claude Code System Prompt 架构
> 分析时间: 2026-04-03
> 目标: 提炼可复用的提示词工程模式

---

## 📊 提示词架构概览

### 核心设计理念

Claude Code 的提示词系统采用**模块化 + 分层 + 缓存友好**的设计：

```
System Prompt
├── Static Sections (跨用户缓存)
│   ├── Identity & Role
│   ├── Tool Instructions
│   ├── System Capabilities
│   └── Common Patterns
│
├── Semi-Static Sections (跨会话缓存)
│   ├── User Preferences
│   ├── Output Style
│   └── Language Settings
│
└── Dynamic Sections (每轮重建)
    ├── Current Context
    ├── Available Skills
    ├── MCP Tools
    └── Permission State
```

---

## 🏗️ 核心架构模式

### 1. System Prompt 分段系统

#### 分段定义 (`constants/systemPromptSections.ts`)

```typescript
type SystemPromptSection = {
  name: string
  compute: () => string | null | Promise<string | null>
  cacheBreak: boolean  // 是否破坏缓存
}

// 静态段 (可缓存)
export function systemPromptSection(
  name: string,
  compute: ComputeFn
): SystemPromptSection {
  return { name, compute, cacheBreak: false }
}

// 动态段 (每轮重建)
export function DANGEROUS_uncachedSystemPromptSection(
  name: string,
  compute: ComputeFn,
  _reason: string  // 必须说明为何破坏缓存
): SystemPromptSection {
  return { name, compute, cacheBreak: true }
}
```

**使用示例**:

```typescript
const SECTIONS = [
  // 静态段
  systemPromptSection('identity', () => getIdentityPrompt()),
  systemPromptSection('tools', () => getToolsPrompt()),
  
  // 动态段
  DANGEROUS_uncachedSystemPromptSection(
    'skills',
    () => getAvailableSkills(),
    'Skills list changes per session'
  )
]

// 解析所有段
const promptParts = await resolveSystemPromptSections(SECTIONS)
```

**学习点**:
- ✅ 显式区分静态/动态内容
- ✅ 强制注释缓存破坏原因
- ✅ 自动缓存静态段结果

---

### 2. Prompt Builder 模式

#### 核心 Builder (`constants/prompts.ts`)

```typescript
export async function getSystemPrompt(
  tools: Tools,
  model: string,
  additionalWorkingDirectories: string[],
  mcpClients: MCPServerConnection[]
): Promise<string[]> {
  const sections: (string | null)[] = await Promise.all([
    // 1. 身份定义
    getSimpleIntroSection(outputStyle),
    
    // 2. 系统能力
    getSimpleSystemSection(),
    
    // 3. 任务执行
    getSimpleDoingTasksSection(),
    
    // 4. 工具说明
    getToolSections(tools),
    
    // 5. MCP 集成
    getMcpInstructionsSection(mcpClients),
    
    // 6. Git 操作
    getCommitAndPRInstructions(),
    
    // 7. 沙箱说明
    getSimpleSandboxSection(),
    
    // 8. 语言偏好
    getLanguageSection(languagePreference),
    
    // 9. 输出风格
    getOutputStyleSection(outputStyle)
  ])
  
  // 过滤 null，返回有效段
  return sections.filter((s): s is string => s !== null)
}
```

**关键特性**:
- **并行构建**: 所有段并行计算
- **条件包含**: 段可返回 `null` 表示不包含
- **模块化**: 每段独立函数，易维护

---

### 3. 工具提示词模式

#### BashTool Prompt (`tools/BashTool/prompt.ts`)

```typescript
export function getSimplePrompt(): string {
  return [
    // 1. 功能概述
    'Executes a given bash command and returns its output.',
    
    // 2. 核心约束
    'IMPORTANT: Avoid using this tool to run `cat`, `head`, `tail`, `sed`, `awk`, or `echo` commands...',
    
    // 3. 工具偏好
    'File search: Use GlobTool (NOT find or ls)',
    'Content search: Use GrepTool (NOT grep or rg)',
    'Read files: Use FileReadTool (NOT cat/head/tail)',
    
    // 4. 详细指令
    '# Instructions',
    '- Always quote file paths with spaces',
    '- Try to maintain current working directory',
    '- Use absolute paths and avoid `cd`',
    
    // 5. 并行执行
    'When issuing multiple commands:',
    '- Independent → parallel calls',
    '- Dependent → chain with &&',
    
    // 6. Git 集成
    getCommitAndPRInstructions(),
    
    // 7. 沙箱说明
    getSimpleSandboxSection()
  ].join('\n')
}
```

**结构化设计**:
1. **功能声明** - 一句话说明
2. **关键约束** - 醒目的 IMPORTANT 标记
3. **替代方案** - 引导使用专用工具
4. **最佳实践** - 分条列举
5. **边界情况** - Git、Sandbox 等特殊场景

---

### 4. 技能提示词模式

#### SkillTool Prompt (`tools/SkillTool/prompt.ts`)

```typescript
export const getPrompt = memoize(async (_cwd: string): Promise<string> => {
  return `
Execute a skill within the main conversation

When users ask you to perform tasks, check if any of the available skills match.
Skills provide specialized capabilities and domain knowledge.

When users reference a "slash command" or "/<something>" (e.g., "/commit", "/review-pr"),
they are referring to a skill. Use this tool to invoke it.

How to invoke:
- Use this tool with the skill name and optional arguments
- Examples:
  - \`skill: "pdf"\` - invoke the pdf skill
  - \`skill: "commit", args: "-m 'Fix bug'"\` - invoke with arguments
  - \`skill: "review-pr", args: "123"\` - invoke with arguments

Important:
- Available skills are listed in system-reminder messages
- When a skill matches: BLOCKING REQUIREMENT → invoke BEFORE generating response
- NEVER mention a skill without actually calling this tool
- Do not invoke a skill that is already running
- If you see <command_name> tag: skill ALREADY loaded → follow instructions directly
`
})
```

**关键设计**:
- ✅ 明确触发条件 ("slash command" 或 "/xxx")
- ✅ 强调优先级 (BLOCKING REQUIREMENT)
- ✅ 防止重复调用 (检测 `<command_name>` 标签)
- ✅ 提供调用示例

---

### 5. Context 预算管理

#### 技能列表预算 (`tools/SkillTool/prompt.ts`)

```typescript
// 技能列表占用 1% 上下文窗口
export const SKILL_BUDGET_CONTEXT_PERCENT = 0.01
export const CHARS_PER_TOKEN = 4

export function getCharBudget(contextWindowTokens?: number): number {
  if (contextWindowTokens) {
    return Math.floor(
      contextWindowTokens * CHARS_PER_TOKEN * SKILL_BUDGET_CONTEXT_PERCENT
    )
  }
  return 8_000  // 默认: 1% of 200k × 4
}

// 每条描述硬上限
export const MAX_LISTING_DESC_CHARS = 250

export function formatCommandsWithinBudget(
  commands: Command[],
  contextWindowTokens?: number
): string {
  const budget = getCharBudget(contextWindowTokens)
  
  // 1. 尝试完整描述
  const fullEntries = commands.map(formatCommandDescription)
  if (getTotalChars(fullEntries) <= budget) {
    return fullEntries.join('\n')
  }
  
  // 2. 分区: bundled (优先保留) vs 其他
  const { bundled, rest } = partitionCommands(commands)
  
  // 3. 计算剩余预算
  const bundledChars = getTotalChars(bundled)
  const remainingBudget = budget - bundledChars
  
  // 4. 截断非 bundled 描述
  const maxDescLen = Math.floor(
    remainingBudget / rest.length
  )
  
  // 5. 如果太短则只显示名称
  if (maxDescLen < 20) {
    return commands.map(c => bundled.has(c) 
      ? formatFull(c) 
      : `- ${c.name}`
    ).join('\n')
  }
  
  // 6. 否则截断描述
  return commands.map(c => bundled.has(c)
    ? formatFull(c)
    : `- ${c.name}: ${truncate(c.description, maxDescLen)}`
  ).join('\n')
}
```

**预算策略**:
- ✅ 优先保留内置技能完整描述
- ✅ 动态计算可分配字符数
- ✅ 降级策略: 完整 → 截断 → 仅名称

---

### 6. 消息格式化模式

#### 用户消息创建 (`utils/messages.ts`)

```typescript
export function createUserMessage(
  content: string,
  attachments?: Attachment[]
): UserMessage {
  return {
    type: 'user',
    message: {
      role: 'user',
      content: [
        { type: 'text', text: content },
        ...(attachments?.map(a => ({
          type: 'image',
          source: { type: 'base64', ...a }
        })) || [])
      ]
    }
  }
}
```

#### System Reminder 注入

```typescript
export function injectSystemReminder(
  message: string,
  reminders: string[]
): string {
  // 在消息后注入系统提醒
  const reminderBlock = reminders
    .map(r => `<system-reminder>${r}</system-reminder>`)
    .join('\n')
  
  return `${message}\n\n${reminderBlock}`
}
```

---

## 🎯 提示词工程精华

### 1. 结构化 Prompt 模板

#### 模板 1: 工具描述

```typescript
interface ToolPromptTemplate {
  // 1. 一句话功能
  summary: string
  
  // 2. 关键约束 (IMPORTANT)
  constraints: string[]
  
  // 3. 使用指南
  instructions: string[]
  
  // 4. 示例
  examples: Array<{
    input: any
    output: any
    explanation: string
  }>
  
  // 5. 边界情况
  edgeCases: string[]
}
```

**实现**:

```typescript
function buildToolPrompt(template: ToolPromptTemplate): string {
  return [
    template.summary,
    '',
    'IMPORTANT:',
    ...template.constraints.map(c => `- ${c}`),
    '',
    '# Instructions',
    ...template.instructions,
    '',
    '# Examples',
    ...template.examples.map(e => 
      `<example>\nInput: ${JSON.stringify(e.input)}\nOutput: ${JSON.stringify(e.output)}\n${e.explanation}\n</example>`
    ),
    '',
    '# Edge Cases',
    ...template.edgeCases
  ].join('\n')
}
```

---

### 2. 分层 Prompt 注入

#### 层次结构

```
L1: Identity Layer
    └── "You are Claude Code, an AI assistant..."
    
L2: Capability Layer
    ├── Available Tools
    ├── System Features
    └── Current Limitations
    
L3: Context Layer
    ├── Working Directory
    ├── Project Structure
    └── Recent Changes
    
L4: Task Layer
    ├── User Request
    ├── Constraints
    └── Success Criteria
```

**动态组合**:

```typescript
class PromptBuilder {
  private layers: Map<string, string[]> = new Map()
  
  addLayer(level: number, name: string, content: string) {
    const key = `${level}_${name}`
    if (!this.layers.has(key)) {
      this.layers.set(key, [])
    }
    this.layers.get(key)!.push(content)
  }
  
  build(): string {
    const sortedLayers = Array.from(this.layers.entries())
      .sort((a, b) => {
        const [levelA] = a[0].split('_')
        const [levelB] = b[0].split('_')
        return parseInt(levelA) - parseInt(levelB)
      })
    
    return sortedLayers
      .map(([_, contents]) => contents.join('\n\n'))
      .join('\n\n---\n\n')
  }
}
```

---

### 3. 条件性 Prompt 段

#### Feature Gate 控制

```typescript
function getToolPrompt(): string {
  const sections: string[] = []
  
  // 基础段 (始终包含)
  sections.push(getBaseInstructions())
  
  // 特性门控段
  if (feature('PROACTIVE')) {
    sections.push(getProactiveInstructions())
  }
  
  if (feature('COORDINATOR_MODE')) {
    sections.push(getCoordinatorInstructions())
  }
  
  // 用户偏好段
  if (getLanguagePreference()) {
    sections.push(getLanguageSection(getLanguagePreference()))
  }
  
  return sections.join('\n\n')
}
```

---

### 4. 预算感知的 Prompt 压缩

#### 动态压缩策略

```typescript
class PromptCompressor {
  compress(
    content: string,
    budget: number,
    priority: 'high' | 'medium' | 'low'
  ): string {
    const len = content.length
    
    if (len <= budget) return content
    
    // 策略 1: 移除示例 (低优先级)
    if (priority === 'low') {
      content = this.removeExamples(content)
      if (content.length <= budget) return content
    }
    
    // 策略 2: 简化描述 (中优先级)
    content = this.simplifyDescriptions(content)
    if (content.length <= budget) return content
    
    // 策略 3: 提取要点 (高优先级)
    return this.extractKeyPoints(content, budget)
  }
  
  private removeExamples(content: string): string {
    return content.replace(/<example>[\s\S]*?<\/example>/g, '')
  }
  
  private simplifyDescriptions(content: string): string {
    return content
      .replace(/\n{3,}/g, '\n\n')
      .replace(/ {2,}/g, ' ')
      .replace(/Detailed explanation:[\s\S]*?(?=\n#|\n$)/g, '')
  }
  
  private extractKeyPoints(content: string, budget: number): string {
    const lines = content.split('\n')
    const keyLines: string[] = []
    let currentLen = 0
    
    for (const line of lines) {
      // 优先保留标题和重要指令
      if (line.startsWith('#') || line.includes('IMPORTANT')) {
        if (currentLen + line.length <= budget) {
          keyLines.push(line)
          currentLen += line.length
        }
      }
    }
    
    return keyLines.join('\n')
  }
}
```

---

### 5. XML 标签模式

#### 结构化标记 (`constants/xml.ts`)

```typescript
// 工具结果标签
export const LOCAL_COMMAND_STDOUT_TAG = 'local-command-stdout'
export const LOCAL_COMMAND_STDERR_TAG = 'local-command-stderr'
export const COMMAND_MESSAGE_TAG = 'command-message'
export const COMMAND_NAME_TAG = 'command-name'

// 示例用法
export function formatToolResult(
  stdout: string,
  stderr: string
): string {
  return `
<${LOCAL_COMMAND_STDOUT_TAG}>
${stdout}
</${LOCAL_COMMAND_STDOUT_TAG}>

${stderr ? `<${LOCAL_COMMAND_STDERR_TAG}>${stderr}</${LOCAL_COMMAND_STDERR_TAG}>` : ''}
`.trim()
}
```

**优势**:
- ✅ 明确的内容边界
- ✅ 易于解析和提取
- ✅ 支持嵌套结构

---

### 6. 多 Agent Prompt 协调

#### Coordinator Prompt (`coordinator/coordinatorMode.ts`)

```typescript
export function getCoordinatorSystemPrompt(): string {
  return `
You are Claude Code, an AI assistant that orchestrates
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

## 3. Worker Results
Worker results arrive as **user-role messages** containing \`<task-notification>\` XML.

Format:
\`\`\`xml
<task-notification>
  <task-id>{agentId}</task-id>
  <status>completed</status>
  <output>
    {worker output}
  </output>
</task-notification>
\`\`\`

## 4. Best Practices
- Do not use one worker to check on another
- Do not set the model parameter (workers need default model)
- After launching agents, briefly tell the user and end response
- Never fabricate results — they arrive separately
`
}
```

**Worker Prompt 自动注入**:

```typescript
export function getCoordinatorUserContext(
  mcpClients: MCPServerConnection[],
  scratchpadDir?: string
): { [k: string]: string } {
  if (!isCoordinatorMode()) return {}
  
  const workerTools = Array.from(ASYNC_AGENT_ALLOWED_TOOLS)
    .filter(name => !INTERNAL_WORKER_TOOLS.has(name))
    .sort()
    .join(', ')
  
  return {
    workerToolsContext: `
Workers spawned via AgentTool have access to: ${workerTools}

${mcpClients.length > 0 ? 
  `Workers also have access to MCP tools from: ${mcpClients.map(c => c.name).join(', ')}` 
  : ''}

${scratchpadDir ? `
Scratchpad directory: ${scratchpadDir}
Workers can read and write here without permission prompts.
` : ''}
`
  }
}
```

---

## 💡 可复用模式总结

### Pattern 1: 分段构建器

```typescript
class SegmentBuilder {
  private segments: Map<string, () => string | null> = new Map()
  
  register(name: string, builder: () => string | null) {
    this.segments.set(name, builder)
  }
  
  async build(): Promise<string[]> {
    const results = await Promise.all(
      Array.from(this.segments.values()).map(builder => builder())
    )
    return results.filter((s): s is string => s !== null)
  }
}
```

### Pattern 2: 预算管理器

```typescript
class BudgetManager {
  constructor(private totalBudget: number) {}
  
  allocate(
    items: Array<{ content: string; priority: number }>
  ): string[] {
    // 按 priority 排序 (高优先级优先)
    const sorted = items.sort((a, b) => b.priority - a.priority)
    
    let remaining = this.totalBudget
    const result: string[] = []
    
    for (const item of sorted) {
      if (item.content.length <= remaining) {
        result.push(item.content)
        remaining -= item.content.length
      } else if (remaining > 20) {
        // 至少保留名称
        result.push(this.truncate(item.content, remaining))
        remaining = 0
      }
    }
    
    return result
  }
}
```

### Pattern 3: 条件注入器

```typescript
class ConditionalInjector {
  private conditions: Map<string, () => boolean> = new Map()
  private templates: Map<string, string> = new Map()
  
  register(
    name: string,
    condition: () => boolean,
    template: string
  ) {
    this.conditions.set(name, condition)
    this.templates.set(name, template)
  }
  
  inject(): string[] {
    const result: string[] = []
    
    for (const [name, condition] of this.conditions) {
      if (condition()) {
        result.push(this.templates.get(name)!)
      }
    }
    
    return result
  }
}
```

### Pattern 4: 格式化助手

```typescript
class PromptFormatter {
  static bulletList(items: string[]): string {
    return items.map(i => `- ${i}`).join('\n')
  }
  
  static numberedList(items: string[]): string {
    return items.map((i, idx) => `${idx + 1}. ${i}`).join('\n')
  }
  
  static section(title: string, content: string): string {
    return `# ${title}\n\n${content}`
  }
  
  static example(input: string, output: string): string {
    return `<example>\nInput: ${input}\nOutput: ${output}\n</example>`
  }
  
  static important(message: string): string {
    return `IMPORTANT: ${message}`
  }
}
```

---

## 🎓 最佳实践清单

### 1. 结构设计

- [ ] **模块化分段**: 每个 prompt 段独立函数
- [ ] **静态/动态分离**: 明确标识缓存边界
- [ ] **优先级分层**: Identity > Capability > Context > Task
- [ ] **预算感知**: 计算并限制每个段的大小

### 2. 内容编写

- [ ] **一句话功能**: 工具/技能描述首句说明用途
- [ ] **IMPORTANT 标记**: 关键约束用大写标记
- [ ] **替代方案引导**: 推荐专用工具而非通用命令
- [ ] **具体示例**: 提供实际输入输出示例
- [ ] **边界情况**: 说明异常场景处理

### 3. 性能优化

- [ ] **并行构建**: 无依赖段并行计算
- [ ] **缓存策略**: 静态段缓存，动态段重建
- [ ] **惰性加载**: 重模块延迟 require
- [ ] **条件包含**: feature gate 控制段可见性

### 4. 可维护性

- [ ] **单一职责**: 每个段只负责一个主题
- [ ] **版本控制**: prompt 变更记录在 commit
- [ ] **A/B 测试**: 通过 feature flag 控制新 prompt
- [ ] **监控埋点**: 记录 prompt 版本和效果

---

## 📈 对 OpenClaw 的启示

### 立即可实施

1. **分段 Prompt 系统**
   - 实现 `SystemPromptSection` 模式
   - 区分静态/动态内容
   - 添加缓存边界标记

2. **预算管理器**
   - 计算上下文窗口预算
   - 优先级驱动的段分配
   - 降级策略 (完整 → 截断 → 名称)

3. **格式化工具**
   - 统一的 bullet/numbered list
   - section/example 格式
   - IMPORTANT 标记辅助

### 中期实施

4. **条件注入系统**
   - Feature gate 控制
   - 用户偏好注入
   - 环境适配

5. **多 Agent Prompt 协调**
   - Coordinator/Worker 分离
   - 结果格式化标准
   - 工具可见性控制

### 长期规划

6. **Prompt 版本管理**
   - 版本号追踪
   - A/B 测试框架
   - 效果监控

---

## 📚 参考资料

- [Claude Code Prompt 源码](https://github.com/jarmuine/claude-code)
- [Anthropic Prompt Engineering Guide](https://docs.anthropic.com/claude/docs/prompt-engineering)
- [Context Window Management](https://www.anthropic.com/research/context-windows)

---

*分析完成时间: 2026-04-03 08:15*
*分析者: 贾维斯*
