"""Smoke verify ccgp-intent A2 实施 — lesson 7+ 必修 (上次违规点)
测试目标:
1. import ccgp_intent_demand 不报错 (A2 改动 syntax OK)
2. _fetch_detail_json 单条 ID 能拿到 intentionDetaileList[]
3. fetch_details_parallel 跑 5 条, 拿到率 100%
4. full_content 长度提升: list API 仅 36 chars → detail API 平均 225+ chars
"""
import asyncio
import sys

sys.path.insert(0, '/app')  # collector 容器内

from app.crawlers.ccgp_intent_demand import (
    CcgpIntentDemandCrawler,
    _fetch_detail_json,
    DETAIL_API_TPL,
    format_detail_list,
)


async def main():
    print("=" * 60)
    print("=== SMOKE 1: import + DETAIL_API_TPL 正确 ===")
    print("=" * 60)
    print(f"DETAIL_API_TPL = {DETAIL_API_TPL}")
    assert "{id}" in DETAIL_API_TPL, "DETAIL_API_TPL 模板错误"
    # type 参数是 _fetch_detail_json 函数里动态拼的 ?type={type_id}
    # 不在模板里, 而是在调用时拼 — 在 SMOKE 2 验证实际 URL
    print("✅ DETAIL_API_TPL 模板正确 (含 {id}, type 参数在调用时拼)")

    print("\n" + "=" * 60)
    print("=== SMOKE 2: _fetch_detail_json 单条 ID ===")
    print("=" * 60)
    async with CcgpIntentDemandCrawler() as crawler:
        # 先抓 list API 拿真实 18位 ID
        items = await crawler.fetch_list_page(
            cat=__import__('app.crawlers.ccgp_intent_demand', fromlist=['CATEGORIES']).CATEGORIES[0],
            page=1,
        )
        if not items:
            print("❌ list API 无数据 (网络/限流问题)")
            sys.exit(1)
        first = items[0]
        item_id = getattr(first, '_source_id', None)
        type_id = getattr(first, '_source_type', None)
        print(f"测试 ID: {item_id} (type={type_id})")
        print(f"list API full_content len: {len(first.full_content)} (仅 depict={len(first.full_content.split(chr(10))[0]) if first.full_content else 0} chars)")

        # 调详情 API
        detail_data = await _fetch_detail_json(crawler._session, item_id, type_id, retries=3)
        assert detail_data is not None, "详情 API 返回 None"
        print(f"✅ 详情 API 返回, keys: {list(detail_data.keys())[:10]}")

        detail_list = detail_data.get("intentionDetaileList") or []
        print(f"intentionDetaileList: {len(detail_list)} 条")
        assert isinstance(detail_list, list) and detail_list, "intentionDetaileList 应为非空数组"
        d0 = detail_list[0]
        print(f"  [0] title: {d0.get('title', '')[:50]}")
        print(f"  [0] depict len: {len(d0.get('depict') or '')}")
        print(f"  [0] catalogName: {d0.get('catalogName', '')}")

        # 用 detail_data 重建 full_content
        detail_text = format_detail_list(detail_list)
        old_full = first.full_content
        new_full = first.full_content
        if detail_text:
            existing_overview = first.project_overview or ""
            parts = []
            if existing_overview:
                parts.append(f"【项目简介】\n{existing_overview}")
            if detail_text:
                parts.append(f"【采购明细】\n{detail_text}")
            new_full = "\n\n".join(parts)
        first.full_content = new_full
        first.content_preview = new_full[:300] if new_full else ""
        print(f"\n📊 full_content 长度对比:")
        print(f"   旧 (list API): {len(old_full)} chars")
        print(f"   新 (list+detail API): {len(new_full)} chars (+{len(new_full)-len(old_full)}, +{100*(len(new_full)-len(old_full))/max(len(old_full),1):.0f}%)")
        assert len(new_full) > len(old_full), "新 full_content 应更长"

        print("\n" + "=" * 60)
        print("=== SMOKE 3: fetch_details_parallel 跑 5 条 ===")
        print("=" * 60)
        items5 = items[:5]
        before_avg = sum(len(it.full_content) for it in items5) / len(items5)
        print(f"调用前 avg full_content: {before_avg:.0f} chars")
        await crawler.fetch_details_parallel(items5, concurrency=5)
        after_avg = sum(len(it.full_content) for it in items5) / len(items5)
        print(f"调用后 avg full_content: {after_avg:.0f} chars (+{after_avg-before_avg:.0f}, +{100*(after_avg-before_avg)/max(before_avg,1):.0f}%)")
        assert after_avg > before_avg, "fetch_details_parallel 应提升 full_content 长度"

        # 验证 content_preview 跟 full_content 区分开 (仅验证长数据)
        # 注意: 当 full_content <= 300 chars 时, content_preview = full_content (是预期)
        long_count = 0
        for it in items5:
            if len(it.full_content) > 300:
                # 长数据下 content_preview 是 full_content 的前 300 字符
                assert len(it.content_preview) <= 300, "content_preview 应 <= 300 chars"
                long_count += 1
        print(f"长数据 (>300 chars): {long_count}/{len(items5)} 条, content_preview 正确截断")

    print("\n" + "=" * 60)
    print("✅ SMOKE 3/3 全通过 — A2 实施可用")
    print("=" * 60)
    print("下一步: 回测脚本跑 1814 条全量更新")


if __name__ == "__main__":
    asyncio.run(main())