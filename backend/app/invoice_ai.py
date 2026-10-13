"""Распознавание накладной по фото/PDF через OpenAI (vision) и сопоставление с номенклатурой."""
import base64
import difflib
import json
import re
from decimal import Decimal

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Product

PROMPT = """Ты распознаёшь товарную накладную (УПД, ТОРГ-12, счёт, чек) поставщика электромонтажных материалов в России.
Верни ТОЛЬКО JSON без пояснений, строго такой формы:
{"supplier": "название поставщика или null", "doc_number": "номер накладной или null", "date": "YYYY-MM-DD или null",
 "lines": [{"raw": "наименование БУКВАЛЬНО как напечатано", "short": "короткое название по шаблону", "qty": число, "unit": "м|шт|упак|кг|компл",
            "unit_price": число, "total": число, "category": "категория из списка или null", "confidence": "high|low"}]}

ПРАВИЛА ЧТЕНИЯ ЧИСЕЛ (самое важное):
- В накладной несколько числовых колонок: цена без НДС, НДС, цена с НДС, сумма без НДС, сумма с НДС. Нужна ЦЕНА С НДС за единицу
  и СУММА С НДС по строке (та, что суммируется в «Итого к оплате»). Если колонки «с НДС» нет — бери то, что есть.
- Всегда проверяй: qty × unit_price ≈ total (допуск 1%). Если не сходится — ты перепутал колонки или количество: перечитай строку.
  Если сходится только при другом qty — значит количество в накладной именно такое.
- Если цена указана за упаковку/бухту (например «бухта 100 м» по 8600), а количество в накладной в метрах — unit_price = цена за метр.
- Числа — только цифры с точкой, без пробелов, валюты и «руб».
- Если не уверен в количестве или цене строки — confidence: "low". Лучше честно "low", чем выдуманное число.

ПРАВИЛА НАЗВАНИЙ:
- raw: точная копия текста из накладной, символ в символ, с артикулами и кодами. Ничего не исправлять и не нормализовать.
- short: короткое название для склада по шаблону «Тип + ключевые параметры», без артикулов, кодов поставщика и лишних слов. Примеры:
  «Дифф 1P+N 32A 30mA тип AC C 4.5kA Sche 16055DEK 16055DEK» → «Диф. автомат 1P+N 32А 30мА тип AC 4.5кА»
  «Кабель ВВГнг(А)-LS 3х2,5 ок(N)-0,66 ГОСТ (бухта 100м)» → «Кабель ВВГнг-LS 3×2,5»
  «Выключатель автоматический ВА47-29 1Р 16А 4,5кА х-ка С IEK» → «Автомат 1P 16А C 4.5кА IEK»
  «Труба гофрированная ПВХ лёгкая 20 мм с протяжкой (100м)» → «Гофра ПВХ d20»
  «Коробка установочная СП 68х45 для бетона» → «Подрозетник бетон d68»
  «Провод ПуГВ 1х6 ж/з» → «ПуГВ 1×6 ж/з»
  Бренд оставляй только если он различает цену/класс (ABB, Schneider, IEK, Dekraft, EKF); артикулы и «ГОСТ» — убирай.
  Сечение — через ×, ток — «А», ток утечки — «мА», отключающая способность — «кА», характеристика — одной буквой (C, B).
- unit: кабель, провод, гофра — «м»; автоматы, подрозетники, коробки, щиты — «шт». Если единица неясна — «шт».
- category: выбери наиболее подходящую из списка категорий пользователя (будет дан ниже), иначе null.
- Служебные строки (доставка, скидка, итого) не включай. Не выдумывай строки.
"""


MAX_SIDE = 2600  # px — цифры в таблице А4 читаются; запрос всё равно в разы легче исходного фото


