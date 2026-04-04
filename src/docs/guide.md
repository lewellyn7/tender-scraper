# OpenClaw 插件开发指南

## 目录

1. [快速开始](#快速开始)
2. [核心概念](#核心概念)
3. [工具开发](#工具开发)
4. [并发调度](#并发调度)
5. [会话内存](#会话内存)
6. [最佳实践](#最佳实践)

---

## 快速开始

### 1. 克隆模板

```bash
cp -r templates/openclaw-plugin my-plugin
cd my-plugin
npm install
```

### 2. 项目结构

```
my-plugin/
├── src/              # 核心代码
├── tools/            # 工具注册
├── hooks/            # 生命周期钩子
├── memory/           # 内存管理
├── docs/             # 文档
└── config.yaml       # 配置文件
```

### 3. 基本使用

```typescript
import { registry } from './tools/registry';
import { ConcurrencyScheduler, Priority } from './src/ConcurrencyScheduler';
import { SessionMemory } from './src/SessionMemory';

// 初始化工具
const tool = {
  metadata: {
    name: 'greeting',
    description: '打招呼工具',
    version: '1.0.0',
    category: 'utility',
    tags: ['greeting'],
    permissions: []
  },
  params: {
    schema: z.object({
      name: z.string()
    })
  },
  execute: async (params: any) => {
    return `Hello, ${params.name}!`;
  }
};

registry.register(tool);

// 初始化调度器
const scheduler = new ConcurrencyScheduler({
  maxConcurrent: 5,
  maxRetries: 3
});

// 初始化内存
const memory = new SessionMemory({
  maxSessions: 10,
  autoSummarize: true
});
```

---

## 核心概念

### 工具注册系统

工具是 OpenClaw 插件的基本功能单元。每个工具包含：

- **元数据**: 描述工具的名称、版本、分类等
- **参数定义**: 使用 Zod 进行类型验证
- **执行函数**: 实际的业务逻辑

### 并发调度

ConcurrencyScheduler 提供：

- 任务优先级管理
- 并发限制
- 自动重试
- 超时控制

### 会话内存

SessionMemory 提供：

- 消息存储
- 自动摘要
- 持久化
- 过期清理

---

## 工具开发

### 创建自定义工具

```typescript
import { registry, ToolDefinition } from './tools/registry';
import { z } from 'zod';

const myTool: ToolDefinition = {
  metadata: {
    name: 'my-custom-tool',
    description: '我的自定义工具',
    version: '1.0.0',
    category: 'custom',
    tags: ['custom', 'example'],
    permissions: ['custom:execute']
  },
  params: {
    schema: z.object({
      input: z.string(),
      options: z.object({
        verbose: z.boolean().optional()
      }).optional()
    })
  },
  execute: async (params) => {
    // 实现你的逻辑
    const result = await processData(params.input);
    return { success: true, result };
  }
};

registry.register(myTool);
```

---

## 并发调度

### 基本使用

```typescript
import { ConcurrencyScheduler, Priority } from './src/ConcurrencyScheduler';

const scheduler = new ConcurrencyScheduler({
  maxConcurrent: 5,
  maxRetries: 3,
  retryDelay: 1000,
  defaultTimeout: 30000
});

// 提交任务
const result = await scheduler.submit(
  'task-name',
  async () => {
    // 你的异步任务
    return await someAsyncOperation();
  },
  {
    priority: Priority.HIGH,
    timeout: 5000,
    maxRetries: 5
  }
);

// 批量提交
const results = await scheduler.submitAll([
  { name: 'task1', executor: async () => 'result1' },
  { name: 'task2', executor: async () => 'result2', priority: Priority.HIGH }
]);

// 获取状态
console.log(scheduler.getStatus());

// 优雅关闭
await scheduler.shutdown();
```

### 优先级说明

- `Priority.CRITICAL` (3): 关键任务，立即执行
- `Priority.HIGH` (2): 高优先级任务
- `Priority.NORMAL` (1): 普通任务
- `Priority.LOW` (0): 低优先级任务

---

## 会话内存

### 基本使用

```typescript
import { SessionMemory, MessageType } from './src/SessionMemory';

const memory = new SessionMemory({
  maxSessions: 10,
  sessionTimeout: 3600000,
  autoSummarize: true,
  summaryThreshold: 10,
  persistence: {
    enabled: true,
    path: './data/memory',
    compression: true
  }
});

// 创建会话
const sessionId = memory.createSession();

// 添加消息
memory.addMessage(
  sessionId,
  MessageType.USER,
  '你好，我想查询天气'
);

memory.addMessage(
  sessionId,
  MessageType.ASSISTANT,
  '好的，请问您想查询哪个城市？'
);

// 获取消息
const messages = memory.getMessages(sessionId, 10);

// 获取摘要
const summary = memory.getSummary(sessionId);

// 获取统计
const stats = memory.getStats();
```

### 消息类型

- `MessageType.USER`: 用户消息
- `MessageType.ASSISTANT`: 助手消息
- `MessageType.SYSTEM`: 系统消息
- `MessageType.TOOL`: 工具调用消息

---

## 最佳实践

### 1. 工具设计

- 保持工具单一职责
- 提供清晰的元数据描述
- 使用 Zod 进行严格的参数验证
- 处理所有可能的错误情况

### 2. 并发控制

- 根据资源限制设置合理的并发数
- 为关键任务设置更高优先级
- 实现优雅关闭逻辑
- 监控任务执行状态

### 3. 内存管理

- 定期清理过期会话
- 合理设置会话超时时间
- 使用持久化防止数据丢失
- 监控内存使用情况

### 4. 错误处理

```typescript
try {
  const result = await scheduler.submit('task', async () => {
    // 可能失败的操作
  });
} catch (error) {
  console.error('任务执行失败:', error);
  // 实现重试或降级逻辑
}
```

### 5. 日志记录

```typescript
import { createLogger } from 'winston';

const logger = createLogger({
  level: 'info',
  format: winston.format.json(),
  transports: [
    new winston.transports.File({ filename: 'plugin.log' })
  ]
});

// 在关键位置记录日志
logger.info('插件初始化完成');
logger.error('工具执行失败', { error });
```

---

## 故障排除

### 常见问题

1. **工具注册失败**
   - 检查工具名称是否唯一
   - 验证元数据完整性

2. **任务超时**
   - 增加 timeout 配置
   - 检查是否有死锁
   - 优化任务执行逻辑

3. **内存泄漏**
   - 定期调用 `cleanupExpiredSessions()`
   - 限制 `maxSessions` 和 `maxMessagesPerSession`
   - 使用持久化减少内存占用

### 调试技巧

```typescript
// 启用调试日志
process.env.DEBUG = 'openclaw:*';

// 监听事件
scheduler.on('task:started', (task) => {
  console.log('任务开始:', task);
});

memory.on('session:summarized', (data) => {
  console.log('会话摘要:', data);
});
```

---

## 下一步

- 查看 [API 参考](./api.md) 了解完整 API
- 阅读 [最佳实践](./best-practices.md) 深入学习
- 贡献代码到 [GitHub 仓库](https://github.com/lewellyn7/openclaw)
