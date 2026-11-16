"""Распознавание документов заказчика для договора: паспорт РФ (разворот с фото), страница с пропиской,
карточка реквизитов ИП/ООО. Сервис — Yandex Vision OCR (Яндекс Облако, РФ): персональные данные не уходят
за границу (в реестре РКН у ИП трансграничная передача — «нет»). Журналирование запросов у Яндекса выключено
заголовком x-data-logging-enabled: false. Фото на сервере CRM не сохраняется — только распознанные поля.

Порядок: сначала модель «passport»; если полей паспорта нет — модель «page» (весь текст) и разбор
реквизитов организации или адреса регистрации по шаблонам.
"""
import base64
import re

import httpx
from fastapi import HTTPException

from .config import settings
from .invoice_ai import _to_jpeg

URL = "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText"


def _call(jpeg: bytes, model: str) -> dict:
    if not (settings.YANDEX_VISION_API_KEY and settings.YANDEX_FOLDER_ID):
        raise HTTPException(400, "Распознавание документов не настроено: укажите YANDEX_VISION_API_KEY и YANDEX_FOLDER_ID в .env на сервере")
    body = {"mimeType": "JPEG", "languageCodes": ["ru", "en"] if model == "page" else ["*"], "model": model,
            "content": base64.b64encode(jpeg).decode()}
    try:
        r = httpx.post(URL, json=body, timeout=60, headers={
            "Authorization": f"Api-Key {settings.YANDEX_VISION_API_KEY}", "x-folder-id": settings.YANDEX_FOLDER_ID,
            "x-data-logging-enabled": "false"})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Yandex Vision недоступен: {e}")
    if r.status_code != 200:
        detail = r.text[:300]
        try:
            detail = r.json().get("message", detail)
        except Exception:
            pass
        raise HTTPException(502, f"Yandex Vision: {detail}")
    return r.json()


