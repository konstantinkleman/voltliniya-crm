import mimetypes
import os
import re
import shutil
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..auth import director
from ..config import settings
from ..db import get_db
from ..schemas import ExpenseIn, ExpenseOut

router = APIRouter(prefix="/api/expenses", tags=["expenses"])


def _out(e: m.Expense) -> ExpenseOut:
    o = ExpenseOut.model_validate(e)
    o.foreman_name = e.foreman.name if e.foreman else None
    o.crew_name = e.crew.name if e.crew else None
    return o


@router.get("", response_model=list[ExpenseOut])
def list_expenses(month: str | None = None, category: str | None = None, crew_id: int | None = None,
                  _: m.User = Depends(director), db: Session = Depends(get_db)):
    qs = select(m.Expense).order_by(m.Expense.date.desc(), m.Expense.id.desc())
    if month:
        y, mo = map(int, month.split("-"))
        start = date(y, mo, 1)
        end = date(y + mo // 12, mo % 12 + 1, 1)
        qs = qs.where(m.Expense.date >= start, m.Expense.date < end)
    if category:
        qs = qs.where(m.Expense.category == category)
    if crew_id:
        qs = qs.where(m.Expense.crew_id == crew_id)
    return [_out(e) for e in db.scalars(qs).all()]


@router.post("", response_model=ExpenseOut)
def create_expense(data: ExpenseIn, user: m.User = Depends(director), db: Session = Depends(get_db)):
    cat = m.EXPENSE_CATEGORIES.get(data.category)
    if not cat:
        raise HTTPException(400, "Неизвестная категория")
    if data.category == "salary" and not data.foreman_id:
        raise HTTPException(400, "Для зарплаты укажите прораба")
    if data.crew_id and not db.get(m.Crew, data.crew_id):
        raise HTTPException(400, "Бригада не найдена")
    e = m.Expense(**data.model_dump(), channel=cat[2], user_id=user.id)
    if e.category == "salary" and not e.period:
        e.period = e.date.strftime("%Y-%m")
    db.add(e)
    db.commit()
    db.refresh(e)
    return _out(e)


@router.get("/autoload")
def autoload_status(_: m.User = Depends(director)):
    """Состояние автозагрузки рекламных расходов: какие каналы подключены, когда и чем закончилась загрузка."""
    from .. import adspend
    ch = {}
    for key, (name, configured, _fn) in adspend.CHANNELS.items():
        ch[key] = {"name": name, "configured": configured(), **adspend.status["channels"].get(key, {})}
    return {"last_run": adspend.status["last_run"], "running": adspend._lock.locked(), "channels": ch,
            "every_hours": adspend.SYNC_EVERY_SECONDS // 3600, "days": adspend.SYNC_DAYS}


@router.post("/autoload")
def autoload_run(days: int = 7, _: m.User = Depends(director)):
    """Загрузить расходы сейчас (в фоне — Директ может строить отчёт до нескольких минут)."""
    import threading
    from .. import adspend
    days = max(1, min(days, 180))
    if not adspend._lock.locked():
        threading.Thread(target=adspend.sync_all, args=(days,), daemon=True).start()
    return {"ok": True}


class ExpenseUpsert(BaseModel):
    date: date
    amount: Decimal
    category: str
    external_ref: str
    note: str | None = None


@router.post("/upsert")
def upsert_expense(data: ExpenseUpsert, _: m.User = Depends(director), db: Session = Depends(get_db)):
    """Создать или обновить расход по ключу источника — для сборщиков, которые работают из браузера директора
    (Профи: месячная сумма откликов за вычетом возвратов). Повтор с тем же external_ref обновляет сумму."""
    from .. import adspend
    cat = m.EXPENSE_CATEGORIES.get(data.category)
    if not cat or cat[1] != "channel":
        raise HTTPException(400, "Категория должна быть рекламным каналом")
    if data.amount < 0:
        raise HTTPException(400, "Сумма не может быть отрицательной")
    ref = data.external_ref.strip()[:120]
    if not ref:
        raise HTTPException(400, "Нужен external_ref")
    what = adspend.upsert_expense(db, ref=ref, day=data.date, amount=data.amount, category=data.category,
                                  note=(data.note or f"{cat[0]} · автозагрузка")[:500])
    db.commit()
    return {"ok": True, "result": what}


# ---------- состав расхода: что за закупка и что покупалось ----------

def file_dir(e: m.Expense | None = None, batch: str | None = None) -> str:
    """Папка файла расхода: накладная прихода — по batch (общая для склада и расходов), иначе — по id расхода."""
    batch = batch or (e.stock_batch if e else None)
    if batch:
        return os.path.join(settings.UPLOAD_DIR, "receipts", re.sub(r"[^\w-]", "", batch))
    return os.path.join(settings.UPLOAD_DIR, "expenses", str(e.id))


def file_info(folder: str) -> tuple[str, str] | None:
    """(путь, исходное имя) единственного файла в папке."""
    try:
        names = sorted(n for n in os.listdir(folder) if not n.startswith("."))
    except OSError:
        return None
    return (os.path.join(folder, names[0]), names[0]) if names else None


async def save_file(folder: str, file: UploadFile) -> None:
    data = await file.read()
    if not data:
        raise HTTPException(400, "Пустой файл")
    if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, "Файл слишком большой")
    name = re.sub(r"[^\w.\-]+", "_", os.path.basename(file.filename or "")).strip("._") or "nakladnaya"
    if "." not in name:
        name += mimetypes.guess_extension(file.content_type or "") or ""
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name[-120:]), "wb") as f:
        f.write(data)


