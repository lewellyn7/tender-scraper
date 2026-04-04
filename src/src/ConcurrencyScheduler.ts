/**
 * ConcurrencyScheduler - 并发任务调度器
 * 
 * 提供基于优先级的任务队列管理，支持：
 * - 并发限制
 * - 任务优先级
 * - 自动重试
 * - 优雅关闭
 * - 超时控制
 */

import { EventEmitter } from 'events';

// ============ 类型定义 ============

/**
 * 任务优先级
 */
enum Priority {
  LOW = 0,
  NORMAL = 1,
  HIGH = 2,
  CRITICAL = 3
}

/**
 * 任务状态
 */
enum TaskStatus {
  PENDING = 'pending',
  RUNNING = 'running',
  COMPLETED = 'completed',
  FAILED = 'failed',
  CANCELLED = 'cancelled'
}

/**
 * 任务定义
 */
interface Task<T = any, R = any> {
  id: string;
  name: string;
  priority: Priority;
  executor: () => Promise<R>;
  params?: T;
  status: TaskStatus;
  retries: number;
  maxRetries: number;
  timeout?: number;
  createdAt: number;
  startedAt?: number;
  completedAt?: number;
  result?: R;
  error?: Error;
}

/**
 * 调度器配置
 */
interface SchedulerConfig {
  maxConcurrent: number;
  maxRetries: number;
  retryDelay: number;
  defaultTimeout: number;
  queueSize: number;
}

// ============ 并发调度器类 ============

class ConcurrencyScheduler extends EventEmitter {
  private config: SchedulerConfig;
  private queue: Task[] = [];
  private running: Map<string, Task> = new Map();
  private isShuttingDown: boolean = false;
  private activeCount: number = 0;

  constructor(config?: Partial<SchedulerConfig>) {
    super();
    
    this.config = {
      maxConcurrent: 5,
      maxRetries: 3,
      retryDelay: 1000,
      defaultTimeout: 30000,
      queueSize: 100,
      ...config
    };

    console.log('[ConcurrencyScheduler] 初始化完成', {
      maxConcurrent: this.config.maxConcurrent,
      maxRetries: this.config.maxRetries
    });
  }

  /**
   * 提交新任务
   * @param name 任务名称
   * @param executor 执行函数
   * @param options 任务选项
   */
  submit<T, R>(
    name: string,
    executor: () => Promise<R>,
    options: {
      priority?: Priority;
      timeout?: number;
      maxRetries?: number;
      params?: T;
    } = {}
  ): Promise<R> {
    if (this.isShuttingDown) {
      throw new Error('调度器正在关闭，无法提交新任务');
    }

    if (this.queue.length >= this.config.queueSize) {
      throw new Error('队列已满，无法接受新任务');
    }

    const task: Task = {
      id: this.generateId(),
      name,
      priority: options.priority ?? Priority.NORMAL,
      executor,
      params: options.params,
      status: TaskStatus.PENDING,
      retries: 0,
      maxRetries: options.maxRetries ?? this.config.maxRetries,
      timeout: options.timeout ?? this.config.defaultTimeout,
      createdAt: Date.now()
    };

    // 按优先级插入队列
    this.insertByPriority(task);
    
    // 尝试调度
    this.schedule();

    // 返回 Promise
    return new Promise((resolve, reject) => {
      const onComplete = (completedTask: Task) => {
        if (completedTask.id === task.id) {
          if (completedTask.status === TaskStatus.COMPLETED) {
            resolve(completedTask.result as R);
          } else {
            reject(completedTask.error || new Error('任务失败'));
          }
        }
      };

      this.once('task:completed', onComplete);
      this.once('task:failed', onComplete);
    });
  }

  /**
   * 批量提交任务
   */
  submitAll<T, R>(
    tasks: Array<{
      name: string;
      executor: () => Promise<R>;
      priority?: Priority;
    }>
  ): Promise<R[]> {
    const promises = tasks.map(task =>
      this.submit(task.name, task.executor, { priority: task.priority })
    );
    return Promise.all(promises);
  }

