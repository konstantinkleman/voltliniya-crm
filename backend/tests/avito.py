"""Сквозной прогон интеграции с Авито на SQLite без внешних сервисов и с подменённым временем:
вебхук → заявка → уведомление сразу → ответ бота с паузой → напоминания → алерты.

cd backend && DATABASE_URL=sqlite:///./test_avito.db UPLOAD_DIR=./uploads ADMIN_EMAIL=d@test.ru ADMIN_PASSWORD=secret123 \
JWT_SECRET=0123456789abcdef0123456789abcdef AVITO_CLIENT_ID=x AVITO_CLIENT_SECRET=y AVITO_WEBHOOK_SECRET=hook \
ANTHROPIC_API_KEY=fake AVITO_WORKER_ENABLED=0 PYTHONPATH=. python tests/avito.py
"""
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

import app.main as main
from app import models as m
from app.avito import agent, notify, service, timing, worker
from app.avito import client as avito_client
from app.avito.client import AvitoError
from app.db import SessionLocal

timing.rng.seed(1)

# ---------- подменённое время ----------
NOW = [datetime(2026, 10, 14, 9, 0)]  # 12:00 МСК, среда
timing.utcnow = lambda: NOW[0]


def at_msk(s: str) -> datetime:
    return datetime.fromisoformat(s) - timedelta(hours=3)


def msk(t: datetime) -> str:
    return (t + timedelta(hours=3)).strftime("%d %H:%M:%S")


# ---------- подменённые Авито и Telegram ----------
sent: list[tuple[str, str, datetime]] = []
reads: list[str] = []
tg: list[dict] = []
FAIL_CHATS: set[str] = set()
ECHO_INLINE: set[str] = set()


class FakeAvito:
    configured = True

    def user_id(self):
        return 100

    def chat_info(self, chat_id):
        return {"id": chat_id, "context": {"type": "item", "value": {"id": 555, "title": "Электромонтаж квартиры в новостройке под ключ", "url": "https://avito.ru/x"}},
                "users": [{"id": 100, "name": "ВольтЛиния"}, {"id": 200, "name": "Марина"}]}

    def send_text(self, chat_id, text):
        if chat_id in FAIL_CHATS:
            raise AvitoError("POST messages → 500")
        sent.append((chat_id, text, NOW[0]))
        mid = f"out-{len(sent)}"
        if chat_id in ECHO_INLINE:  # эхо вебхука приходит раньше, чем отправка вернула ответ
            hook(chat_id, f"echo-{len(sent)}", text, author=100)
        return {"id": mid, "direction": "out"}

    def mark_read(self, chat_id):
        reads.append(chat_id)

    def subscriptions(self):
        return [{"url": avito_client.webhook_url()}]

    def subscribe(self, url):
        return {"ok": True}


fake = FakeAvito()
import app.avito.router as router_mod  # noqa: E402
for mod in (service, avito_client, router_mod, worker):
    mod.client = fake


def tg_send(text, silent=False):
    tg.append({"id": len(tg) + 1, "text": text, "silent": silent, "edits": []})
    return len(tg)


def tg_edit(mid, text):
    tg[mid - 1]["edits"].append(text)
    return True


notify.tg_send, notify.tg_edit = tg_send, tg_edit
notify.telegram = lambda text, disable_preview=True: tg_send(text) is not None

# ---------- подменённый бот ----------
calls: list[dict] = []


