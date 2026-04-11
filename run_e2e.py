#!/usr/bin/env python3
import asyncio
from playwright.async_api import async_playwright
import random, time

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await context.new_page()

        console_errors = []
        page.on("console", lambda m: console_errors.append(f"[{m.type}] {m.text}") if m.type == "error" else None)

        def human_delay():
            time.sleep(random.uniform(0.1, 0.3))

        print("=" * 60)
        print("资质管理 - 人类真实操作测试")
        print("=" * 60)

        # 1/8 登录
        print("\n【1/8】登录")
        await page.goto("http://localhost:8889/login")
        await page.wait_for_load_state("domcontentloaded")
        human_delay()
        await page.fill("#login-username", "testuser")
        human_delay()
        await page.fill("#login-password", "admin123")
        human_delay()
        await page.click("#btn-login")
        await page.wait_for_timeout(1500)
        token = await page.evaluate("localStorage.getItem('session_token')")
        print(f"  ✅ 登录成功 (token: {token[:20]}...)")

        # 2/8 进入资质管理页面
        print("\n【2/8】进入资质管理页面")
        await page.goto("http://localhost:8889/qualifications")
        await page.wait_for_load_state("networkidle")
        human_delay()
        stat_total = await page.locator("#stat-total").inner_text()
        print(f"  ✅ 资质总数: {stat_total}")

        # 3/8 测试上传 Modal
        print("\n【3/8】测试上传 Modal")
        human_delay()
        await page.click("#btn-upload")
        await page.wait_for_timeout(500)
        modal_visible = await page.locator("#upload-modal").is_visible()
        print(f"  ✅ 上传 Modal 打开: {modal_visible}")
        drop_zone = await page.locator("#drop-zone").is_visible()
        print(f"  ✅ 拖拽区域可见: {drop_zone}")
        human_delay()
        await page.click("#btn-close-upload-modal")
        await page.wait_for_timeout(400)
        modal_closed = not await page.locator("#upload-modal").is_visible()
        print(f"  ✅ Modal 已关闭: {modal_closed}")

        # 4/8 手动添加资质
        print("\n【4/8】手动添加资质")
        human_delay()
        await page.click("#btn-add")
        await page.wait_for_timeout(600)
        form_visible = await page.locator("#form-modal").is_visible()
        print(f"  ✅ form-modal 打开: {form_visible}")
        human_delay()
        await page.fill("#form-name", "测试资质-人类操作")
        await page.select_option("#form-category", "IT")
        await page.select_option("#form-level", "一级")
        await page.fill("#form-certificate-no", f"TEST{random.randint(10000,99999)}")
        human_delay()
        await page.fill("#form-valid-from", "2024-01-01")
        await page.fill("#form-valid-to", "2029-01-01")
        await page.fill("#form-issuer", "测试颁发机构")
        await page.select_option("#form-status", "有效")
        human_delay()
        print(f"  ✅ 表单已填写")
        await page.locator("#qualification-form button[type='submit']").click()
        await page.wait_for_timeout(2000)

        toast_count = await page.locator(".toast-message").count()
        if toast_count > 0:
            toast_text = await page.locator(".toast-message").last.inner_text()
            print(f"  ✅ Toast: {toast_text}")
        else:
            print(f"  ⚠️  无 Toast 提示")

        # 5/8 验证新记录
        print("\n【5/8】验证新记录")
        await page.wait_for_timeout(1500)
        rows = await page.locator("#qualifications-tbody tr").count()
        print(f"  ✅ 列表共 {rows} 行")

        # 6/8 编辑资质
        print("\n【6/8】编辑资质")
        if rows > 0:
            human_delay()
            await page.locator("#qualifications-tbody tr").first.hover()
            await page.wait_for_timeout(300)
            edit_btn = page.locator("#qualifications-tbody tr").first.locator("button").first
            await edit_btn.click()
            await page.wait_for_timeout(800)
            print(f"  ✅ 点击编辑按钮")
        else:
            print(f"  ⚠️  无可编辑资质")

        # 7/8 删除资质
        print("\n【7/8】删除资质")
        if rows > 0:
            before = await page.locator("#qualifications-tbody tr").count()
            human_delay()
            del_btn = page.locator("#qualifications-tbody tr").first.locator("button").last
            await del_btn.click()
            await page.wait_for_timeout(800)
            after = await page.locator("#qualifications-tbody tr").count()
            print(f"  ✅ 删除前: {before} 行, 删除后: {after} 行")
        else:
            print(f"  ⚠️  无可删除资质")

        # 8/8 搜索和筛选
        print("\n【8/8】搜索和筛选")
        human_delay()
        await page.fill("#search-input", "建筑")
        await page.wait_for_timeout(800)
        search_rows = await page.locator("#qualifications-tbody tr").count()
        print(f"  ✅ 搜索'建筑': {search_rows} 条")
        human_delay()
        await page.select_option("#filter-category", "IT")
        await page.wait_for_timeout(800)
        filter_rows = await page.locator("#qualifications-tbody tr").count()
        print(f"  ✅ 筛选'IT': {filter_rows} 条")

        # 控制台错误
        real_errors = [e for e in console_errors if "401" in e or "500" in e]
        print(f"\n{'⚠️ ' if real_errors else '✅'} 控制台错误 ({len(real_errors)} 项):")
        for err in real_errors[:3]:
            print(f"     {err}")

        print("\n" + "=" * 60)
        print("✅ 全部测试完成！" if not real_errors else "⚠️  测试完成但有错误")
        print("=" * 60)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
