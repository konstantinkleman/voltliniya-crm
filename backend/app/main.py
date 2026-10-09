import os

from fastapi import FastAPI
from sqlalchemy import select

from . import models as m
from .auth import hash_password
from .config import settings
from .db import Base, SessionLocal, engine
from .routers import auth, crews, documents, expenses, leads, objects, stats

app = FastAPI(title="ВольтЛиния CRM", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

for r in (auth.router, leads.router, objects.router, crews.router, expenses.router, documents.router, stats.router):
    app.include_router(r)


@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    if settings.ADMIN_EMAIL and settings.ADMIN_PASSWORD:
        with SessionLocal() as db:
            if not db.scalar(select(m.User).where(m.User.email == settings.ADMIN_EMAIL.lower())):
                db.add(m.User(email=settings.ADMIN_EMAIL.lower(), name=settings.ADMIN_NAME,
                              password_hash=hash_password(settings.ADMIN_PASSWORD),
                              is_director=True, is_foreman=True))
                db.commit()


@app.get("/api/health")
def health():
    return {"ok": True}