def fake_run(script, messages, ctx, purpose="reply", feedback=None):
    assert script.lower().count("трассировк") == 1  # только в правиле «не пиши»
    calls.append({"messages": messages, "ctx": ctx, "purpose": purpose, "feedback": feedback})
    if purpose.startswith("followup"):
        return agent.AgentResult(parts=["Подскажите, вопрос с электрикой ещё актуален?" if purpose == "followup1" else "Если вопрос станет актуален — напишите сюда, посчитаем."])
    client_texts = [x["text"].lower() for x in messages if x["direction"] == "in"]
    last = client_texts[-1]
    if "навсегда" in last:
        return agent.AgentResult(parts=["Сначала делаем трассировку, звоните +7 911 469-16-70"])
    if "трасс" in last:
        if feedback:
            return agent.AgentResult(parts=["Все трассы фотографируем до закрытия штроб."], expects_answer=False)
        return agent.AgentResult(parts=["Сначала делаем трассировку."])
    if "розетк" in last:
        return agent.AgentResult(parts=["Здравствуйте. Мы делаем только комплексный электромонтаж от 50 000 ₽, на разовые работы не выезжаем."],
                                 qualified="no", summary="мелкая работа")
    if "спасибо" in last:
        return agent.AgentResult(parts=[], summary="клиент поблагодарил")
    if "3d" in last:
        return agent.AgentResult(parts=["3D-тур — платная опция, Константин расскажет на замере."], summary="спросила про 3D-тур")
    if "новостройка" in last:
        return agent.AgentResult(parts=["Хорошо, с проектом посчитать проще. Константин свяжется с вами в рабочее время."],
                                 fields={"object_type": "новостройка", "district": "ЖК Остров", "has_project": "designer", "call_time": "после 18"},
                                 qualified="yes", handoff=True, handoff_reason="готова к замеру", summary="Марина, 70 м², ЖК Остров, проект есть")
    # первый вопрос о цене; клиент мог дописать второе сообщение — бот отвечает на всё одним ходом
    return agent.AgentResult(parts=["Здравствуйте. Для 70 м² работы обычно выходят около 175–210 тыс. ₽ — точнее после замера.", "Это новостройка или вторичка?"],
                             fields={"area_m2": 70}, qualified="unknown", expects_answer=True, summary="70 м², уточняем тип")


agent.run = fake_run

c = TestClient(main.app)


def hook(chat, mid, text, author=200, mtype="text"):
    r = c.post("/api/avito/webhook/hook", json={"id": mid, "version": "v3.0.0", "timestamp": 0,
                                                "payload": {"type": "message", "value": {"id": mid, "chat_id": chat, "user_id": 100, "author_id": author,
                                                                                           "created": 0, "type": mtype, "chat_type": "u2i",
                                                                                           "content": {"text": text}, "item_id": 555}}})
    assert r.status_code == 200, r.text


def tick(seconds: float = 0, times: int = 1):
    """Сдвинуть часы и прокрутить очередь."""
    for _ in range(times):
        NOW[0] += timedelta(seconds=seconds)
        with SessionLocal() as db:
            worker.run_due(db, NOW[0])


def tasks(chat_id: str, status="pending"):
    with SessionLocal() as db:
        ch = db.scalar(select(m.AvitoChat).where(m.AvitoChat.chat_id == chat_id))
        return [(t.kind, t.due_at) for t in db.scalars(select(m.AvitoTask).where(m.AvitoTask.chat_pk == ch.id, m.AvitoTask.status == status)).all()]


def sent_to(chat_id):
    return [x for x in sent if x[0] == chat_id]


def run_until_sent(chat_id, n, step=20, limit=200):
    for _ in range(limit):
        if len(sent_to(chat_id)) >= n:
            return
        tick(step)
    raise AssertionError(f"{chat_id}: не дождались {n} сообщений, отправлено {sent_to(chat_id)}")


