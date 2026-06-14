"""P0-4: 调度辅助模块 — 从 main.py 拆出
=========================================

负责:
- _build_crawl_task: 将 TenderInfo 映射为 SmartScheduler 的 CrawlTask

原 main.py:87-117
"""
from app.core.harvest.smart_scheduler import CrawlTask


def _build_crawl_task(item, index: int) -> CrawlTask:
    """将 TenderInfo 映射为 CrawlTask（用于 SmartScheduler）"""
    source = "cqggzy"
    if hasattr(item, "source_url") and item.source_url:
        if "ccgp" in item.source_url:
            source = "ccgp"
        elif "ggzy" in item.source_url:
            source = "cqggzy"

    # 静态优先级：预算越高优先级越高（归一化到 1-10）
    priority_static = 5
    if hasattr(item, "budget") and item.budget:
        try:
            budget_str = item.budget.replace("万元", "").replace("元", "").replace(",", "").strip()
            budget_val = float(budget_str)
            priority_static = min(10, max(1, int(budget_val / 500)))  # 每500万1分，上限10
        except (ValueError, AttributeError):
            pass

    return CrawlTask(
        task_id=f"detail_{index}_{item.url}",
        source=source,
        url=item.url,
        info_type=getattr(item, "info_type", "招标公告"),
        region="重庆",
        deadline=getattr(item, "deadline", None),
        publish_date=getattr(item, "publish_date", None),  # 2026-06-08 新增：透传 publish_date 用于时效性计算
        keywords=getattr(item, "keywords_matched", []),
        priority_static=priority_static,
    )
