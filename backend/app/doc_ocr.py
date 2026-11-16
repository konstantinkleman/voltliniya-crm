"""Распознавание документов заказчика для договора: паспорт РФ (разворот с фото), страница с пропиской,
карточка реквизитов ИП/ООО. Фото на сервере CRM не сохраняется — только распознанные поля, их проверяет директор.

Сервис по умолчанию — OpenAI (тот же ключ, что для накладных; решение владельца 16.11.2026). Это трансграничная
передача персональных данных (США) — в реестре РКН у ИП сейчас указано «нет», политика тоже говорит «не осуществляется».
Альтернатива без передачи за рубеж — Yandex Vision OCR: DOC_OCR_PROVIDER=yandex + YANDEX_VISION_API_KEY и YANDEX_FOLDER_ID.
"""
import base64
import json
import re

import httpx
from fastapi import HTTPException

from .config import settings
from .invoice_ai import _image_parts, _to_jpeg

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


def provider() -> str:
    return "yandex" if settings.DOC_OCR_PROVIDER == "yandex" else "openai"


def ready() -> bool:
    if provider() == "yandex":
        return bool(settings.YANDEX_VISION_API_KEY and settings.YANDEX_FOLDER_ID)
    return bool(settings.OPENAI_API_KEY)


def recognize(images: list[tuple[bytes, str]]) -> dict:
    """images: [(данные, mime)]. Возвращает {"fields": {...}, "kinds": [...], "text": "..."} — поля для формы договора."""
    return _recognize_yandex(images) if provider() == "yandex" else _recognize_openai(images)


PROMPT = """Ты переносишь данные из документов заказчика в договор подряда (Россия). На фото может быть: разворот паспорта РФ
с фотографией, страница паспорта со штампом о регистрации (прописка), карточка реквизитов ИП/ООО, выписка ЕГРИП/ЕГРЮЛ, счёт.
Верни ТОЛЬКО JSON без пояснений:
{"kinds": ["passport"|"registration"|"org"|"other" — по одному на каждое фото, в том же порядке],
 "fields": {"fio": null, "birth": null, "pass_series": null, "pass_number": null, "pass_issued": null, "pass_date": null,
            "pass_code": null, "reg_address": null, "org_name": null, "ogrn": null, "inn": null, "kpp": null,
            "legal_address": null, "signer": null, "sign_name": null, "basis": null, "account": null, "bank": null,
            "corr": null, "bik": null, "org_phone": null, "org_email": null}}
Правила:
- Переписывай только то, что видно на фото. Не угадывай: нечитаемое или отсутствующее — null.
- fio — «Фамилия Имя Отчество» обычным регистром (Иванов Иван Иванович).
- Даты (birth — дата рождения, pass_date — дата выдачи паспорта) — в формате YYYY-MM-DD.
- pass_series — 4 цифры без пробелов, pass_number — 6 цифр, pass_code — код подразделения «000-000».
- pass_issued — кем выдан, как напечатано в паспорте (заглавными, как в документе), одной строкой.
- reg_address — адрес из действующего штампа о регистрации (если штампов несколько — последний не погашенный «снят с учёта»),
  одной строкой: регион, город/населённый пункт, улица, дом, корпус/строение, квартира.
- org_name — полное наименование: «Общество с ограниченной ответственностью «…»» или «Индивидуальный предприниматель Фамилия Имя Отчество».
- ogrn — ОГРН (13 цифр) или ОГРНИП (15 цифр); inn — 10 или 12 цифр; kpp — 9 цифр (у ИП нет — null);
  account — расчётный счёт (20 цифр), corr — корреспондентский счёт (20 цифр), bik — 9 цифр, bank — наименование банка.
- signer — кто подписывает, в родительном падеже для фразы «в лице …»: «генерального директора Иванова Ивана Ивановича»;
  sign_name — его фамилия и инициалы «Иванов И.И.»; basis — «Устава» для ООО, «записи в ЕГРИП» для ИП, либо как указано.
- Все числа реквизитов — только цифры, без пробелов.
"""

FIELD_KEYS = ["fio", "birth", "pass_series", "pass_number", "pass_issued", "pass_date", "pass_code", "reg_address", "org_name",
              "ogrn", "inn", "kpp", "legal_address", "signer", "sign_name", "basis", "account", "bank", "corr", "bik",
              "org_phone", "org_email"]
DIGITS = {"pass_series": (4,), "pass_number": (6,), "inn": (10, 12), "kpp": (9,), "ogrn": (13, 15), "account": (20,), "corr": (20,),
          "bik": (9,)}


def clean_fields(raw: dict) -> dict:
    """Проверка и нормализация ответа модели: неверные по формату значения отбрасываются."""
    out = {}
    for k in FIELD_KEYS:
        v = raw.get(k)
        if v in (None, "", "null"):
            continue
        v = re.sub(r"\s+", " ", str(v)).strip()
        if k in DIGITS:
            d = re.sub(r"\D", "", v)
            if len(d) not in DIGITS[k]:
                continue
            v = d
        elif k in ("birth", "pass_date"):
            v = v if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else _iso(v)
            if not v:
                continue
        elif k == "pass_code":
            d = re.sub(r"\D", "", v)
            if len(d) != 6:
                continue
            v = d[:3] + "-" + d[3:]
        out[k] = v[:300]
    return out


def _recognize_openai(images: list[tuple[bytes, str]]) -> dict:
    if not settings.OPENAI_API_KEY:
        raise HTTPException(400, "Распознавание не настроено: укажите OPENAI_API_KEY в .env на сервере")
    parts = []
    for data, mime in images:
        parts += _image_parts(data, mime)
    body = {"model": settings.OPENAI_MODEL, "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": PROMPT},
                         {"role": "user", "content": [{"type": "text", "text": f"Фото: {len(images)}. Перенеси данные и верни JSON."}] + parts}]}
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
    content = r.json()["choices"][0]["message"].get("content") or ""
    try:
        out = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            raise HTTPException(502, "OpenAI не вернул данные (возможно, отказался читать документ) — заполните поля вручную")
        out = json.loads(m.group(0))
    fields = clean_fields(out.get("fields") or {})
    kinds = [k if k in ("passport", "registration", "org") else "unknown" for k in (out.get("kinds") or [])][:len(images)]
    if any(k in fields for k in ("org_name", "ogrn", "account")) and not any(k in fields for k in ("fio", "pass_number")):
        ip = len(fields.get("ogrn", "")) == 15 or len(fields.get("inn", "")) == 12 or \
            re.match(r"(индивидуальный предприниматель|ип)\b", fields.get("org_name", ""), re.I)
        fields["kind"] = "ip" if ip else "org"
    elif any(k in fields for k in ("fio", "pass_number", "reg_address")):
        fields["kind"] = "person"
    return {"fields": fields, "kinds": kinds, "text": ""}


def _recognize_yandex(images: list[tuple[bytes, str]]) -> dict:
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
        fields["kind"] = "ip" if len(fields.get("ogrn", "")) == 15 or len(fields.get("inn", "")) == 12 else "org"
    elif "passport" in kinds or "registration" in kinds:
        fields["kind"] = "person"
    return {"fields": fields, "kinds": kinds, "text": "\n\n".join(t for t in texts if t)}