with c:
    assert c.post("/api/avito/webhook/wrong", json={}).status_code == 404
    r = c.post("/api/auth/login", data={"username": "d@test.ru", "password": "secret123"}); assert r.status_code == 200, r.text
    c.headers["Authorization"] = "Bearer " + r.json()["access_token"]

    # === 1. Новый чат днём: уведомление сразу, ответ через 2–6 минут, второе сообщение клиента — в тот же ответ ===
    t0 = NOW[0]
    hook("chat-1", "m1", "Здравствуйте! Сколько будет стоить электрика в квартире 70 м²?")
    hook("chat-1", "m1", "Здравствуйте! Сколько будет стоить электрика в квартире 70 м²?")  # дубль вебхука
    assert len(tg) == 1 and tg[0]["text"].startswith("<b>🆕 Новый чат Авито") and "⏳ Бот ответит около" in tg[0]["text"], tg
    assert sent == [] and reads == [], "ответ не должен уходить мгновенно"
    [(kind, due)] = tasks("chat-1")
    assert kind == "think" and timedelta(seconds=110) <= due - t0 <= timedelta(seconds=290), due - t0
    tick(50)
    hook("chat-1", "m1b", "И ещё: щит нужен на 36 модулей")
    assert len(tasks("chat-1")) == 1, "дописанное сообщение не создаёт второй ответ"
    assert len(tg) == 2  # уведомление — на каждое входящее
    run_until_sent("chat-1", 2, step=10)
    first_reply = sent_to("chat-1")[0][2] - t0
    assert timedelta(minutes=2) <= first_reply <= timedelta(minutes=6, seconds=15), first_reply  # +шаг часов теста
    gap = sent_to("chat-1")[1][2] - sent_to("chat-1")[0][2]
    assert timedelta(seconds=8) <= gap <= timedelta(seconds=60), gap  # два коротких сообщения подряд
    assert len([x for x in calls if x["purpose"] == "reply"]) == 1, "на два сообщения клиента — один ход бота"
    assert "щит нужен" in calls[-1]["messages"][-1]["text"], calls[-1]["messages"]
    assert reads == ["chat-1"]
    assert tg[1]["edits"] and "Бот: «Здравствуйте. Для 70" in tg[1]["edits"][-1] and "Итог: 70 м²" in tg[1]["edits"][-1], tg[1]
    assert [k for k, _ in tasks("chat-1")] == ["followup"]

    leads = c.get("/api/leads?source=avito").json(); assert len(leads) == 1, leads
    lead_id = leads[0]["id"]
    lead = c.get(f"/api/leads/{lead_id}").json()
    assert lead["name"] == "Марина" and float(lead["area_m2"]) == 70 and lead["stage"] == "new", lead
    texts = [a["text"] for a in lead["activities"]]
    assert any(t.startswith("Клиент (Авито): Здравствуйте") for t in texts) and any(t.startswith("Бот (Авито): Это новостройка") for t in texts), texts

    # === 2. Клиент замолчал после нашего вопроса → напоминание через 20–26 ч в рабочее время ===
    asked_at = sent_to("chat-1")[-1][2]
    [(kind, due)] = tasks("chat-1")
    assert timing.in_window(due, 10, 20) and timedelta(hours=20) <= due - asked_at <= timedelta(hours=27), (msk(due), due - asked_at)
    tick(0)
    NOW[0] = due - timedelta(minutes=1); tick(0)
    assert len(sent_to("chat-1")) == 2
    run_until_sent("chat-1", 3, step=30)
    assert sent_to("chat-1")[-1][1].startswith("Подскажите"), sent
    assert tg[-1]["silent"] and "Напоминание 1" in tg[-1]["text"]
    assert [k for k, _ in tasks("chat-1")] == ["followup"]  # второе — через ~3 дня

    # === 3. Клиент ответил → напоминание отменено, ответ 40 с – 3 мин, квалификация и передача Константину ===
    NOW[0] += timedelta(hours=2)
    t1 = NOW[0]
    hook("chat-1", "m2", "Новостройка, ЖК Остров, проект от дизайнера есть. Звоните после 18")
    assert [k for k, _ in tasks("chat-1")] == ["think"]
    run_until_sent("chat-1", 4, step=5)
    d = sent_to("chat-1")[-1][2] - t1
    assert timedelta(seconds=40) <= d <= timedelta(minutes=3) + timedelta(seconds=5), d
    lead = c.get(f"/api/leads/{lead_id}").json()
    assert float(lead["area_m2"]) == 70 and lead["project_kind"] == "designer" and lead["address"] == "ЖК Остров", lead
    assert "новостройка" in lead["note"] and "после 18" in lead["note"] and lead["stage"] == "contacted", lead
    assert any(a["text"].startswith("Бот передал вам: готова к замеру") for a in lead["activities"]), lead["activities"]
    handoff_msgs = [x for x in tg if x["text"].startswith("<b>🙋 Нужен ваш ответ")]
    assert len(handoff_msgs) == 1 and "ЖК Остров" in handoff_msgs[0]["text"] and f"Заявка № {lead_id}" in handoff_msgs[0]["text"], tg[-3:]
    edited = tg[-2]["edits"][-1]
    assert edited.startswith("<b>🔥 Наш объект") and "нужен ваш ответ" in edited, edited
    assert tasks("chat-1") == [], "после передачи бот не напоминает"

    # === 4. Ночное сообщение → уведомление сразу, ответ утром 9:00–9:40 без извинений ===
    NOW[0] = at_msk("2026-10-15 23:30")
    hook("chat-1", "m3", "А 3D-тур делаете?")
    assert "⏳ Бот ответит около" in tg[-1]["text"] and "09:" in tg[-1]["text"], tg[-1]["text"]
    [(kind, due)] = tasks("chat-1")
    assert at_msk("2026-10-16 09:00") <= due <= at_msk("2026-10-16 09:40"), msk(due)
    tick(600, times=6)
    assert len(sent_to("chat-1")) == 4, "ночью не отвечаем"
    NOW[0] = at_msk("2026-10-16 08:55"); tick(0)
    assert len(sent_to("chat-1")) == 4
    run_until_sent("chat-1", 5, step=30)
    morning = sent_to("chat-1")[-1][2]
    assert at_msk("2026-10-16 09:00") <= morning <= at_msk("2026-10-16 09:43"), msk(morning)
    assert calls[-1]["ctx"]["now_msk"].hour == 9 and calls[-1]["ctx"]["handoff_done"]

    # === 5. Директор ответил из приложения Авито → бот молчит, «клиент ждёт» — алерт директору один раз ===
    hook("chat-1", "dir-1", "Марина, добрый день, наберу вам в 18:30", author=100)
    with SessionLocal() as db:
        ch = db.scalar(select(m.AvitoChat).where(m.AvitoChat.chat_id == "chat-1"))
        assert ch.mode == "manual" and ch.manual_until > NOW[0] + timedelta(hours=23), (ch.mode, ch.manual_until)
    NOW[0] += timedelta(minutes=5)
    hook("chat-1", "m4", "Хорошо, а сколько стоит 3D-тур?")
    assert "вы ведёте чат сами" in tg[-1]["text"] and "Бот молчит" in tg[-1]["text"], tg[-1]["text"]
    assert tasks("chat-1") == []
    tick(600, times=3)
    with SessionLocal() as db:
        assert worker.watchdog(db, NOW[0]) == 0
    NOW[0] += timedelta(minutes=35)
    with SessionLocal() as db:
        assert worker.watchdog(db, NOW[0]) == 1
        assert worker.watchdog(db, NOW[0] + timedelta(hours=1)) == 0, "алерт по одному сообщению — один раз"
    assert tg[-1]["text"].startswith("<b>⚠️ Клиент ждёт ответа") and "Чат ведёте вы" in tg[-1]["text"], tg[-1]["text"]
    assert len(sent_to("chat-1")) == 5

    # ответ из CRM и возврат боту; эхо нашего сообщения не считается ответом директора повторно
    chat1 = next(x for x in c.get("/api/avito/chats").json() if x["chat_id"] == "chat-1")
    assert c.post(f"/api/avito/chats/{chat1['id']}/send", json={"text": "3D-тур — платная опция, посчитаю на замере."}).status_code == 200
    hook("chat-1", "out-6", "3D-тур — платная опция, посчитаю на замере.", author=100)
    assert c.post(f"/api/avito/chats/{chat1['id']}/mode", json={"mode": "bot"}).json()["reply_planned_at"] is None
    lc = c.get(f"/api/avito/leads/{lead_id}/chat").json()
    assert lc["chat"]["mode"] == "bot" and [x["author"] for x in lc["messages"]][-2:] == ["client", "director"], lc

    # === 6. Мелкая работа: отказ одной фразой, без напоминаний ===
    NOW[0] = at_msk("2026-10-16 14:00")
    hook("chat-2", "s1", "Нужно поменять две розетки")
    run_until_sent("chat-2", 1)
    assert sent_to("chat-2")[0][1].startswith("Здравствуйте. Мы делаем только комплексный")
    assert tasks("chat-2") == []
    chats = {x["chat_id"]: x for x in c.get("/api/avito/chats").json()}
    assert chats["chat-2"]["qualified"] == "no"

    # === 7. Фильтр запретов: первая попытка с «трассировкой» переписывается, вторая уходит ===
    hook("chat-3", "g1", "Как вы делаете трассы?")
    run_until_sent("chat-3", 1)
    assert sent_to("chat-3")[0][1] == "Все трассы фотографируем до закрытия штроб.", sent_to("chat-3")
    assert "трассировка" in calls[-1]["feedback"], calls[-1]
    # обе попытки с нарушением — клиенту ничего не уходит, директору алерт
    hook("chat-4", "g2", "Трассы навсегда?")
    tick(400, times=2)
    assert sent_to("chat-4") == [] and tg[-1]["text"].startswith("<b>⚠️ Бот не отправил ответ — нарушение правил"), tg[-1]["text"]

    # === 8. «Спасибо» — бот не отвечает, сторож не шумит ===
    hook("chat-3", "g3", "Понял, спасибо")
    tick(400, times=2)
    assert len(sent_to("chat-3")) == 1
    with SessionLocal() as db:
        assert worker.watchdog(db, NOW[0] + timedelta(hours=2)) == 0

    # === 9. Авито не принимает сообщение → 3 попытки, затем алерт; сторож не дублирует ===
    FAIL_CHATS.add("chat-5")
    hook("chat-5", "f1", "Сколько стоит электрика в квартире 70 м²?")
    tick(60, times=15)
    with SessionLocal() as db:
        failed = db.scalars(select(m.AvitoTask).where(m.AvitoTask.status == "failed")).all()
        assert len(failed) == 1 and failed[0].attempts == 3, [(t.kind, t.attempts) for t in failed]
        assert worker.watchdog(db, NOW[0] + timedelta(hours=1)) == 0
    assert tg[-1]["text"].startswith("<b>⚠️ Бот не смог ответить клиенту"), tg[-1]["text"]
    assert c.get("/api/avito/status").json()["failed_7d"] == 1

    # === 10. Эхо вебхука раньше ответа отправки — не переводит чат в ручной режим ===
    ECHO_INLINE.add("chat-6")
    hook("chat-6", "e1", "Сколько будет стоить электрика в квартире 70 м²?")
    run_until_sent("chat-6", 2)
    with SessionLocal() as db:
        ch = db.scalar(select(m.AvitoChat).where(m.AvitoChat.chat_id == "chat-6"))
        assert ch.mode == "bot" and all(x.author != "director" for x in ch.messages), [(x.author, x.text) for x in ch.messages]

    # === 11. Молчит после двух напоминаний → заявка «Проиграна: не ответил» ===
    for _ in range(1500):  # шаг 10 минут, до ~10 суток
        tick(600)
        if len(sent_to("chat-6")) >= 4 and not tasks("chat-6"):
            break
    assert [x[1][:10] for x in sent_to("chat-6")][2:] == ["Подскажите", "Если вопро"], sent_to("chat-6")
    for x in sent_to("chat-6")[2:]:
        assert timing.in_window(x[2], 10, 20), msk(x[2])
    with SessionLocal() as db:
        ch = db.scalar(select(m.AvitoChat).where(m.AvitoChat.chat_id == "chat-6"))
        assert ch.lead.stage == "lost" and ch.lead.lost_reason == "не ответил", (ch.lead.stage, ch.lead.lost_reason)
        assert ch.followup_stage == 2

    # === 12. Статус, скрипт, разбор ===
    st = c.get("/api/avito/status").json()
    assert st["subscribed"] is True and st["active_script_version"] == 1 and st["chats"] == 6 and st["hours"].startswith("9:00"), st
    scripts = c.get("/api/avito/script").json(); assert scripts[0]["is_active"] and scripts[0]["version"] == 1
    new = c.post("/api/avito/script", json={"text": scripts[0]["text"] + "\n\nДОПОЛНЕНИЕ: отвечай ещё короче.", "note": "тест", "activate": False}).json()
    assert new["version"] == 2 and not new["is_active"]
    from app.avito.review import apply_token
    assert c.get(f"/api/avito/script/{new['id']}/apply/deadbeef").status_code == 404
    assert c.get(f"/api/avito/script/{new['id']}/apply/{apply_token(new['id'])}").status_code == 200
    assert c.get("/api/avito/status").json()["active_script_version"] == 2

    agent.review = lambda script, transcripts: {"report": "Всё хорошо.", "changes": "Короче здороваться", "new_script": script + "\n\n# v3"}
    import app.avito.review as rv
    rv.agent = agent
    rv.telegram = notify.telegram
    r = c.post("/api/avito/review?days=7"); assert r.status_code == 200 and r.json()["review_id"], r.text
    assert "Разбор чатов" in tg[-1]["text"] and "/api/avito/script/" in tg[-1]["text"], tg[-1]["text"]
    assert c.get("/api/avito/reviews").json()[0]["draft_script_id"]
    print("avito OK: сообщений клиентам", len(sent), "уведомлений", len(tg))
