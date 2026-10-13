"""Приход по фото накладной (фейковый OpenAI на 8111)."""
import asyncio, base64, sys, os
from playwright.async_api import async_playwright
BASE = "http://127.0.0.1:8080"; OUT = sys.argv[1]; os.makedirs(OUT, exist_ok=True)
errors = []

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome", args=["--no-sandbox"])
        pg = await (await b.new_context(viewport={"width": 1400, "height": 900}, locale="ru-RU")).new_page()
        pg.on("pageerror", lambda e: errors.append(str(e)))
        await pg.goto(BASE + "/#/login"); await pg.wait_for_selector(".login form")
        await pg.fill("[name=email]", "k@voltliniya.ru"); await pg.fill("[name=password]", "secret123"); await pg.click(".login button")
        await pg.wait_for_selector(".kan, .empty", timeout=8000)
        await pg.goto(BASE + "/#/stock"); await pg.wait_for_selector("[data-receipt]"); await pg.wait_for_timeout(300)
        await pg.click("[data-newprod]"); await pg.wait_for_selector(".modal.open form"); await pg.fill(".modal.open [name=name]", "ВВГнг-LS 3×2,5"); await pg.click(".modal.open form [type=submit]"); await pg.wait_for_selector(".modal.open", state="detached"); await pg.wait_for_timeout(400)
        await pg.click("[data-receipt]"); await pg.wait_for_selector(".modal.open [data-scan]", state="attached")
        png = f"{OUT}/nakl.png"; open(png, "wb").write(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="))
        await pg.locator(".modal.open [data-scan]").set_input_files(png)
        await pg.wait_for_function("document.querySelector('[data-scan-status]').textContent.includes('Распознано')", timeout=15000)
        await pg.wait_for_timeout(300); await pg.screenshot(path=f"{OUT}/scan-1.png", full_page=True)
        f = pg.locator(".modal.open form")
        assert await f.locator("[name=supplier]").input_value() == "ООО Кабель-Центр"
        assert await f.locator("[name=doc_number]").input_value() == "УТ-123"
        rows = await f.locator("tr[data-line]").count(); assert rows == 2, rows
        status = await pg.locator("[data-scan-status]").text_content(); print(status)
        # вторая строка — новая позиция, название подставлено
        names = await f.locator("div[name^=new]:not(.hidden) input[name^=n]").all(); assert len(names) == 1 and "Коробка" in await names[0].input_value()
        assert await f.locator("tr[data-line]").nth(1).evaluate("e=>e.style.background") != "", "сомнительная строка не подсвечена"
        await pg.click(".modal.open form [type=submit]"); await pg.wait_for_selector(".modal.open", state="detached"); await pg.wait_for_timeout(600)
        await pg.screenshot(path=f"{OUT}/scan-2.png", full_page=True)
        t = await pg.locator(".wh").inner_text(); assert "Коробка распред. 100×100" in t and "500" in t, t
        await b.close()
asyncio.run(main())
print("\n".join(errors) if errors else "no browser errors"); print("SCAN E2E OK")
