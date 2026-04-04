/**
 * SessionMemory - 会话内存管理
 * 
 * 提供会话级别的内存管理，支持：
 * - 消息存储和检索
 * - 自动摘要和压缩
 * - 时间窗口管理
 * - 持久化存储
 * - 内存限制控制
 */

import { EventEmitter } from 'events';
import * as fs from 'fs';
import * as path from 'path';

// ============ 类型定义 ============

/**
 * 消息类型
 */
enum MessageType {
  USER = 'user',
  ASSISTANT = 'assistant',
  SYSTEM = 'system',
  TOOL = 'tool'
}

/**
 * 消息结构
 */
interface Message {
  id: string;
  type: MessageType;
  content: string;
  timestamp: number;
  metadata?: Record<string, any>;
}

/**
 * 会话摘要
 */
interface SessionSummary {
  sessionId: string;
  summary: string;
  keyPoints: string[];
  createdAt: number;
  updatedAt: number;
  messageCount: number;
}

/**
 * 会话数据
 */
interface SessionData {
  id: string;
  messages: Message[];
  summary?: SessionSummary;
  createdAt: number;
  lastActivity: number;
  metadata?: Record<string, any>;
}

/**
 * 内存管理配置
 */
interface MemoryConfig {
  maxSessions: number;
  sessionTimeout: number;
  maxMessagesPerSession: number;
  autoSummarize: boolean;
  summaryThreshold: number;
  persistence: {
    enabled: boolean;
    path: string;
    compression: boolean;
  };
}

// ============ 会话内存管理类 ============

class SessionMemory extends EventEmitter {
  private config: MemoryConfig;
  private sessions: Map<string, SessionData> = new Map();
  private summaries: Map<string, SessionSummary> = new Map();

  constructor(config?: Partial<MemoryConfig>) {
    super();
    
    this.config = {
      maxSessions: 10,
      sessionTimeout: 3600000, // 1 hour
      maxMessagesPerSession: 100,
      autoSummarize: true,
      summaryThreshold: 10,
      persistence: {
        enabled: true,
        path: './data/memory',
        compression: true
      },
      ...config
    };

    // 初始化持久化存储
    if (this.config.persistence.enabled) {
      this.ensurePersistencePath();
      this.loadSessions();
    }

    console.log('[SessionMemory] 初始化完成', {
      maxSessions: this.config.maxSessions,
      autoSummarize: this.config.autoSummarize
    });
  }

  /**
   * 创建新会话
   */
  createSession(sessionId?: string): string {
    const id = sessionId || this.generateId();
    
    if (this.sessions.size >= this.config.maxSessions) {
      this.evictOldestSession();
    }

    const session: SessionData = {
      id,
      messages: [],
      createdAt: Date.now(),
      lastActivity: Date.now()
    };

    this.sessions.set(id, session);
    this.emit('session:created', id);
    console.log(`[SessionMemory] 创建会话：${id}`);
    
    return id;
  }

  /**
   * 添加消息
   */
  addMessage(
    sessionId: string,
    type: MessageType,
    content: string,
    metadata?: Record<string, any>
  ): Message {
    const session = this.sessions.get(sessionId);
    
    if (!session) {
      throw new Error(`会话不存在：${sessionId}`);
    }

    const message: Message = {
      id: this.generateId(),
      type,
      content,
      timestamp: Date.now(),
      metadata
    };

    session.messages.push(message);
    session.lastActivity = Date.now();

    // 检查是否需要摘要
    if (
      this.config.autoSummarize &&
      session.messages.length % this.config.summaryThreshold === 0
    ) {
      this.summarizeSession(sessionId);
    }

    // 持久化
    this.persistSession(sessionId);
    
    this.emit('message:added', { sessionId, message });
    return message;
  }

  /**
   * 获取会话消息
   */
  getMessages(sessionId: string, limit?: number): Message[] {
    const session = this.sessions.get(sessionId);
    
    if (!session) {
      return [];
    }

    if (limit) {
      return session.messages.slice(-limit);
    }

    return session.messages;
  }

  /**
   * 获取最近 N 条消息
   */
  getRecentMessages(sessionId: string, count: number): Message[] {
    return this.getMessages(sessionId, count);
  }

  /**
   * 生成会话摘要
   */
  async summarizeSession(sessionId: string): Promise<SessionSummary | null> {
    const session = this.sessions.get(sessionId);
    
    if (!session) {
      return null;
    }

    // 调用摘要生成逻辑（实际实现中可能调用 LLM）
    const summary = await this.generateSummary(session);
    
    session.summary = summary;
    this.summaries.set(sessionId, summary);
    
    this.emit('session:summarized', { sessionId, summary });
    console.log(`[SessionMemory] 会话摘要完成：${sessionId}`);
    
    return summary;
  }

  /**
   * 获取会话摘要
   */
  getSummary(sessionId: string): SessionSummary | undefined {
    return this.summaries.get(sessionId);
  }

