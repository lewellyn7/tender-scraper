"""
Tool 并发安全调度器 - Python 版本

基于 P0-2 设计文档和 Claw-Code 权限系统，提供：
- 工具安全级别分级 (SafetyLevel)
- 并发执行分组
- 分批调度执行
- 自动重试机制
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

from loguru import logger


class SafetyLevel(Enum):
    """工具安全级别"""

    READ_ONLY = "read_only"  # 只读操作，完全可并发
    WORKSPACE_WRITE = "workspace_write"  # 工作区写入，限制并发
    DANGER_FULL_ACCESS = "danger_full_access"  # 危险操作，串行执行


@dataclass
class ToolDefinition:
    """工具定义"""

    name: str
    description: str
    safety_level: SafetyLevel
    is_concurrency_safe: bool = False
    max_concurrent: int = 1  # 最大并发数
    timeout_seconds: int = 30
    retry_count: int = 3
    tags: List[str] = field(default_factory=list)


@dataclass
class Task:
    """执行任务"""

    id: str
    tool_name: str
    params: Dict[str, Any]
    priority: int = 1  # 1-10, 10 最高
    created_at: datetime = field(default_factory=datetime.now)

    def __lt__(self, other):
        return self.priority > other.priority  # 高优先级在前


@dataclass
class ExecutionResult:
    """执行结果"""

    task_id: str
    tool_name: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    duration_ms: int = 0
    timestamp: datetime = field(default_factory=datetime.now)


class ConcurrencyScheduler:
    """
    并发任务调度器

    核心功能：
    1. 根据 SafetyLevel 分组工具
    2. 控制每组最大并发数
    3. 优先级队列调度
    4. 自动重试与超时
    """

    def __init__(self):
        self.tools: Dict[str, ToolDefinition] = {}
        self.task_queue: List[Task] = []
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self.results: List[ExecutionResult] = []

        # 每组并发信号量
        self.semaphores: Dict[SafetyLevel, asyncio.Semaphore] = {
            SafetyLevel.READ_ONLY: asyncio.Semaphore(10),  # 只读操作允许高并发
            SafetyLevel.WORKSPACE_WRITE: asyncio.Semaphore(3),  # 写入操作限制并发
            SafetyLevel.DANGER_FULL_ACCESS: asyncio.Semaphore(1),  # 危险操作串行
        }

        # 每组当前运行计数
        self.running_counts: Dict[SafetyLevel, int] = defaultdict(int)

        logger.info("[ConcurrencyScheduler] 初始化完成")

    def register_tool(self, tool: ToolDefinition):
        """注册工具"""
        self.tools[tool.name] = tool
        logger.info(
            f"[ConcurrencyScheduler] 注册工具: {tool.name} (级别: {tool.safety_level.value})"
        )

    def register_tool_from_metadata(
        self,
        name: str,
        description: str,
        is_concurrency_safe: bool,
        safety_level: Optional[SafetyLevel] = None,
        max_concurrent: int = 1,
        **kwargs,
    ):
        """
        从元数据注册工具

        Args:
            name: 工具名称
            description: 工具描述
            is_concurrency_safe: 是否可并发 (True -> READ_ONLY)
            safety_level: 安全级别 (优先使用)
            max_concurrent: 最大并发数
        """
        # 确定安全级别
        if safety_level:
            level = safety_level
        elif is_concurrency_safe:
            level = SafetyLevel.READ_ONLY
        else:
            level = SafetyLevel.WORKSPACE_WRITE  # 默认视为有风险

        tool = ToolDefinition(
            name=name,
            description=description,
            safety_level=level,
            is_concurrency_safe=is_concurrency_safe,
            max_concurrent=max_concurrent,
        )
        self.register_tool(tool)

    async def execute(
        self,
        tool_name: str,
        params: Dict[str, Any],
        executor: Callable[[Dict[str, Any]], Awaitable[Any]],
        priority: int = 1,
        task_id: Optional[str] = None,
    ) -> ExecutionResult:
        """
        执行工具

        Args:
            tool_name: 工具名称
            params: 参数
            executor: 执行函数
            priority: 优先级
            task_id: 任务 ID (自动生成)

        Returns:
            执行结果
        """
        if tool_name not in self.tools:
            raise ValueError(f"工具不存在: {tool_name}")

        tool = self.tools[tool_name]
        task_id = task_id or f"{tool_name}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

        task = Task(id=task_id, tool_name=tool_name, params=params, priority=priority)

        logger.debug(f"[ConcurrencyScheduler] 提交任务: {task_id}, 优先级: {priority}")

        # 执行任务（带重试）
        result = await self._execute_with_retry(task, executor, tool)
        self.results.append(result)

        return result

    async def _execute_with_retry(
        self, task: Task, executor: Callable[[Dict[str, Any]], Awaitable[Any]], tool: ToolDefinition
    ) -> ExecutionResult:
        """带重试的执行"""
        last_error = None

        for attempt in range(tool.retry_count + 1):
            try:
                # 获取信号量
                semaphore = self.semaphores[tool.safety_level]
                async with semaphore:
                    self.running_counts[tool.safety_level] += 1
                    logger.debug(
                        f"[ConcurrencyScheduler] 执行任务: {task.id}, 并发数: {self.running_counts[tool.safety_level]}"  # noqa: E501
                    )

                    start_time = datetime.now()

                    # 执行（带超时）
                    result = await asyncio.wait_for(
                        executor(task.params), timeout=tool.timeout_seconds
                    )

                    duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                    self.running_counts[tool.safety_level] -= 1

                    return ExecutionResult(
                        task_id=task.id,
                        tool_name=task.tool_name,
                        success=True,
                        result=result,
                        duration_ms=duration_ms,
                    )

            except asyncio.TimeoutError:
                last_error = f"超时 (>{tool.timeout_seconds}s)"
                logger.warning(
                    f"[ConcurrencyScheduler] 任务超时: {task.id}, 尝试 {attempt + 1}/{tool.retry_count + 1}"
                )

            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"[ConcurrencyScheduler] 任务失败: {task.id}, 错误: {last_error}, 尝试 {attempt + 1}/{tool.retry_count + 1}"
                )

            # 等待后重试
            if attempt < tool.retry_count:
                await asyncio.sleep(2**attempt)  # 指数退避

        # 所有重试失败
        return ExecutionResult(
            task_id=task.id, tool_name=task.tool_name, success=False, error=last_error
        )

    async def execute_batch(
        self,
        tasks: List[Dict[str, Any]],
        executor_map: Dict[str, Callable[[Dict[str, Any]], Awaitable[Any]]],
    ) -> List[ExecutionResult]:
        """
        批量执行任务

        Args:
            tasks: 任务列表 [{tool_name, params, priority}, ...]
            executor_map: 工具执行函数映射 {tool_name: executor}

        Returns:
            执行结果列表
        """
        coroutines = []

        for task_data in tasks:
            tool_name = task_data["tool_name"]
            if tool_name not in executor_map:
                logger.error(f"[ConcurrencyScheduler] 工具无执行函数: {tool_name}")
                continue

            coro = self.execute(
                tool_name=tool_name,
                params=task_data["params"],
                executor=executor_map[tool_name],
                priority=task_data.get("priority", 1),
                task_id=task_data.get("task_id"),
            )
            coroutines.append(coro)

        # 并发执行所有任务
        results = await asyncio.gather(*coroutines, return_exceptions=True)

        # 处理异常结果
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(
                    ExecutionResult(
                        task_id=tasks[i].get("task_id", f"unknown_{i}"),
                        tool_name=tasks[i]["tool_name"],
                        success=False,
                        error=str(result),
                    )
                )
            else:
                processed_results.append(result)

        return processed_results

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "registered_tools": len(self.tools),
            "tools_by_level": {
                level.value: sum(1 for t in self.tools.values() if t.safety_level == level)
                for level in SafetyLevel
            },
            "running_counts": dict(self.running_counts),
            "total_results": len(self.results),
            "success_rate": (
                sum(1 for r in self.results if r.success) / len(self.results) * 100
                if self.results
                else 0
            ),
        }

    def list_tools(self) -> List[Dict[str, Any]]:
        """列出所有工具"""
        return [
            {
                "name": t.name,
                "description": t.description,
                "safety_level": t.safety_level.value,
                "is_concurrency_safe": t.is_concurrency_safe,
                "max_concurrent": t.max_concurrent,
            }
            for t in self.tools.values()
        ]


# ============ 示例用法 ============


async def example_usage():
    """示例用法"""
    # 安全临时目录
    import tempfile

    temp_dir = tempfile.mkdtemp(prefix="tender_", mode=0o700)

    scheduler = ConcurrencyScheduler()

    # 注册工具
    scheduler.register_tool_from_metadata(
        name="read_file", description="读取文件", is_concurrency_safe=True
    )

    scheduler.register_tool_from_metadata(
        name="write_file",
        description="写入文件",
        is_concurrency_safe=False,
        safety_level=SafetyLevel.WORKSPACE_WRITE,
    )

    scheduler.register_tool_from_metadata(
        name="delete_file",
        description="删除文件",
        is_concurrency_safe=False,
        safety_level=SafetyLevel.DANGER_FULL_ACCESS,
    )

    # 定义执行函数
    async def read_file_executor(params):
        await asyncio.sleep(0.1)  # 模拟 IO
        return f"Read {params['path']}"

    async def write_file_executor(params):
        await asyncio.sleep(0.5)  # 模拟 IO
        return f"Wrote {params['path']}"

    async def delete_file_executor(params):
        await asyncio.sleep(0.3)
        return f"Deleted {params['path']}"

    executor_map = {
        "read_file": read_file_executor,
        "write_file": write_file_executor,
        "delete_file": delete_file_executor,
    }

    # 批量执行
    tasks = [
        {"tool_name": "read_file", "params": {"path": f"{temp_dir}/a.txt"}, "priority": 5},
        {"tool_name": "read_file", "params": {"path": f"{temp_dir}/b.txt"}, "priority": 5},
        {"tool_name": "write_file", "params": {"path": f"{temp_dir}/c.txt"}, "priority": 8},
        {
            "tool_name": "delete_file",
            "params": {"path": f"{temp_dir}/d.txt"},
            "priority": 10,
        },
    ]

    results = await scheduler.execute_batch(tasks, executor_map)

    for r in results:
        status = "✅" if r.success else "❌"
        logger.info(f"{status} {r.task_id}: {r.tool_name} - {r.duration_ms}ms")

    # 统计
    stats = scheduler.get_stats()
    logger.info(f"统计: {stats}")


if __name__ == "__main__":
    asyncio.run(example_usage())