def _find(obj, key):
    """Первое значение ключа в ответе (структура: result.textAnnotation.{entities, fullText})."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            x = _find(v, key)
            if x is not None:
                return x
    elif isinstance(obj, list):
        for v in obj:
            x = _find(v, key)
            if x is not None:
                return x
    return None


def _title(s: str) -> str:
    return "-".join(p[:1].upper() + p[1:].lower() for p in s.strip().split("-"))


def _iso(s: str) -> str:
    m = re.search(r"(\d{1,2})[.\s/-](\d{1,2})[.\s/-](\d{4})", s or "")
    return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}" if m else ""


def passport_fields(entities: list[dict]) -> dict:
    e = {}
    for x in entities or []:
        name, text = x.get("name"), (x.get("text") or "").strip()
        if name and text and text != "-":
            e[name] = text
    out = {}
    fio = " ".join(_title(e[k]) for k in ("surname", "name", "middle_name") if e.get(k))
    if fio:
        out["fio"] = fio
    if e.get("birth_date"):
        out["birth"] = _iso(e["birth_date"])
    digits = re.sub(r"\D", "", e.get("number", ""))
    if len(digits) == 10:
        out["pass_series"], out["pass_number"] = digits[:4], digits[4:]
    elif digits:
        out["pass_number"] = digits
    if e.get("issued_by"):
        out["pass_issued"] = re.sub(r"\s+", " ", e["issued_by"]).upper()
    if e.get("issue_date"):
        out["pass_date"] = _iso(e["issue_date"])
    code = re.sub(r"\D", "", e.get("subdivision", ""))
    if len(code) == 6:
        out["pass_code"] = code[:3] + "-" + code[3:]
    return {k: v for k, v in out.items() if v}


def _after(text: str, label: str, pattern: str) -> str:
    m = re.search(label + r"[^\d\n]{0,40}?(" + pattern + r")", text, re.I)
    return m.group(1) if m else ""


def org_fields(text: str) -> dict:
    t = text.replace(" ", " ")
    flat = re.sub(r"\s+", " ", t)
    out = {}
    inn = _after(flat, r"ИНН", r"\d{12}|\d{10}")
    if inn:
        out["inn"] = inn
    kpp = _after(flat, r"КПП", r"\d{9}")
    if kpp:
        out["kpp"] = kpp
    ogrn = _after(flat, r"ОГРН(?:ИП)?", r"\d{15}|\d{13}")
    if ogrn:
        out["ogrn"] = ogrn
    acc = _after(flat, r"(?:р/с|р\.с\.|расч[её]тный сч[её]т|сч[её]т получателя)", r"\d{20}") or \
        next(iter(re.findall(r"\b40[78]\d{17}\b", flat)), "")
    if acc:
        out["account"] = acc
    corr = _after(flat, r"(?:к/с|к\.с\.|корр?\.? ?сч[её]т|корреспондентский сч[её]т)", r"\d{20}") or \
        next(iter(re.findall(r"\b301\d{17}\b", flat)), "")
    if corr:
        out["corr"] = corr
    bik = _after(flat, r"БИК", r"\d{9}")
    if bik:
        out["bik"] = bik
    lines = [ln.strip(" :;,") for ln in t.splitlines() if ln.strip()]
    for ln in lines:
        if re.search(r"(общество с ограниченной ответственностью|^ООО\b|индивидуальный предприниматель|^ИП\s)", ln, re.I) \
                and not re.search(r"ИНН|ОГРН", ln):
            out.setdefault("org_name", re.sub(r"^(полное|сокращ[её]нное)?\s*наименование\s*[:—-]?\s*", "", ln, flags=re.I))
        m = re.search(r"(?:юридический адрес|адрес регистрации|адрес места нахождения|адрес)\s*[:—-]?\s*(.+)", ln, re.I)
        if m and len(m.group(1)) > 8 and "addr" not in out:
            out["legal_address"] = m.group(1)
            out["addr"] = True
        m = re.search(r"((?:генеральный )?директор|руководитель)\s*[:—-]?\s*(.+)", ln, re.I)
        if m and len(m.group(2).split()) >= 2:
            out.setdefault("signer_hint", m.group(1).strip() + " " + m.group(2).strip())
        if re.search(r"банк", ln, re.I) and not re.search(r"БИК|сч[её]т|ИНН", ln, re.I):
            out.setdefault("bank", re.sub(r"^(банк|наименование банка)\s*[:—-]?\s*", "", ln, flags=re.I))
    out.pop("addr", None)
    hint = out.pop("signer_hint", "")
    if hint:
        out["signer"] = hint    # в именительном падеже — поправить на «генерального директора Иванова И. И.»
        p = hint.split()[-3:]
        if len(p) == 3:
            out["sign_name"] = _title(p[0]) + " " + p[1][:1].upper() + "." + p[2][:1].upper() + "."
    if re.search(r"индивидуальный предприниматель|ОГРНИП|^ИП\s", t, re.I | re.M):
        out.setdefault("basis", "записи в ЕГРИП")
    return out


ADDR_MARK = re.compile(r"(\bг\.|\bгор\.|город|\bул\.|улица|\bд\.|\bдом\b|\bкв\.|квартира|\bкорп|\bстр\.|пр-т|проспект|\bпер\.|переулок|"
                       r"шоссе|\bш\.|набережная|\bнаб\.|бульвар|\bб-р|\bобл\.|область|р-н|район|\bпос\.|посёлок|поселок|\bмкр|\bс\.\s|деревня)", re.I)
ADDR_STOP = re.compile(r"(МВД|УФМС|ОВД|отдел|подпись|код подразделения|выдан|паспорт|начальник|место жительства|снят)", re.I)


def registration_address(text: str) -> str:
    """Адрес из штампа о регистрации: строки с признаками адреса после слова «Зарегистрирован»."""
    lines = [ln.strip(" .,;") for ln in (text or "").splitlines() if ln.strip()]
    start = next((i for i, ln in enumerate(lines) if re.search(r"зарегистрирован", ln, re.I)), None)
    if start is None:
        return ""
    picked = []
    for ln in lines[start + 1:start + 12]:
        if ADDR_STOP.search(ln):
            if picked:
                break
            continue
        if ADDR_MARK.search(ln) or (picked and re.search(r"\d", ln) and len(ln) < 40):
            picked.append(ln)
        elif picked:
            break
    return ", ".join(picked)


def recognize(images: list[tuple[bytes, str]]) -> dict:
    """images: [(данные, mime)]. Возвращает {"fields": {...}, "kinds": [...], "text": "..."} — поля для формы договора."""
    if not (settings.YANDEX_VISION_API_KEY and settings.YANDEX_FOLDER_ID):
        raise HTTPException(400, "Распознавание документов не настроено: укажите YANDEX_VISION_API_KEY и YANDEX_FOLDER_ID в .env на сервере")
    fields: dict = {}
    kinds, texts = [], []
    for data, mime in images:
        if mime == "application/pdf" or data[:4] == b"%PDF":
            raise HTTPException(400, "Пришлите фото или скан в JPEG/PNG/HEIC — PDF для паспорта не поддерживается")
        jpeg = _to_jpeg(data)
        res = _call(jpeg, "passport")
        pf = passport_fields(_find(res, "entities") or [])
        if pf.get("fio") or pf.get("pass_number"):
            kinds.append("passport")
            for k, v in pf.items():
                fields.setdefault(k, v)
            continue
        res = _call(jpeg, "page")
        text = _find(res, "fullText") or ""
        texts.append(text)
        of = org_fields(text)
        if any(k in of for k in ("inn", "ogrn", "account", "bik")):
            kinds.append("org")
            for k, v in of.items():
                fields.setdefault(k, v)
            continue
        addr = registration_address(text)
        if addr:
            kinds.append("registration")
            fields.setdefault("reg_address", addr)
        else:
            kinds.append("unknown")
    if "org" in kinds and "passport" not in kinds:
        fields["kind"] = "org"
    elif "passport" in kinds or "registration" in kinds:
        fields["kind"] = "person"
    return {"fields": fields, "kinds": kinds, "text": "\n\n".join(t for t in texts if t)}
