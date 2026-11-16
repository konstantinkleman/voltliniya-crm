"""Договор по расчёту: данные заказчика, пакет документов (договор + приложения), распознавание паспорта/реквизитов."""
import json
import os
import re
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import calc, calc_params, contract, doc_ocr
from .. import models as m
from ..auth import director
from ..config import settings
from ..db import get_db

router = APIRouter(prefix="/api", tags=["contracts"])

TEXT_FIELDS = {k for k, _ in contract.PERSON_FIELDS + contract.ORG_FIELDS + contract.COMMON_FIELDS} | {"kind"}
MIME = {".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".zip": "application/zip"}


def _get(db: Session, eid: int) -> m.Estimate:
    e = db.get(m.Estimate, eid)
    if not e:
        raise HTTPException(404, "Расчёт не найден")
    return e


def _data(e: m.Estimate) -> dict:
    saved = json.loads(e.contract or "{}") if e.contract else {}
    base = contract.default_data(e.lead, json.loads(e.inputs or "{}"))
    base.update({k: v for k, v in saved.items() if k in TEXT_FIELDS})
    return base


def _state(e: m.Estimate, db: Session) -> dict:
    data = _data(e)
    res = calc.compute(json.loads(e.inputs or "{}"), json.loads(e.params or "{}"))
    n = contract.numbers(res, e.tariff, data.get("advance"))
    n.pop("smeta")
    con = calc_params.contractor(db)
    return {"estimate_id": e.id, "lead_id": e.lead_id, "title": e.title, "tariff": e.tariff, "data": data, "numbers": n,
            "missing": contract.missing(data, con), "saved": bool(e.contract),
            "fields": {"common": contract.COMMON_FIELDS, "person": contract.PERSON_FIELDS, "org": contract.ORG_FIELDS},
            "ocr_ready": bool(settings.YANDEX_VISION_API_KEY and settings.YANDEX_FOLDER_ID)}


@router.get("/estimates/{eid}/contract")
def get_contract(eid: int, _: m.User = Depends(director), db: Session = Depends(get_db)):
    return _state(_get(db, eid), db)


class ContractIn(BaseModel):
    data: dict
    tariff: str | None = None


@router.put("/estimates/{eid}/contract")
def save_contract(eid: int, body: ContractIn, _: m.User = Depends(director), db: Session = Depends(get_db)):
    e = _get(db, eid)
    clean = {}
    for k, v in body.data.items():
        if k not in TEXT_FIELDS:
            continue
        if k == "advance":
            clean[k] = None if v in (None, "") else max(0, round(calc.num(v)))
        else:
            clean[k] = str(v or "").strip()[:500]
    if clean.get("kind") not in ("person", "org"):
        clean["kind"] = "person"
    e.contract = json.dumps(clean, ensure_ascii=False)
    if body.tariff in calc.TARIFFS:
        e.tariff = body.tariff
    db.commit()
    db.refresh(e)
    return _state(e, db)


def _files(e: m.Estimate, db: Session) -> dict[str, bytes]:
    data = _data(e)
    res = calc.compute(json.loads(e.inputs or "{}"), json.loads(e.params or "{}"))
    return contract.build(res, e.tariff, data, calc_params.contractor(db))


def _download(name: str, content: bytes) -> Response:
    ext = os.path.splitext(name)[1]
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", name) or "file" + ext
    return Response(content, media_type=MIME.get(ext, "application/octet-stream"),
                    headers={"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"})


@router.get("/estimates/{eid}/contract/files")
def contract_files(eid: int, name: str | None = None, _: m.User = Depends(director), db: Session = Depends(get_db)):
    """Без name — весь пакет одним zip; с name — один файл пакета."""
    e = _get(db, eid)
    files = _files(e, db)
    if name:
        if name not in files:
            raise HTTPException(404, "Нет такого файла в пакете")
        return _download(name, files[name])
    num = re.sub(r"[^\w\-]+", "-", _data(e).get("number") or str(e.id))
    return _download(f"Договор_{num}.zip", contract.zip_files(files))


@router.get("/estimates/{eid}/contract/list")
def contract_list(eid: int, _: m.User = Depends(director), db: Session = Depends(get_db)):
    names = list(_files(_get(db, eid), db))
    return [{"name": n, "title": re.sub(r"^\d+_", "", os.path.splitext(n)[0]).replace("_", " ")} for n in names]


DOC_KIND = {"01": "contract", "02": "appendix", "03": "appendix", "05": "act"}


@router.post("/estimates/{eid}/contract/to-lead")
def contract_to_lead(eid: int, user: m.User = Depends(director), db: Session = Depends(get_db)):
    """Сохранить пакет в документы заявки (прежний пакет этого расчёта заменяется)."""
    e = _get(db, eid)
    if not e.lead_id:
        raise HTTPException(400, "Расчёт не привязан к заявке")
    files = _files(e, db)
    mark = f" · расчёт {e.id}"
    for d in db.scalars(select(m.Document).where(m.Document.lead_id == e.lead_id, m.Document.title.like(f"%{mark}"))).all():
        try:
            os.remove(d.path)
        except OSError:
            pass
        db.delete(d)
    folder = os.path.join(settings.UPLOAD_DIR, f"leads/{e.lead_id}")
    os.makedirs(folder, exist_ok=True)
    num = _data(e).get("number") or ""
    for name, content in files.items():
        path = os.path.join(folder, f"{uuid.uuid4().hex[:8]}_{re.sub(r'[^\w.\-]+', '_', name)}")
        with open(path, "wb") as f:
            f.write(content)
        title = re.sub(r"^\d+_", "", os.path.splitext(name)[0]).replace("_", " ")
        db.add(m.Document(lead_id=e.lead_id, kind=DOC_KIND.get(name[:2], "other"), title=(title + mark)[:300], filename=name,
                          path=path, mime=MIME.get(os.path.splitext(name)[1]), size=len(content), user_id=user.id))
    db.add(m.LeadActivity(lead_id=e.lead_id, kind="note", user_id=user.id,
                          text=f"Сформирован договор № {num} ({calc.TARIFF_NAMES[e.tariff]}) — {len(files)} файлов в документах"))
    db.commit()
    return {"ok": True, "count": len(files)}


@router.post("/contract/recognize")
async def recognize(files: list[UploadFile] = File(...), _: m.User = Depends(director)):
    """Фото паспорта / страницы с пропиской / карточки реквизитов → поля договора. Фото не сохраняются."""
    if not files or len(files) > 4:
        raise HTTPException(400, "Пришлите от 1 до 4 фото")
    images = []
    for f in files:
        data = await f.read()
        if len(data) > 25 * 1024 * 1024:
            raise HTTPException(413, "Фото больше 25 МБ")
        images.append((data, f.content_type or ""))
    return doc_ocr.recognize(images)
