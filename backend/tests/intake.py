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
    assert c.get("/api/stats/summary").status_code in (200, 404)

print("intake OK")
