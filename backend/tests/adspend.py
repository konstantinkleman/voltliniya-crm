"""Автозагрузка рекламных расходов: Директ (поиск/РСЯ), Авито, приём от сборщиков. HTTP подменяется.

cd backend
rm -f test_adspend.db; DATABASE_URL=sqlite:///./test_adspend.db UPLOAD_DIR=./uploads ADMIN_EMAIL=d@test.ru \
ADMIN_PASSWORD=secret123 JWT_SECRET=0123456789abcdef0123456789abcdef INTAKE_TOKEN=tok-123 \
YANDEX_DIRECT_TOKEN=y-tok AVITO_CLIENT_ID=a-id AVITO_CLIENT_SECRET=a-sec PYTHONPATH=. python tests/adspend.py
"""
from datetime import date, timedelta
from decimal import Decimal

import httpx
from fastapi.testclient import TestClient

import app.adspend as ads
import app.main as main
from app.db import SessionLocal
from app import models as m

today = date.today()
d1, d2 = today.replace(day=1), today
prev = d1 - timedelta(days=1)          # последний день прошлого месяца


class R:
    def __init__(self, code, text="", js=None, headers=None):
        self.status_code, self.text, self._js, self.headers = code, text, js, headers or {}

    def json(self):
        return self._js


calls = {"direct": 0}
direct_cost = {"search": "1000.50", "net": "300"}


def fake_post(url, **kw):
    if "direct.yandex" in url:
        calls["direct"] += 1
        assert kw["headers"]["Authorization"] == "Bearer y-tok"
        assert kw["json"]["params"]["IncludeVAT"] == "YES"
        if calls["direct"] == 1:
            return R(201, headers={"retryIn": "0"})       # отчёт в очереди
        tsv = "Date\tAdNetworkType\tCost\n" + "\n".join([
            f"{d1}\tSEARCH\t{direct_cost['search']}", f"{d1}\tAD_NETWORK\t{direct_cost['net']}",
            f"{d2}\tSEARCH\t200", f"{prev}\tSEARCH\t50",
        ])
        return R(200, tsv)
    if url.endswith("/token"):
        return R(200, js={"access_token": "av"})
    if "/spendings" in url:
        return R(200, js={"result": {"groupings": [
            {"date": str(d1), "spendings": [{"slug": "all", "value": 120}, {"slug": "promotion", "value": 100}]},
            {"date": str(d2), "spendings": [{"slug": "all", "value": "80.5"}]},
        ]}})
    raise AssertionError(url)


def fake_get(url, **kw):
    assert url.endswith("/core/v1/accounts/self")
    return R(200, js={"id": 42})


httpx.post, httpx.get = fake_post, fake_get
ads.time.sleep = lambda s: None
ads.start_background = lambda: None      # фоновый цикл в тесте не нужен — загрузку вызываем сами

# разбор ответа Авито в другом возможном виде
assert ads.parse_avito_spendings({"result": [{"date": "2026-11-01", "amount": 10}, {"date": "2026-11-01T00:00:00", "amount": "5"}]}) == [(date(2026, 11, 1), Decimal(15))]
assert ads.parse_avito_spendings({"result": {"items": []}}) == []

c = TestClient(main.app)
with c:
    tok = c.post("/api/auth/login", data={"username": "d@test.ru", "password": "secret123"}).json()["access_token"]
    A = {"Authorization": "Bearer " + tok}

    st = ads.sync_all(days=40 if today.day > 7 else 7)
    assert st["channels"]["direct"]["ok"], st
    assert st["channels"]["avito"]["ok"], st

    def rows():
        with SessionLocal() as db:
            return {e.external_ref: (e.category, e.channel, e.amount, e.date) for e in db.query(m.Expense).all()}

    r = rows()
    mon = f"{today:%Y-%m}"
    assert r[f"direct:{mon}:search"][:3] == ("direct", "site_direct", Decimal("1200.50")), r
    assert r[f"direct:{mon}:search"][3] == d2
    assert r[f"direct:{mon}:rsya"][:3] == ("rsya", "site_rsya", Decimal("300.00")), r
    assert r[f"direct:{prev:%Y-%m}:search"][:3] == ("direct", "site_direct", Decimal("50.00")), r
    assert r[f"avito:{mon}"][:3] == ("avito", "avito", Decimal("200.50")), r
    n = len(r)

    # повторная загрузка: уточнённая сумма обновляется, дублей нет
    calls["direct"] = 0
    direct_cost["net"] = "350"
    ads.sync_all()
    r = rows()
    assert len(r) == n, r
    assert r[f"direct:{mon}:rsya"][2] == Decimal("350.00")

    # ошибка одного канала не мешает другому
    orig = ads.fetch_avito
    ads.fetch_avito = lambda a, b: (_ for _ in ()).throw(RuntimeError("Авито недоступно"))
    calls["direct"] = 0
    st = ads.sync_all()
    assert st["channels"]["avito"]["ok"] is False and "недоступно" in st["channels"]["avito"]["error"]
    assert st["channels"]["direct"]["ok"]
    ads.fetch_avito = orig

    # статус для страницы «Расходы»
    s = c.get("/api/expenses/autoload", headers=A).json()
    assert s["channels"]["direct"]["configured"] and s["channels"]["avito"]["configured"], s
    lst = c.get(f"/api/expenses?month={mon}", headers=A).json()
    assert any(e["external_ref"] == f"direct:{mon}:search" for e in lst)

    # сборщики Профи/SMS: токен, категория-канал, повтор по external_ref обновляет
    H = {"X-Intake-Token": "tok-123"}
    body = {"date": str(today), "amount": "450", "category": "profi", "external_ref": "profi:resp-1", "note": "отклик на заказ"}
    assert c.post("/api/intake/expense", json=body).status_code == 401
    assert c.post("/api/intake/expense", json=body, headers=H).json()["result"] == "created"
    assert c.post("/api/intake/expense", json={**body, "amount": "500"}, headers=H).json()["result"] == "updated"
    assert c.post("/api/intake/expense", json=body | {"amount": "500"}, headers=H).json()["result"] == "same"
    assert c.post("/api/intake/expense", json={**body, "category": "rent", "external_ref": "x"}, headers=H).status_code == 400
    assert c.post("/api/intake/expense", json={**body, "category": "sms", "external_ref": "sms:1", "amount": "-1"}, headers=H).status_code == 400
    assert rows()["profi:resp-1"][2] == Decimal("500.00")

    # сборщик из браузера директора (Профи): месячная сумма по ключу, повтор обновляет
    pb = {"date": str(today), "amount": "4160", "category": "profi", "external_ref": f"profi:{mon}", "note": "Профи · отклики − возвраты"}
    assert c.post("/api/expenses/upsert", json=pb).status_code == 401
    assert c.post("/api/expenses/upsert", json=pb, headers=A).json()["result"] == "created"
    assert c.post("/api/expenses/upsert", json={**pb, "amount": "4747"}, headers=A).json()["result"] == "updated"
    assert c.post("/api/expenses/upsert", json={**pb, "category": "tools"}, headers=A).status_code == 400
    assert rows()[f"profi:{mon}"][2] == Decimal("4747.00")

    # кнопка «Обновить сейчас»
    assert c.post("/api/expenses/autoload", headers=A).json()["ok"]

print("ADSPEND OK")
