"""tests/test_crawlers/test_cqggzy_daily_mode.py
2026-06-18 验证: 切到今日模式后 URL date 参数 + 列表 start_date 都为 today.

覆盖:
- 3 个 category URL 构造都含 date=today
- 切换前的 date=3m 痕迹已清理
"""
import re

from app.crawlers.cqggzy import CQGGZYCrawlerV2


def _url_construction_code():
    """读源码, 不需要实例化 crawler (避免启动浏览器)"""
    src = open('app/crawlers/cqggzy.py').read()
    return src


class TestURLDateParam:
    """URL 构造使用 date=today (而非 date=3m)"""

    def test_gov_purchase_url_uses_today(self):
        """政府采购 URL 含 date=today"""
        src = _url_construction_code()
        # gov_purchase 分支
        assert 'base_url = "https://www.cqggzy.com/trade/014005"' in src
        assert 'pageNum={page_num}&date=today&categoryNum=014005001' in src
        assert 'pageNum={page_num}&date=3m&categoryNum=014005001' not in src

    def test_engineering_url_uses_today(self):
        """工程建设 URL 含 date=today"""
        src = _url_construction_code()
        assert 'base_url = "https://www.cqggzy.com/trade/014001"' in src
        assert 'pageNum={page_num}&date=today&categoryNum=014001001' in src
        assert 'pageNum={page_num}&date=3m&categoryNum=014001001' not in src

    def test_fallback_url_uses_today(self):
        """其他 category fallback URL 含 date=today (2026-06-23: 变量名 base → base_url)"""
        src = _url_construction_code()
        # 2026-06-23: 变量名重命名 (base → base_url) + trade_id 从 LIST_URLS 拿
        assert 'f"{base_url}?pageNum={page_num}&date=today&categoryNum={cat_num}"' in src
        assert 'f"{base}?pageNum={page_num}&date=3m&categoryNum={cat_num}"' not in src
        # 验证 LIST_URLS fallback 正确
        assert 'self.LIST_URLS.get(category, ("014005", "014005001"))' in src

    def test_no_stale_date3m_string(self):
        """代码中无任何 date=3m 残留"""
        src = _url_construction_code()
        # 注释里的"date=3m"应该都被清理 (除历史说明注释外)
        # 检查实际 URL 拼接处无 date=3m
        url_pattern = re.compile(r'f["\'][^"\']*date=3m[^"\']*["\']')
        matches = url_pattern.findall(src)
        assert matches == [], f"Found stale date=3m in URL: {matches}"


class TestPipelineDateRange:
    """pipeline.py start_date = today (今日模式)"""

    def test_pipeline_start_date_is_today(self):
        """pipeline start_date = today (无 timedelta(days=N) 减法)"""
        src = open('app/core/harvest/pipeline.py').read()
        # 找到 "start_date = " 行
        m = re.search(r'start_date\s*=\s*([^\n]+)', src)
        assert m, "start_date assignment not found"
        line = m.group(1).strip()
        # 应该形如: "today  # 今日模式..."
        assert line.startswith('today'), f"start_date line: {line}"
        assert 'timedelta' not in line, f"start_date should not use timedelta: {line}"

    def test_pipeline_end_date_keeps_t1(self):
        """end_date 仍为 today + 1 day (CQGGZY edt 排他补偿)"""
        src = open('app/core/harvest/pipeline.py').read()
        m = re.search(r'end_date\s*=\s*([^\n]+)', src)
        assert m
        line = m.group(1).strip()
        assert 'today' in line and 'timedelta(days=1)' in line
