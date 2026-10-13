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
 "lines": [{"name": "наименование как в накладной", "qty": число, "unit": "м|шт|упак|кг|компл", "unit_price": число_без_НДС_или_с_НДС_как_в_итоге, "total": число}]}
Правила:
- qty и цены — числа (точка как разделитель), без валюты. Если цена указана за упаковку/бухту, а количество в штуках/метрах — пересчитай цену за единицу.
- Если в документе есть итоговая сумма с НДС по строке — unit_price = total / qty (цена, которую реально заплатили).
- unit: кабель и гофра — «м», автоматы/подрозетники/коробки — «шт». Если единица неясна — «шт».
- Не выдумывай строки. Служебные строки (доставка, скидка, итого) не включай в lines.
- Сохраняй маркировку полностью: сечение (3x2,5 / 3х2.5), тип (ВВГнг-LS, ПУгВ), номинал (16A, 2P).
"""


MAX_SIDE = 2000  # px — для распознавания накладной достаточно, а запрос в 3–5 раз легче


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


def recognize(data: bytes, mime: str) -> dict:
    if not settings.OPENAI_API_KEY:
        raise HTTPException(400, "Распознавание не настроено: укажите OPENAI_API_KEY в .env на сервере")
    body = {
        "model": settings.OPENAI_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": [{"type": "text", "text": "Распознай накладную и верни JSON."}] + _image_parts(data, mime)},
        ],
    }
    try:
        r = httpx.post(f"{settings.OPENAI_BASE_URL}/chat/completions", json=body, timeout=120,
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
        name = str(ln.get("name") or "").strip()
        if not name:
            continue
        qty = _num(ln.get("qty")); price = _num(ln.get("unit_price")); total = _num(ln.get("total"))
        if price is None and total is not None and qty:
            price = total / qty
        lines.append({"name": name, "qty": qty or Decimal(0), "unit": _unit(ln.get("unit")), "unit_cost": (price or Decimal(0)).quantize(Decimal("0.01")), "total": total})
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
    """К каждой строке добавляет product_id (если уверенное совпадение) и candidates (варианты)."""
    prods = db.scalars(select(Product).where(Product.is_active == True)).all()  # noqa: E712
    index = {p.id: _norm(p.name) for p in prods}
    by_name = {}
    for p in prods:
        by_name.setdefault(index[p.id], p)
    out = []
    for ln in lines:
        n = _norm(ln["name"])
        pid = None; cands = []
        if n in by_name:
            pid = by_name[n].id
        else:
            scored = sorted(((_score(n, index[p.id]), p) for p in prods), key=lambda x: -x[0])
            cands = [{"id": p.id, "name": p.name, "unit": p.unit, "score": round(r, 2)} for r, p in scored[:4] if r >= 0.4]
            if scored and scored[0][0] >= 0.75 and (len(scored) < 2 or scored[0][0] - scored[1][0] >= 0.15):
                pid = scored[0][1].id
        out.append({**ln, "product_id": pid, "candidates": cands})
    return out
