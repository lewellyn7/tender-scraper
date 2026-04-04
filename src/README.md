# OpenClaw 插件架构模板

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0-blue)](https://www.typescriptlang.org/)
[![Node](https://img.shields.io/badge/node-%3E%3D18.0.0-green)](https://nodejs.org/)

开箱即用的 OpenClaw 插件开发模板，包含工具注册、并发调度、会话内存等核心功能。

## ✨ 特性

- 🛠️ **工具注册系统** - 元数据驱动的声明式工具定义
- ⚡ **并发调度器** - 基于优先级的任务队列，支持自动重试
- 💾 **会话内存** - 自动摘要、持久化存储
- 🔌 **即插即用** - 完整的项目结构，开箱即用
- 📝 **类型安全** - 完整的 TypeScript 类型定义
- 📚 **文档完善** - 详细的使用指南和 API 文档

## 📦 安装

```bash
# 克隆模板
git clone <your-repo>/templates/openclaw-plugin.git my-plugin
cd my-plugin

# 安装依赖
npm install

# 运行示例
npm run example
```

## 🚀 快速开始

### 1. 注册工具

```typescript
import { registry, ToolDefinition } from './tools/registry';
import { z } from 'zod';

const myTool: ToolDefinition = {
  metadata: {
    name: 'my-tool',
    description: '我的工具',
    version: '1.0.0',
    category: 'custom',
    tags: ['custom'],
    permissions: []
  },
  params: {
    schema: z.object({
      input: z.string()
    })
  },
  execute: async (params) => {
    return { result: `处理：${params.input}` };
  }
};

registry.register(myTool);
```

### 2. 使用并发调度

```typescript
import { ConcurrencyScheduler, Priority } from './src/ConcurrencyScheduler';

const scheduler = new ConcurrencyScheduler({
  maxConcurrent: 5,
  maxRetries: 3
});

await scheduler.submit(
  'my-task',
  async () => {
    // 你的异步任务
    return await doSomething();
  },
  { priority: Priority.HIGH }
);
```

### 3. 管理会话内存

```typescript
import { SessionMemory, MessageType } from './src/SessionMemory';

const memory = new SessionMemory({
  maxSessions: 10,
  autoSummarize: true
});

const sessionId = memory.createSession();

memory.addMessage(sessionId, MessageType.USER, '你好');
memory.addMessage(sessionId, MessageType.ASSISTANT, '有什么可以帮助你的？');

const messages = memory.getMessages(sessionId);
```

## 📁 目录结构

```
my-plugin/
├── src/                    # 核心源代码
│   ├── ConcurrencyScheduler.ts    # 并发调度器
│   └── SessionMemory.ts           # 会话内存
├── tools/                  # 工具注册
│   └── registry.ts        # 工具注册表
├── hooks/                  # 生命周期钩子
│   └── index.ts
├── memory/                 # 内存管理
│   └── index.ts
├── examples/               # 示例代码
│   └── basic.ts
├── docs/                   # 文档
│   └── guide.md
├── config.yaml             # 配置模板
├── package.json
├── tsconfig.json
└── README.md
```

## 📖 文档

- [开发指南](docs/guide.md) - 详细的开发文档
- [API 参考](docs/api.md) - 完整 API 文档
- [最佳实践](docs/best-practices.md) - 开发技巧

## 🛠️ 开发

```bash
# 开发模式
npm run dev

# 构建
npm run build

# 测试
npm test

# 代码检查
npm run lint
```

## ⚙️ 配置

复制 `config.yaml` 为 `config.local.yaml` 进行自定义配置：

```yaml
plugin:
  name: "my-plugin"
  version: "1.0.0"

scheduler:
  maxConcurrent: 5
  maxRetries: 3

memory:
  maxSessions: 10
  autoSummarize: true
```

## 🎯 核心功能

### 工具注册系统

- ✅ 元数据驱动的声明式定义
- ✅ 自动参数验证（Zod）
- ✅ 工具分类和标签
- ✅ 权限控制

### 并发调度器

- ✅ 基于优先级的任务队列
- ✅ 并发限制
- ✅ 自动重试机制
- ✅ 超时控制
- ✅ 优雅关闭

### 会话内存

- ✅ 消息存储和检索
- ✅ 自动摘要生成
- ✅ 时间窗口管理
- ✅ 持久化存储
- ✅ 过期清理

## 📝 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

**开始构建你的 OpenClaw 插件吧！** 🚀
