#!/usr/bin/env python3
"""
report_bid_rank.py — 中标排名分析报告 (Markdown)

调用 /api/analysis/bid-rank 端点, 生成 4 份季度报告 (Q1-Q4 + 全年):
  - 政府采购 + 工程招投标 各一份
  - 默认输出到 stdout, 可指定 --output 写文件

用法:
  python scripts/report_bid_rank.py --year 2026
  python scripts/report_bid_rank.py --year 2026 --quarter 2 --info-type 中标结果公示
  python scripts/report_bid_rank.py --year 2026 --output report_2026.md

输出示例 (单 section):
  ## 政府采购 Q2 2026 中标排名

  **汇总**: 50 个中标单位, 487 个项目, 中标金额合计 ¥45.67 亿
  **数据源**: 7854 条 bid_results 记录 (2026-04-01 ~ 2026-06-30)

  | # | 中标单位 | 项目数 | 中标金额 | 单项目均值 | 平均评分 | 首次/末次 |
  |---|----------|--------|----------|------------|----------|-----------|
  | 1 | 重庆数字资源集团 | 8 | ¥4.28亿 | ¥5352万 | - | 2026-04-15 / 2026-05-21 |
  | 2 | 重庆市地勘院 208 队 | 45 | ¥1.71亿 | ¥381万 | - | 2026-04-09 / 2026-05-22 |
"""
import argparse
import json
import os
import sys
from datetime import date
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# 项目根目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def fetch_bid_rank(base_url: str, category: str, period: str, year: int, quarter: int = None,
                   info_type: str = None, limit: int = 20, timeout: int = 30) -> dict:
    """调用 /api/analysis/bid-rank 端点."""
    params = {
        'category': category,
        'period': period,
        'year': year,
        'limit': str(limit),
    }
    if quarter is not None:
        params['quarter'] = str(quarter)
    if info_type:
        params['info_type'] = info_type

    url = f"{base_url.rstrip('/')}/api/analysis/bid-rank?{urlencode(params)}"
    req = Request(url, headers={'Accept': 'application/json'})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def fmt_amount(n: float) -> str:
    """元 → 亿元/万元 显示."""
    if not n or n == 0:
        return '-'
    if n >= 1e8:
        return f'¥{n/1e8:.2f}亿'
    if n >= 1e4:
        return f'¥{n/1e4:.2f}万'
    return f'¥{n:.2f}'


def render_section(category: str, data: dict, info_type: str = None) -> str:
    """渲染单个 ranking section."""
    # info_type 标签只对工程招投标有意义 (政府采购只有 1 种 info_type)
    if category == '工程招投标' and info_type and info_type != 'all':
        info_label = f" ({info_type})"
    else:
        info_label = ""
    period = data['period']['label']
    lines = [
        f"## {category} {period} 中标排名{info_label}",
        "",
        f"**汇总**: {data['total_winners']} 个中标单位, {data['total_projects']} 个项目, "
        f"中标金额合计 **{fmt_amount(data['total_amount'])}**",
        f"**数据源**: bid_results 表 ({data['date_start']} ~ {data['date_end']})",
        "",
        "| # | 中标单位 | 项目数 | 中标金额 | 单项目均值 | 平均评分 | 首次 / 末次 |",
        "|---|----------|--------|----------|------------|----------|-------------|",
    ]
    for r in data['rankings']:
        score = f"{r['avg_score']:.2f}" if r['avg_score'] is not None else '-'
        first_last = f"{r['first_win']} / {r['last_win']}" if r['first_win'] else '-'
        lines.append(
            f"| {r['rank']} | {r['winner_name']} | {r['project_count']} | "
            f"{fmt_amount(r['total_amount'])} | {fmt_amount(r['avg_amount'])} | "
            f"{score} | {first_last} |"
        )

    return '\n'.join(lines) + '\n'


def render_report(year: int, base_url: str, quarter: int = None,
                  info_type: str = None, limit: int = 20) -> str:
    """生成完整报告 (政府采购 + 工程招投标)."""
    out = [
        f"# 中标排名分析报告 ({year})",
        "",
        f"_生成时间: {date.today().isoformat()}_  ",
        f"_API: {base_url}_  ",
        f"_每分类 Top {limit}_",
        "",
    ]

    period = 'quarter' if quarter else 'year'
    for category in ['政府采购', '工程招投标']:
        # 政府采购只接受采购结果公告 (1 种), info_type 参数对其无意义
        cat_info_type = info_type if category == '工程招投标' else None
        try:
            data = fetch_bid_rank(
                base_url=base_url, category=category,
                period=period, year=year, quarter=quarter,
                info_type=cat_info_type, limit=limit,
            )
            out.append(render_section(category, data, info_type))
        except Exception as e:
            out.append(f"## {category}\n\n> ⚠️ 拉取失败: {e}\n")

    out.append("\n---\n_报告由 scripts/report_bid_rank.py 自动生成_\n")
    return '\n'.join(out)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--year', type=int, default=date.today().year, help='年份')
    p.add_argument('--quarter', type=int, choices=[1, 2, 3, 4], help='季度 (1-4), 缺省=全年')
    p.add_argument('--info-type', choices=['中标结果公示', '中标候选人公示', 'all'],
                   default='中标结果公示', help='工程招投标的 info_type 过滤 (默认 中标结果公示)')
    p.add_argument('--base-url', default=os.getenv('TENDER_API_URL', 'http://localhost:8889'),
                   help='API base URL')
    p.add_argument('--limit', type=int, default=20, help='每分类 Top N (默认 20)')
    p.add_argument('--output', '-o', help='输出文件 (默认 stdout)')
    args = p.parse_args()

    report = render_report(
        year=args.year, base_url=args.base_url,
        quarter=args.quarter, info_type=args.info_type,
        limit=args.limit,
    )

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"✅ 报告已写入 {args.output} ({len(report)} 字符)")
    else:
        print(report)


if __name__ == '__main__':
    main()
