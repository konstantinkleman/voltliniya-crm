"""Проверка часов, пауз и фильтра запретов бота Авито. Только стандартная библиотека:

cd backend && PYTHONPATH=. python tests/avito_timing.py
"""
import importlib.util
import pathlib
import sys
from datetime import datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1] / "app" / "avito"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


timing = load("timing")
guard = load("guard")
timing.rng.seed(7)


def utc(msk: str) -> datetime:
    """'2026-10-14 08:30' по Москве → наивное UTC."""
    return datetime.fromisoformat(msk) - timedelta(hours=3)


def msk(t: datetime) -> str:
    return (t + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")


# --- окно 9–23 ---
assert timing.in_window(utc("2026-10-14 09:00"), 9, 23)
assert timing.in_window(utc("2026-10-14 22:59"), 9, 23)
assert not timing.in_window(utc("2026-10-14 23:00"), 9, 23)
assert not timing.in_window(utc("2026-10-14 08:59"), 9, 23)
assert not timing.in_window(utc("2026-10-15 02:00"), 9, 23)

# --- ночное сообщение → ответ утром 9:00–9:40, тем же утром или следующим ---
for _ in range(500):
    for sent, day in (("2026-10-14 23:30", "2026-10-15"), ("2026-10-15 03:10", "2026-10-15"), ("2026-10-15 08:59", "2026-10-15")):
        t = timing.fit_window(utc(sent), 9, 23, 40)
        assert msk(t)[:10] == day and "09:00" <= msk(t)[11:] <= "09:40", (sent, msk(t))
# днём не переносим
assert timing.fit_window(utc("2026-10-14 15:00"), 9, 23, 40) == utc("2026-10-14 15:00")
# крайний срок для сторожа — без случайности
assert msk(timing.latest_start(utc("2026-10-15 01:00"), 9, 23, 40)) == "2026-10-15 09:40"
assert timing.latest_start(utc("2026-10-15 12:00"), 9, 23, 40) == utc("2026-10-15 12:00")

# --- паузы: первый ответ 2–6 мин, дальше 40 с – 3 мин, длинный ответ печатается дольше ---
short, long_ = "Это новостройка или вторичка?", "Здравствуйте. " + "Для 70 м² работы обычно выходят около 175–210 тыс. ₽. " * 8
for _ in range(2000):
    first = timing.think_delay(True) + timing.typing_delay(long_ if _ % 2 else short, True)
    assert timedelta(minutes=2) <= first <= timedelta(minutes=6), first
    nxt = timing.think_delay(False) + timing.typing_delay(long_ if _ % 2 else short, False)
    assert timedelta(seconds=40) <= nxt <= timedelta(minutes=3), nxt
assert timing.typing_delay(long_, False) > timing.typing_delay(short, False)
assert timing.think_delay(False) > timedelta(seconds=0)  # никогда не в ту же секунду

# --- напоминания: 20–26 ч, затем ~3 дня ---
for _ in range(500):
    assert timedelta(hours=20) <= timing.followup_delay(1) <= timedelta(hours=26)
    assert timedelta(hours=70) <= timing.followup_delay(2) <= timedelta(hours=76)

# --- фильтр запретов ---
ok = [
    "Здравствуйте. Для 70 м² работы обычно выходят около 175–210 тыс. ₽ — точнее после замера.",
    "Наши объекты: 78 м², 65 точек, щит 36 модулей — работы 150 000 ₽, срок 1 неделя.",
    "Щит: 24 модуля — 16 800 ₽, 36 модулей — 25 200 ₽. Минимальный заказ — 50 000 ₽.",
    "Для 21 м² выходит около 53 тыс. ₽ за работы.",
    "Это чат компании: на первые вопросы отвечает помощник, замер и смету делает Константин.",
    "Фотографируем все трассы до закрытия штроб, маркировка и схема в дверце щита.",
    "Пришлите план — рассчитаем стоимость работ за 30 минут в рабочее время.",
]
for t in ok:
    assert guard.violations(t) == [], (t, guard.violations(t))
bad = {
    "Позвоните нам: +7 911 469-16-70": "телефон",
    "Звоните 8 (911) 469 16 70": "телефон",
    "Подробнее на voltliniya.ru": "ссылка",
    "Пишите на voltliniya@yandex.ru": "e-mail",
    "Сначала делаем трассировку": "слово «трассировка»",
    "У мастеров V группа по электробезопасности": "группа по электробезопасности",
    "У нас 53 объекта за плечами": "число выполненных объектов",
    "Передаём схему скрытых трасс": "«схема скрытых трасс»",
    "Есть лицензия и допуск СРО": "лицензии, СРО, допуски",
    "Сделаем за 5 дней": "срок «за N дней»",
    "Работаем без предоплаты": "«без предоплаты»",
    "Дадим скидку 10 %": "скидки",
    "Работаем 24/7": "«24/7», круглосуточно",
    "Приедем за 30 минут": "«выезд за 30 минут»",
    "Выезд мастера за 40 минут": "«выезд за 30 минут»",
}
for t, rule in bad.items():
    assert rule in guard.violations(t), (t, guard.violations(t))

print("avito_timing OK")
