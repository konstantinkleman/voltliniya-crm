"""Прогон интеграции с Авито на SQLite без внешних сервисов: вебхук → заявка → ответ бота → уведомление.

cd backend && DATABASE_URL=sqlite:///./test_avito.db UPLOAD_DIR=./uploads ADMIN_EMAIL=d@test.ru ADMIN_PASSWORD=secret123 \
JWT_SECRET=0123456789abcdef0123456789abcdef AVITO_CLIENT_ID=x AVITO_CLIENT_SECRET=y AVITO_WEBHOOK_SECRET=hook \
ANTHROPIC_API_KEY=fake PYTHONPATH=. python tests/avito.py
"""
import time

from fastapi.testclient import TestClient

import app.main as main
from app.avito import agent, service
from app.avito import client as avito_client
from app.avito import notify

sent_messages: list[tuple[str, str]] = []
telegrams: list[str] = []


class FakeAvito:
    configured = True

    def user_id(self):
        return 100

    def chat_info(self, chat_id):
        return {"id": chat_id, "context": {"type": "item", "value": {"id": 555, "title": "Электромонтаж квартиры в новостройке под ключ", "url": "https://avito.ru/x"}},
                "users": [{"id": 100, "name": "ВольтЛиния"}, {"id": 200, "name": "Марина"}]}

    def send_text(self, chat_id, text):
        sent_messages.append((chat_id, text))
        return {"id": f"out-{len(sent_messages)}", "direction": "out"}

    def mark_read(self, chat_id):
        pass

    def subscriptions(self):
        return [{"url": avito_client.webhook_url()}]

    def subscribe(self, url):
        return {"ok": True}


fake = FakeAvito()
service.client = fake
avito_client.client = fake
import app.avito.router as router_mod  # noqa: E402
router_mod.client = fake


def fake_run(script, messages, ctx):
    assert script.lower().count("трассировк") == 1  # только в правиле «не упоминай»
    last = messages[-1]["text"].lower()
    if "розетк" in last:
        return agent.AgentResult(reply="Мы делаем только комплексный монтаж от 50 000 ₽.", qualified="no", summary="мелкая работа")
    if "70" in last:
        return agent.AgentResult(reply="Для 70 м² работы обычно около 175 тыс. ₽. Новостройка или вторичка?",
                                 fields={"area_m2": 70}, qualified="unknown", summary="70 м², уточняем тип")
    return agent.AgentResult(reply="Передал Константину, он свяжется в рабочее время.",
                             fields={"object_type": "новостройка", "district": "ЖК Остров", "has_project": "designer", "call_time": "после 18"},
                             qualified="yes", handoff=True, handoff_reason="готов к замеру", summary="Марина, 70 м², ЖК Остров, проект есть")


agent.run = fake_run
service.agent = agent
notify.telegram = lambda text, disable_preview=True: telegrams.append(text) or True
service.telegram = notify.telegram