def _note_parts(note: str | None) -> tuple[str | None, str | None]:
    """«Закупка материалов · Поставщик · накладная 123» → (поставщик, номер)."""
    parts = [p.strip() for p in (note or "").split(" · ")]
    if not parts or parts[0] != "Закупка материалов":
        return None, None
    doc = next((p[len("накладная "):] for p in parts[1:] if p.startswith("накладная ")), None)
    sup = next((p for p in parts[1:] if not p.startswith("накладная ")), None)
    return sup, doc


def _guess_batch(db: Session, e: m.Expense) -> str | None:
    """Расходы, записанные до появления связи: ищем приход того же дня с той же суммой (и поставщиком/накладной из комментария)."""
    rows = db.scalars(select(m.StockMovement).where(m.StockMovement.kind == "receipt", m.StockMovement.date == e.date,
                                                    m.StockMovement.batch.is_not(None))).all()
    groups: dict[str, list[m.StockMovement]] = {}
    for mv in rows:
        groups.setdefault(mv.batch, []).append(mv)
    used = set(db.scalars(select(m.Expense.stock_batch).where(m.Expense.stock_batch.is_not(None), m.Expense.id != e.id)).all())
    sup, doc = _note_parts(e.note)
    cands = []
    for b, mvs in groups.items():
        if b in used:
            continue
        total = sum((Decimal(mv.qty) * Decimal(mv.unit_cost) for mv in mvs), Decimal(0))
        if abs(total - Decimal(e.amount)) > Decimal("0.05"):
            continue
        if (mvs[0].supplier or None) != sup or (mvs[0].doc_number or None) != doc:
            continue
        cands.append(b)
    return cands[0] if len(cands) == 1 else None


def _receipt(db: Session, batch: str) -> dict | None:
    mvs = db.scalars(select(m.StockMovement).where(m.StockMovement.batch == batch, m.StockMovement.kind == "receipt")
                     .order_by(m.StockMovement.id)).all()
    if not mvs:
        return None
    lines = []
    for mv in mvs:
        p = mv.product
        lines.append({"product_id": mv.product_id, "name": p.name if p else f"Позиция {mv.product_id}",
                      "category": p.category.name if p and getattr(p, "category", None) else None,
                      "unit": p.unit if p else "", "qty": mv.qty, "unit_cost": mv.unit_cost,
                      "sum": (Decimal(mv.qty) * Decimal(mv.unit_cost)).quantize(Decimal("0.01"))})
    f = mvs[0]
    return {"batch": batch, "date": f.date, "supplier": f.supplier, "doc_number": f.doc_number,
            "warehouse_id": f.warehouse_id, "warehouse_name": f.warehouse.name if f.warehouse else "",
            "note": f.note, "user_name": f.user.name if f.user else None, "lines": lines,
            "total": sum((l["sum"] for l in lines), Decimal(0))}


def _get(db: Session, eid: int) -> m.Expense:
    e = db.get(m.Expense, eid)
    if not e:
        raise HTTPException(404, "Расход не найден")
    return e


@router.get("/{eid}/details")
def expense_details(eid: int, _: m.User = Depends(director), db: Session = Depends(get_db)):
    """Раскрытый расход: кто и когда внёс, а для закупки материалов — приход на склад: поставщик, накладная, позиции."""
    e = _get(db, eid)
    if e.category == "materials" and not e.stock_batch:
        b = _guess_batch(db, e)
        if b:
            e.stock_batch = b
            db.commit()
    rec = _receipt(db, e.stock_batch) if e.stock_batch else None
    fi = file_info(file_dir(e))
    author = db.get(m.User, e.user_id) if e.user_id else None
    cat = m.EXPENSE_CATEGORIES.get(e.category)
    return {"expense": _out(e), "category_name": cat[0] if cat else e.category, "user_name": author.name if author else None,
            "method_name": m.PAY_METHODS.get(e.method, e.method) if e.method else None,
            "receipt": rec, "file": {"name": fi[1], "size": os.path.getsize(fi[0])} if fi else None}


@router.get("/{eid}/file")
def expense_file(eid: int, _: m.User = Depends(director), db: Session = Depends(get_db)):
    fi = file_info(file_dir(_get(db, eid)))
    if not fi:
        raise HTTPException(404, "Файл не прикреплён")
    return FileResponse(fi[0], media_type=mimetypes.guess_type(fi[1])[0] or "application/octet-stream", filename=fi[1],
                        content_disposition_type="inline")


@router.post("/{eid}/file")
async def expense_file_upload(eid: int, file: UploadFile = File(...), _: m.User = Depends(director), db: Session = Depends(get_db)):
    """Фото/PDF накладной или чека к расходу (заменяет прежний файл)."""
    await save_file(file_dir(_get(db, eid)), file)
    return expense_details(eid, _, db)


@router.delete("/{eid}/file")
def expense_file_delete(eid: int, _: m.User = Depends(director), db: Session = Depends(get_db)):
    shutil.rmtree(file_dir(_get(db, eid)), ignore_errors=True)
    return expense_details(eid, _, db)


@router.delete("/{eid}")
def delete_expense(eid: int, _: m.User = Depends(director), db: Session = Depends(get_db)):
    e = db.get(m.Expense, eid)
    if e:
        if not e.stock_batch:
            shutil.rmtree(file_dir(e), ignore_errors=True)
        db.delete(e)
        db.commit()
    return {"ok": True}
