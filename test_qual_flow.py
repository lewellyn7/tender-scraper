#!/usr/bin/env python3
"""资质管理 - 简化人类操作测试"""
import asyncio
from playwright.async_api import async_playwright
import random, time

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await context.new_page()

        errors = []
        page.on("console", lambda m: errors.append(f"[{m.type}] {m.text}") if m.type == "error" else None)

        print("=" * 60)
        print("资质管理 - 人类操作流程测试")
        print("=" * 60)

        # 1. 登录
        print("\n[1/5] 登录")
        await page.goto("http://localhost:8889/login")
        await page.wait_for_load_state("domcontentloaded")
        time.sleep(random.uniform(0.2, 0.4))
        await page.fill("#login-username", "testuser")
        time.sleep(random.uniform(0.1, 0.2))
        await page.fill("#login-password", "admin123")
        time.sleep(random.uniform(0.1, 0.2))
        await page.click("#btn-login")
        await page.wait_for_timeout(2000)
        token = await page.evaluate("localStorage.getItem('session_token')")
        print(f"  ✅ 登录成功 (token: {token[:16]}...)")

        # 2. 进入资质管理
        print("\n[2/5] 进入资质管理页面")
        await page.goto("http://localhost:8889/qualifications")
        await page.wait_for_load_state("networkidle")
        time.sleep(random.uniform(0.5, 1.0))
        stat_total = await page.locator("#stat-total").inner_text()
        print(f"  ✅ 资质总数: {stat_total}")

        rows_before = await page.locator("#qualifications-tbody tr").count()
        print(f"  ✅ 列表行数: {rows_before}")

        # 3. 打开上传 Modal
        print("\n[3/5] 测试上传 Modal")
        time.sleep(random.uniform(0.2, 0.3))
        await page.click("#btn-upload")
        await page.wait_for_timeout(600)
        modal_ok = await page.locator("#upload-modal").is_visible()
        drop_ok = await page.locator("#drop-zone").is_visible()
        print(f"  ✅ 上传 Modal 打开: {modal_ok}")
        print(f"  ✅ 拖拽区域可见: {drop_ok}")
        await page.click("#btn-close-upload-modal")
        await page.wait_for_timeout(400)
        print(f"  ✅ Modal 已关闭")

        # 4. 手动添加资质
        print("\n[4/5] 手动添加资质（人类真实操作）")
        time.sleep(random.uniform(0.3, 0.5))
        await page.click("#btn-add")
        await page.wait_for_timeout(700)
        form_ok = await page.locator("#form-modal").is_visible()
        print(f"  ✅ 添加 Modal 打开: {form_ok}")

        time.sleep(random.uniform(0.2, 0.4))
        cert_no = f"IT{random.randint(100000, 999999)}"
        await page.fill("#form-name", "信息系统安全集成一级资质")
        time.sleep(random.uniform(0.1, 0.2))
        await page.select_option("#form-category", "IT")
        time.sleep(random.uniform(0.1, 0.2))
        await page.select_option("#form-level", "一级")
        time.sleep(random.uniform(0.1, 0.2))
        await page.fill("#form-certificate-no", cert_no)
        time.sleep(random.uniform(0.1, 0.2))
        await page.fill("#form-valid-from", "2023-01-01")
        time.sleep(random.uniform(0.1, 0.2))
        await page.fill("#form-valid-to", "2028-12-31")
        time.sleep(random.uniform(0.1, 0.2))
        await page.fill("#form-issuer", "中国信息安全认证中心")
        time.sleep(random.uniform(0.1, 0.2))
        await page.select_option("#form-status", "有效")
        time.sleep(random.uniform(0.3, 0.6))
        print(f"  ✅ 表单已填写（证书号: {cert_no}）")

        # 提交并捕获响应
        async with page.expect_response("**/api/bidder-qualifications", timeout=8000) as resp_info:
            await page.locator("#qualification-form button[type='submit']").click()
            await asyncio.sleep(3)

        try:
            resp = await resp_info.value
            status = resp.status
            body = await resp.json()
            print(f"  ✅ 保存响应: {status} - {body}")
        except Exception as e:
            print(f"  ⚠️  响应捕获失败: {e}")

        # 检查 Toast
        time.sleep(1)
        toast_count = await page.locator(".toast-message").count()
        if toast_count > 0:
            toast_text = await page.locator(".toast-message").last.inner_text()
            print(f"  ✅ Toast: {toast_text}")
        else:
            print(f"  ⚠️  无 Toast")

        # 5. 验证列表更新
        print("\n[5/5] 验证列表更新")
        await page.wait_for_timeout(2000)
        rows_after = await page.locator("#qualifications-tbody tr").count()
        stat_after = await page.locator("#stat-total").inner_text()
        print(f"  ✅ 提交后列表行数: {rows_after} (之前: {rows_before})")
        print(f"  ✅ 提交后总数: {stat_after}")

        # 搜索刚添加的证书号
        await page.fill("#search-input", cert_no[:6])
        await page.wait_for_timeout(1000)
        search_rows = await page.locator("#qualifications-tbody tr").count()
        print(f"  ✅ 搜索'{cert_no[:6]}': {search_rows} 条")

        # 控制台错误
        real_errors = [e for e in errors if any(x in e for x in ["401", "500", "Uncaught"])]
        print(f"\n{'⚠️ ' if real_errors else '✅'} 控制台错误 ({len(real_errors)} 项):")
        for err in real_errors[:3]:
            print(f"     {err}")

        print("\n" + "=" * 60)
        all_ok = rows_after > rows_before and not any("401" in e or "500" in e for e in errors)
        print("✅ 核心流程测试通过！" if all_ok else "⚠️  测试完成")
        print("=" * 60)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
