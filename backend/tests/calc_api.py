"""API калькулятора на SQLite: справочник → расчёт из заявки → правки → документы → ссылка клиенту → сумма в заявку."""
import json
import pathlib

from fastapi.testclient import TestClient

import app.main as main
from app import calc
from app.calc_defaults import DEFAULTS

fx = json.loads((pathlib.Path(__file__).parent / "calc_fixtures.json").read_text())
P0 = {k: {"v1": v1, "v2": v2, "v3": v3, "vtext": vt} for (k, s, l, u, v1, v2, v3, n, vt) in DEFAULTS}

c = TestClient(main.app)
with c:
    def ok(r):
        assert r.status_code == 200, (r.request.method, r.request.url, r.status_code, r.text)
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text

    t = ok(c.post("/api/auth/login", data={"username": "d@test.ru", "password": "secret123"}))["access_token"]
    c.headers["Authorization"] = "Bearer " + t

    # справочник засеян с листа «Расценки»
    secs = ok(c.get("/api/calc/params"))["sections"]
    keys = {it["key"] for s in secs for it in s["items"]}
    assert {"work.chase", "auto.dif16", "case.flush.36", "mat.vvg25", "general.brand"} <= keys, keys
    auto = next(s for s in secs if s["section"] == "auto")
    assert auto["cols"] == ["Dekraft, ₽", "ABB, ₽", "Модулей"]

    # заявка → новый расчёт: объект и площадь из заявки
    lead = ok(c.post("/api/leads", json={"name": "Антон, ЖК Шагал", "source": "profi", "area_m2": 60, "address": "ЖК Шагал"}))
    e = ok(c.post("/api/estimates", json={"lead_id": lead["id"]}))
    assert e["lead_id"] == lead["id"] and e["result"]["inputs"]["area"] == 60 and "ЖК Шагал" in e["result"]["inputs"]["object"]

    # данные замера из примера Excel → цены как в файле
    ex = fx[0]
    e = ok(c.put(f"/api/estimates/{e['id']}", json={"inputs": ex["inputs"], "tariff": "turnkey"}))
    for tn in calc.TARIFFS:
        assert abs(e["result"]["tariffs"][tn]["price"] - ex["expected"]["tariffs"][tn]["price"]) < 0.02, (tn, e["result"]["tariffs"][tn]["price"])
    assert e["tariff"] == "turnkey" and e["summary"]["std"]["price"] == ex["expected"]["kp"]["std"]

    # документы
    kp = ok(c.get(f"/api/estimates/{e['id']}/doc/kp"))
    assert "Коммерческое предложение" in kp and "Стандарт" in kp
    sm = ok(c.get(f"/api/estimates/{e['id']}/doc/smeta?tariff=std"))
    assert "Смета — тариф «Стандарт»" in sm and "ИТОГО К ОПЛАТЕ" in sm
    pn = ok(c.get(f"/api/estimates/{e['id']}/doc/panel"))
    assert "Наполнение электрощита" in pn and "Свет: Спальня" in pn and "Розетки: Детская" in pn

    # ссылка для клиента — без входа
    sh = ok(c.post(f"/api/estimates/{e['id']}/share"))
    anon = TestClient(main.app)
    page = anon.get(sh["url"])
    assert page.status_code == 200 and "Коммерческое предложение" in page.text and "Позвонить" in page.text
    assert anon.get("/api/public/kp/" + "x" * 24).status_code == 404
    assert anon.get(f"/api/estimates/{e['id']}").status_code == 401

    # смена цен в справочнике не меняет сохранённый расчёт, пока не пересчитать
    ok(c.patch("/api/calc/params/work.chase", json={"v1": 500}))
    e2 = ok(c.get(f"/api/estimates/{e['id']}"))
    assert e2["params_outdated"] and abs(e2["result"]["tariffs"]["std"]["price"] - ex["expected"]["tariffs"]["std"]["price"]) < 0.02
    e3 = ok(c.put(f"/api/estimates/{e['id']}", json={"refresh_params": True}))
    assert e3["result"]["tariffs"]["std"]["price"] > e2["result"]["tariffs"]["std"]["price"] and not e3["params_outdated"]
    ok(c.patch("/api/calc/params/work.chase", json={"v1": 400}))

    # привязка цены к складу: цена клиенту позиции заменяет значение справочника
    wh = ok(c.get("/api/stock/warehouses"))[0]
    prod = ok(c.post("/api/stock/products", json={"name": "ВВГнг-LS 3×2,5 тест", "unit": "м", "client_price": 130,
                                                  "init_qty": 100, "init_cost": 90, "init_warehouse_id": wh["id"]}))
    assert c.patch("/api/calc/params/norm.c15_corr", json={"product_id": prod["id"]}).status_code == 400
    ok(c.patch("/api/calc/params/mat.vvg25", json={"product_id": prod["id"]}))
    e4 = ok(c.post("/api/estimates", json={"inputs": ex["inputs"]}))
    m25 = next(x for x in e4["result"]["materials"] if x["key"] == "vvg25")
    assert m25["price"] == 130 and abs(m25["cost"] - 90) < 0.01, m25
    assert e4["result"]["margin"]["std"]["lines"] >= 1
    ok(c.patch("/api/calc/params/mat.vvg25", json={"unlink": ["product_id"]}))

    # сумма КП в заявку
    ok(c.put(f"/api/estimates/{e['id']}", json={"tariff": "std"}))
    r = ok(c.post(f"/api/estimates/{e['id']}/to-lead"))
    L = ok(c.get(f"/api/leads/{lead['id']}"))
    assert float(L["offer_sum"]) == r["offer_sum"] and L["tariff"] == "Стандарт" and L["stage"] == "offer_sent", L

    # список, копия, удаление
    lst = ok(c.get(f"/api/estimates?lead_id={lead['id']}"))
    assert len(lst) == 1 and lst[0]["share_token"]
    cp = ok(c.post(f"/api/estimates/{e['id']}/copy"))
    ok(c.delete(f"/api/estimates/{cp['id']}"))
    ok(c.delete(f"/api/estimates/{e['id']}/share"))
    assert anon.get(sh["url"]).status_code == 404
    assert c.patch("/api/calc/params/general.brand", json={"vtext": "Schneider"}).status_code == 400
    ok(c.patch("/api/calc/params/general.brand", json={"vtext": "ABB"}))
    assert ok(c.get("/api/calc/defaults"))["inputs"]["brand"] == "ABB"

print("CALC API OK")