  /**
   * 调度任务
   */
  private schedule(): void {
    while (this.activeCount < this.config.maxConcurrent && this.queue.length > 0) {
      const task = this.queue.shift();
      if (task) {
        this.runTask(task);
      }
    }
  }

  /**
   * 运行任务
   */
  private async runTask(task: Task): Promise<void> {
    this.activeCount++;
    this.running.set(task.id, task);
    task.status = TaskStatus.RUNNING;
    task.startedAt = Date.now();

    this.emit('task:started', task);
    console.log(`[Scheduler] 开始任务：${task.name} (${task.id})`);

    try {
      // 设置超时
      const timeoutPromise = new Promise((_, reject) => {
        setTimeout(() => reject(new Error('任务超时')), task.timeout);
      });

      const result = await Promise.race([
        task.executor(),
        timeoutPromise
      ]);

      task.status = TaskStatus.COMPLETED;
      task.result = result as any;
      task.completedAt = Date.now();
      
      this.emit('task:completed', task);
      console.log(`[Scheduler] 任务完成：${task.name} (${task.id})`);
    } catch (error) {
      task.error = error as Error;
      
      // 重试逻辑
      if (task.retries < task.maxRetries) {
        task.retries++;
        task.status = TaskStatus.PENDING;
        
        console.log(`[Scheduler] 任务重试：${task.name} (${task.retries}/${task.maxRetries})`);
        
        setTimeout(() => {
          this.queue.push(task);
          this.schedule();
        }, this.config.retryDelay * task.retries);
      } else {
        task.status = TaskStatus.FAILED;
        task.completedAt = Date.now();
        
        this.emit('task:failed', task);
        console.error(`[Scheduler] 任务失败：${task.name} (${task.id})`, error);
      }
    } finally {
      this.running.delete(task.id);
      this.activeCount--;
      this.schedule();
    }
  }

  /**
   * 按优先级插入队列
   */
  private insertByPriority(task: Task): void {
    const index = this.queue.findIndex(t => t.priority < task.priority);
    if (index === -1) {
      this.queue.push(task);
    } else {
      this.queue.splice(index, 0, task);
    }
  }

  /**
   * 取消任务
   */
  cancel(taskId: string): boolean {
    const task = this.running.get(taskId);
    if (task) {
      task.status = TaskStatus.CANCELLED;
      this.running.delete(taskId);
      this.activeCount--;
      return true;
    }

    const queueIndex = this.queue.findIndex(t => t.id === taskId);
    if (queueIndex !== -1) {
      this.queue.splice(queueIndex, 1);
      return true;
    }

    return false;
  }

  /**
   * 获取队列状态
   */
  getStatus(): {
    queued: number;
    running: number;
    activeCount: number;
    isShuttingDown: boolean;
  } {
    return {
      queued: this.queue.length,
      running: this.running.size,
      activeCount: this.activeCount,
      isShuttingDown: this.isShuttingDown
    };
  }

  /**
   * 优雅关闭
   */
  async shutdown(timeout: number = 5000): Promise<void> {
    console.log('[Scheduler] 开始关闭...');
    this.isShuttingDown = true;

    const start = Date.now();
    while (this.activeCount > 0) {
      if (Date.now() - start > timeout) {
        console.warn('[Scheduler] 关闭超时，强制退出');
        break;
      }
      await this.sleep(100);
    }

    console.log('[Scheduler] 关闭完成');
  }

  /**
   * 生成唯一 ID
   */
  private generateId(): string {
    return `task_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }

  private sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}

// ============ 导出 ============

export {
  ConcurrencyScheduler,
  Priority,
  TaskStatus,
  Task,
  SchedulerConfig
};

export default ConcurrencyScheduler;
