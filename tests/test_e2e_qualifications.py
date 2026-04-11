"""资质管理 - 人类真实操作模式 E2E 测试"""
import asyncio

async def human_like_test():
    from playwright.async_api import async_playwright
    import random

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        errors = []
        page.on("console", lambda msg: errors.append(f"[{msg.type}] {msg.text}") if msg.type == "error" else None)
        page.on("pageerror", lambda err: errors.append(f"[PAGE ERROR] {err}"))

        print("=" * 60)
        print("资质管理 - 人类真实操作测试")
        print("=" * 60)

        # 1. Login - human typing
        print("\n【1/8】登录")
        await page.goto("http://localhost:8889/login")
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(0.5)

        await page.click("#login-username")
        for char in "testuser":
            await page.keyboard.type(char, delay=random.uniform(0.05, 0.15))
        await asyncio.sleep(0.3)
        await page.click("#login-password")
        for char in "admin123":
            await page.keyboard.type(char, delay=random.uniform(0.08, 0.2))
        await asyncio.sleep(0.2)

        await page.click("#btn-login")
        await page.wait_for_url("**/", timeout=5000)
        print(f"  ✅ 登录成功")
        await asyncio.sleep(1)

        # 2. Qualifications page
        print("\n【2/8】进入资质管理页面")
        await page.goto("http://localhost:8889/qualifications")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)

        stat_total = await page.locator("#stat-total").inner_text()
        print(f"  ✅ 资质总数: {stat_total}")

        # 3. Test upload modal
        print("\n【3/8】测试上传 Modal")
        await page.click("#btn-upload")
        await page.wait_for_timeout(800)

        upload_modal = page.locator("#upload-modal")
        is_visible = await upload_modal.is_visible()
        print(f"  ✅ 上传 Modal 打开: {is_visible}")
        await page.screenshot(path="/tmp/01_upload_modal.png", full_page=False)

        drop_zone = page.locator("#drop-zone")
        print(f"  ✅ 拖拽区域可见: {await drop_zone.is_visible()}")

        await page.click("#btn-close-upload-modal")
        await page.wait_for_timeout(500)
        print(f"  ✅ Modal 已关闭")

        # 4. Manual add qualification
        print("\n【4/8】手动添加资质")
        await page.click("#btn-add")
        await page.wait_for_timeout(600)

        form_modal = page.locator("#form-modal")
        print(f"  ✅ form-modal 打开: {await form_modal.is_visible()}")
        await page.screenshot(path="/tmp/02_form_modal.png", full_page=False)

        # Fill form like a human
        await page.click("#form-name")
        await page.keyboard.type("消防设施工程专业承包一级资质", delay=random.uniform(0.05, 0.1))
        await page.select_option("#form-category", "建筑")
        await asyncio.sleep(0.2)
        await page.select_option("#form-level", "一级")
        await asyncio.sleep(0.2)
        await page.click("#form-certificate-no")
        await page.keyboard.type("XF20260001", delay=random.uniform(0.08, 0.15))
        await page.click("#form-valid-from")
        await page.keyboard.type("2024-01-01", delay=random.uniform(0.05, 0.1))
        await page.click("#form-valid-to")
        await page.keyboard.type("2030-12-31", delay=random.uniform(0.05, 0.1))
        await page.click("#form-issuer")
        await page.keyboard.type("住房和城乡建设部", delay=random.uniform(0.08, 0.15))
        await page.select_option("#form-status", "有效")
        await asyncio.sleep(0.3)

        await page.screenshot(path="/tmp/03_form_filled.png", full_page=False)
        print("  ✅ 表单已填写")

        await page.locator("#qualification-form button[type='submit']").click()
        await page.wait_for_timeout(2500)

        toast = await page.locator(".toast-message").last
        if await toast.is_visible():
            print(f"  ✅ Toast: {await toast.inner_text()}")
        await asyncio.sleep(1)

        # 5. Verify new record in list
        print("\n【5/8】验证新记录")
        await page.wait_for_timeout(1000)
        rows = await page.locator("#qualifications-tbody tr").count()
        print(f"  ✅ 列表共 {rows} 行")
        if rows > 0:
            name = await page.locator("#qualifications-tbody tr").first.locator("td").nth(1).inner_text()
            print(f"  ✅ 首条资质: {name}")
        await page.screenshot(path="/tmp/04_list.png", full_page=False)

        # 6. Edit
        print("\n【6/8】编辑资质")
        edit_btn = page.locator("#qualifications-tbody tr button[data-edit]").first
        await edit_btn.click()
        await page.wait_for_timeout(600)
        print(f"  ✅ 编辑 Modal 打开: {await form_modal.is_visible()}")

        cert_field = page.locator("#form-certificate-no")
        await cert_field.click()
        await cert_field.fill("")
        await cert_field.type("XF20260001-UPDATED", delay=0.1)
        await page.screenshot(path="/tmp/05_edit.png", full_page=False)

        await page.locator("#qualification-form button[type='submit']").click()
        await page.wait_for_timeout(2000)
        toast2 = await page.locator(".toast-message").last
        if await toast2.is_visible():
            print(f"  ✅ Toast: {await toast2.inner_text()}")

        # 7. Delete
        print("\n【7/8】删除资质")
        rows_before = await page.locator("#qualifications-tbody tr").count()
        print(f"  ✅ 删除前: {rows_before} 行")

        delete_btn = page.locator("#qualifications-tbody tr button[data-delete]").first
        await delete_btn.click()
        await page.wait_for_timeout(500)

        # Handle confirmation dialog if present
        confirm_btn = page.locator("button:has-text('确认')")
        if await confirm_btn.is_visible():
            await confirm_btn.click()
            print("  ✅ 确认删除")

        await page.wait_for_timeout(1500)
        rows_after = await page.locator("#qualifications-tbody tr").count()
        print(f"  ✅ 删除后: {rows_after} 行")

        # 8. Search and filter
        print("\n【8/8】搜索和筛选")
        search_input = page.locator("#search-input")
        await search_input.click()
        await search_input.type("建筑", delay=0.1)
        await page.wait_for_timeout(1500)
        filtered = await page.locator("#qualifications-tbody tr").count()
        print(f"  ✅ 搜索'建筑': {filtered} 条")

        await search_input.fill("")
        await page.wait_for_timeout(1000)

        await page.select_option("#filter-category", "IT")
        await page.wait_for_timeout(1500)
        cat_filtered = await page.locator("#qualifications-tbody tr").count()
        print(f"  ✅ 筛选'IT': {cat_filtered} 条")

        # Summary
        print("\n" + "=" * 60)
        if errors:
            unique = list(dict.fromkeys(errors))
            print(f"⚠️  控制台错误 ({len(unique)} 项):")
            for e in unique[:5]:
                print(f"     {e[:200]}")
        else:
            print("✅ 无控制台错误")
        print("=" * 60)
        print("✅ 全部测试完成！")
        print("=" * 60)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(human_like_test())
