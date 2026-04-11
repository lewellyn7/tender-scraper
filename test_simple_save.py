import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await context.new_page()

        errors = []
        page.on("console", lambda msg: errors.append(f"[{msg.type}] {msg.text}") if msg.type == "error" else None)
        page.on("pageerror", lambda err: errors.append(f"[PAGE ERROR] {err}"))

        print("1. Login")
        await page.goto("http://localhost:8889/login")
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(0.5)
        await page.fill("#login-username", "testuser")
        await page.fill("#login-password", "admin123")
        await page.click("#btn-login")
        await page.wait_for_timeout(2000)
        print(f"   URL: {page.url}")

        token = await page.evaluate("localStorage.getItem('session_token')")
        print(f"   Token: {token}")

        print("2. Qualifications page")
        await page.goto("http://localhost:8889/qualifications")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)
        stat_total = await page.locator("#stat-total").inner_text()
        print(f"   资质总数: {stat_total}")
        rows = await page.locator("#qualifications-tbody tr").count()
        print(f"   列表行数: {rows}")

        print("3. Click add")
        await page.click("#btn-add")
        await page.wait_for_timeout(600)

        print("4. Fill form")
        await page.fill("#form-name", "Test Qualification Simple")
        await page.select_option("#form-category", "IT")
        await page.select_option("#form-level", "一级")
        await page.fill("#form-certificate-no", "SIMPLE123")
        await page.fill("#form-valid-from", "2024-01-01")
        await page.fill("#form-valid-to", "2029-01-01")
        await page.fill("#form-issuer", "Test Issuer")
        await page.select_option("#form-status", "有效")

        print("5. Save with network capture")
        async with page.expect_response("**/api/bidder-qualifications", timeout=10000) as resp_info:
            await page.locator("#qualification-form button[type='submit']").click()
            await asyncio.sleep(3)

        try:
            resp = await resp_info.value
            print(f"   Save status: {resp.status}")
            print(f"   Save body: {(await resp.json())}")
        except Exception as e:
            print(f"   Save error: {e}")

        toast_count = await page.locator(".toast-message").count()
        if toast_count > 0:
            t = await page.locator(".toast-message").last.inner_text()
            print(f"   Toast: {t}")

        if errors:
            print(f"   Errors: {errors[:3]}")

        await browser.close()
        print("Done")

asyncio.run(main())
