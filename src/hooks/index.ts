/**
 * 生命周期钩子
 * 
 * 提供插件生命周期管理：
 * - onInitialize: 插件初始化
 * - onReady: 插件就绪
 * - onShutdown: 插件关闭
 * - onError: 错误处理
 */

import { EventEmitter } from 'events';

// ============ 类型定义 ============

type HookType =
  | 'onInitialize'
  | 'onReady'
  | 'onShutdown'
  | 'onError'
  | 'onMessage'
  | 'onToolCall';

type HookHandler<T = any> = (data: T) => Promise<void> | void;

interface HookDefinition {
  name: HookType;
  handler: HookHandler;
  priority: number;
}

// ============ 钩子系统 ============

class HookSystem extends EventEmitter {
  private hooks: Map<HookType, HookDefinition[]> = new Map();

  /**
   * 注册钩子处理器
   */
  register<T>(
    name: HookType,
    handler: HookHandler<T>,
    priority: number = 0
  ): void {
    const hook: HookDefinition = { name, handler, priority };
    
    if (!this.hooks.has(name)) {
      this.hooks.set(name, []);
    }

    const hooks = this.hooks.get(name)!;
    hooks.push(hook);
    
    // 按优先级排序
    hooks.sort((a, b) => b.priority - a.priority);
    
    console.log(`[Hooks] 注册钩子：${name} (priority: ${priority})`);
  }

  /**
   * 移除钩子处理器
   */
  unregister(name: HookType, handler: HookHandler): boolean {
    const hooks = this.hooks.get(name);
    
    if (!hooks) {
      return false;
    }

    const index = hooks.findIndex(h => h.handler === handler);
    
    if (index !== -1) {
      hooks.splice(index, 1);
      return true;
    }

    return false;
  }

  /**
   * 触发钩子
   */
  async trigger<T>(name: HookType, data: T): Promise<void> {
    const hooks = this.hooks.get(name);
    
    if (!hooks) {
      return;
    }

    console.log(`[Hooks] 触发钩子：${name} (${hooks.length} 个处理器)`);

    for (const hook of hooks) {
      try {
        await hook.handler(data);
      } catch (error) {
        console.error(`[Hooks] 钩子执行失败：${name}`, error);
        this.emit('hook:error', { name, error });
      }
    }
  }

  /**
   * 清除所有钩子
   */
  clear(): void {
    this.hooks.clear();
    console.log('[Hooks] 清除所有钩子');
  }
}

// ============ 导出 ============

export {
  HookSystem,
  HookType,
  HookHandler,
  HookDefinition
};

export default HookSystem;
