"""
test_timeliness_factor.py
2026-06-08 新增：验证 _timeliness_factor 在 publish_date 路径下的正确性

修复 Bug 1（当天数据采不全）：
- 旧逻辑：task.deadline 为 None 时返回 0.5（中性）
- 新逻辑：deadline 缺失时按 publish_date 计算时效性
  - 今天发布 → 1.0
  - 7 天前发布 → 0.2
  - > 7 天 → 0.2
  - 未来日期（数据异常）→ 1.0
  - 都缺失 → 0.3
"""
import asyncio
from datetime import datetime, timezone, timedelta

import pytest

from app.core.harvest.smart_scheduler import DynamicPriorityEngine, CrawlTask


@pytest.fixture
def engine():
    return DynamicPriorityEngine()


def _make_task(deadline=None, publish_date=None) -> CrawlTask:
    return CrawlTask(
        task_id="t1",
        source="cqggzy",
        url="https://example.com/x",
        deadline=deadline,
        publish_date=publish_date,
    )


def test_no_deadline_no_publish_date(engine):
    """都缺失：应返回 0.3（不再中性 0.5）"""
    task = _make_task()
    score = asyncio.run(engine._timeliness_factor(task))
    assert score == pytest.approx(0.3, abs=0.01), f"expected 0.3, got {score}"


def test_publish_date_today(engine):
    """今天发布：应返回 1.0"""
    today = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    task = _make_task(publish_date=today)
    score = asyncio.run(engine._timeliness_factor(task))
    assert score == pytest.approx(1.0, abs=0.01), f"expected 1.0, got {score}"


def test_publish_date_1_day_ago(engine):
    """1 天前：应返回 ~0.886 (1.0 - 0.8 * 1/7)"""
    one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    task = _make_task(publish_date=one_day_ago)
    score = asyncio.run(engine._timeliness_factor(task))
    expected = 1.0 - 0.8 * (1.0 / 7.0)
    assert score == pytest.approx(expected, abs=0.01), f"expected {expected}, got {score}"


def test_publish_date_3_days_ago(engine):
    """3 天前：应返回 ~0.657 (1.0 - 0.8 * 3/7)"""
    three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
    task = _make_task(publish_date=three_days_ago)
    score = asyncio.run(engine._timeliness_factor(task))
    expected = 1.0 - 0.8 * (3.0 / 7.0)
    assert score == pytest.approx(expected, abs=0.01), f"expected {expected}, got {score}"


def test_publish_date_7_days_ago(engine):
    """7 天前：应返回 0.2 (下限)"""
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    task = _make_task(publish_date=seven_days_ago)
    score = asyncio.run(engine._timeliness_factor(task))
    assert score == pytest.approx(0.2, abs=0.01), f"expected 0.2, got {score}"


def test_publish_date_30_days_ago(engine):
    """> 7 天的旧数据：应返回 0.2（让位给新数据）"""
    old_date = datetime.now(timezone.utc) - timedelta(days=30)
    task = _make_task(publish_date=old_date)
    score = asyncio.run(engine._timeliness_factor(task))
    assert score == pytest.approx(0.2, abs=0.01), f"expected 0.2, got {score}"


def test_publish_date_future_data_anomaly(engine):
    """未来日期（数据异常）：应返回 1.0"""
    future = datetime.now(timezone.utc) + timedelta(days=1)
    task = _make_task(publish_date=future)
    score = asyncio.run(engine._timeliness_factor(task))
    assert score == pytest.approx(1.0, abs=0.01), f"expected 1.0, got {score}"


def test_publish_date_naive_tz_assumed_utc(engine):
    """naive datetime 应假定为 UTC"""
    naive_today = datetime.now(timezone.utc).replace(tzinfo=None)
    task = _make_task(publish_date=naive_today)
    # 修复后 task.publish_date 应被加上 UTC tzinfo
    score = asyncio.run(engine._timeliness_factor(task))
    assert task.publish_date.tzinfo is not None, "publish_date 应被加上 UTC tzinfo"
    assert 0.95 <= score <= 1.0, f"naive today 应在 ~1.0，实际 {score}"


def test_deadline_takes_precedence_over_publish_date(engine):
    """deadline 存在时走 deadline 路径，不读 publish_date"""
    now = datetime.now(timezone.utc)
    deadline = now + timedelta(hours=24)  # 24h 后到期
    old_publish = now - timedelta(days=60)  # publish_date 很旧
    task = _make_task(deadline=deadline, publish_date=old_publish)

    # deadline 路径：1 - exp(-24/48) ≈ 0.393
    expected = 1.0 - 2.71828 ** (-24.0 / 48.0)
    score = asyncio.run(engine._timeliness_factor(task))
    assert score == pytest.approx(expected, abs=0.01), f"deadline 应优先，实际 {score}"


def test_today_higher_priority_than_old(engine):
    """核心修复目标：今天发布的 priority 显著高于 6 天前"""
    today = datetime.now(timezone.utc)
    six_days_ago = today - timedelta(days=6)
    task_today = _make_task(publish_date=today)
    task_old = _make_task(publish_date=six_days_ago)
    score_today = asyncio.run(engine._timeliness_factor(task_today))
    score_old = asyncio.run(engine._timeliness_factor(task_old))
    # 今天: 1.0, 6天前: 1.0 - 0.8 * 6/7 ≈ 0.314
    assert score_today > score_old + 0.5, (
        f"修复失败：今天({score_today:.3f}) 应远高于 6 天前({score_old:.3f})"
    )