def _to_jpeg(data: bytes) -> bytes:
    """Любой формат (HEIC с iPhone, TIFF, BMP, PNG, WebP) → JPEG до 2000 px по длинной стороне, с учётом EXIF-поворота."""
    import io
    from PIL import Image, ImageOps
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        raise HTTPException(400, "Не удалось прочитать изображение. Поддерживаются фото JPEG/PNG/HEIC/WebP и PDF")
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_SIDE:
        k = MAX_SIDE / max(w, h)
        img = img.resize((int(w * k), int(h * k)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88, optimize=True)
    return buf.getvalue()


def _image_parts(data: bytes, mime: str) -> list[dict]:
    """Фото → JPEG; PDF → первые 3 страницы как JPEG."""
    if mime == "application/pdf" or data[:4] == b"%PDF":
        try:
            import pypdfium2 as pdfium
        except ImportError:
            raise HTTPException(500, "PDF не поддерживается: нет pypdfium2")
        pdf = pdfium.PdfDocument(data)
        parts = []
        for i in range(min(len(pdf), 3)):
            import io
            page = pdf[i]
            img = page.render(scale=2).to_pil()
            buf = io.BytesIO(); img.save(buf, format="JPEG", quality=85)
            parts.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(_to_jpeg(buf.getvalue())).decode(), "detail": "high"}})
        return parts
    jpeg = _to_jpeg(data)
    return [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode(), "detail": "high"}}]


def recognize(data: bytes, mime: str, categories: list[str] | None = None) -> dict:
    if not settings.OPENAI_API_KEY:
        raise HTTPException(400, "Распознавание не настроено: укажите OPENAI_API_KEY в .env на сервере")
    cats_text = "Категории пользователя (поле category): " + "; ".join(categories) if categories else "Категорий у пользователя пока нет: category = null."
    body = {
        "model": settings.OPENAI_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": [{"type": "text", "text": cats_text + "\n\nРаспознай накладную и верни JSON."}] + _image_parts(data, mime)},
        ],
    }
    try:
        r = httpx.post(f"{settings.OPENAI_BASE_URL}/chat/completions", json=body, timeout=180,
                       headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"OpenAI недоступен: {e}")
    if r.status_code != 200:
        detail = r.text[:300]
        try:
            detail = r.json().get("error", {}).get("message", detail)
        except Exception:
            pass
        raise HTTPException(502, f"OpenAI: {detail}")
    content = r.json()["choices"][0]["message"]["content"]
    try:
        out = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.S)
        out = json.loads(m.group(0)) if m else {"lines": []}
    lines = []
    for ln in out.get("lines") or []:
        raw = str(ln.get("raw") or ln.get("name") or "").strip()
        short = str(ln.get("short") or "").strip() or raw
        if not raw:
            continue
        qty = _num(ln.get("qty")); price = _num(ln.get("unit_price")); total = _num(ln.get("total"))
        conf = str(ln.get("confidence") or "high").lower()
        # сверка qty × price = total: если расходится больше чем на 1% — помечаем low и доверяем total/qty
        if qty and price and total and abs(qty * price - total) > max(total * Decimal("0.01"), Decimal("1")):
            conf = "low"
            price = total / qty
        if price is None and total is not None and qty:
            price = total / qty
        lines.append({"name": short, "raw": raw, "qty": qty or Decimal(0), "unit": _unit(ln.get("unit")),
                      "unit_cost": (price or Decimal(0)).quantize(Decimal("0.01")), "total": total,
                      "category": ln.get("category") or None, "confidence": conf})
    return {"supplier": out.get("supplier"), "doc_number": out.get("doc_number"), "date": out.get("date"), "lines": lines}


def _num(x):
    if x is None or x == "":
        return None
    try:
        return Decimal(str(x).replace(" ", "").replace(",", "."))
    except Exception:
        return None


def _unit(u) -> str:
    u = (u or "").strip().lower()
    if u in ("м", "m", "метр", "метры", "п.м", "пм", "м."):
        return "м"
    if u in ("шт", "шт.", "pcs", "штук"):
        return "шт"
    if u in ("упак", "уп", "уп.", "упаковка", "упак."):
        return "упак"
    if u in ("кг",):
        return "кг"
    if u in ("компл", "компл.", "комплект"):
        return "компл"
    return u or "шт"


# ---------- сопоставление с номенклатурой ----------

