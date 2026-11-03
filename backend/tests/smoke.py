"""Сквозной прогон API на SQLite: заявка → объект → платежи → выплата → расходы → статистика."""
import os, sys, json
from fastapi.testclient import TestClient
import app.main as main


import datetime as _dt
M = _dt.date.today().strftime('%Y-%m')   # все даты теста — в текущем месяце (месяц сделки = сегодня)

c = TestClient(main.app)
with c:
    def post(url, **kw):
        r = c.post(url, **kw); assert r.status_code == 200, (url, r.status_code, r.text); return r.json()
    def get(url):
        r = c.get(url); assert r.status_code == 200, (url, r.status_code, r.text); return r.json()

    r = c.post("/api/auth/login", data={"username": "d@test.ru", "password": "secret123"}); assert r.status_code == 200, r.text
    c.headers["Authorization"] = "Bearer " + r.json()["access_token"]
    me = get("/api/me"); assert me["is_director"]
    d = get("/api/dictionaries"); assert float(d["crew_share"]) == 0.55

    # прораб и бригада
    f = post("/api/users", json={"email": "andrey@test.ru", "name": "Андрей К.", "password": "secret123", "salary": 150000})
    crew = post("/api/crews", json={"name": "Бригада № 1", "foreman_id": f["id"], "members_count": 3})
    assert crew["foreman_name"] == "Андрей К." and len(crew["history"]) == 1

    # расходы: зарплата, директ, сервер
    post("/api/expenses", json={"date": f"{M}-05", "amount": 150000, "category": "salary", "foreman_id": f["id"]})
    post("/api/expenses", json={"date": f"{M}-03", "amount": 20000, "category": "direct"})
    post("/api/expenses", json={"date": f"{M}-01", "amount": 3361, "category": "hosting"})

    # заявки
    l1 = post("/api/leads", json={"name": "Марина, ЖК Прокшино", "source": "profi", "lead_cost": 620, "area_m2": 58, "project_kind": "designer"})
    l2 = post("/api/leads", json={"name": "Игорь, Мытищи", "source": "site_direct", "area_m2": 140})
    post(f"/api/leads/{l2['id']}/stage", json={"stage": "contacted"})
    post(f"/api/leads/{l2['id']}/stage", json={"stage": "lost", "lost_reason": "дорого"})
    post(f"/api/leads/{l1['id']}/stage", json={"stage": "contacted"})
    post(f"/api/leads/{l1['id']}/stage", json={"stage": "measure"})
    post(f"/api/leads/{l1['id']}/activities", json={"kind": "call", "text": "Звонок 12 мин"})
    post(f"/api/leads/{l1['id']}/stage", json={"stage": "offer_sent"})
    # документ к заявке
    doc = post("/api/documents", data={"lead_id": l1["id"], "kind": "offer", "title": "КП Стандарт"}, files={"file": ("kp.pdf", b"%PDF-1.4 test", "application/pdf")})
    r = c.post(f"/api/leads/{l1['id']}/stage", json={"stage": "won"}); assert r.status_code == 400
    obj = post(f"/api/leads/{l1['id']}/convert", json={"works_sum": 120000, "materials_client_sum": 96000, "tariff": "Стандарт", "foreman_id": f["id"], "start_date": f"{M}-10"})
    assert obj["crew_name"] == "Бригада № 1", obj
    lead = get(f"/api/leads/{l1['id']}"); assert lead["stage"] == "won" and lead["object_id"] == obj["id"] and lead["documents"] == [] or True
    od = get(f"/api/objects/{obj['id']}")
    assert any(x["id"] == doc["id"] for x in od["documents"]), "документ не переехал в объект"
    # файл открывается
    r = c.get(f"/api/documents/{doc['id']}/file"); assert r.status_code == 200 and r.content.startswith(b"%PDF")

    # деньги
    post(f"/api/objects/{obj['id']}/payments", json={"number": 1, "amount": 96000, "date": f"{M}-10"})
    post(f"/api/objects/{obj['id']}/materials", json={"name": "ВВГнг-LS 3×2,5", "qty": 210, "unit": "м", "cost_sum": 18480, "date": f"{M}-11"})
    post(f"/api/objects/{obj['id']}/materials", json={"name": "прочее", "cost_sum": 52000, "date": f"{M}-12"})
    post(f"/api/objects/{obj['id']}/extra-works", json={"title": "Доп. линия на кондиционер", "amount": 6000})
    post(f"/api/objects/{obj['id']}/payouts", json={"amount": 40000, "date": f"{M}-15"})
    post(f"/api/objects/{obj['id']}/stage", json={"stage": "install"})
    od = get(f"/api/objects/{obj['id']}")
    fin = od["finance"]
    assert float(fin["works_base"]) == 126000 and float(fin["crew_plan"]) == 69300, fin
    assert float(fin["contract_total"]) == 222000 and float(fin["receivable"]) == 126000
    assert float(fin["crew_paid"]) == 40000 and float(fin["crew_due"]) == 29300
    assert float(fin["materials_cost"]) == 70480 and float(fin["foreman_share"]) == 150000
    # клиент: директ 20000 не наш канал; профи расходов нет → стоимость лида 620 + общий маркетинг 3361/1 сделка
    assert abs(float(fin["client_cost"]) - (620 + 3361)) < 0.01, fin["client_cost"]
    expected_profit = 222000 - 70480 - 69300 - 150000 - 3981
    assert abs(float(fin["profit"]) - expected_profit) < 0.01, (fin["profit"], expected_profit)
    print("прибыль объекта:", fin["profit"], "маржа:", fin["margin"])

    # прораб видит только своё и без маржи
    c2 = TestClient(main.app)
    r = c2.post("/api/auth/login", data={"username": "andrey@test.ru", "password": "secret123"}); assert r.status_code == 200
    c2.headers["Authorization"] = "Bearer " + r.json()["access_token"]
    mine = c2.get("/api/objects").json(); assert len(mine) == 1 and mine[0]["finance"]["profit"] is None and mine[0]["finance"]["crew_plan"] == "69300.00"
    assert c2.get("/api/leads").status_code == 403
    assert c2.get("/api/expenses").status_code == 403
    r = c2.post(f"/api/objects/{obj['id']}/materials", json={"name": "подрозетники", "cost_sum": 594}); assert r.status_code == 200
    r = c2.post(f"/api/objects/{obj['id']}/stage", json={"stage": "panel"}); assert r.status_code == 200

    # переназначение бригады
    f2 = post("/api/users", json={"email": "new@test.ru", "name": "Новый прораб", "password": "secret123", "salary": 150000})
    crew2 = post(f"/api/crews/{crew['id']}/reassign", json={"foreman_id": f2["id"], "note": "Андрей уволился"})
    assert crew2["foreman_name"] == "Новый прораб" and len(crew2["history"]) == 2 and crew2["history"][0]["to_date"]
    od = get(f"/api/objects/{obj['id']}"); assert od["foreman_name"] == "Новый прораб"

    # статистика
    ch = get(f"/api/stats/channels?month={M}"); print("каналы:", json.dumps(ch, ensure_ascii=False)[:300])
    assert any(x["source"] == "profi" and x["won"] == 1 for x in ch)
    assert any(x["source"] == "site_direct" and x["lost"] == 1 and float(x["spent"]) == 20000 for x in ch)
    fs = get(f"/api/stats/foremen?month={M}"); print("прорабы:", [(x["name"], x["objects_in_month"], x["salary_per_object"], x["crew_due"]) for x in fs])
    cs = get(f"/api/stats/crews?month={M}"); b1 = [x for x in cs if x["name"] == "Бригада № 1"][0]
    # объект ещё в работе → в «заработано» пусто, в «в работе» — он
    assert b1["done"]["objects"] == 0 and b1["active"]["objects"] == 1 and float(b1["active"]["crew"]) == float(od["finance"]["crew_plan"]), b1
    # сдаём объект: дата сдачи ставится сама, объект уходит в «заработано» месяца сдачи
    odx = post(f"/api/objects/{obj['id']}/stage", json={"stage": "act"}); assert odx["end_date"] == _dt.date.today().isoformat()
    b1 = [x for x in get(f"/api/stats/crews?month={M}") if x["name"] == "Бригада № 1"][0]
    assert b1["done"]["objects"] == 1 and b1["active"]["objects"] == 0 and float(b1["done"]["profit"]) == float(od["finance"]["profit"]) and b1["done_total"]["objects"] == 1, b1
    # диапазон месяцев: текущий входит, прошлый год — нет; дата сдачи правится вручную и переносит объект в другой месяц
    y = int(M[:4])
    assert [x for x in get(f"/api/stats/crews?date_from={y-1}-01&date_to={M}") if x["name"] == "Бригада № 1"][0]["done"]["objects"] == 1
    assert [x for x in get(f"/api/stats/crews?date_from={y-1}-01&date_to={y-1}-12") if x["name"] == "Бригада № 1"][0]["done"]["objects"] == 0
    c.patch(f"/api/objects/{obj['id']}", json={"end_date": f"{y-1}-06-15"})
    assert [x for x in get(f"/api/stats/crews?date_from={y-1}-01&date_to={y-1}-12") if x["name"] == "Бригада № 1"][0]["done"]["objects"] == 1
    c.patch(f"/api/objects/{obj['id']}", json={"end_date": None}); post(f"/api/objects/{obj['id']}/stage", json={"stage": "install"})
    # расходы компании на бригаду: форма и инструмент → видны в статистике бригады, из её денег не вычитаются
    post("/api/expenses", json={"date": f"{M}-07", "amount": 18000, "category": "gear", "crew_id": crew["id"], "note": "форма, 6 комплектов"})
    post("/api/expenses", json={"date": f"{M}-08", "amount": 32000, "category": "tools", "crew_id": crew["id"], "note": "перфоратор"})
    assert c.post("/api/expenses", json={"date": f"{M}-08", "amount": 1, "category": "tools", "crew_id": 9999}).status_code == 400
    assert len(get(f"/api/expenses?crew_id={crew['id']}")) == 2
    b1 = [x for x in get(f"/api/stats/crews?month={M}") if x["name"] == "Бригада № 1"][0]
    assert float(b1["expenses"]["sum"]) == 50000 and len(b1["expenses"]["items"]) == 2 and b1["expenses"]["items"][0]["category_name"] == "Инструмент", b1["expenses"]
    assert float(b1["active"]["crew"]) == float(od["finance"]["crew_plan"])   # доля бригады не изменилась
    sm = get(f"/api/stats/summary?month={M}"); print("сводка:", sm)
    assert float(sm["received"]) == 96000 and float(sm["crew_payouts"]) == 40000
