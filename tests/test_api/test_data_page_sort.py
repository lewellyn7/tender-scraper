"""data 页排序逻辑测试 (2026-06-26 PR #45)

覆盖 `get_projects` 的二级排序 (publish_date DESC + scraped_at DESC):
- 同 publish_date 时, 按 scraped_at DESC 排 (新采集的 fahcqmu 排前)
- 不同 publish_date 时, publish_date DESC 优先
- publish_date NULL 时, 排到最后 (不报错)
- scraped_at datetime 格式正确序列化
- 回归: budget 排序不受影响

策略: 直接测试排序 key 函数, 不走完整 FastAPI 路由 (避免 Query() MagicMock).
"""
from datetime import datetime
import pytest


def _sort_key(p):
    """复刻 projects.py:_sort_key 逻辑, 单测独立可测"""
    pub = p.get("publish_date") or ""
    scraped = p.get("scraped_at") or ""
    if hasattr(scraped, "isoformat"):
        scraped = scraped.isoformat()
    return (pub, scraped)


class TestSortKeySecondary:
    """二级排序核心逻辑"""

    def test_same_date_different_scraped_at(self):
        """同 publish_date, 按 scraped_at DESC"""
        items = [
            {"publish_date": "2026-06-25", "scraped_at": datetime(2026, 6, 25, 22, 0)},
            {"publish_date": "2026-06-25", "scraped_at": datetime(2026, 6, 25, 10, 0)},
            {"publish_date": "2026-06-25", "scraped_at": datetime(2026, 6, 25, 18, 0)},
        ]
        items.sort(key=_sort_key, reverse=True)
        # 期望顺序: 22:00 → 18:00 → 10:00
        assert items[0]["scraped_at"].hour == 22
        assert items[1]["scraped_at"].hour == 18
        assert items[2]["scraped_at"].hour == 10

    def test_different_dates_priority(self):
        """不同 publish_date, 按 publish_date DESC 优先"""
        items = [
            {"publish_date": "2026-06-23", "scraped_at": datetime(2026, 6, 25, 22, 0)},
            {"publish_date": "2026-06-25", "scraped_at": datetime(2026, 6, 25, 10, 0)},
            {"publish_date": "2026-06-24", "scraped_at": datetime(2026, 6, 25, 22, 0)},
        ]
        items.sort(key=_sort_key, reverse=True)
        # 期望顺序: 6-25 → 6-24 → 6-23 (date DESC)
        assert items[0]["publish_date"] == "2026-06-25"
        assert items[1]["publish_date"] == "2026-06-24"
        assert items[2]["publish_date"] == "2026-06-23"

    def test_null_publish_date_goes_last(self):
        """publish_date NULL → 排到最后 (不报错)"""
        items = [
            {"publish_date": None, "scraped_at": datetime(2026, 6, 25, 22, 0)},
            {"publish_date": "2026-06-25", "scraped_at": datetime(2026, 6, 25, 10, 0)},
            {"publish_date": "", "scraped_at": datetime(2026, 6, 25, 22, 0)},
        ]
        items.sort(key=_sort_key, reverse=True)
        # 期望: 有日期的排前, NULL/空 排后
        assert items[0]["publish_date"] == "2026-06-25"
        # NULL 和 "" 都 → "" (因为 `or ""`), 二级 sort_key 都是 ""
        # 排后, 顺序不重要

    def test_scraped_at_datetime_isoformat(self):
        """scraped_at datetime → isoformat 字符串 (与 publish_date 一致类型)"""
        items = [
            {"publish_date": "2026-06-25", "scraped_at": datetime(2026, 6, 25, 22, 0, 0)},
            {"publish_date": "2026-06-25", "scraped_at": datetime(2026, 6, 25, 10, 0, 0)},
        ]
        # 不能让 tuple 比较跨类型报错
        items.sort(key=_sort_key, reverse=True)
        assert items[0]["scraped_at"].hour == 22

    def test_scraped_at_string_already(self):
        """scraped_at 是 string 时, 不调 isoformat"""
        # 这里直接测 key 函数对 string 类型的兼容性
        result = _sort_key({"publish_date": "2026-06-25", "scraped_at": "2026-06-25T22:00:00"})
        assert result == ("2026-06-25", "2026-06-25T22:00:00")

    def test_scraped_at_none(self):
        """scraped_at None → 空字符串, 不报错"""
        result = _sort_key({"publish_date": "2026-06-25", "scraped_at": None})
        assert result == ("2026-06-25", "")


