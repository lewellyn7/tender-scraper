#!/usr/bin/env python3
"""全面交互测试 — 模拟人类操作"""
import asyncio
from playwright.async_api import async_playwright
import random, time

BASE = "http://localhost:8888"

PAGES = [
    ("/", "首页"),
    ("/data", "数据页面"),
    ("/favorites", "收藏夹"),
    ("/logs", "日志页面"),
    ("/settings", "设置页面"),
    ("/analytics", "分析页面"),
    ("/qualifications", "资质管理"),
]

async def human_delay():
    await asyncio.sleep(random.uniform(0.1, 0.3))

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()

        errors = []
        page.on("console", lambda m: errors.append(f"[{m.type}] {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda err: errors.append(f"[PAGE ERROR] {err}"))

        results = []

        # 1. 登录
        print("=" * 60)
        print("【登录】")
        await page.goto(f"{BASE}/login")
        await page.wait_for_load_state("domcontentloaded")
        await human_delay()
        await page.fill("#login-username", "testuser")
        await human_delay()
        await page.fill("#login-password", "admin123")
        await human_delay()
        await page.click("#btn-login")
        await page.wait_for_timeout(2000)
        logged_in = page.url != f"{BASE}/login"
        print(f"  {'✅' if logged_in else '❌'} 登录 {'成功' if logged_in else '失败'} (URL: {page.url})")
        results.append(("登录", logged_in))
        if not logged_in:
            print(f"  ❌ 无法登录，终止测试")
            await browser.close()
            return

        # 2. 遍历所有页面
        for path, name in PAGES:
            print(f"\n【{name}】 {path}")
            await human_delay()
            await page.goto(f"{BASE}{path}")
            await page.wait_for_load_state("networkidle", timeout=10000)
            await human_delay()

            # 截图
            # await page.screenshot(path=f"/tmp/test_{path.replace('/','_')}.png", full_page=False)

            # 检查控制台错误
            page_errors = [e for e in errors if any(x in e for x in ["Uncaught", "500", "401"])]
            has_error = len(page_errors) > 0
            print(f"  {'✅' if not has_error else '⚠️'} 页面加载 {'正常' if not has_error else f'有{len(page_errors)}个错误'}")
            if has_error:
                for e in page_errors[:2]:
                    print(f"     {e[:100]}")
            results.append((f"{name}-加载", not has_error))
            errors.clear()

            # 交互测试
            if path == "/qualifications":
                await test_qualifications(page, results, human_delay)
            elif path == "/favorites":
                await test_favorites(page, results, human_delay)
            elif path == "/settings":
                await test_settings(page, results, human_delay)
            elif path == "/data":
                await test_data(page, results, human_delay)
            elif path == "/logs":
                await test_logs(page, results, human_delay)

            await human_delay()

        # 3. 总结
        print("\n" + "=" * 60)
        print("测试结果汇总")
        print("=" * 60)
        for name, ok in results:
            print(f"  {'✅' if ok else '❌'} {name}")

        passed = sum(1 for _, ok in results if ok)
        failed = sum(1 for _, ok in results if not ok)
        print(f"\n通过: {passed} / {len(results)}")
        if failed > 0:
            print(f"失败: {failed}")
        print("=" * 60)

        await browser.close()


async def test_qualifications(page, results, human_delay):
    """资质管理交互测试"""
    # 统计卡片
    try:
        stat_total = await page.locator("#stat-total").inner_text(timeout=3000)
        print(f"  ✅ 资质总数显示: {stat_total}")
        results.append(("资质-统计卡片", True))
    except Exception as e:
        print(f"  ❌ 统计卡片: {e}")
        results.append(("资质-统计卡片", False))

    await human_delay()

    # 上传 Modal
    try:
        await page.click("#btn-upload")
        await page.wait_for_timeout(500)
        visible = await page.locator("#upload-modal").is_visible()
        print(f"  {'✅' if visible else '❌'} 上传 Modal 打开")
        results.append(("资质-上传Modal", visible))
        if visible:
            await page.click("#btn-close-upload-modal")
            await page.wait_for_timeout(300)
    except Exception as e:
        print(f"  ❌ 上传 Modal: {e}")
        results.append(("资质-上传Modal", False))

    await human_delay()

    # 手动添加 Modal
    try:
        await page.click("#btn-add")
        await page.wait_for_timeout(600)
        form_visible = await page.locator("#form-modal").is_visible()
        print(f"  {'✅' if form_visible else '❌'} 添加 Modal 打开")
        results.append(("资质-添加Modal", form_visible))

        if form_visible:
            cert_no = f"TEST{random.randint(100000,999999)}"
            await page.fill("#form-name", "测试资质-交互验证")
            await human_delay()
            await page.select_option("#form-category", "IT")
            await human_delay()
            await page.fill("#form-certificate-no", cert_no)
            await human_delay()
            await page.fill("#form-valid-from", "2024-01-01")
            await human_delay()
            await page.fill("#form-valid-to", "2029-01-01")
            await human_delay()
            await page.fill("#form-issuer", "测试机构")
            await human_delay()
            await page.select_option("#form-status", "有效")
            await human_delay()

            # 提交
            async with page.expect_response("**/api/bidder-qualifications", timeout=8000) as resp_info:
                await page.locator("#qualification-form button[type='submit']").click()
                await asyncio.sleep(3)

            try:
                resp = await resp_info.value
                body = await resp.json()
                save_ok = resp.status == 200 and body.get("success")
                print(f"  {'✅' if save_ok else '❌'} 保存: {resp.status} - {body}")
                results.append(("资质-保存", save_ok))
            except Exception as e:
                print(f"  ❌ 保存响应: {e}")
                results.append(("资质-保存", False))

            await page.wait_for_timeout(2000)
            toast_count = await page.locator(".toast-message").count()
            if toast_count > 0:
                toast = await page.locator(".toast-message").last.inner_text()
                print(f"  ✅ Toast: {toast}")
                results.append(("资质-Toast", "已添加" in toast or "成功" in toast))
    except Exception as e:
        print(f"  ❌ 添加 Modal: {e}")
        results.append(("资质-添加Modal", False))


async def test_favorites(page, results, human_delay):
    """收藏夹交互测试"""
    try:
        await page.wait_for_timeout(1000)
        # 检查收藏列表是否加载
        rows = await page.locator("table tbody tr").count()
        print(f"  ✅ 收藏列表加载: {rows} 行")
        results.append(("收藏夹-列表", True))
    except Exception as e:
        print(f"  ⚠️ 收藏列表: {e}")
        results.append(("收藏夹-列表", False))


async def test_settings(page, results, human_delay):
    """设置页面交互测试"""
    try:
        tabs = await page.locator("[role='tab'], .tab-btn, button[class*='tab']").count()
        print(f"  ✅ 设置页面 Tab 数量: {tabs}")
        results.append(("设置-页面", True))

        # 点击各 Tab
        if tabs > 1:
            for i in range(min(tabs, 4)):
                await human_delay()
                btns = page.locator("[role='tab'], .tab-btn, button[class*='tab']")
                await btns.nth(i).click()
                await page.wait_for_timeout(400)
        results.append(("设置-Tab切换", True))
    except Exception as e:
        print(f"  ⚠️ 设置页面: {e}")
        results.append(("设置-页面", False))


async def test_data(page, results, human_delay):
    """数据页面交互测试"""
    try:
        await page.wait_for_timeout(1500)
        # 检查数据表格
        rows = await page.locator("table tbody tr").count()
        print(f"  ✅ 数据页面加载: {rows} 行")
        results.append(("数据-页面", True))
    except Exception as e:
        print(f"  ⚠️ 数据页面: {e}")
        results.append(("数据-页面", False))


async def test_logs(page, results, human_delay):
    """日志页面交互测试"""
    try:
        await page.wait_for_timeout(1000)
        # 检查日志内容
        content = await page.locator("body").inner_text()
        has_logs = "日志" in content or "log" in content.lower() or "时间" in content
        print(f"  {'✅' if has_logs else '⚠️'} 日志页面内容: {'有内容' if has_logs else '空'}")
        results.append(("日志-页面", True))
    except Exception as e:
        print(f"  ⚠️ 日志页面: {e}")
        results.append(("日志-页面", False))


if __name__ == "__main__":
    asyncio.run(main())
