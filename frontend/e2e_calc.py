"""Калькулятор в браузере: заявка → «+ новый расчёт» → заполнение с телефона → три тарифа → КП / смета / щит / ссылка.
Запуск: uvicorn на :8000, devserver.py на :8080, затем python e2e_calc.py <папка для скриншотов>."""
import asyncio, os, sys
from playwright.async_api import async_playwright

BASE = os.environ.get("BASE", "http://127.0.0.1:8080")
OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
errors = []


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(**({"executable_path": os.environ["CHROME"]} if os.environ.get("CHROME") else {}))
        # телефон
        ctx = await b.new_context(**p.devices["iPhone 13"], locale="ru-RU")
        pg = await ctx.new_page()
        pg.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
        pg.on("console", lambda m: errors.append("console.error: " + m.text) if m.type == "error" else None)
        shot = lambda name, full=False: pg.screenshot(path=f"{OUT}/{name}.png", full_page=full)

        await pg.goto(BASE + "/#/login"); await pg.wait_for_selector(".login form")
        await pg.fill("[name=email]", "d@test.ru"); await pg.fill("[name=password]", "secret123"); await pg.click(".login button")
        await pg.wait_for_selector(".kan, .empty", timeout=8000)
        tok = await pg.evaluate("localStorage.getItem('token')")
        r = await pg.request.post(BASE + "/api/leads", headers={"Authorization": "Bearer " + tok},
                                  data={"name": "Антон, ЖК Шагал кв. 112", "source": "site_direct", "area_m2": 74.5, "address": "ЖК Шагал, кв. 112"})
        lead = await r.json()
        await pg.goto(BASE + f"/#/leads/{lead['id']}"); await pg.wait_for_selector("#lead-calc .btn")
        await pg.wait_for_timeout(500); await shot("m01-lead-drawer")
        await pg.click("#lead-calc .btn")
        await pg.wait_for_selector(".calc-form .cs", timeout=8000); await pg.wait_for_timeout(400)
        await shot("m02-new-calc")

        async def setnum(key, val):
            await pg.fill(f"input[data-k={key}]", str(val))
        await setnum("sockets", 54); await setnum("lv", 4); await setnum("switches", 16); await setnum("lights", 14); await setnum("out220", 2)
        await setnum("windows", 9)
        for _ in range(2):
            await pg.click("button[data-inc=sockets]")
        # помещения
        for label in ["Спальня", "Детская", "Кухня-гостиная", "Прихожая", "Санузел", "Санузел", "Балкон"]:
            await pg.locator(".quick .chip", has_text=label).first.click(); await pg.wait_for_timeout(60)
        rooms = pg.locator(".room")
        await rooms.nth(0).locator("[data-rt=ac]").click()
        await rooms.nth(1).locator("[data-rt=ac]").click()
        await rooms.nth(4).locator("[data-rt=floor]").click()
        # техника
        for k in ["oven", "hob", "dishwasher", "washer", "apron", "fridge", "router"]:
            await pg.click(f"[data-chip={k}]"); await pg.wait_for_timeout(60)
        await pg.locator("[data-seg=master] button", has_text="свет + розетки").click()
        await pg.locator("[data-seg=brand] button", has_text="ABB").click()
        await pg.wait_for_function("document.querySelector('[data-status]').textContent === 'Сохранено'", timeout=8000)
        await pg.wait_for_timeout(300)
        await shot("m03-form-top")
        await pg.locator(".room").first.scroll_into_view_if_needed(); await shot("m04-rooms")
        await pg.locator("[data-seg=master]").scroll_into_view_if_needed(); await shot("m05-panel")
        await pg.locator(".tcards").scroll_into_view_if_needed(); await pg.wait_for_timeout(200); await shot("m06-results")
        await shot("m07-full", True)
        # тариф «Под ключ» в нижней панели
        await pg.locator(".bar-prices button", has_text="Под ключ").click(); await pg.wait_for_timeout(700)
        # КП
        await pg.click("[data-doc=kp]"); await pg.wait_for_selector(".docview iframe"); await pg.wait_for_timeout(800)
        await shot("m08-kp")
        await pg.click(".docview [data-close]")
        await pg.click("[data-doc=smeta]"); await pg.wait_for_selector(".docview iframe"); await pg.wait_for_timeout(800)
        await shot("m09-smeta")
        await pg.click(".docview [data-close]")
        await pg.click("[data-doc=panel]"); await pg.wait_for_selector(".docview iframe"); await pg.wait_for_timeout(800)
        await shot("m10-panel")
        await pg.click(".docview [data-close]")
        # ссылка для клиента
        await pg.click("[data-share]"); await pg.wait_for_selector(".modal.open [data-url]")
        url = await pg.locator(".modal.open [data-url]").input_value()
        await shot("m11-share")
        await pg.click(".modal.open [data-cancel]")
        # клиент открывает ссылку без входа
        cctx = await b.new_context(**p.devices["iPhone 13"], locale="ru-RU")
        cp = await cctx.new_page(); await cp.goto(url); await cp.wait_for_timeout(500)
        await cp.screenshot(path=f"{OUT}/m12-client-kp.png", full_page=True)
        assert "Коммерческое предложение" in await cp.content()
        # сумма в заявку
        await pg.click("[data-more]"); await pg.wait_for_selector(".modal.open [data-a=tolead]")
        await pg.click(".modal.open [data-a=tolead]"); await pg.wait_for_timeout(600)
        lr = await (await pg.request.get(BASE + f"/api/leads/{lead['id']}", headers={"Authorization": "Bearer " + tok})).json()
        assert lr["stage"] == "offer_sent" and float(lr["offer_sum"]) > 0, lr
        # планшет: тот же расчёт
        tctx = await b.new_context(**p.devices["iPad (gen 7)"], locale="ru-RU")
        tp = await tctx.new_page()
        tp.on("pageerror", lambda e: errors.append("pageerror(tablet): " + str(e)))
        await tp.goto(BASE + "/#/login"); await tp.evaluate(f"localStorage.setItem('token', {tok!r})")
        await tp.goto(BASE + pg.url[pg.url.index('/#'):]); await tp.wait_for_selector(".tcards"); await tp.wait_for_timeout(500)
        await tp.screenshot(path=f"{OUT}/t01-calc.png")
        await tp.screenshot(path=f"{OUT}/t02-calc-full.png", full_page=True)
        # десктоп: справочник и список
        dctx = await b.new_context(viewport={"width": 1400, "height": 900}, locale="ru-RU")
        dp = await dctx.new_page()
        dp.on("pageerror", lambda e: errors.append("pageerror(desktop): " + str(e)))
        await dp.goto(BASE + "/#/login"); await dp.evaluate(f"localStorage.setItem('token', {tok!r})")
        await dp.goto(BASE + "/#/calc"); await dp.wait_for_selector("table, .empty"); await dp.wait_for_timeout(300)
        await dp.screenshot(path=f"{OUT}/d01-list.png")
        await dp.goto(BASE + "/#/calc/params"); await dp.wait_for_selector("table.params"); await dp.wait_for_timeout(300)
        await dp.screenshot(path=f"{OUT}/d02-params.png", full_page=True)
        await dp.locator("input[data-key='work.chase']").fill("410"); await dp.locator("input[data-key='work.chase']").dispatch_event("change")
        await dp.wait_for_timeout(400)
        await dp.goto(BASE + pg.url[pg.url.index('/#'):]); await dp.wait_for_selector(".tcards"); await dp.wait_for_timeout(500)
        await dp.screenshot(path=f"{OUT}/d03-calc-outdated.png")
        assert await dp.locator("[data-outdated]").count() == 1
        await b.close()


asyncio.run(main())
if errors:
    print("\n".join(errors))
    raise SystemExit("E2E CALC: ошибки в консоли")
print("E2E CALC OK")
