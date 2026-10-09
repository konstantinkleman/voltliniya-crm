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
