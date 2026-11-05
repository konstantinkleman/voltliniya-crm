"""Приём заявок из внешних каналов: токен, источник по UTM, дубли по external_ref и телефону.

cd backend
rm -f test_intake.db; DATABASE_URL=sqlite:///./test_intake.db UPLOAD_DIR=./uploads ADMIN_EMAIL=d@test.ru \
ADMIN_PASSWORD=secret123 JWT_SECRET=0123456789abcdef0123456789abcdef INTAKE_TOKEN=tok-123 PYTHONPATH=. python tests/intake.py
"""
from fastapi.testclient import TestClient

import app.main as main

H = {"X-Intake-Token": "tok-123"}
c = TestClient(main.app)
with c:
    def intake(body, headers=H, code=200):
        r = c.post("/api/intake/lead", json=body, headers=headers)
        assert r.status_code == code, (body, r.status_code, r.text)
        return r.json()

    # токен
    intake({"phone": "+7 900 000-00-01"}, headers={}, code=401)
    intake({"phone": "+7 900 000-00-01"}, headers={"X-Intake-Token": "wrong"}, code=401)
    intake({}, code=400)

    # источник по меткам
    a = intake({"name": "Ольга", "phone": "+7 900 000-00-01", "utm_source": "yandex", "utm_campaign": "poisk", "page": "/kalkulyator"})
    assert a["created"] and a["source"] == "site_direct", a
    assert intake({"name": "Пётр", "phone": "89000000002", "utm_source": "sms", "utm_campaign": "konkurenty"})["source"] == "sms"
    assert intake({"phone": "89000000003", "yclid": "123"})["source"] == "site_direct"
    assert intake({"phone": "89000000004", "referrer": "https://yandex.ru/search/?text=электрик"})["source"] == "site_seo"
    assert intake({"phone": "89000000005"})["source"] == "site_other"
    assert intake({"phone": "89000000006", "utm_source": "telegram"})["source"] == "site_other"
    intake({"phone": "89000000007", "source": "nonsense"}, code=400)
    # Директ: поиск и РСЯ различаются по {source_type}, иначе — по меткам в medium/campaign
    assert intake({"phone": "89000000011", "utm_source": "yandex", "source_type": "search"})["source"] == "site_direct"
    assert intake({"phone": "89000000012", "utm_source": "yandex", "source_type": "context"})["source"] == "site_rsya"
    assert intake({"phone": "89000000013", "utm_source": "yandex", "utm_medium": "cpc", "utm_campaign": "rsya_moscow"})["source"] == "site_rsya"
    assert intake({"phone": "89000000014", "yclid": "1", "source_type": "context"})["source"] == "site_rsya"
    assert intake({"phone": "89000000015", "utm_source": "yandex", "utm_medium": "cpc", "utm_campaign": "poisk"})["source"] == "site_direct"

    # повтор по телефону в другом формате — та же заявка, запись в истории
    b = intake({"name": "Ольга", "phone": "8 (900) 000 00 01", "message": "Перезвоните после 18"})
    assert not b["created"] and b["duplicate"] == "phone" and b["lead_id"] == a["lead_id"], b

    # Профи: явный источник + id чата, повторный сбор не плодит дубли и дописывает телефон
    p1 = intake({"name": "Марина", "source": "profi", "external_ref": "chat-42", "message": "Новостройка 60 м²", "lead_cost": 650})
    assert p1["created"] and p1["source"] == "profi"
    p2 = intake({"name": "Марина", "source": "profi", "external_ref": "chat-42", "phone": "+7 900 111-22-33"})
    assert not p2["created"] and p2["duplicate"] == "external_ref" and p2["lead_id"] == p1["lead_id"]

    # заявки видны директору, метки и стоимость лида сохранены
    r = c.post("/api/auth/login", data={"username": "d@test.ru", "password": "secret123"}); assert r.status_code == 200
    c.headers["Authorization"] = "Bearer " + r.json()["access_token"]
    la = c.get(f"/api/leads/{a['lead_id']}").json()
    assert "utm_campaign=poisk" in la["utm"] and "page=/kalkulyator" in la["utm"], la["utm"]
    assert any("Повторное обращение" in x["text"] and "18" in x["text"] for x in la["activities"]), la["activities"]
    lp = c.get(f"/api/leads/{p1['lead_id']}").json()
    assert lp["phone"] == "+7 900 111-22-33" and float(lp["lead_cost"]) == 650 and lp["external_ref"] == "chat-42"
    assert len([l for l in c.get("/api/leads").json() if l["source"] == "profi"]) == 1
    assert c.get("/api/dictionaries").json()["sources"]["sms"] == "SMS-рассылка"
    assert c.get("/api/dictionaries").json()["sources"]["site_rsya"] == "сайт · РСЯ"
    assert c.get("/api/stats/summary").status_code in (200, 404)

# --- форма сайта: без токена, только поля формы ---
with c:
    c.headers.pop("Authorization", None)
    def site(body, code=200):
        r = c.post("/api/intake/site", json=body)
        assert r.status_code == code, (body, r.status_code, r.text)
        return r.json()
    s1 = site({"name": "Сергей", "phone": "+7 (916) 555-12-34", "message": "Квартира 62 м²", "area_m2": 62.5, "utm_source": "yandex", "utm_campaign": "poisk_msk", "page": "/"})
    assert s1["created"] and s1["source"] == "site_direct", s1
    assert site({"phone": "+7 916 555-00-01", "utm_source": "yandex", "source_type": "context"})["source"] == "site_rsya"
    assert site({"phone": "89165551234", "message": "ещё кондиционеры"})["duplicate"] == "phone"
    site({"phone": "+79990000000", "website": "http://spam"}, code=400)          # бот
    site({"phone": "123"}, code=400)                                           # не телефон
    site({"name": "x"}, code=422)                                              # без телефона
    # нельзя выдать себя за Профи или задать стоимость лида — таких полей у формы нет
    s2 = site({"phone": "+7 900 777-66-55", "source": "profi", "lead_cost": 9999, "external_ref": "x"})
    r = c.post("/api/auth/login", data={"username": "d@test.ru", "password": "secret123"}); c.headers["Authorization"] = "Bearer " + r.json()["access_token"]
    l2 = c.get(f"/api/leads/{s2['lead_id']}").json()
    assert l2["source"] == "site_other" and float(l2["lead_cost"]) == 0 and not l2["external_ref"], l2
print("intake OK")
