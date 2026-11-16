"""Договор по расчёту (пакет ИП из «Договоры_ИП»): данные заказчика, дизайн-проект PDF, документы, распознавание паспорта/реквизитов."""
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

TEXT_FIELDS = {k for k, _ in contract.PERSON_FIELDS + contract.ORG_FIELDS + contract.COMMON_FIELDS} | {"kind", "materials"}
KINDS = ("person", "ip", "org")
MIME = {".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".zip": "application/zip",
        ".pdf": "application/pdf"}
PANEL_FILE = "Щит_для_монтажника.xlsx"


def _get(db: Session, eid: int) -> m.Estimate:
    e = db.get(m.Estimate, eid)
    if not e:
        raise HTTPException(404, "Расчёт не найден")
    return e


def _design_path(eid: int) -> str:
    return os.path.join(settings.UPLOAD_DIR, "estimates", str(eid), "design.pdf")


def _design(eid: int) -> bytes | None:
    p = _design_path(eid)
    if os.path.exists(p):
        with open(p, "rb") as f:
            return f.read()
    return None


def _data(e: m.Estimate) -> dict:
    saved = json.loads(e.contract or "{}") if e.contract else {}
    base = contract.default_data(e.lead, json.loads(e.inputs or "{}"))
    base.update({k: v for k, v in saved.items() if k in TEXT_FIELDS})
    if base.get("kind") not in KINDS:
        base["kind"] = "person"
    return base


def _res(e: m.Estimate) -> dict:
    return calc.compute(json.loads(e.inputs or "{}"), json.loads(e.params or "{}"))


def _state(e: m.Estimate, db: Session) -> dict:
    data = _data(e)
    N = contract.numbers(_res(e), e.tariff, data.get("materials", "executor"))
    con = calc_params.contractor(db)
    design = os.path.exists(_design_path(e.id))
    nums = {k: N[k] for k in ("tariff", "tariff_name", "M", "works_sum", "stage2_sum", "mat_sum", "total", "warranty", "limit",
                              "mech", "brand")}
    return {"estimate_id": e.id, "lead_id": e.lead_id, "title": e.title, "tariff": e.tariff, "data": data, "numbers": nums,
            "missing": contract.missing(data, con, design), "saved": bool(e.contract), "design": design,
            "fields": {"common": contract.COMMON_FIELDS, "person": contract.form_fields("person"),
                       "ip": contract.form_fields("ip"), "org": contract.form_fields("org")},
            "ocr_ready": doc_ocr.ready(), "ocr_provider": doc_ocr.provider()}


@router.get("/estimates/{eid}/contract")
def get_contract(eid: int, _: m.User = Depends(director), db: Session = Depends(get_db)):
    return _state(_get(db, eid), db)


class ContractIn(BaseModel):
    data: dict
    tariff: str | None = None


@router.put("/estimates/{eid}/contract")
def save_contract(eid: int, body: ContractIn, _: m.User = Depends(director), db: Session = Depends(get_db)):
    e = _get(db, eid)
    clean = {k: str(v or "").strip()[:500] for k, v in body.data.items() if k in TEXT_FIELDS}
    if clean.get("kind") not in KINDS:
        clean["kind"] = "person"
    if clean.get("materials") not in ("executor", "customer"):
        clean["materials"] = "executor"
    e.contract = json.dumps(clean, ensure_ascii=False)
    if body.tariff in calc.TARIFFS:
        e.tariff = body.tariff
    db.commit()
    db.refresh(e)
    return _state(e, db)


@router.post("/estimates/{eid}/contract/design")
async def upload_design(eid: int, file: UploadFile = File(...), _: m.User = Depends(director), db: Session = Depends(get_db)):
    """Дизайн-проект (PDF) — станет Приложением № 3 со штампом на выбранных страницах."""
    e = _get(db, eid)
    data = await file.read()
    if data[:4] != b"%PDF":
        raise HTTPException(400, "Нужен PDF")
    if len(data) > 60 * 1024 * 1024:
        raise HTTPException(413, "PDF больше 60 МБ")
    p = _design_path(e.id)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)
    return _state(e, db)


@router.delete("/estimates/{eid}/contract/design")
def delete_design(eid: int, _: m.User = Depends(director), db: Session = Depends(get_db)):
    e = _get(db, eid)
    try:
        os.remove(_design_path(e.id))
    except OSError:
        pass
    return _state(e, db)


def _files(e: m.Estimate, db: Session) -> dict[str, bytes]:
    return contract.build(_res(e), e.tariff, _data(e), calc_params.contractor(db), _design(e.id))


def _download(name: str, content: bytes) -> Response:
    ext = os.path.splitext(name)[1]
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", name) or "file" + ext
    return Response(content, media_type=MIME.get(ext, "application/octet-stream"),
                    headers={"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"})


@router.get("/estimates/{eid}/contract/files")
def contract_files(eid: int, name: str | None = None, _: m.User = Depends(director), db: Session = Depends(get_db)):
    """Без name — пакет для заказчика одним zip; с name — один файл (в т. ч. «Щит для монтажника»)."""
    e = _get(db, eid)
    if name == PANEL_FILE:
        return _download(name, contract.panel_xlsx(_res(e), e.tariff))
    files = _files(e, db)
    if name:
        if name not in files:
            raise HTTPException(404, "Нет такого файла в пакете")
        return _download(name, files[name])
    num = re.sub(r"[^\w\-]+", "-", _data(e).get("number") or str(e.id))
    return _download(f"Договор_{num}.zip", contract.zip_files(files))


@router.get("/estimates/{eid}/contract/list")
def contract_list(eid: int, _: m.User = Depends(director), db: Session = Depends(get_db)):
    names = list(_files(_get(db, eid), db)) + [PANEL_FILE]
    return [{"name": n, "title": re.sub(r"_\d+-\d+.*$|_\d{4}-\d{2}.*$", "", re.sub(r"^\d+_", "", os.path.splitext(n)[0])).replace("_", " ")
             + ("" if n != PANEL_FILE else " (не для заказчика)")} for n in names]


def _doc_kind(name: str) -> str:
    if "Договор" in name:
        return "contract"
    if "Акт" in name:
        return "act"
    return "appendix"


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
        db.add(m.Document(lead_id=e.lead_id, kind=_doc_kind(name), title=(title + mark)[:300], filename=name,
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
