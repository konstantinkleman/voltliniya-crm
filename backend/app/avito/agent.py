"""Бот-продажник: по истории чата и активному скрипту формирует ответ и извлекает данные заявки."""
import json
import logging
from dataclasses import dataclass, field

from ..config import settings

log = logging.getLogger("avito.agent")

REPLY_TOOL = {
    "name": "reply",
    "description": "Ответ клиенту в чате Авито и извлечённые из разговора данные заявки.",
    "input_schema": {
        "type": "object",
        "properties": {
            "messages": {
                "type": "array", "items": {"type": "string"}, "maxItems": 2,
                "description": "Сообщения клиенту по порядку. Обычно одно (2–5 предложений). Иногда два коротких подряд "
                               "вместо одного длинного — например, ответ и отдельным сообщением вопрос. "
                               "Пустой массив — если отвечать не нужно.",
            },
            "fields": {
                "type": "object",
                "description": "Только то, что клиент сообщил явно. Неизвестное не заполнять.",
                "properties": {
                    "name": {"type": "string"},
                    "phone": {"type": "string"},
                    "object_type": {"type": "string", "enum": ["новостройка", "вторичка", "дом", "коммерция", "другое"]},
                    "area_m2": {"type": "number"},
                    "district": {"type": "string", "description": "Район, ЖК или адрес"},
                    "has_project": {"type": "string", "enum": ["designer", "own", "none"]},
                    "start_when": {"type": "string", "description": "Когда планируют начинать"},
                    "call_time": {"type": "string", "description": "Удобное время для звонка"},
                },
            },
            "qualified": {"type": "string", "enum": ["yes", "no", "unknown"],
                          "description": "yes — комплексный объект от 50 000 ₽; no — мелкая работа или не наш профиль"},
            "handoff": {"type": "boolean", "description": "Передать руководителю прямо сейчас"},
            "handoff_reason": {"type": "string"},
            "expects_answer": {"type": "boolean",
                               "description": "В последнем сообщении задан вопрос клиенту, и мы ждём его ответа"},
            "summary": {"type": "string", "description": "Одна строка для руководителя: кто, что, где, когда, на чём остановились"},
        },
        "required": ["messages", "fields", "qualified", "handoff", "expects_answer", "summary"],
    },
}

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]

FOLLOWUP_TASK = {
    1: "Клиент не ответил на наш последний вопрос почти сутки. Напиши одно короткое напоминание своими словами "
       "(1–2 предложения): уточни, актуален ли ещё вопрос, и предложи следующий шаг. Без давления, без упрёков, "
       "без извинений, не повторяй прошлые сообщения дословно.",
    2: "Клиент молчит несколько дней, одно напоминание уже было. Напиши последнее короткое сообщение (1–2 предложения): "
       "если вопрос станет актуален — пусть напишет сюда, посчитаем. Без давления и без вопросов «почему не отвечаете».",
}


@dataclass
class AgentResult:
    parts: list[str] = field(default_factory=list)
    fields: dict = field(default_factory=dict)
    qualified: str = "unknown"
    handoff: bool = False
    handoff_reason: str = ""
    expects_answer: bool = False
    summary: str = ""

    @property
    def reply(self) -> str:
        return "\n".join(self.parts)


def _history(messages: list[dict], tail: str | None = None) -> list[dict]:
    """История чата в формате Claude: client → user, bot/director → assistant. Подряд идущие склеиваем."""
    out: list[dict] = []
    for msg in messages:
        role = "user" if msg["direction"] == "in" else "assistant"
        prefix = "[Константин ответил сам] " if msg.get("author") == "director" else ""
        text = prefix + msg["text"]
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n" + text
        else:
            out.append({"role": role, "content": text})
    if not out or out[0]["role"] != "user":
        out.insert(0, {"role": "user", "content": "[клиент открыл чат]"})
    if out[-1]["role"] != "user":
        out.append({"role": "user", "content": tail or "[продолжи, если есть что добавить, иначе верни пустой список сообщений]"})
    elif tail:
        out[-1]["content"] += "\n" + tail
    return out


