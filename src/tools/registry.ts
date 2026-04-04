/**
 * 工具注册表 - 包含元数据声明
 * 
 * 提供声明式的工具注册机制，支持：
 * - 元数据驱动的工具定义
 * - 自动参数验证
 * - 工具分类和标签系统
 * - 权限控制
 */

import { z } from 'zod';

// ============ 类型定义 ============

/**
 * 工具元数据
 */
interface ToolMetadata {
  name: string;
  description: string;
  version: string;
  category: string;
  tags: string[];
  permissions: string[];
  author?: string;
}

/**
 * 工具参数定义
 */
interface ToolParams {
  schema: z.ZodObject<any>;
  required?: string[];
}

/**
 * 工具执行函数类型
 */
type ToolExecutor<T = any, R = any> = (params: T) => Promise<R>;

/**
 * 工具定义
 */
interface ToolDefinition<T = any, R = any> {
  metadata: ToolMetadata;
  params: ToolParams;
  execute: ToolExecutor<T, R>;
}

// ============ 工具注册表类 ============

class ToolRegistry {
  private registry: Map<string, ToolDefinition> = new Map();

  /**
   * 注册新工具
   * @param tool 工具定义
   */
  register<T, R>(tool: ToolDefinition<T, R>): void {
    const { name } = tool.metadata;
    
    if (this.registry.has(name)) {
      throw new Error(`工具已存在：${name}`);
    }

    this.registry.set(name, tool as ToolDefinition);
    console.log(`[ToolRegistry] 已注册工具：${name}`);
  }

  /**
   * 获取工具
   * @param name 工具名称
   */
  get(name: string): ToolDefinition | undefined {
    return this.registry.get(name);
  }

  /**
   * 移除工具
   * @param name 工具名称
   */
  unregister(name: string): boolean {
    return this.registry.delete(name);
  }

  /**
   * 列出所有工具
   */
  list(): string[] {
    return Array.from(this.registry.keys());
  }

  /**
   * 按分类列出工具
   * @param category 分类名称
   */
  listByCategory(category: string): string[] {
    return this.list().filter(name => {
      const tool = this.registry.get(name);
      return tool?.metadata.category === category;
    });
  }

  /**
   * 按标签搜索工具
   * @param tag 标签名称
   */
  searchByTag(tag: string): string[] {
    return this.list().filter(name => {
      const tool = this.registry.get(name);
      return tool?.metadata.tags.includes(tag);
    });
  }

  /**
   * 执行工具
   * @param name 工具名称
   * @param params 参数
   */
  async execute<T, R>(name: string, params: T): Promise<R> {
    const tool = this.get(name);
    
    if (!tool) {
      throw new Error(`工具不存在：${name}`);
    }

    // 参数验证
    const validatedParams = tool.params.schema.parse(params);
    
    // 执行工具
    return tool.execute(validatedParams) as Promise<R>;
  }
}

// ============ 示例工具定义 ============

/**
 * 示例：文件系统工具
 */
const filesystemTool: ToolDefinition = {
  metadata: {
    name: 'filesystem',
    description: '文件系统操作工具',
    version: '1.0.0',
    category: 'system',
    tags: ['file', 'system', 'io'],
    permissions: ['file:read', 'file:write'],
    author: 'OpenClaw'
  },
  params: {
    schema: z.object({
      path: z.string(),
      operation: z.enum(['read', 'write', 'delete']),
      content: z.string().optional()
    }),
    required: ['path', 'operation']
  },
  execute: async (params: any) => {
    // 实际实现将在这里
    console.log('执行文件系统操作:', params);
    return { success: true, data: null };
  }
};

/**
 * 示例：网络请求工具
 */
const webTool: ToolDefinition = {
  metadata: {
    name: 'web',
    description: '网络请求工具',
    version: '1.0.0',
    category: 'network',
    tags: ['http', 'web', 'api'],
    permissions: ['network:access'],
    author: 'OpenClaw'
  },
  params: {
    schema: z.object({
      url: z.string().url(),
      method: z.enum(['GET', 'POST', 'PUT', 'DELETE']).optional(),
      headers: z.record(z.string()).optional(),
      body: z.any().optional()
    }),
    required: ['url']
  },
  execute: async (params: any) => {
    // 实际实现将在这里
    console.log('执行网络请求:', params);
    return { success: true, data: null };
  }
};

// ============ 导出 ============

export {
  ToolRegistry,
  ToolDefinition,
  ToolMetadata,
  ToolParams,
  ToolExecutor,
  filesystemTool,
  webTool
};

// 默认导出单例
export const registry = new ToolRegistry();
