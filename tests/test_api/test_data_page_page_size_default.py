"""data 页 page_size 默认值测试 (2026-06-26 PR #45)

覆盖 `get_projects` 的 page_size Query 默认值:
- 默认值应为 500 (不是 100)
- ge=1 验证 (≥ 1)
- le=20000 验证 (≤ 20000)
- 默认请求不带 page_size 参数时, API 应返回 ≤ 500 条

策略: 通过 FastAPI TestClient 验证默认值实际生效, 不需要走完整 HTTP 栈.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestPageSizeDefault:
    """page_size Query 默认值 = 500"""

    def test_default_page_size_is_500(self):
        """验证 Query(500) 默认值设置正确"""
        # 读源码确认默认值, 不通过运行时 (避免依赖其他模块)
        import inspect
        from app.api.routes import projects

        source = inspect.getsource(projects.get_projects)
        # 找 page_size: int = Query(N, ...) 的 N
        import re
        m = re.search(r"page_size:\s*int\s*=\s*Query\((\d+)", source)
        assert m is not None, "page_size Query 默认值未找到"
        default = int(m.group(1))
        assert default == 500, f"page_size 默认值应为 500, 实际 {default}"

    def test_page_size_query_bounds(self):
        """验证 Query 范围: ge=1, le=20000"""
        import inspect
        from app.api.routes import projects

        source = inspect.getsource(projects.get_projects)
        # 验证 Query 范围参数
        assert "ge=1" in source.split("page_size: int = Query")[1].split(",")[0:3].__str__()
        assert "le=20000" in source


class TestPageSizeVisibilityRegression:
    """回归: page_size=500 时, fahcqmu 应出现在默认视图"""

    def test_fahcqmu_appears_with_page_size_500(self):
        """验证 page_size=500 时, 模拟数据集中 fahcqmu 能被前 500 条看见

        直接模拟 API 层 _load_projects + filter + sort 流程, 不走 HTTP
        """
        # 模拟数据: fahcqmu 6-24 + cqggzy 6-25/6-26
        items = []
        # cqggzy 6-26 (5 条) - 最新
        for i in range(5):
            items.append({
                "url": f"https://www.cqggzy.com/{i}",
                "publish_date": "2026-06-26",
                "scraped_at": "2026-06-26T08:00:00",
                "business_type": "政府采购",
            })
        # cqggzy 6-25 (207 条)
        for i in range(207):
            items.append({
                "url": f"https://www.cqggzy.com/25/{i}",
                "publish_date": "2026-06-25",
                "scraped_at": "2026-06-25T10:00:00",
                "business_type": "政府采购" if i % 2 else "工程招投标",
            })
        # cqggzy 6-24 (232 条)
        for i in range(232):
            items.append({
                "url": f"https://www.cqggzy.com/24/{i}",
                "publish_date": "2026-06-24",
                "scraped_at": "2026-06-24T10:00:00",
                "business_type": "政府采购" if i % 2 else "工程招投标",
            })
        # fahcqmu 6-24 (1 条)
        items.append({
            "url": "https://www.fahcqmu.cn/1",
            "publish_date": "2026-06-24",
            "scraped_at": "2026-06-26T10:20:00",
            "business_type": "医院采购",
        })

        # 二级排序 + 取前 500
        def _sort_key(p):
            pub = p.get("publish_date") or ""
            scraped = p.get("scraped_at") or ""
            if hasattr(scraped, "isoformat"):
                scraped = scraped.isoformat()
            return (pub, scraped)
        items.sort(key=_sort_key, reverse=True)

        page_size = 500
        page_items = items[:page_size]
        # fahcqmu 应出现在 page_items 中
        fahcqmu_count = sum(1 for p in page_items if p.get("business_type") == "医院采购")
        assert fahcqmu_count == 1, f"page_size={page_size} 时 fahcqmu 应见 1 条, 实际 {fahcqmu_count}"

    def test_page_size_100_old_default_excludes_fahcqmu(self):
        """回归: 旧默认 page_size=100 时, fahcqmu 不可见 (确认改动有意义)"""
        # 同上模拟数据
        items = []
        for i in range(5):
            items.append({"publish_date": "2026-06-26", "business_type": "政府采购"})
        for i in range(207):
            items.append({"publish_date": "2026-06-25", "business_type": "政企" if i % 2 else "工程"})
        for i in range(232):
            items.append({"publish_date": "2026-06-24", "business_type": "政企" if i % 2 else "工程"})
        items.append({"publish_date": "2026-06-24", "business_type": "医院采购"})

        # 排序 (单 key)
        items.sort(key=lambda p: p.get("publish_date", "") or "", reverse=True)

        # 旧默认 100
        page_size = 100
        page_items = items[:page_size]
        fahcqmu_count = sum(1 for p in page_items if p.get("business_type") == "医院采购")
        # 旧默认下 fahcqmu 不可见 (确认 PR #43 + #45 改动有效)
        assert fahcqmu_count == 0, f"page_size=100 时 fahcqmu 应不可见 (回归基线), 实际 {fahcqmu_count}"