from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..auth import create_token, current_user, director, hash_password, verify_password
from ..config import settings
from ..db import get_db
from ..schemas import Dictionaries, Token, UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/auth/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.scalar(select(m.User).where(m.User.email == form.username.strip().lower()))
    if not user or not verify_password(form.password, user.password_hash) or not user.is_active:
        raise HTTPException(400, "Неверный e-mail или пароль")
    return Token(access_token=create_token(user))


@router.get("/me", response_model=UserOut)
def me(user: m.User = Depends(current_user)):
    return user


@router.get("/dictionaries", response_model=Dictionaries)
def dictionaries(_: m.User = Depends(current_user)):
    return Dictionaries(
        sources=m.SOURCES, lead_stages=m.LEAD_STAGES, lead_stage_names=m.LEAD_STAGE_NAMES,
        lost_reasons=m.LOST_REASONS, object_stages=m.OBJECT_STAGES, object_stage_names=m.OBJECT_STAGE_NAMES,
        tariffs=m.TARIFFS, project_kinds=m.PROJECT_KINDS, pay_methods=m.PAY_METHODS,
        expense_categories={k: {"name": v[0], "type": v[1], "channel": v[2]} for k, v in m.EXPENSE_CATEGORIES.items()},
        doc_kinds=m.DOC_KINDS, crew_share=settings.CREW_SHARE,
    )


# ---------- пользователи (директор) ----------
@router.get("/users", response_model=list[UserOut])
def list_users(_: m.User = Depends(director), db: Session = Depends(get_db)):
    return db.scalars(select(m.User).order_by(m.User.id)).all()


@router.get("/foremen", response_model=list[UserOut])
def list_foremen(_: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(m.User).where(m.User.is_foreman == True, m.User.is_active == True).order_by(m.User.name)).all()  # noqa: E712


@router.post("/users", response_model=UserOut)
def create_user(data: UserCreate, _: m.User = Depends(director), db: Session = Depends(get_db)):
    email = data.email.strip().lower()
    if db.scalar(select(m.User).where(m.User.email == email)):
        raise HTTPException(400, "Пользователь с таким e-mail уже есть")
    u = m.User(email=email, name=data.name, password_hash=hash_password(data.password), phone=data.phone,
               is_director=data.is_director, is_foreman=data.is_foreman, salary=data.salary)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@router.patch("/users/{uid}", response_model=UserOut)
def update_user(uid: int, data: UserUpdate, me_: m.User = Depends(director), db: Session = Depends(get_db)):
    u = db.get(m.User, uid)
    if not u:
        raise HTTPException(404)
    patch = data.model_dump(exclude_unset=True)
    if "password" in patch:
        u.password_hash = hash_password(patch.pop("password"))
    if uid == me_.id and patch.get("is_director") is False:
        raise HTTPException(400, "Нельзя снять права директора с себя")
    for k, v in patch.items():
        setattr(u, k, v)
    db.commit()
    db.refresh(u)
    return u