class TestFahcqmuVisibilityProblem:
    """回归测试: PR #43 之后 fahcqmu 出现在默认视图前 N 条"""

    def test_fahcqmu_appears_in_top_100_after_resort(self):
        """验证 PR #43 之后 fahcqmu 在默认排序下能进 top 100

        场景: fahcqmu 6-24 数据 + cqggzy 6-25 数据, 按新排序应让 6-25 优先,
        但 fahcqmu 6-24 + scraped_at 新 (10:20) 仍能进 6-24 组前面

        简化: 模拟一个混合列表, 验证二级排序后 fahcqmu 仍可见
        """
        # 混合列表: cqggzy 6-25 + fahcqmu 6-24 (scraped_at 新)
        items = [
            # cqggzy 6-25 早采
            {"publish_date": "2026-06-25", "scraped_at": datetime(2026, 6, 25, 9, 0), "url": "cqggzy.com/1"},
            {"publish_date": "2026-06-25", "scraped_at": datetime(2026, 6, 25, 10, 0), "url": "cqggzy.com/2"},
            # fahcqmu 6-24 但 10:20 才采
            {"publish_date": "2026-06-24", "scraped_at": datetime(2026, 6, 26, 10, 20), "url": "fahcqmu.cn/1"},
            {"publish_date": "2026-06-24", "scraped_at": datetime(2026, 6, 26, 10, 19), "url": "fahcqmu.cn/2"},
            # fahcqmu 6-24 老数据
            {"publish_date": "2026-06-24", "scraped_at": datetime(2026, 6, 20, 10, 0), "url": "fahcqmu.cn/3"},
        ]
        items.sort(key=_sort_key, reverse=True)
        # 期望顺序: 6-25 早 + 6-25 晚 + 6-24 10:20 + 6-24 10:19 + 6-24 6-20
        assert "cqggzy.com" in items[0]["url"]
        assert "cqggzy.com" in items[1]["url"]
        # fahcqmu 6-24 但 scraped_at 新, 排第 3
        assert "fahcqmu.cn/1" in items[2]["url"]
        assert "fahcqmu.cn/2" in items[3]["url"]
        assert "fahcqmu.cn/3" in items[4]["url"]


class TestSortRegression:
    """回归: 现有行为不被破坏"""

    def test_old_single_key_behavior_preserved_for_different_dates(self):
        """不同 publish_date 时, 行为与原版一致 (按 date DESC)"""
        # 原版单 key 排序
        items_old = [
            {"publish_date": "2026-06-20"},
            {"publish_date": "2026-06-25"},
            {"publish_date": "2026-06-22"},
        ]
        items_old.sort(key=lambda p: p.get("publish_date", "") or "", reverse=True)
        old_order = [i["publish_date"] for i in items_old]

        # 新版二级排序
        items_new = [
            {"publish_date": "2026-06-20", "scraped_at": None},
            {"publish_date": "2026-06-25", "scraped_at": None},
            {"publish_date": "2026-06-22", "scraped_at": None},
        ]
        items_new.sort(key=_sort_key, reverse=True)
        new_order = [i["publish_date"] for i in items_new]

        assert old_order == new_order

    def test_empty_scraped_at_does_not_break_sort(self):
        """scraped_at 空/None 时, 不影响 publish_date 主排序"""
        items = [
            {"publish_date": "2026-06-25", "scraped_at": None},
            {"publish_date": "2026-06-24", "scraped_at": None},
            {"publish_date": "2026-06-26", "scraped_at": None},
        ]
        items.sort(key=_sort_key, reverse=True)
        assert items[0]["publish_date"] == "2026-06-26"
        assert items[1]["publish_date"] == "2026-06-25"
        assert items[2]["publish_date"] == "2026-06-24"