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
            "reply": {"type": "string", "description": "Текст ответа клиенту. Пустая строка — если отвечать не нужно."},
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
                    "start_when": {"type": "string"},
                    "call_time": {"type": "string", "description": "Удобное время для звонка"},
                },
            },
            "qualified": {"type": "string", "enum": ["yes", "no", "unknown"],
                          "description": "yes — комплексный объект от 50 000 ₽; no — мелкая работа или не наш профиль"},
            "handoff": {"type": "boolean", "description": "Передать руководителю прямо сейчас"},
            "handoff_reason": {"type": "string"},
            "summary": {"type": "string", "description": "Одна строка для уведомления руководителю: кто, что, где, когда"},
        },
        "required": ["reply", "fields", "qualified", "handoff", "summary"],
    },
}


@dataclass
class AgentResult:
    reply: str = ""
    fields: dict = field(default_factory=dict)
    qualified: str = "unknown"
    handoff: bool = False
    handoff_reason: str = ""
    summary: str = ""


def _history(messages: list[dict]) -> list[dict]:
    """История чата в формате Claude: client → user, bot/director → assistant. Подряд идущие склеиваем."""
    out: list[dict] = []
    for msg in messages:
        role = "user" if msg["direction"] == "in" else "assistant"
        prefix = "[Руководитель ответил сам] " if msg.get("author") == "director" else ""
        text = prefix + msg["text"]
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n" + text
        else:
            out.append({"role": role, "content": text})
    if not out or out[0]["role"] != "user":
        out.insert(0, {"role": "user", "content": "[клиент открыл чат]"})
    if out[-1]["role"] != "user":
        out.append({"role": "user", "content": "[продолжи, если есть что добавить, иначе ответь пустой строкой]"})
    return out


def run(script: str, messages: list[dict], chat_ctx: dict) -> AgentResult:
    """messages: [{direction, author, text}], chat_ctx: {item_title, client_name, known: {...}}"""
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("Не задан ANTHROPIC_API_KEY")
    import anthropic  # импорт здесь, чтобы тесты без ключа не тянули SDK

    system = script.strip() + "\n\nКОНТЕКСТ ЧАТА\n"
    system += f"Объявление, по которому написал клиент: {chat_ctx.get('item_title') or 'неизвестно'}.\n"
    if chat_ctx.get("client_name"):
        system += f"Имя клиента в Авито: {chat_ctx['client_name']}.\n"
    known = {k: v for k, v in (chat_ctx.get("known") or {}).items() if v}
    if known:
        system += "Уже известно о заявке: " + json.dumps(known, ensure_ascii=False) + ". Не переспрашивай это.\n"
    system += "Отвечай ТОЛЬКО вызовом инструмента reply."

    cl = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    resp = cl.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=1200,
        system=system,
        messages=_history(messages),
        tools=[REPLY_TOOL],
        tool_choice={"type": "tool", "name": "reply"},
    )
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use" and block.name == "reply":
            d = block.input or {}
            return AgentResult(
                reply=(d.get("reply") or "").strip(),
                fields={k: v for k, v in (d.get("fields") or {}).items() if v not in (None, "", 0)},
                qualified=d.get("qualified") or "unknown",
                handoff=bool(d.get("handoff")),
                handoff_reason=d.get("handoff_reason") or "",
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