def run(script: str, messages: list[dict], chat_ctx: dict, purpose: str = "reply", feedback: str | None = None) -> AgentResult:
    """messages: [{direction, author, text}]; chat_ctx: {item_title, client_name, known, now_msk, handoff_done};
    purpose: reply | followup1 | followup2; feedback — замечание к прошлой попытке (нарушение правил)."""
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("Не задан ANTHROPIC_API_KEY")
    import anthropic  # импорт здесь, чтобы тесты без ключа не тянули SDK

    system = script.strip() + "\n\nКОНТЕКСТ ЧАТА\n"
    now = chat_ctx.get("now_msk")
    if now:
        system += f"Сейчас {WEEKDAYS[now.weekday()]}, {now:%d.%m %H:%M} по Москве. Не извиняйся за время ответа и не упоминай время суток.\n"
    system += f"Объявление, по которому написал клиент: {chat_ctx.get('item_title') or 'неизвестно'}.\n"
    if chat_ctx.get("client_name"):
        system += f"Имя клиента в Авито: {chat_ctx['client_name']}.\n"
    known = {k: v for k, v in (chat_ctx.get("known") or {}).items() if v}
    if known:
        system += "Уже известно о заявке: " + json.dumps(known, ensure_ascii=False) + ". Не переспрашивай это.\n"
    if chat_ctx.get("handoff_done"):
        system += ("Разговор уже передан Константину. Отвечай коротко на вопросы по фактам, не договаривайся о времени "
                   "и условиях сам, не переспрашивай уже известное.\n")
    tail = None
    if purpose.startswith("followup"):
        tail = "[" + FOLLOWUP_TASK[int(purpose[-1])] + "]"
    if feedback:
        system += f"\nВАЖНО: прошлый вариант ответа нарушил правила ({feedback}). Перепиши без этого.\n"
    system += "Отвечай ТОЛЬКО вызовом инструмента reply."

    cl = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    resp = cl.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=1200,
        system=system,
        messages=_history(messages, tail),
        tools=[REPLY_TOOL],
        tool_choice={"type": "tool", "name": "reply"},
    )
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use" and block.name == "reply":
            d = block.input or {}
            parts = d.get("messages")
            if isinstance(parts, str):
                parts = [parts]
            parts = [p.strip() for p in (parts or []) if isinstance(p, str) and p.strip()][:2]
            return AgentResult(
                parts=parts,
                fields={k: v for k, v in (d.get("fields") or {}).items() if v not in (None, "", 0)},
                qualified=d.get("qualified") or "unknown",
                handoff=bool(d.get("handoff")),
                handoff_reason=d.get("handoff_reason") or "",
                expects_answer=bool(d.get("expects_answer")),
                summary=d.get("summary") or "",
            )
    log.warning("agent: нет tool_use в ответе: %s", resp.content)
    return AgentResult()


REVIEW_PROMPT = """\
Ты — руководитель отдела продаж электромонтажной компании «ВольтЛиния». Ниже — переписки бота-продажника с клиентами Авито за неделю и текущий скрипт бота.

Задача:
1. Коротко оцени, что работает, а что нет: где клиенты уходят, какие вопросы бот не закрыл, где отвечал слишком длинно или не по делу, где пропустил квалификацию или handoff, были ли ответы не по фактам.
2. Посчитай по переписке: чатов всего, квалифицированных, переданных руководителю, отказов (мелкие работы), «замолчавших» клиентов после ответа бота.
3. Предложи новую версию скрипта: внеси только обоснованные правки (формулировки, порядок вопросов, примеры ответов). Не меняй факты о компании, цены и правила «не упоминать». Скрипт должен остаться примерно той же длины.

Верни ответ вызовом инструмента review.
"""

REVIEW_TOOL = {
    "name": "review",
    "input_schema": {
        "type": "object",
        "properties": {
            "report": {"type": "string", "description": "Отчёт для руководителя, Markdown, до 2500 знаков"},
            "changes": {"type": "string", "description": "Список правок скрипта в 3–7 строк"},
            "new_script": {"type": "string", "description": "Полный текст новой версии скрипта"},
        },
        "required": ["report", "changes", "new_script"],
    },
}


def review(script: str, transcripts: str) -> dict:
    import anthropic

    cl = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    resp = cl.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=8000,
        system=REVIEW_PROMPT,
        messages=[{"role": "user", "content": f"ТЕКУЩИЙ СКРИПТ\n\n{script}\n\nПЕРЕПИСКИ\n\n{transcripts}"}],
        tools=[REVIEW_TOOL],
        tool_choice={"type": "tool", "name": "review"},
    )
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use" and block.name == "review":
            return block.input or {}
    return {}