  /**
   * 删除会话
   */
  deleteSession(sessionId: string): boolean {
    const existed = this.sessions.delete(sessionId);
    this.summaries.delete(sessionId);
    
    if (existed) {
      this.emit('session:deleted', sessionId);
      console.log(`[SessionMemory] 删除会话：${sessionId}`);
    }
    
    return existed;
  }

  /**
   * 清理过期会话
   */
  cleanupExpiredSessions(): number {
    const now = Date.now();
    let cleaned = 0;

    for (const [id, session] of this.sessions) {
      if (now - session.lastActivity > this.config.sessionTimeout) {
        this.deleteSession(id);
        cleaned++;
      }
    }

    if (cleaned > 0) {
      console.log(`[SessionMemory] 清理了 ${cleaned} 个过期会话`);
    }

    return cleaned;
  }

  /**
   * 获取所有会话 ID
   */
  listSessions(): string[] {
    return Array.from(this.sessions.keys());
  }

  /**
   * 获取会话统计
   */
  getStats(): {
    totalSessions: number;
    totalMessages: number;
    totalSummaries: number;
  } {
    let totalMessages = 0;
    for (const session of this.sessions.values()) {
      totalMessages += session.messages.length;
    }

    return {
      totalSessions: this.sessions.size,
      totalMessages,
      totalSummaries: this.summaries.size
    };
  }

  // ============ 私有方法 ============

  /**
   * 生成摘要（骨架实现）
   */
  private async generateSummary(session: SessionData): Promise<SessionSummary> {
    // TODO: 实际实现中调用 LLM 生成摘要
    // 这里提供骨架实现
    
    const messages = session.messages.slice(-20); // 使用最近 20 条消息
    const keyPoints: string[] = [];
    
    // 简单提取关键信息（骨架实现）
    for (const msg of messages) {
      if (msg.type === MessageType.USER && msg.content.length > 20) {
        keyPoints.push(msg.content.substring(0, 50) + '...');
      }
    }

    return {
      sessionId: session.id,
      summary: `[摘要] 会话包含 ${session.messages.length} 条消息`,
      keyPoints: keyPoints.slice(0, 5), // 最多 5 个关键点
      createdAt: session.createdAt,
      updatedAt: Date.now(),
      messageCount: session.messages.length
    };
  }

  /**
   * 持久化会话
   */
  private persistSession(sessionId: string): void {
    if (!this.config.persistence.enabled) {
      return;
    }

    const session = this.sessions.get(sessionId);
    if (!session) return;

    try {
      const filePath = path.join(
        this.config.persistence.path,
        `${sessionId}.json`
      );
      
      const content = this.config.persistence.compression
        ? JSON.stringify(session) // 简化版，实际可使用 gzip 压缩
        : JSON.stringify(session, null, 2);
      
      fs.writeFileSync(filePath, content, 'utf-8');
    } catch (error) {
      console.error('[SessionMemory] 持久化失败:', error);
    }
  }

  /**
   * 加载会话
   */
  private loadSessions(): void {
    if (!this.config.persistence.enabled) {
      return;
    }

    try {
      const dir = this.config.persistence.path;
      if (!fs.existsSync(dir)) {
        return;
      }

      const files = fs.readdirSync(dir).filter(f => f.endsWith('.json'));
      
      for (const file of files) {
        try {
          const filePath = path.join(dir, file);
          const content = fs.readFileSync(filePath, 'utf-8');
          const session: SessionData = JSON.parse(content);
          this.sessions.set(session.id, session);
        } catch (error) {
          console.error('[SessionMemory] 加载会话失败:', file, error);
        }
      }

      console.log(`[SessionMemory] 加载了 ${this.sessions.size} 个会话`);
    } catch (error) {
      console.error('[SessionMemory] 加载会话失败:', error);
    }
  }

  /**
   * 确保持久化路径存在
   */
  private ensurePersistencePath(): void {
    if (!fs.existsSync(this.config.persistence.path)) {
      fs.mkdirSync(this.config.persistence.path, { recursive: true });
    }
  }

  /**
   * 驱逐最旧的会话
   */
  private evictOldestSession(): void {
    let oldestId: string | null = null;
    let oldestTime = Date.now();

    for (const [id, session] of this.sessions) {
      if (session.lastActivity < oldestTime) {
        oldestTime = session.lastActivity;
        oldestId = id;
      }
    }

    if (oldestId) {
      this.deleteSession(oldestId);
      console.log(`[SessionMemory] 驱逐最旧会话：${oldestId}`);
    }
  }

  /**
   * 生成唯一 ID
   */
  private generateId(): string {
    return `sess_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }
}

// ============ 导出 ============

export {
  SessionMemory,
  MessageType,
  Message,
  SessionSummary,
  SessionData,
  MemoryConfig
};

export default SessionMemory;
