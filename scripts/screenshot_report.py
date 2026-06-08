"""
Opens the audit form, submits it, waits for the report, takes a full-page screenshot.
"""
import asyncio
from playwright.async_api import async_playwright

AUDIT_ID = "dcb93aec-b082-4a5b-9eb8-4947984b042c"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})

        # Navigate directly to the app and trigger report rendering via JS
        await page.goto("http://localhost:8000")
        await page.wait_for_load_state("networkidle")

        # Take a screenshot of the form first
        await page.screenshot(path="scripts/shot_form.png", full_page=True)
        print("Form screenshot saved.")

        # Use the existing completed audit — fetch report and render it directly
        await page.evaluate(f"""
            async () => {{
                const res = await fetch('/audit/{AUDIT_ID}/report');
                const report = await res.json();
                // Hide form, show report section
                document.getElementById('form-section').classList.add('hidden');
                document.getElementById('progress-section').classList.add('hidden');
                const rs = document.getElementById('report-section');
                rs.classList.remove('hidden');
                renderReport(report);
            }}
        """)

        # Wait for animations to finish
        await page.wait_for_timeout(3000)

        # Full page screenshot of the report
        await page.screenshot(path="scripts/shot_report.png", full_page=True)
        print("Report screenshot saved.")

        await browser.close()

asyncio.run(main())
