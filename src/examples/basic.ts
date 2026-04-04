/**
 * 示例代码 - 展示模板核心功能的使用
 */

import { registry, ToolDefinition } from '../tools/registry';
import { ConcurrencyScheduler, Priority } from '../src/ConcurrencyScheduler';
import { SessionMemory, MessageType } from '../src/SessionMemory';
import { z } from 'zod';

// ============ 1. 工具注册表示例 ============

const exampleTool: ToolDefinition = {
  metadata: {
    name: 'example-tool',
    description: '示例工具 - 展示工具注册',
    version: '1.0.0',
    category: 'example',
    tags: ['example', 'demo'],
    permissions: []
  },
  params: {
    schema: z.object({
      message: z.string()
    })
  },
  execute: async (params: any) => {
    console.log('执行示例工具:', params);
    return { success: true, message: `收到：${params.message}` };
  }
};

// ============ 2. 并发调度示例 ============

async function schedulerExample() {
  console.log('\n=== 并发调度示例 ===\n');

  const scheduler = new ConcurrencyScheduler({
    maxConcurrent: 3,
    maxRetries: 2,
    retryDelay: 500,
    defaultTimeout: 5000
  });

  // 提交多个任务
  const tasks = [
    { name: 'task-1', priority: Priority.NORMAL },
    { name: 'task-2', priority: Priority.HIGH },
    { name: 'task-3', priority: Priority.CRITICAL },
    { name: 'task-4', priority: Priority.LOW }
  ];

  const results = await scheduler.submitAll(
    tasks.map(t => ({
      name: t.name,
      priority: t.priority,
      executor: async () => {
        console.log(`执行 ${t.name}`);
        await new Promise(resolve => setTimeout(resolve, 1000));
        return `结果：${t.name}`;
      }
    }))
  );

  console.log('任务结果:', results);
  console.log('调度器状态:', scheduler.getStatus());

  // 优雅关闭
  await scheduler.shutdown();
}

// ============ 3. 会话内存示例 ============

async function memoryExample() {
  console.log('\n=== 会话内存示例 ===\n');

  const memory = new SessionMemory({
    maxSessions: 5,
    sessionTimeout: 3600000,
    autoSummarize: true,
    summaryThreshold: 3,
    persistence: {
      enabled: false, // 示例中禁用持久化
      path: './data/memory',
      compression: true
    }
  });

  // 创建会话
  const sessionId = memory.createSession('demo-session');
  console.log('创建会话:', sessionId);

  // 添加消息
  memory.addMessage(sessionId, MessageType.USER, '你好，我想了解天气');
  memory.addMessage(sessionId, MessageType.ASSISTANT, '好的，请问您想查询哪个城市？');
  memory.addMessage(sessionId, MessageType.USER, '北京');

  // 获取消息
  const messages = memory.getMessages(sessionId);
  console.log('消息数量:', messages.length);

  // 获取统计
  const stats = memory.getStats();
  console.log('内存统计:', stats);

  // 获取摘要（如果已触发）
  const summary = memory.getSummary(sessionId);
  if (summary) {
    console.log('会话摘要:', summary.summary);
  }
}

// ============ 主函数 ============

async function main() {
  console.log('=== OpenClaw 插件模板示例 ===\n');

  // 注册工具
  registry.register(exampleTool);
  console.log('已注册工具:', registry.list());

  // 运行示例
  await schedulerExample();
  await memoryExample();

  console.log('\n=== 示例完成 ===');
}

// 执行示例
main().catch(console.error);
