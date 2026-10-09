import os
import re
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import models as m
from ..auth import current_user
from ..config import settings
from ..db import get_db
from ..schemas import DocumentOut

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _check_access(db: Session, user: m.User, lead_id: int | None, object_id: int | None) -> None:
    if lead_id and not user.is_director:
        raise HTTPException(403)
    if object_id:
        o = db.get(m.WorkObject, object_id)
        if not o:
            raise HTTPException(404, "Объект не найден")
        if not user.is_director and o.foreman_id != user.id:
            raise HTTPException(403)
    if not lead_id and not object_id:
        raise HTTPException(400, "Укажите заявку или объект")


@router.post("", response_model=DocumentOut)
async def upload(file: UploadFile = File(...), kind: str = Form("other"), title: str | None = Form(None),
                 lead_id: int | None = Form(None), object_id: int | None = Form(None),
                 user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    _check_access(db, user, lead_id, object_id)
    if kind not in m.DOC_KINDS:
        kind = "other"
    data = await file.read()
    if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"Файл больше {settings.MAX_UPLOAD_MB} МБ")
    safe = re.sub(r"[^\w.\-]+", "_", file.filename or "file")
    sub = f"objects/{object_id}" if object_id else f"leads/{lead_id}"
    folder = os.path.join(settings.UPLOAD_DIR, sub)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{uuid.uuid4().hex[:8]}_{safe}")
    with open(path, "wb") as f:
        f.write(data)
    doc = m.Document(lead_id=lead_id, object_id=object_id, kind=kind, title=title or (file.filename or "Файл"),
                     filename=file.filename or safe, path=path, mime=file.content_type, size=len(data), user_id=user.id)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/{did}/file")
def download(did: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    doc = db.get(m.Document, did)
    if not doc:
        raise HTTPException(404)
    _check_access(db, user, None if doc.object_id else doc.lead_id, doc.object_id)
    return FileResponse(doc.path, media_type=doc.mime or "application/octet-stream", filename=doc.filename,
                        content_disposition_type="inline")


@router.delete("/{did}")
def delete(did: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    doc = db.get(m.Document, did)
    if not doc:
        return {"ok": True}
    if not user.is_director and doc.user_id != user.id:
        raise HTTPException(403)
    try:
        os.remove(doc.path)
    except OSError:
        pass
    db.delete(doc)
    db.commit()
    return {"ok": True}
