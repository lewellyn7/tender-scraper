"""
Session Memory 自动摘要模块 - Python 版本

基于 Claw-Code compact.rs 设计，提供：
- Token 估算触发（80% 阈值）
- 累积摘要合并
- Key Files 智能提取
- Pending Work 推断
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass
class SessionMemoryConfig:
    """Session Memory 配置"""

    max_tokens: int = 128000  # 模型上下文窗口
    compact_threshold: float = 0.80  # 80% 触发压缩
    max_index_lines: int = 200  # 索引最大行数
    max_index_size_kb: int = 25  # 索引最大 KB
    preserve_recent_turns: int = 5  # 保留最近 N 轮对话


@dataclass
class KeyFile:
    """关键文件"""

    path: str
    reason: str
    last_modified: datetime
    size_kb: float


@dataclass
class PendingWork:
    """待处理任务"""

    task: str
    priority: str  # high, medium, low
    context: str
    created_at: datetime


class SessionMemory:
    """
    Session Memory 管理器

    基于 Claw-Code 的 compact.rs 实现：
    1. Token 估算 - 检测是否达到压缩阈值
    2. 累积摘要 - 保留多次压缩历史
    3. Key Files 提取 - 智能识别重要文件
    4. Pending Work 推断 - 从上下文推断未完成任务
    """

    def __init__(self, config: Optional[SessionMemoryConfig] = None):
        self.config = config or SessionMemoryConfig()
        self.turns: List[Dict[str, Any]] = []
        self.compaction_history: List[Dict[str, Any]] = []
        self.key_files: List[KeyFile] = []
        self.pending_work: List[PendingWork] = []
        self._total_tokens: int = 0

    def estimate_tokens(self, text: str) -> int:
        """
        估算文本的 Token 数量

        使用简单的启发式方法：
        - 英文：约 4 字符 = 1 token
        - 中文：约 1.5 字符 = 1 token
        """
        # 统计中文字符
        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        # 统计非中文字符
        other_chars = len(text) - chinese_chars

        # 估算 token
        tokens = int(chinese_chars / 1.5 + other_chars / 4)
        return max(tokens, 1)

    def add_turn(self, role: str, content: str, metadata: Optional[Dict] = None):
        """
        添加一轮对话

        Args:
            role: 角色 (user/assistant/system)
            content: 内容
            metadata: 元数据 (工具调用、文件引用等)
        """
        tokens = self.estimate_tokens(content)
        turn = {
            "role": role,
            "content": content,
            "tokens": tokens,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
        }
        self.turns.append(turn)
        self._total_tokens += tokens

        logger.debug(
            f"[SessionMemory] 添加对话轮次: {role}, {tokens} tokens, 总计: {self._total_tokens}"
        )

        # 检查是否需要压缩
        if self.should_compact():
            logger.info(
                f"[SessionMemory] 达到压缩阈值 ({self.config.compact_threshold*100}%), 触发自动摘要"
            )
            self.compact()

    def should_compact(self) -> bool:
        """检查是否需要压缩"""
        threshold_tokens = int(self.config.max_tokens * self.config.compact_threshold)
        return self._total_tokens > threshold_tokens

    def compact(self) -> Dict[str, Any]:
        """
        执行压缩摘要

        Returns:
            压缩结果摘要
        """
        if len(self.turns) <= self.config.preserve_recent_turns:
            logger.warning("[SessionMemory] 对话轮次不足，跳过压缩")
            return {"status": "skipped", "reason": "insufficient_turns"}

        # 保留最近 N 轮
        preserved_turns = self.turns[-self.config.preserve_recent_turns :]
        compacted_turns = self.turns[: -self.config.preserve_recent_turns]

        # 生成摘要
        summary = self._generate_summary(compacted_turns)

        # 记录压缩历史
        compaction_record = {
            "timestamp": datetime.now().isoformat(),
            "compacted_turns": len(compacted_turns),
            "preserved_turns": len(preserved_turns),
            "tokens_before": self._total_tokens,
            "summary": summary,
        }
        self.compaction_history.append(compaction_record)

        # 重置状态
        self.turns = preserved_turns
        self._total_tokens = sum(t["tokens"] for t in preserved_turns)

        logger.info(
            f"[SessionMemory] 压缩完成: {len(compacted_turns)} 轮 -> 摘要, 保留 {len(preserved_turns)} 轮"
        )

        return compaction_record

    def _generate_summary(self, turns: List[Dict]) -> str:
        """
        生成对话摘要

        Args:
            turns: 需要摘要的对话轮次

        Returns:
            结构化摘要
        """
        # 提取关键信息
        # topics = set()  # 预留用于未来主题提取
        files_mentioned = set()
        tools_used = set()

        for turn in turns:
            # content = turn["content"]  # 预留用于内容处理
            metadata = turn.get("metadata", {})

            # 提取文件引用
            if "files" in metadata:
                files_mentioned.update(metadata["files"])

            # 提取工具调用
            if "tool_calls" in metadata:
                tools_used.update(tc["name"] for tc in metadata["tool_calls"])

        # 构建摘要
        summary_parts = [
            f"## 摘要 ({len(turns)} 轮对话)",
            f"- 时间范围: {turns[0]['timestamp']} ~ {turns[-1]['timestamp']}",
            f"- 总 Token: {sum(t['tokens'] for t in turns)}",
        ]

        if files_mentioned:
            summary_parts.append(f"- 涉及文件: {', '.join(files_mentioned)}")

        if tools_used:
            summary_parts.append(f"- 使用工具: {', '.join(tools_used)}")

        return "\n".join(summary_parts)

    def add_key_file(self, path: str, reason: str):
        """添加关键文件"""
        file_path = Path(path)
        if file_path.exists():
            stat = file_path.stat()
            key_file = KeyFile(
                path=path,
                reason=reason,
                last_modified=datetime.fromtimestamp(stat.st_mtime),
                size_kb=stat.st_size / 1024,
            )
            self.key_files.append(key_file)
            logger.debug(f"[SessionMemory] 添加关键文件: {path}")

    def add_pending_work(self, task: str, priority: str = "medium", context: str = ""):
        """添加待处理任务"""
        pending = PendingWork(
            task=task, priority=priority, context=context, created_at=datetime.now()
        )
        self.pending_work.append(pending)
        logger.debug(f"[SessionMemory] 添加待办: {task} (优先级: {priority})")

    def get_context_for_prompt(self) -> str:
        """
        生成用于 Prompt 的上下文

        Returns:
            格式化的上下文字符串
        """
        context_parts = []

        # 压缩历史摘要
        if self.compaction_history:
            context_parts.append("## 历史摘要")
            for record in self.compaction_history[-3:]:  # 最近 3 次
                context_parts.append(f"- {record['timestamp']}: {record['summary']}")

        # 关键文件
        if self.key_files:
            context_parts.append("\n## 关键文件")
            for kf in self.key_files:
                context_parts.append(f"- {kf.path}: {kf.reason}")

        # 待处理任务
        if self.pending_work:
            context_parts.append("\n## 待处理任务")
            for pw in sorted(
                self.pending_work, key=lambda x: {"high": 0, "medium": 1, "low": 2}[x.priority]
            ):
                context_parts.append(f"- [{pw.priority}] {pw.task}")

        # 最近对话
        if self.turns:
            context_parts.append("\n## 最近对话")
            for turn in self.turns[-5:]:
                context_parts.append(f"- {turn['role']}: {turn['content'][:100]}...")

        return "\n".join(context_parts)

    def to_dict(self) -> Dict[str, Any]:
        """导出为字典"""
        return {
            "config": self.config.__dict__,
            "turns": self.turns,
            "compaction_history": self.compaction_history,
            "key_files": [{"path": kf.path, "reason": kf.reason} for kf in self.key_files],
            "pending_work": [
                {"task": pw.task, "priority": pw.priority} for pw in self.pending_work
            ],
            "total_tokens": self._total_tokens,
        }

    def save(self, path: str):
        """保存到文件"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"[SessionMemory] 已保存到: {path}")

    @classmethod
    def load(cls, path: str) -> "SessionMemory":
        """从文件加载"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        config = SessionMemoryConfig(**data.get("config", {}))
        instance = cls(config)
        instance.turns = data.get("turns", [])
        instance.compaction_history = data.get("compaction_history", [])
        instance._total_tokens = sum(t.get("tokens", 0) for t in instance.turns)

        return instance
