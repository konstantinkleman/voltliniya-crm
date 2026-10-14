"""Время ответов бота: рабочие часы по Москве, паузы «живого менеджера», напоминания.

Только стандартная библиотека — модуль проверяется отдельно (tests/avito_timing.py).
В базе все даты — наивные UTC (как datetime.utcnow()); Москва — UTC+3 без перехода на летнее время.
"""
import random
from datetime import datetime, timedelta, timezone

MSK = timezone(timedelta(hours=3))
rng = random.Random()


def utcnow() -> datetime:
    """Текущее время, наивное UTC. Тесты подменяют эту функцию."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_msk(t: datetime) -> datetime:
    return t.replace(tzinfo=timezone.utc).astimezone(MSK)


def from_msk(t: datetime) -> datetime:
    return t.astimezone(timezone.utc).replace(tzinfo=None)


def in_window(t: datetime, start_h: int, end_h: int) -> bool:
    """t (наивное UTC) попадает в окно [start_h:00; end_h:00) по Москве."""
    loc = to_msk(t)
    return start_h <= loc.hour < end_h


def next_window_start(t: datetime, start_h: int, spread_min: float) -> datetime:
    """Ближайшее начало окна (сегодня, если ещё не наступило, иначе завтра) + случайно 0…spread_min минут."""
    loc = to_msk(t)
    cand = loc.replace(hour=start_h, minute=0, second=0, microsecond=0)
    if cand <= loc:
        cand += timedelta(days=1)
    return from_msk(cand) + timedelta(seconds=rng.uniform(0, spread_min * 60))


def latest_start(t: datetime, start_h: int, end_h: int, spread_min: float) -> datetime:
    """Самое позднее время, к которому бот должен начать отвечать на сообщение, пришедшее в t (без случайности)."""
    if in_window(t, start_h, end_h):
        return t
    loc = to_msk(t)
    cand = loc.replace(hour=start_h, minute=0, second=0, microsecond=0)
    if cand <= loc:
        cand += timedelta(days=1)
    return from_msk(cand) + timedelta(minutes=spread_min)


def fit_window(t: datetime, start_h: int, end_h: int, spread_min: float) -> datetime:
    """Если t вне окна — переносит на начало следующего окна со случайным разбросом."""
    return t if in_window(t, start_h, end_h) else next_window_start(t, start_h, spread_min)


# ---------- паузы ----------
# Первый ответ в новом чате: «прочитал и думает» 110–290 с + «печатает» 10–70 с → 2–6 мин.
# В идущем диалоге: 25–90 с + 15–90 с (длиннее при длинном ответе) → 40 с – 3 мин.

def think_delay(first: bool) -> timedelta:
    return timedelta(seconds=rng.uniform(110, 290) if first else rng.uniform(25, 90))


def typing_delay(text: str, first: bool) -> timedelta:
    lo, hi = (10, 70) if first else (15, 90)
    return timedelta(seconds=max(lo, min(hi, len(text or "") / 10 + rng.uniform(-3, 3))))


def second_part_delay(text: str) -> timedelta:
    """Пауза перед вторым коротким сообщением подряд."""
    return timedelta(seconds=max(8, min(40, len(text or "") / 10 + rng.uniform(2, 6))))


def debounce_delay() -> timedelta:
    """Клиент дописал, пока «бот думал»: подождать ещё, чтобы ответить одним сообщением на всё."""
    return timedelta(seconds=rng.uniform(30, 60))


def regenerate_delay() -> timedelta:
    """Клиент дописал, когда ответ уже был готов: перечитать переписку и ответить заново."""
    return timedelta(seconds=rng.uniform(20, 45))


# ---------- напоминания ----------

def followup_delay(stage: int) -> timedelta:
    """1-е напоминание — через 20–26 ч после нашего вопроса; 2-е — через ~3 дня после первого."""
    if stage == 1:
        return timedelta(hours=rng.uniform(20, 26))
    return timedelta(hours=rng.uniform(70, 76))