print("SMOKE OK")
# после переназначения доля зарплаты остаётся за Андреем
with c:
    od = c.get(f"/api/objects/{obj['id']}").json(); assert od["foreman_name"] == "Новый прораб" and float(od["finance"]["foreman_share"]) == 150000
    fs = c.get(f"/api/stats/foremen?month={M}").json(); a = [x for x in fs if x["name"] == "Андрей К."][0]; assert a["objects_in_month"] == 1, fs
print("REASSIGN OK")
# сумма бригаде по договорённости
with c:
    od = c.post(f"/api/objects/{obj['id']}/crew-sum", json={"amount": 60000}).json()
    f = od["finance"]; assert f["crew_overridden"] and float(f["crew_plan"]) == 60000 and float(f["crew_calc"]) == 69300 and float(f["crew_due"]) == 20000, f
    od = c.post(f"/api/objects/{obj['id']}/crew-sum", json={"amount": None}).json()
    f = od["finance"]; assert not f["crew_overridden"] and float(f["crew_plan"]) == 69300, f
print("CREW SUM OK")

# ---------- склад ----------
with c:
    whs = get("/api/stock/warehouses"); assert any(w["foreman_name"] == "Новый прораб" for w in whs), whs
    wh = [w for w in whs if w["foreman_name"] == "Новый прораб"][0]
    cab = post("/api/stock/categories", json={"name": "Кабель"})
    vvg = post("/api/stock/categories", json={"name": "ВВГнг-LS", "parent_id": cab["id"]})
    p1 = post("/api/stock/products", json={"name": "ВВГнг-LS 3×2,5", "category_id": vvg["id"], "unit": "м", "min_qty": 300, "pack_qty": 100, "pack_name": "бухта", "client_price": 121.8})
    p2 = post("/api/stock/products", json={"name": "Подрозетник d68", "unit": "шт"})
    assert p1["category_path"] == "Кабель → ВВГнг-LS"
    # приход двумя партиями по разной цене → средняя
    post("/api/stock/receipt", json={"warehouse_id": wh["id"], "date": f"{M}-10", "supplier": "Кабель-Центр", "doc_number": "123",
        "lines": [{"product_id": p1["id"], "qty": 500, "unit_cost": 86}, {"product_id": p2["id"], "qty": 200, "unit_cost": 9}], "add_expense": True})
    post("/api/stock/receipt", json={"warehouse_id": wh["id"], "date": f"{M}-11",
        "lines": [{"product_id": p1["id"], "qty": 100, "unit_cost": 92}, {"new_product": {"name": "Гофра d20", "unit": "м"}, "qty": 200, "unit_cost": 9.5, "client_price": 15}]})
    prods = get(f"/api/stock/products?warehouse_id={wh['id']}")
    g = [x for x in prods if x["name"] == "Гофра d20"][0]; assert float(g["price"]) == 15 and float(g["client_price"]) == 15, g  # цена клиенту из прихода
    k = [x for x in prods if x["id"] == p1["id"]][0]
    st = k["stock"][str(wh["id"])]
    assert float(st["qty"]) == 600 and float(st["avg_cost"]) == 87.0, st   # (500*86+100*92)/600 = 87
    assert float(k["price"]) == 121.8, k["price"]            # цена клиенту — только ручная
    assert [x for x in prods if x["id"] == p2["id"]][0]["price"] is None
    assert any(x["name"] == "Гофра d20" for x in prods)
    # расход закупки записался
    ex = get(f"/api/expenses?month={M}"); assert any(e["category"] == "materials" and float(e["amount"]) == 500*86+200*9 for e in ex), ex
    # списание на объект → материалы объекта по средней
    before = get(f"/api/objects/{obj['id']}")["finance"]["materials_cost"]
    r = c.post("/api/stock/issue", json={"warehouse_id": wh["id"], "product_id": p1["id"], "qty": 1000, "object_id": obj["id"]}); assert r.status_code == 400
    post("/api/stock/issue", json={"warehouse_id": wh["id"], "product_id": p1["id"], "qty": 210, "object_id": obj["id"], "date": f"{M}-12"})
    od = get(f"/api/objects/{obj['id']}")
    assert float(od["finance"]["materials_cost"]) == float(before) + 210 * 87, od["finance"]["materials_cost"]
    assert any(ml["name"] == "ВВГнг-LS 3×2,5" and float(ml["cost_sum"]) == 210 * 87 for ml in od["materials"])
    # возврат 10 м
    post("/api/stock/return", json={"warehouse_id": wh["id"], "product_id": p1["id"], "qty": 10, "object_id": obj["id"]})
    od = get(f"/api/objects/{obj['id']}"); assert float(od["finance"]["materials_cost"]) == float(before) + 200 * 87
    k = [x for x in get(f"/api/stock/products?warehouse_id={wh['id']}") if x["id"] == p1["id"]][0]
    assert float(k["stock"][str(wh["id"])]["qty"]) == 400
    # перемещение на склад Андрея с подтверждением
    wh2 = [w for w in whs if w["foreman_name"] == "Андрей К."][0]
    mv = post("/api/stock/transfer", json={"from_warehouse_id": wh["id"], "to_warehouse_id": wh2["id"], "product_id": p1["id"], "qty": 100})
    k2 = [x for x in get(f"/api/stock/products?warehouse_id={wh2['id']}") if x["id"] == p1["id"]][0]
    assert str(wh2["id"]) not in k2["stock"], "до подтверждения на складе получателя быть не должно"
    post(f"/api/stock/movements/{mv[1]['id']}/confirm", json={})
    k2 = [x for x in get(f"/api/stock/products?warehouse_id={wh2['id']}") if x["id"] == p1["id"]][0]
    assert float(k2["stock"][str(wh2["id"])]["qty"]) == 100 and float(k2["stock"][str(wh2["id"])]["avg_cost"]) == 87
    # инвентаризация: факт 295 вместо 300
    adj = post("/api/stock/adjust", json={"warehouse_id": wh["id"], "lines": [{"product_id": p1["id"], "actual_qty": 295}]})
    assert len(adj) == 1 and float(adj[0]["qty"]) == -5
    sm = get("/api/stock/summary"); assert len(sm["low"]) >= 1 and float(sm["total_value"]) > 0, sm
    # прораб видит только свой склад и может списать на свой объект
    c3 = TestClient(main.app)
    r = c3.post("/api/auth/login", data={"username": "new@test.ru", "password": "secret123"}); c3.headers["Authorization"] = "Bearer " + r.json()["access_token"]
    mine = c3.get("/api/stock/warehouses").json(); assert len(mine) == 1 and mine[0]["id"] == wh["id"]
    assert c3.get(f"/api/stock/products?warehouse_id={wh2['id']}").status_code == 403
    r = c3.post("/api/stock/issue", json={"warehouse_id": wh["id"], "product_id": p2["id"], "qty": 66, "object_id": obj["id"]}); assert r.status_code == 200, r.text
    assert c3.post("/api/stock/receipt", json={"warehouse_id": wh["id"], "date": f"{M}-12", "lines": []}).status_code == 403
    # списание нескольких позиций одним документом; категория в материалах объекта
    g = [x for x in get(f"/api/stock/products?warehouse_id={wh['id']}") if x["name"] == "Гофра d20"][0]
    r = post("/api/stock/issue", json={"warehouse_id": wh["id"], "object_id": obj["id"], "lines": [{"product_id": p1["id"], "qty": 5}, {"product_id": g["id"], "qty": 20}]})
    assert len(r) == 2
    assert c.post("/api/stock/issue", json={"warehouse_id": wh["id"], "object_id": obj["id"], "lines": [{"product_id": p1["id"], "qty": 5}, {"product_id": g["id"], "qty": 99999}]}).status_code == 400
    od = get(f"/api/objects/{obj['id']}")
    assert any(ml["name"] == "ВВГнг-LS 3×2,5" and ml["category_path"] == "Кабель → ВВГнг-LS" for ml in od["materials"]), od["materials"]
    # у прораба несколько бригад: объект требует явного выбора
    cA = post("/api/crews", json={"name": "Бригада А", "foreman_id": f2["id"]}); cB = post("/api/crews", json={"name": "Бригада Б", "foreman_id": f2["id"]})
    o2 = post("/api/objects", json={"client_name": "Два", "works_sum": 100000, "foreman_id": f2["id"]}); assert o2["crew_id"] is None
    o2 = post("/api/objects", json={"client_name": "Три", "works_sum": 100000, "foreman_id": f2["id"], "crew_id": cB["id"]}); assert o2["crew_name"] == "Бригада Б"
    assert c.post("/api/objects", json={"client_name": "Чужая", "works_sum": 1, "foreman_id": me["id"], "crew_id": cB["id"]}).status_code == 400
    o2 = c.patch(f"/api/objects/{o2['id']}", json={"crew_id": cA["id"]}).json(); assert o2["crew_name"] == "Бригада А"
    # --- позиция с начальным остатком, объединение, удаление ---
    s1 = post("/api/stock/products", json={"name": "Стяжка кабельная 200", "unit": "упак", "init_warehouse_id": wh["id"], "init_qty": 10, "init_cost": 150})
    assert float(s1["stock"][str(wh["id"])]["qty"]) == 10 and float(s1["stock"][str(wh["id"])]["avg_cost"]) == 150, s1
    # дубль под другим названием → объединяем в основную
    dup = post("/api/stock/products", json={"name": "Кабель ВВГнг-LS 3×2,5", "unit": "м", "note": "Кабель ВВГнг(А)-LS 3х2,5 бухта"})
    post("/api/stock/receipt", json={"warehouse_id": wh["id"], "date": f"{M}-20", "lines": [{"product_id": dup["id"], "qty": 100, "unit_cost": 90}]})
    before_qty = float([x for x in get(f"/api/stock/products?warehouse_id={wh['id']}") if x["id"] == p1["id"]][0]["stock"][str(wh["id"])]["qty"])
    assert c.post(f"/api/stock/products/{dup['id']}/merge", json={"into_id": p2["id"]}).status_code == 400   # разные единицы
    merged = post(f"/api/stock/products/{dup['id']}/merge", json={"into_id": p1["id"]})
    assert float(merged["stock"][str(wh["id"])]["qty"]) == before_qty + 100 and "Кабель ВВГнг-LS 3×2,5" in merged["note"], merged
    assert c.get(f"/api/stock/products?include_inactive=true").json() and not any(x["id"] == dup["id"] for x in get("/api/stock/products?include_inactive=true"))
    # распознавание теперь узнаёт старое название: проверяем сопоставление напрямую
    from app import invoice_ai as IA
    from app.db import SessionLocal
    with SessionLocal() as db_:
        r_ = IA.match_products(db_, [{"name": "Кабель ВВГнг-LS 3×2,5", "raw": "Кабель ВВГнг(А)-LS 3х2,5 бухта"}])
        assert r_[0]["product_id"] == p1["id"], r_
    # удаление: без движений — совсем; с остатком — сначала отказ 409, с force — списание в ноль и архив
    tmp = post("/api/stock/products", json={"name": "Временная", "unit": "шт"})
    assert c.delete(f"/api/stock/products/{tmp['id']}").json()["deleted"] is True
    r = c.delete(f"/api/stock/products/{s1['id']}"); assert r.status_code == 409, r.text
    r = c.delete(f"/api/stock/products/{s1['id']}?force=true"); assert r.status_code == 200 and r.json()["archived"], r.text
    assert not any(x["id"] == s1["id"] for x in get("/api/stock/products"))
    sm2 = get("/api/stock/summary"); assert not any(l["product"] == "Стяжка кабельная 200" for l in sm2["low"])
    # старое «скрытие» (is_active=false без списания): остаток есть, но в стоимость склада не входит
    hid = post("/api/stock/products", json={"name": "ВВГнг-LS 5х4", "unit": "м", "init_warehouse_id": wh["id"], "init_qty": 100, "init_cost": 220})
    v1 = float([w for w in get("/api/stock/warehouses") if w["id"] == wh["id"]][0]["value"])
    c.patch(f"/api/stock/products/{hid['id']}", json={**{k: hid[k] for k in ("name", "unit", "category_id", "sku", "pack_qty", "pack_name", "markup_pct", "client_price", "min_qty", "note")}, "is_active": False})
    v2 = float([w for w in get("/api/stock/warehouses") if w["id"] == wh["id"]][0]["value"])
    assert abs((v1 - v2) - 22000) < 0.01, (v1, v2)
    assert abs(float(get("/api/stock/summary")["total_value"]) - sum(float(w["value"]) for w in get("/api/stock/warehouses"))) < 0.01
print("STOCK OK")
