#!/usr/bin/env python3
"""
审计日志查询工具

支持：
- 按工具名查询
- 按时间范围查询
- 按执行状态查询
- 按会话ID查询

Usage:
    python audit_query.py --query "write_file" --since "1h"
    python audit_query.py --status "FAILED" --since "2024-01-01"
    python audit_query.py --session "session-abc123"
    python audit_query.py --stats
"""

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional


class AuditLogQuery:
    """审计日志查询引擎"""

    # 日志行正则：时间戳 | 会话ID | 工具名 | 参数哈希 | 执行结果 | 耗时(ms) | 详细信息
    # 支持两种时间戳格式：标准格式 (%Y-%m-%dT%H:%M:%S.%fZ) 和 Python logging 默认格式
    LOG_PATTERN = re.compile(
        r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^|]*?)\s*\|\s*([^\|]+)\s*\|\s*([^\|]+)\s*\|\s*([^\|]+)\s*\|\s*([^\|]+)\s*\|\s*(\d+)\s*\|\s*(.+)$'
    )

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_file = self.log_dir / "audit.log"

    def parse_line(self, line: str) -> Optional[Dict]:
        """
        解析日志行
        
        Args:
            line: 日志行
            
        Returns:
            解析后的字典，或 None（如果解析失败）
        """
        match = self.LOG_PATTERN.match(line.strip())
        if not match:
            return None

        timestamp_str, session_id, tool_name, params_hash, result_status, duration_ms, details = match.groups()

        # 尝试多种时间戳格式
        timestamp = datetime.now()
        for fmt in ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S,%fZ", "%Y-%m-%d %H:%M:%S,%f", "%Y-%m-%d %H:%M:%S"]:
            try:
                # 处理 Python logging 使用的逗号格式
                ts_clean = timestamp_str.replace('.%fZ', ',%f').replace('Z', '').strip()
                timestamp = datetime.strptime(ts_clean, fmt.replace('%fZ', '%f').replace('Z', '').replace(',%f', '.%f') if '.' in fmt else fmt)
                break
            except ValueError:
                continue

        try:
            details_json = json.loads(details)
        except json.JSONDecodeError:
            details_json = {"raw": details}

        return {
            "timestamp": timestamp,
            "timestamp_str": timestamp_str,
            "session_id": session_id.strip(),
            "tool_name": tool_name.strip(),
            "params_hash": params_hash.strip(),
            "result_status": result_status.strip(),
            "duration_ms": int(duration_ms),
            "details": details_json
        }

    def parse_time_range(self, since: str) -> datetime:
        """
        解析时间范围字符串
        
        Args:
            since: 时间范围字符串（如 "1h", "2d", "30m", "2024-01-01"）
            
        Returns:
            起始时间
        """
        # 相对时间
        match = re.match(r'^(\d+)([hdwm])$', since.lower())
        if match:
            value, unit = int(match.group(1)), match.group(2)
            if unit == 'h':
                return datetime.now() - timedelta(hours=value)
            elif unit == 'd':
                return datetime.now() - timedelta(days=value)
            elif unit == 'w':
                return datetime.now() - timedelta(weeks=value)
            elif unit == 'm':
                return datetime.now() - timedelta(minutes=value)

        # 绝对时间
        try:
            return datetime.strptime(since, "%Y-%m-%d")
        except ValueError:
            try:
                return datetime.strptime(since, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                raise ValueError(f"无法解析时间范围: {since}")

    def query(
        self,
        tool_name: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        status: Optional[str] = None,
        session_id: Optional[str] = None,
        params_hash: Optional[str] = None,
        min_duration: Optional[int] = None,
        max_duration: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        查询审计日志
        
        Args:
            tool_name: 工具名（支持模糊匹配）
            since: 起始时间
            until: 结束时间
            status: 执行状态
            session_id: 会话ID
            params_hash: 参数哈希
            min_duration: 最小耗时（ms）
            max_duration: 最大耗时（ms）
            limit: 返回结果数量限制
            
        Returns:
            匹配的日志记录列表
        """
        results = []

        if not self.log_file.exists():
            return results

        # 解析时间范围
        since_dt = self.parse_time_range(since) if since else None
        until_dt = self.parse_time_range(until) if until else None

        with open(self.log_file, 'r', encoding='utf-8') as f:
            for line in f:
                record = self.parse_line(line)
                if not record:
                    continue

                # 应用过滤条件
                if tool_name and tool_name.lower() not in record["tool_name"].lower():
                    continue

                if since_dt and record["timestamp"] < since_dt:
                    continue

                if until_dt and record["timestamp"] > until_dt:
                    continue

                if status and record["result_status"].upper() != status.upper():
                    continue

                if session_id and session_id not in record["session_id"]:
                    continue

                if params_hash and record["params_hash"] != params_hash:
                    continue

                if min_duration and record["duration_ms"] < min_duration:
                    continue

                if max_duration and record["duration_ms"] > max_duration:
                    continue

                results.append(record)

                if len(results) >= limit:
                    break

        return results

    def get_stats(self, since: Optional[str] = None) -> Dict:
        """
        获取审计统计信息
        
        Args:
            since: 起始时间
            
        Returns:
            统计信息字典
        """
        stats = {
            "total_calls": 0,
            "success_count": 0,
            "failed_count": 0,
            "started_count": 0,
            "avg_duration_ms": 0,
            "max_duration_ms": 0,
            "min_duration_ms": float('inf'),
            "tool_breakdown": defaultdict(lambda: {"count": 0, "success": 0, "failed": 0, "total_duration": 0}),
            "session_breakdown": defaultdict(int)
        }

        records = self.query(since=since, limit=100000) if since else self.query(limit=100000)

        total_duration = 0
        duration_count = 0

        for record in records:
            stats["total_calls"] += 1
            stats["session_breakdown"][record["session_id"]] += 1
            stats["tool_breakdown"][record["tool_name"]]["count"] += 1

            if record["result_status"] == "SUCCESS":
                stats["success_count"] += 1
                stats["tool_breakdown"][record["tool_name"]]["success"] += 1
            elif record["result_status"] == "FAILED":
                stats["failed_count"] += 1
                stats["tool_breakdown"][record["tool_name"]]["failed"] += 1
            elif record["result_status"] == "STARTED":
                stats["started_count"] += 1
                continue  # STARTED 状态不计入耗时统计

            # 耗时统计
            if record["duration_ms"] > 0:
                total_duration += record["duration_ms"]
                duration_count += 1
                stats["max_duration_ms"] = max(stats["max_duration_ms"], record["duration_ms"])
                stats["min_duration_ms"] = min(stats["min_duration_ms"], record["duration_ms"])
                stats["tool_breakdown"][record["tool_name"]]["total_duration"] += record["duration_ms"]

        if duration_count > 0:
            stats["avg_duration_ms"] = total_duration // duration_count

        if stats["min_duration_ms"] == float('inf'):
            stats["min_duration_ms"] = 0

        # 转换 defaultdict 为普通 dict
        stats["tool_breakdown"] = dict(stats["tool_breakdown"])
        stats["session_breakdown"] = dict(stats["session_breakdown"])

        return stats

    def format_result(self, record: Dict) -> str:
        """格式化单条记录"""
        status_icon = "✓" if record["result_status"] == "SUCCESS" else "✗" if record["result_status"] == "FAILED" else "→"
        return f"[{record['timestamp_str']}] {status_icon} {record['tool_name']:20} | {record['result_status']:8} | {record['duration_ms']:6}ms | {record['session_id']}"


def main():
    parser = argparse.ArgumentParser(
        description="审计日志查询工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python audit_query.py --query "write_file" --since "1h"
  python audit_query.py --status "FAILED" --since "2024-01-01"
  python audit_query.py --session "session-abc123"
  python audit_query.py --stats --since "24h"
  python audit_query.py --min-duration 1000 --since "1h"
        """
    )

    parser.add_argument("--query", "-q", help="按工具名查询（支持模糊匹配）")
    parser.add_argument("--since", "-s", help="起始时间（如 '1h', '2d', '2024-01-01'）")
    parser.add_argument("--until", "-u", help="结束时间")
    parser.add_argument("--status", help="按执行状态过滤（SUCCESS/FAILED/STARTED）")
    parser.add_argument("--session", help="按会话ID过滤")
    parser.add_argument("--params-hash", help="按参数哈希过滤")
    parser.add_argument("--min-duration", type=int, help="最小耗时（ms）")
    parser.add_argument("--max-duration", type=int, help="最大耗时（ms）")
    parser.add_argument("--limit", "-l", type=int, default=100, help="返回结果数量限制")
    parser.add_argument("--stats", action="store_true", help="显示统计信息")
    parser.add_argument("--log-dir", default="logs", help="日志目录")

    args = parser.parse_args()

    query_engine = AuditLogQuery(log_dir=args.log_dir)

    if args.stats:
        stats = query_engine.get_stats(since=args.since)

        print("=" * 60)
        print("审计日志统计")
        if args.since:
            print(f"时间范围: {args.since} 至今")
        print("=" * 60)
        print(f"总调用次数: {stats['total_calls']}")
        print(f"成功: {stats['success_count']} | 失败: {stats['failed_count']} | 进行中: {stats['started_count']}")
        print(f"平均耗时: {stats['avg_duration_ms']}ms")
        print(f"最小耗时: {stats['min_duration_ms']}ms | 最大耗时: {stats['max_duration_ms']}ms")
        print()

        print("工具调用分布:")
        print("-" * 60)
        for tool, data in sorted(stats['tool_breakdown'].items(), key=lambda x: x[1]['count'], reverse=True):
            avg_dur = data['total_duration'] // data['count'] if data['count'] > 0 else 0
            print(f"  {tool:25} | 调用: {data['count']:5} | 成功: {data['success']:5} | 失败: {data['failed']:3} | 平均耗时: {avg_dur:5}ms")

        print()
        print(f"会话数: {len(stats['session_breakdown'])}")

    else:
        results = query_engine.query(
            tool_name=args.query,
            since=args.since,
            until=args.until,
            status=args.status,
            session_id=args.session,
            params_hash=args.params_hash,
            min_duration=args.min_duration,
            max_duration=args.max_duration,
            limit=args.limit
        )

        if not results:
            print("未找到匹配的审计记录")
            return

        print(f"找到 {len(results)} 条记录:")
        print("-" * 80)
        for record in results:
            print(query_engine.format_result(record))
            if 'details' in record and 'error' in record['details']:
                print(f"  错误: {record['details']['error']}")


if __name__ == "__main__":
    main()
