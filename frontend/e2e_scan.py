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
        # категории Установочные → Коробки (через API, чтобы не кликать дерево)
        cat_id = await pg.evaluate("""async () => { const h = {'Content-Type':'application/json', Authorization: 'Bearer ' + localStorage.getItem('token')};
            const p = await (await fetch('/api/stock/categories', {method:'POST', headers:h, body: JSON.stringify({name:'Установочные', parent_id:null})})).json();
            const c = await (await fetch('/api/stock/categories', {method:'POST', headers:h, body: JSON.stringify({name:'Коробки', parent_id:p.id})})).json(); return c.id; }""")
        await pg.reload(); await pg.wait_for_selector("[data-receipt]"); await pg.wait_for_timeout(300)
        await pg.click("[data-receipt]"); await pg.wait_for_selector(".modal.open [data-scan]", state="attached")
        png = f"{OUT}/nakl.png"; open(png, "wb").write(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="))
        await pg.locator(".modal.open [data-scan]").set_input_files(png)
        await pg.wait_for_function("document.querySelector('[data-scan-status]').textContent.includes('Распознано')", timeout=15000)
        await pg.wait_for_timeout(300); await pg.screenshot(path=f"{OUT}/scan-1.png", full_page=True)
        f = pg.locator(".modal.open form")
        assert await f.locator("[name=supplier]").input_value() == "ООО Кабель-Центр"
        assert await f.locator("[name=doc_number]").input_value() == "УТ-123"
        rows = await f.locator("tr[data-line]").count(); assert rows == 3, rows
        status = await pg.locator("[data-scan-status]").text_content(); print(status)
        r0, r1, r2 = [f.locator("tr[data-line]").nth(k) for k in range(3)]
        # 1-я строка найдена → категория/единица не редактируются, видна подпись
        assert await r0.locator("div[name^=info]:not(.hidden)").count() == 1 and await r0.locator("div[name^=meta]:not(.hidden)").count() == 0
        # 2-я и 3-я — новые: название подставлено, выбор категории и единицы виден
        names = await f.locator("div[name^=new]:not(.hidden) input[name^=n]").all(); assert len(names) == 2 and "Коробка" in await names[0].input_value()
        assert await f.locator("div[name^=meta]:not(.hidden) .combo[data-combo^=k]").count() == 2, "выбор категории не показан"
        assert await r1.locator("input[name^=k]").input_value() == str(cat_id), "категория «Коробки» не сопоставлена"
        assert "Коробки" in await r1.locator(".combo[data-combo^=k] .combo-in").input_value()
        # поиск в списке позиций: ввод «ввг» показывает кабель
        await r1.locator(".combo[data-combo^=p] .combo-in").click(); await r1.locator(".combo[data-combo^=p] .combo-in").fill("ввг")
        items = await pg.locator(".combo-list .combo-it").all_text_contents(); assert any("ВВГ" in x for x in items) and not any("новая" in x for x in items), items
        await pg.keyboard.press("Escape"); assert await r1.locator("input[name^=p]").input_value() == "new"
        assert await r1.locator("select[name^=u]").input_value() == "шт"
        assert await r1.evaluate("e=>e.style.background") != "", "сомнительная строка не подсвечена"
        # 3-ю (доставка) исключаем из прихода
        await r2.locator("[data-skip]").click(); assert await r2.get_attribute("data-skip") == "1"
        await pg.screenshot(path=f"{OUT}/scan-1b.png", full_page=True)
        await pg.click(".modal.open form [type=submit]"); await pg.wait_for_selector(".modal.open", state="detached"); await pg.wait_for_timeout(600)
        await pg.screenshot(path=f"{OUT}/scan-2.png", full_page=True)
        t = await pg.locator(".wh").inner_text(); assert "Коробка распред. 100×100" in t and "500" in t, t
        assert "Доставка" not in t, "исключённая строка попала в приход"
        prods = await pg.evaluate("fetch('/api/stock/products', {headers:{Authorization:'Bearer '+localStorage.getItem('token')}}).then(r=>r.json())")
        box = next(p for p in prods if p["name"].startswith("Коробка")); assert box["category_id"] == cat_id, box
        await b.close()
asyncio.run(main())
print("\n".join(errors) if errors else "no browser errors"); print("SCAN E2E OK")