c = TestClient(main.app)
with c:
    def hook(mid, text, author=200, mtype="text"):
        r = c.post("/api/avito/webhook/hook", json={"id": mid, "version": "v3.0.0", "timestamp": int(time.time()),
                                                    "payload": {"type": "message", "value": {"id": mid, "chat_id": "chat-1", "user_id": 100, "author_id": author,
                                                                                               "created": int(time.time()), "type": mtype, "chat_type": "u2i",
                                                                                               "content": {"text": text}, "item_id": 555}}})
        assert r.status_code == 200, r.text

    assert c.post("/api/avito/webhook/wrong", json={}).status_code == 404

    hook("m1", "Здравствуйте! Сколько будет стоить электрика в квартире 70 м²?")
    hook("m1", "Здравствуйте! Сколько будет стоить электрика в квартире 70 м²?")  # дубль
    hook("m2", "Новостройка, ЖК Остров, проект от дизайнера есть. Звоните после 18")
    hook("out-2", "Передал Константину, он свяжется в рабочее время.", author=100)  # эхо нашего сообщения
    hook("m3", "И ещё: у вас есть 3D-тур?", author=200)

    r = c.post("/api/auth/login", data={"username": "d@test.ru", "password": "secret123"}); assert r.status_code == 200, r.text
    c.headers["Authorization"] = "Bearer " + r.json()["access_token"]

    leads = c.get("/api/leads?source=avito").json()
    assert len(leads) == 1, leads
    lead = c.get(f"/api/leads/{leads[0]['id']}").json()
    assert lead["name"] == "Марина" and float(lead["area_m2"]) == 70 and lead["project_kind"] == "designer" and lead["address"] == "ЖК Остров", lead
    assert "новостройка" in lead["note"] and "после 18" in lead["note"], lead["note"]
    assert lead["stage"] == "contacted"
    texts = [a["text"] for a in lead["activities"]]
    assert any(t.startswith("Клиент (Авито): Здравствуйте") for t in texts) and any(t.startswith("Бот (Авито): Для 70") for t in texts), texts
    assert len(sent_messages) == 3, sent_messages
    assert len(telegrams) == 3, telegrams
    assert telegrams[0].startswith("<b>🆕 Новый чат Авито") and "🔥" in telegrams[1] and "нужен ваш ответ" in telegrams[1], telegrams

    chats = c.get("/api/avito/chats").json()
    assert len(chats) == 1 and chats[0]["qualified"] == "yes" and chats[0]["messages"] == 6, chats
    st = c.get("/api/avito/status").json()
    assert st["subscribed"] is True and st["active_script_version"] == 1 and st["chats"] == 1, st

    # директор отвечает сам из CRM → бот замолкает
    assert c.post(f"/api/avito/chats/{chats[0]['id']}/send", json={"text": "Да, 3D-тур делаем, это платная опция."}).status_code == 200
    hook("m4", "Отлично, а сколько стоит?")
    assert len(sent_messages) == 4 and sent_messages[-1][1].startswith("Да, 3D-тур"), sent_messages
    assert "вы ведёте чат сами" in telegrams[-1]
    assert c.post(f"/api/avito/chats/{chats[0]['id']}/mode", json={"mode": "bot"}).status_code == 200
    hook("m5", "Нужно поменять две розетки")
    assert sent_messages[-1][1].startswith("Мы делаем только комплексный")

    # скрипт: новая версия, активация ссылкой
    scripts = c.get("/api/avito/script").json(); assert scripts[0]["is_active"] and scripts[0]["version"] == 1
    new = c.post("/api/avito/script", json={"text": scripts[0]["text"] + "\n\nДОПОЛНЕНИЕ: отвечай ещё короче.", "note": "тест", "activate": False}).json()
    assert new["version"] == 2 and not new["is_active"]
    from app.avito.review import apply_token
    assert c.get(f"/api/avito/script/{new['id']}/apply/deadbeef").status_code == 404
    assert c.get(f"/api/avito/script/{new['id']}/apply/{apply_token(new['id'])}").status_code == 200
    assert c.get("/api/avito/status").json()["active_script_version"] == 2

    # еженедельный разбор с фальшивой моделью
    agent.review = lambda script, transcripts: {"report": "Всё хорошо, 2 чата.", "changes": "Короче здороваться", "new_script": script + "\n\n# v3"}
    import app.avito.review as rv
    rv.agent = agent
    rv.telegram = notify.telegram
    r = c.post("/api/avito/review?days=7"); assert r.status_code == 200 and r.json()["review_id"], r.text
    assert "Разбор чатов" in telegrams[-1] and "/api/avito/script/" in telegrams[-1], telegrams[-1]
    assert c.get("/api/avito/reviews").json()[0]["draft_script_id"]
    print("avito OK: сообщений боту", len(sent_messages), "уведомлений", len(telegrams))
