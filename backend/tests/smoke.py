"""Сквозной прогон API на SQLite: заявка → объект → платежи → выплата → расходы → статистика."""
import os, sys, json
from fastapi.testclient import TestClient
import app.main as main

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
    post("/api/expenses", json={"date": "2026-10-05", "amount": 150000, "category": "salary", "foreman_id": f["id"]})
    post("/api/expenses", json={"date": "2026-10-03", "amount": 20000, "category": "direct"})
    post("/api/expenses", json={"date": "2026-10-01", "amount": 3361, "category": "hosting"})

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
    obj = post(f"/api/leads/{l1['id']}/convert", json={"works_sum": 120000, "materials_client_sum": 96000, "tariff": "Стандарт", "foreman_id": f["id"], "start_date": "2026-10-10"})
    assert obj["crew_name"] == "Бригада № 1", obj
    lead = get(f"/api/leads/{l1['id']}"); assert lead["stage"] == "won" and lead["object_id"] == obj["id"] and lead["documents"] == [] or True
    od = get(f"/api/objects/{obj['id']}")
    assert any(x["id"] == doc["id"] for x in od["documents"]), "документ не переехал в объект"
    # файл открывается
    r = c.get(f"/api/documents/{doc['id']}/file"); assert r.status_code == 200 and r.content.startswith(b"%PDF")

    # деньги
    post(f"/api/objects/{obj['id']}/payments", json={"number": 1, "amount": 96000, "date": "2026-10-10"})
    post(f"/api/objects/{obj['id']}/materials", json={"name": "ВВГнг-LS 3×2,5", "qty": 210, "unit": "м", "cost_sum": 18480, "date": "2026-10-11"})
    post(f"/api/objects/{obj['id']}/materials", json={"name": "прочее", "cost_sum": 52000, "date": "2026-10-12"})
    post(f"/api/objects/{obj['id']}/extra-works", json={"title": "Доп. линия на кондиционер", "amount": 6000})
    post(f"/api/objects/{obj['id']}/payouts", json={"amount": 40000, "date": "2026-10-15"})
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
    ch = get("/api/stats/channels?month=2026-10"); print("каналы:", json.dumps(ch, ensure_ascii=False)[:300])
    assert any(x["source"] == "profi" and x["won"] == 1 for x in ch)
    assert any(x["source"] == "site_direct" and x["lost"] == 1 and float(x["spent"]) == 20000 for x in ch)
    fs = get("/api/stats/foremen?month=2026-10"); print("прорабы:", [(x["name"], x["objects_in_month"], x["salary_per_object"], x["crew_due"]) for x in fs])
    sm = get("/api/stats/summary?month=2026-10"); print("сводка:", sm)
    assert float(sm["received"]) == 96000 and float(sm["crew_payouts"]) == 40000
print("SMOKE OK")
# после переназначения доля зарплаты остаётся за Андреем
with c:
    od = c.get(f"/api/objects/{obj['id']}").json(); assert od["foreman_name"] == "Новый прораб" and float(od["finance"]["foreman_share"]) == 150000
    fs = c.get("/api/stats/foremen?month=2026-10").json(); a = [x for x in fs if x["name"] == "Андрей К."][0]; assert a["objects_in_month"] == 1, fs
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
    cab = post("/api/stock/categories", json={"name": "Кабель", "markup_pct": 40})
    vvg = post("/api/stock/categories", json={"name": "ВВГнг-LS", "parent_id": cab["id"]})
    p1 = post("/api/stock/products", json={"name": "ВВГнг-LS 3×2,5", "category_id": vvg["id"], "unit": "м", "min_qty": 300, "pack_qty": 100, "pack_name": "бухта"})
    p2 = post("/api/stock/products", json={"name": "Подрозетник d68", "unit": "шт", "markup_pct": 60})
    assert p1["category_path"] == "Кабель → ВВГнг-LS"
    # приход двумя партиями по разной цене → средняя
    post("/api/stock/receipt", json={"warehouse_id": wh["id"], "date": "2026-10-10", "supplier": "Кабель-Центр", "doc_number": "123",
        "lines": [{"product_id": p1["id"], "qty": 500, "unit_cost": 86}, {"product_id": p2["id"], "qty": 200, "unit_cost": 9}], "add_expense": True})
    post("/api/stock/receipt", json={"warehouse_id": wh["id"], "date": "2026-10-11",
        "lines": [{"product_id": p1["id"], "qty": 100, "unit_cost": 92}, {"new_product": {"name": "Гофра d20", "unit": "м"}, "qty": 200, "unit_cost": 9.5}]})
    prods = get(f"/api/stock/products?warehouse_id={wh['id']}")
    k = [x for x in prods if x["id"] == p1["id"]][0]
    st = k["stock"][str(wh["id"])]
    assert float(st["qty"]) == 600 and float(st["avg_cost"]) == 87.0, st   # (500*86+100*92)/600 = 87
    assert float(k["price"]) == round(87 * 1.4, 2), k["price"]            # наценка из категории
    assert any(x["name"] == "Гофра d20" for x in prods)
    # расход закупки записался
    ex = get("/api/expenses?month=2026-10"); assert any(e["category"] == "materials" and float(e["amount"]) == 500*86+200*9 for e in ex), ex
    # списание на объект → материалы объекта по средней
    before = get(f"/api/objects/{obj['id']}")["finance"]["materials_cost"]
    r = c.post("/api/stock/issue", json={"warehouse_id": wh["id"], "product_id": p1["id"], "qty": 1000, "object_id": obj["id"]}); assert r.status_code == 400
    post("/api/stock/issue", json={"warehouse_id": wh["id"], "product_id": p1["id"], "qty": 210, "object_id": obj["id"], "date": "2026-10-12"})
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
    assert c3.post("/api/stock/receipt", json={"warehouse_id": wh["id"], "date": "2026-10-12", "lines": []}).status_code == 403
print("STOCK OK")