STOP = {"кабель", "провод", "труба", "трубка", "гофрированная", "гофрированный", "автоматический", "выключатель", "автомат",
        "силовой", "медный", "медь", "гибкий", "установочный", "монтажный", "электрический", "бухта", "катушка", "упаковка", "уп", "шт", "м", "мм", "п.м"}


def _norm(s: str) -> str:
    s = s.lower().replace("ё", "е")
    s = re.sub(r"\((?:а|a)\)", "", s)                 # ВВГнг(А)-LS → ВВГнг-LS
    s = re.sub(r"\([^)]*\)", " ", s)                   # (бухта 100м) — убрать
    s = s.replace("х", "x").replace("×", "x").replace("*", "x").replace(",", ".")
    s = re.sub(r"(\d)\s*x\s*(\d)", r"\1x\2", s)      # 3 x 2.5 → 3x2.5
    s = re.sub(r"\bd\s*(\d+)\b", r"\1мм", s)          # d20 → 20мм
    s = re.sub(r"\b(\d+)\s*мм\b", r"\1мм", s)
    s = re.sub(r"\b[cв]\s*(\d+)\b", r"\1a", s)        # C16 / В16 → 16a (характеристика автомата)
    s = re.sub(r"\b(\d+)\s*[aа]\b", r"\1a", s)
    s = re.sub(r"\b(\d)\s*[pр]\b", r"\1p", s)          # 2P / 2Р
    s = re.sub(r"\b(\d+(?:\.\d+)?)\s*0+\b", r"\1", s)
    s = s.replace("-", "")                                # ВВГнг-LS → ВВГнгLS, ВВГ-Пнг → ВВГПнг
    s = re.sub(r"[^\w.x+]+", " ", s)
    toks = [t for t in s.split() if t not in STOP]
    return " ".join(toks)


def _tokens(n: str) -> set:
    return set(re.findall(r"\d+(?:\.\d+)?x\d+(?:\.\d+)?|\d+a\b|\d+p\b|\d+мм|[a-zа-я]{2,}", n))


def _score(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return difflib.SequenceMatcher(None, a, b).ratio()
    # сечение/номинал обязаны совпасть, если есть у обоих
    key_a = {t for t in ta if re.match(r"\d", t)}; key_b = {t for t in tb if re.match(r"\d", t)}
    if key_a and key_b and not (key_a & key_b):
        return 0.0
    jac = len(ta & tb) / len(ta | tb)
    cover = len(ta & tb) / min(len(ta), len(tb))   # все токены короткого имени есть в длинном
    return 0.5 * jac + 0.5 * cover


def match_products(db: Session, lines: list[dict]) -> list[dict]:
    """К каждой строке добавляет product_id (уверенное совпадение) и candidates. Сопоставление идёт по короткому
    названию и по буквальному тексту накладной (он хранится в note позиции с прошлых приходов)."""
    prods = db.scalars(select(Product).where(Product.is_active == True)).all()  # noqa: E712
    index = {p.id: _norm(p.name) for p in prods}
    raw_index = {p.id: _norm(p.note or "") for p in prods}
    by_name = {}
    for p in prods:
        by_name.setdefault(index[p.id], p)
        if raw_index[p.id]:
            by_name.setdefault(raw_index[p.id], p)
    out = []
    for ln in lines:
        n = _norm(ln["name"]); nr = _norm(ln.get("raw") or "")
        pid = None; cands = []
        if n in by_name:
            pid = by_name[n].id
        elif nr and nr in by_name:
            pid = by_name[nr].id
        else:
            scored = sorted(((max(_score(n, index[p.id]), _score(nr, raw_index[p.id]) if nr and raw_index[p.id] else 0), p) for p in prods), key=lambda x: -x[0])
            cands = [{"id": p.id, "name": p.name, "unit": p.unit, "score": round(r, 2)} for r, p in scored[:4] if r >= 0.4]
            if scored and scored[0][0] >= 0.75 and (len(scored) < 2 or scored[0][0] - scored[1][0] >= 0.15):
                pid = scored[0][1].id
        out.append({**ln, "product_id": pid, "candidates": cands})
    return out
