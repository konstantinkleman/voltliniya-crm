"""Проход по интерфейсу в headless Chromium: вход → заявка → смета → договор → объект → платёж → выплата → прораб."""
import asyncio, sys, os
from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8080"
OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
errors = []

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome", args=["--no-sandbox"])
        ctx = await b.new_context(viewport={"width": 1400, "height": 900}, locale="ru-RU")
        pg = await ctx.new_page()
        pg.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
        pg.on("console", lambda m: errors.append("console." + m.type + ": " + m.text) if m.type == "error" else None)

        async def shot(name): await pg.screenshot(path=f"{OUT}/{name}.png", full_page=True)
        async def fill_modal(values):
            for k, v in values.items():
                el = pg.locator(f".modal.open form [name={k}]")
                tag = await el.evaluate("e=>e.tagName")
                if tag == "SELECT": await el.select_option(str(v))
                elif (await el.get_attribute("type")) == "file": await el.set_input_files(v)
                else: await el.fill(str(v))
            await pg.click(".modal.open form [type=submit]")
            await pg.wait_for_selector(".modal.open", state="detached", timeout=5000)
            await pg.wait_for_timeout(400)

        await pg.goto(BASE + "/#/login"); await pg.wait_for_selector(".login form")
        await shot("00-login")
        await pg.fill("[name=email]", "k@voltliniya.ru"); await pg.fill("[name=password]", "secret123"); await pg.click(".login button")
        await pg.wait_for_selector(".kan, .empty", timeout=8000); await pg.wait_for_timeout(300)
        await shot("01-leads-empty")

        # прораб + бригада
        await pg.goto(BASE + "/#/crews"); await pg.wait_for_selector("[data-new-foreman]")
        await pg.click("[data-new-foreman]"); await fill_modal({"name": "Андрей К.", "email": "andrey@voltliniya.ru", "password": "secret123", "salary": 150000})
        await pg.click("[data-new-crew]"); await pg.wait_for_selector(".modal.open")
        opts = await pg.locator(".modal.open [name=foreman_id] option").all_text_contents()
        await fill_modal({"name": "Бригада № 1", "members_count": 3, "foreman_id": await pg.locator(".modal.open [name=foreman_id] option", has_text="Андрей").get_attribute("value")})
        await pg.wait_for_timeout(300); await shot("02-crews")

        # расходы
        await pg.goto(BASE + "/#/expenses"); await pg.wait_for_selector("[data-new]")
        await pg.click("[data-new]"); await fill_modal({"amount": 18400, "category": "direct", "note": "открутка за неделю"})
        await pg.click("[data-new]"); await fill_modal({"amount": 3361, "category": "hosting", "note": "Timeweb"})
        await shot("03-expenses")

        # заявка → этапы → смета → договор
        await pg.goto(BASE + "/#/leads"); await pg.wait_for_selector("[data-new]")
        await pg.click("[data-new]"); await fill_modal({"name": "Марина, ЖК Прокшино", "phone": "+7 999 000-00-00", "source": "profi", "lead_cost": 620, "area_m2": 58, "project_kind": "designer", "address": "Москва, Прокшино, 12"})
        await pg.wait_for_selector(".drawer.open"); await pg.wait_for_timeout(300); await shot("04-lead-new")
        await pg.click(".drawer.open [data-next]"); await pg.wait_for_timeout(600)   # связались
        await pg.click(".drawer.open [data-next]"); await pg.wait_for_timeout(600)   # замер
        await pg.click(".drawer.open [data-act]"); await fill_modal({"kind": "call", "text": "Звонок 12 минут, проект есть"})
        await pg.click(".drawer.open [data-next]"); await pg.wait_for_selector(".modal.open")
        kp = f"{OUT}/kp.pdf"; open(kp, "wb").write(b"%PDF-1.4 KP test")
        await fill_modal({"offer_sum": 244000, "tariff": "Стандарт", "file": kp})
        await pg.wait_for_timeout(500); await shot("05-lead-offer")
        assert await pg.locator(".drawer.open .doc").count() == 1, "КП не прикрепилось к заявке"
        await pg.click(".drawer.open [data-convert]"); await pg.wait_for_selector(".modal.open")
        fid = await pg.locator(".modal.open [name=foreman_id] option", has_text="Андрей").get_attribute("value")
        await fill_modal({"works_sum": 120000, "materials_client_sum": 96000, "foreman_id": fid, "contract_number": "14"})
        await pg.wait_for_selector(".ladder", timeout=8000); await pg.wait_for_timeout(400)
        await shot("06-object")
        assert await pg.locator("#obj-docs .doc").count() == 1, "КП не переехало в объект"

        # платёж, материалы, выплата, этап
        await pg.click("[data-pay]"); await fill_modal({"number": 1, "amount": 96000})
        await pg.click("[data-mat]"); await fill_modal({"name": "ВВГнг-LS 3×2,5", "qty": 210, "unit": "м", "cost_sum": 18480})
        await pg.click("[data-payout]"); await fill_modal({"amount": 40000})
        await pg.click("[data-next]"); await pg.wait_for_timeout(600)
        await pg.click("[data-next]"); await pg.wait_for_timeout(600)
        await shot("07-object-money")
        txt = await pg.locator(".ladder").inner_text()
        assert "66\u00a0000" in txt or "66 000" in txt, txt  # 55% от 120 000

        await pg.goto(BASE + "/#/objects"); await pg.wait_for_selector("tr.click"); await shot("08-objects")
        await pg.goto(BASE + "/#/stats"); await pg.wait_for_selector(".kpi"); await pg.wait_for_timeout(300); await shot("09-stats")
        await pg.goto(BASE + "/#/settings"); await pg.wait_for_selector("table"); await shot("10-settings")

        # прораб на телефоне
        await pg.goto(BASE + "/#/logout"); await pg.wait_for_selector(".login form")
        mob = await ctx.browser.new_context(viewport={"width": 390, "height": 844}, locale="ru-RU", is_mobile=True, has_touch=True)
        m = await mob.new_page()
        m.on("pageerror", lambda e: errors.append("mobile pageerror: " + str(e)))
        await m.goto(BASE + "/#/login"); await m.wait_for_selector(".login form")
        await m.fill("[name=email]", "andrey@voltliniya.ru"); await m.fill("[name=password]", "secret123"); await m.click(".login button")
        await m.wait_for_selector(".fm .pcard", timeout=8000); await m.wait_for_timeout(300); await m.screenshot(path=f"{OUT}/11-foreman-objects.png", full_page=True)
        await m.click(".fm a.pcard"); await m.wait_for_selector("[data-photo]"); await m.wait_for_timeout(300); await m.screenshot(path=f"{OUT}/12-foreman-object.png", full_page=True)
        body = await m.locator(".fm").inner_text()
        assert "Прибыль" not in body and "96 000" not in body, "прораб видит деньги клиента"
        await m.click("[data-photo]"); await m.wait_for_selector(".modal.open")
        ph = f"{OUT}/photo.png"
        import base64; open(ph, "wb").write(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="))
        for k, v in {"file": ph, "title": "День 1 — разметка"}.items():
            el = m.locator(f".modal.open form [name={k}]")
            if k == "file": await el.set_input_files(v)
            else: await el.fill(v)
        await m.click(".modal.open form [type=submit]"); await m.wait_for_selector(".modal.open", state="detached"); await m.wait_for_timeout(500)
        assert await m.locator("#fm-photos a").count() == 1, "фото не появилось"
        await m.click("[data-mat]");
        for k, v in {"name": "Подрозетники", "qty": "66", "unit": "шт"}.items(): await m.locator(f".modal.open form [name={k}]").fill(v)
        await m.click(".modal.open form [type=submit]"); await m.wait_for_selector(".modal.open", state="detached"); await m.wait_for_timeout(400)
        await m.screenshot(path=f"{OUT}/13-foreman-after.png", full_page=True)
        await m.goto(BASE + "/#/my/money"); await m.wait_for_selector(".fm .pcard"); await m.wait_for_timeout(300); await m.screenshot(path=f"{OUT}/14-foreman-money.png", full_page=True)
        await b.close()

asyncio.run(main())
bad = [e for e in errors if "favicon" not in e]
print("\n".join(bad) if bad else "no browser errors")
print("E2E OK")
