"""招投标采集系统 - 主入口 V3
=========================================

**P0-4 重构 (2026-06-14)**:
- 主体代码已拆分到 app/core/harvest/ 子模块
- 本文件仅保留入口 (main + safety check)
- 业务逻辑 0 改动 (PURE LIFT)

子模块:
- app.core.harvest.vectorize: _build_vector_text, _upsert_to_vector_store
- app.core.harvest.scheduler: _build_crawl_task
- app.core.harvest.pipeline:  run_collection (主流程)

采集源策略（2026-06-02 决策）:
- CCGP (重庆政府采购网): **不再进行采集**。详见 memory/2026-06-02.md 和 AGENTS.md
  - SPA 架构, 无服务端日期过滤, 3 个月 API 窗口限制
  - 详情页 URL 提取依赖 JS navigation 拦截, 稳定性差
  - 现存 58 条 CCGP 数据保留不删, 仅停采
- CQGGZY (重庆公共资源交易中心): 唯一活跃采集源
  - 9 个分类并行采集, 每日 9-19 点每 2 小时一次
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loguru import logger

from app.core.harvest.pipeline import run_collection
from app.core.safety_guard import check_production_safety

# 配置日志
logger.add(sys.stderr, format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}", level="INFO", colorize=False)


def main():
    """主入口"""
    result = asyncio.run(run_collection())
    if result:
        print(f"\n✅ 采集完成: {result['filtered']}/{result['total']} 条匹配")
        if result.get('excel_path'):
            print(f"📊 Excel 报表: {result['excel_path']}")
        if result.get('data_path'):
            print(f"📊 数据文件: {result['data_path']}")
    else:
        print("\n⚠️ 未采集到数据")


if __name__ == "__main__":
    # P0-3: production 环境 startup 安全断言 (defense-in-depth)
    check_production_safety()
    main()
