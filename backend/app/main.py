from __future__ import annotations

import os
import logging
from collections import defaultdict, deque
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, NotFoundError, PermissionDeniedError, RateLimitError
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .ai import active_facts, chat_answer, client_for_saved_key, extract_and_save_memory, maybe_summarize
from .business import STATIC_KNOWLEDGE, active_membership, class_payload, iso_utc, plan_payload
from .db import Base, SessionLocal, engine, get_db
from .models import AuditLog, Booking, ClassSession, Conversation, MemoryFact, Membership, Message, Plan, Service, Trainer, User, now_utc
from .operations import audit, book_class, cancel_booking, confirm_action
from .security import delete_openai_key, hash_password, openai_key_storage_mode, read_anonymous, read_openai_key, read_user, save_openai_key, sign_anonymous, sign_user, verify_password
from .seed import seed


app = FastAPI(title="Пульс & Баланс", version="1.0")
logger = logging.getLogger(__name__)
REQUESTS: dict[tuple[str, str], deque] = defaultdict(deque)


def ai_error_detail(exc: Exception) -> tuple[int, str]:
    if isinstance(exc, AuthenticationError):
        return 502, "OpenAI отклонил API-ключ. Проверьте ключ в настройках администратора."
    if isinstance(exc, PermissionDeniedError):
        return 502, "У API-проекта нет доступа к выбранной модели. Проверьте права проекта и ключа."
    if isinstance(exc, NotFoundError):
        return 502, "Выбранная модель OpenAI недоступна для этого API-проекта."
    if isinstance(exc, RateLimitError):
        code = getattr(exc, "code", None)
        body = getattr(exc, "body", None)
        if not code and isinstance(body, dict):
            nested = body.get("error")
            code = body.get("code") or (nested.get("code") if isinstance(nested, dict) else None)
        if code == "insufficient_quota":
            return 502, "На API-проекте OpenAI исчерпан баланс или лимит расходов. Проверьте оплату и лимиты в OpenAI Platform."
        return 503, "OpenAI ограничил частоту запросов. Подождите немного и повторите попытку."
    if isinstance(exc, APITimeoutError):
        return 503, "OpenAI не ответил вовремя. Повторите попытку позже."
    if isinstance(exc, APIConnectionError):
        return 503, "Сервер не может подключиться к OpenAI. Проверьте исходящий доступ к api.openai.com."
    if isinstance(exc, APIStatusError):
        return 502, f"OpenAI вернул ошибку HTTP {exc.status_code}. Проверьте настройки API-проекта."
    return 502, "Сервис AI временно недоступен. Сообщение сохранено, попробуйте ещё раз позже."


@app.exception_handler(RequestValidationError)
async def safe_validation_error(_request: Request, exc: RequestValidationError):
    # FastAPI includes submitted values by default; never echo passwords or API keys.
    issues = [{k: v for k, v in issue.items() if k not in {"input", "ctx"}} for issue in exc.errors()]
    return JSONResponse({"detail": issues}, status_code=422)


@app.on_event("startup")
def startup() -> None:
    if os.getenv("VERCEL") == "1":
        # The persistent database is prepared before deployment, not on every cold start.
        return
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
        cutoff = now_utc() - timedelta(hours=24)
        expired = list(db.scalars(select(Conversation.id).where(Conversation.user_id.is_(None), Conversation.created_at < cutoff)))
        if expired:
            db.execute(delete(Message).where(Message.conversation_id.in_(expired)))
            db.execute(delete(Conversation).where(Conversation.id.in_(expired)))
            db.commit()


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(503, "База данных временно недоступна")
    return {"status": "ok", "database": engine.dialect.name}


@app.middleware("http")
async def protections(request: Request, call_next):
    path = request.url.path
    if request.method not in {"GET", "HEAD", "OPTIONS"} and path.startswith("/api/"):
        origin = request.headers.get("origin")
        if origin:
            allowed = {f"{request.url.scheme}://{request.headers.get('host', '')}", "http://localhost:5173", "http://127.0.0.1:5173"}
            if origin not in allowed:
                return JSONResponse({"detail": "Недопустимый источник запроса"}, status_code=403)
    if path in {"/api/auth/login", "/api/chat"}:
        key = (request.client.host if request.client else "local", path)
        bucket = REQUESTS[key]
        now = now_utc().timestamp()
        while bucket and now - bucket[0] > 60:
            bucket.popleft()
        limit = 10 if path.endswith("login") else 30
        if len(bucket) >= limit:
            return JSONResponse({"detail": "Слишком много запросов. Подождите минуту."}, status_code=429)
        bucket.append(now)
    anon_id = read_anonymous(request.cookies.get("fitness_anonymous"))
    if not anon_id:
        anon_id = str(uuid4())
        request.state.new_anonymous = True
    request.state.anonymous_id = anon_id
    response = await call_next(request)
    if getattr(request.state, "new_anonymous", False):
        response.set_cookie("fitness_anonymous", sign_anonymous(anon_id), httponly=True, secure=os.getenv("FITNESS_SECURE_COOKIES") == "1", samesite="lax", max_age=86400)
    response.headers["Cache-Control"] = "no-store"
    return response


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user_id = read_user(request.cookies.get("fitness_session"))
    return db.get(User, user_id) if user_id else None


def require_user(user: User | None = Depends(current_user)) -> User:
    if not user:
        raise HTTPException(401, "Требуется вход")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != "ADMIN":
        raise HTTPException(403, "Только для администратора")
    return user


def owner_conversation(db: Session, request: Request, user: User | None, conversation_id: int) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(404, "Диалог не найден")
    allowed = conversation.user_id == user.id if user else conversation.user_id is None and conversation.anonymous_id == request.state.anonymous_id
    if not allowed:
        raise HTTPException(404, "Диалог не найден")
    return conversation


def user_payload(user: User) -> dict:
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role, "created_at": iso_utc(user.created_at)}


def membership_payload(m: Membership) -> dict:
    return {"id": m.id, "plan": plan_payload(m.plan), "starts_at": iso_utc(m.starts_at), "ends_at": iso_utc(m.ends_at), "status": m.status}


def fact_payload(f: MemoryFact) -> dict:
    return {"id": f.id, "category": f.category, "key": f.fact_key, "value": f.value, "source": f.source, "status": f.status, "created_at": iso_utc(f.created_at), "updated_at": iso_utc(f.updated_at)}


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class Registration(Credentials):
    full_name: str = Field(min_length=2, max_length=120)


class ChatInput(BaseModel):
    conversation_id: int | None = None
    message: str = Field(min_length=1, max_length=4000)


class MemoryInput(BaseModel):
    category: str = Field(max_length=40)
    key: str = Field(max_length=80)
    value: str = Field(min_length=1, max_length=500)


class ProfileUpdate(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)


class MembershipCreate(BaseModel):
    plan_id: int
    duration_days: int = Field(default=30, ge=1, le=365)


class ClassCreate(BaseModel):
    service_id: int
    trainer_id: int | None = None
    starts_at: str
    capacity: int = Field(ge=1, le=100)


class ClassUpdate(BaseModel):
    capacity: int = Field(ge=1, le=100)
    status: str


class PlanUpdate(BaseModel):
    price_rub: int = Field(ge=0, le=100000)
    description: str = Field(min_length=5, max_length=1000)
    active: bool = True


@app.get("/api/public/info")
def public_info():
    return {"name": "Пульс & Баланс", "knowledge": STATIC_KNOWLEDGE}


@app.get("/api/plans")
def plans(db: Session = Depends(get_db)):
    return [plan_payload(p) for p in db.scalars(select(Plan).where(Plan.active == True).order_by(Plan.price_rub))]


@app.get("/api/services")
def services(db: Session = Depends(get_db)):
    return [{"id": s.id, "code": s.code, "name": s.name, "description": s.description, "price_rub": s.price_rub, "duration_minutes": s.duration_minutes, "requires_booking": s.requires_booking} for s in db.scalars(select(Service).order_by(Service.id))]


@app.get("/api/trainers")
def trainers(db: Session = Depends(get_db)):
    return [{"id": t.id, "full_name": t.full_name, "specialty": t.specialty} for t in db.scalars(select(Trainer).order_by(Trainer.id))]


@app.get("/api/schedule")
def schedule(service_code: str | None = None, limit: int = 60, db: Session = Depends(get_db)):
    query = select(ClassSession).where(ClassSession.starts_at > now_utc(), ClassSession.status == "OPEN").order_by(ClassSession.starts_at).limit(min(max(limit, 1), 100))
    if service_code:
        query = query.join(Service).where(Service.code == service_code)
    return [class_payload(db, item) for item in db.scalars(query)]


@app.post("/api/auth/register", status_code=201)
def register(data: Registration, response: Response, db: Session = Depends(get_db)):
    email = data.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "Этот email уже зарегистрирован")
    user = User(email=email, full_name=data.full_name.strip(), password_hash=hash_password(data.password), role="CLIENT")
    db.add(user)
    db.flush()
    audit(db, user.id, "REGISTER", "user", user.id)
    db.commit()
    response.set_cookie("fitness_session", sign_user(user.id), httponly=True, secure=os.getenv("FITNESS_SECURE_COOKIES") == "1", samesite="lax", max_age=7 * 86400)
    return user_payload(user)


@app.post("/api/auth/login")
def login(data: Credentials, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email.strip().lower()))
    if not user or not verify_password(user.password_hash, data.password):
        raise HTTPException(401, "Неверный email или пароль")
    audit(db, user.id, "LOGIN", "user", user.id)
    db.commit()
    response.set_cookie("fitness_session", sign_user(user.id), httponly=True, secure=os.getenv("FITNESS_SECURE_COOKIES") == "1", samesite="lax", max_age=7 * 86400)
    return user_payload(user)


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie("fitness_session")
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: User | None = Depends(current_user)):
    return {"user": user_payload(user) if user else None}


@app.get("/api/membership")
def my_membership(user: User = Depends(require_user), db: Session = Depends(get_db)):
    membership = active_membership(db, user.id)
    return {"membership": membership_payload(membership) if membership else None}


@app.get("/api/bookings")
def my_bookings(user: User = Depends(require_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Booking).where(Booking.user_id == user.id).order_by(Booking.id.desc()).limit(100))
    return [{"id": b.id, "status": b.status, "class": class_payload(db, b.class_session)} for b in rows]


@app.post("/api/bookings", status_code=201)
def create_booking(data: dict, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        class_id = int(data["class_id"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(422, "Укажите class_id")
    booking = book_class(db, user, class_id)
    return {"id": booking.id, "status": booking.status}


@app.delete("/api/bookings/{booking_id}")
def delete_booking(booking_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    booking = cancel_booking(db, user, booking_id)
    return {"id": booking.id, "status": booking.status}


@app.post("/api/actions/{action_id}/confirm")
def confirm(action_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    return confirm_action(db, user, action_id)


@app.post("/api/conversations", status_code=201)
def create_conversation(request: Request, user: User | None = Depends(current_user), db: Session = Depends(get_db)):
    conversation = Conversation(user_id=user.id if user else None, anonymous_id=None if user else request.state.anonymous_id)
    db.add(conversation)
    db.commit()
    return {"id": conversation.id, "title": conversation.title}


@app.get("/api/conversations")
def conversations(request: Request, user: User | None = Depends(current_user), db: Session = Depends(get_db)):
    query = select(Conversation).where(Conversation.user_id == user.id) if user else select(Conversation).where(Conversation.user_id.is_(None), Conversation.anonymous_id == request.state.anonymous_id)
    return [{"id": c.id, "title": c.title, "created_at": iso_utc(c.created_at), "updated_at": iso_utc(c.updated_at)} for c in db.scalars(query.order_by(Conversation.updated_at.desc()).limit(50))]


@app.get("/api/conversations/{conversation_id}")
def conversation_detail(conversation_id: int, request: Request, user: User | None = Depends(current_user), db: Session = Depends(get_db)):
    conversation = owner_conversation(db, request, user, conversation_id)
    messages = db.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id))
    return {"id": conversation.id, "title": conversation.title, "messages": [{"id": m.id, "role": m.role, "content": m.content, "created_at": iso_utc(m.created_at)} for m in messages]}


@app.post("/api/chat")
def chat(data: ChatInput, request: Request, user: User | None = Depends(current_user), db: Session = Depends(get_db)):
    try:
        if not read_openai_key():
            raise HTTPException(503, "Консультант пока не подключён. Администратор может добавить ключ OpenAI в настройках.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Системное хранилище ключей недоступно")
    if data.conversation_id:
        conversation = owner_conversation(db, request, user, data.conversation_id)
    else:
        conversation = Conversation(user_id=user.id if user else None, anonymous_id=None if user else request.state.anonymous_id, title=data.message[:80])
        db.add(conversation)
        db.flush()
    message = Message(conversation_id=conversation.id, role="user", content=data.message.strip())
    db.add(message)
    conversation.updated_at = now_utc()
    db.flush()
    history = list(db.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id)))
    try:
        answer, actions = chat_answer(db, user, conversation, history)
    except Exception as exc:
        db.rollback()
        status, detail = ai_error_detail(exc)
        logger.warning("AI request failed: exception=%s status=%s", type(exc).__name__, getattr(exc, "status_code", "transport"))
        raise HTTPException(status, detail)
    db.add(Message(conversation_id=conversation.id, role="assistant", content=answer))
    conversation.updated_at = now_utc()
    db.commit()
    remembered = []
    if user and user.role == "CLIENT":
        try:
            remembered = extract_and_save_memory(db, user, message)
        except Exception:
            db.rollback()
    try:
        maybe_summarize(db, conversation)
    except Exception:
        db.rollback()
    return {"conversation_id": conversation.id, "answer": answer, "actions": actions, "remembered": remembered}


@app.get("/api/memory")
def memory(user: User = Depends(require_user), db: Session = Depends(get_db)):
    return [fact_payload(f) for f in active_facts(db, user.id)]


@app.put("/api/memory")
def upsert_memory(data: MemoryInput, user: User = Depends(require_user), db: Session = Depends(get_db)):
    from .ai import ALLOWED_MEMORY
    if data.key not in ALLOWED_MEMORY.get(data.category, set()):
        raise HTTPException(422, "Недопустимый тип предпочтения")
    fact = db.scalar(select(MemoryFact).where(MemoryFact.user_id == user.id, MemoryFact.category == data.category, MemoryFact.fact_key == data.key))
    if fact:
        fact.value, fact.status, fact.updated_at, fact.source = data.value, "ACTIVE", now_utc(), "USER_EDIT"
    else:
        fact = MemoryFact(user_id=user.id, category=data.category, fact_key=data.key, value=data.value, source="USER_EDIT")
        db.add(fact)
    db.flush()
    audit(db, user.id, "MEMORY_UPSERT", "memory_fact", fact.id, {"category": data.category, "key": data.key})
    db.commit()
    return fact_payload(fact)


@app.delete("/api/memory/{fact_id}")
def delete_memory(fact_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    fact = db.get(MemoryFact, fact_id)
    if not fact or fact.user_id != user.id:
        raise HTTPException(404, "Факт не найден")
    fact.status = "DELETED"
    fact.updated_at = now_utc()
    audit(db, user.id, "MEMORY_DELETE", "memory_fact", fact.id)
    db.commit()
    return {"ok": True}


@app.get("/api/admin/key")
def key_status(admin: User = Depends(require_admin)):
    storage = openai_key_storage_mode()
    return {"configured": storage is not None, "storage": storage}


@app.put("/api/admin/key")
async def set_key(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        body = await request.json()
        candidate = body.get("api_key")
    except (ValueError, AttributeError):
        raise HTTPException(422, "Некорректный запрос")
    if not isinstance(candidate, str) or not 24 <= len(candidate) <= 300:
        raise HTTPException(422, "Некорректный формат ключа")
    try:
        storage = save_openai_key(candidate)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception:
        raise HTTPException(503, "Не удалось сохранить ключ в системном хранилище")
    audit(db, admin.id, "OPENAI_KEY_SET", "settings", "openai")
    db.commit()
    return {"configured": True, "storage": storage}


@app.delete("/api/admin/key")
def remove_key(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        delete_openai_key()
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except Exception:
        raise HTTPException(503, "Не удалось удалить ключ")
    audit(db, admin.id, "OPENAI_KEY_DELETE", "settings", "openai")
    db.commit()
    return {"configured": False, "storage": None}


@app.get("/api/admin/users")
def admin_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [user_payload(u) for u in db.scalars(select(User).order_by(User.id))]


@app.patch("/api/admin/users/{user_id}")
def admin_update_user(user_id: int, data: ProfileUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Клиент не найден")
    user.full_name = data.full_name.strip()
    audit(db, admin.id, "USER_UPDATE", "user", user_id)
    db.commit()
    return user_payload(user)


@app.get("/api/admin/users/{user_id}/memory")
def admin_user_memory(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not db.get(User, user_id):
        raise HTTPException(404, "Клиент не найден")
    return [fact_payload(f) for f in active_facts(db, user_id)]


@app.delete("/api/admin/users/{user_id}/memory/{fact_id}")
def admin_delete_memory(user_id: int, fact_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    fact = db.get(MemoryFact, fact_id)
    if not fact or fact.user_id != user_id:
        raise HTTPException(404, "Факт не найден")
    fact.status, fact.updated_at = "DELETED", now_utc()
    audit(db, admin.id, "ADMIN_MEMORY_DELETE", "memory_fact", fact_id, {"user_id": user_id})
    db.commit()
    return {"ok": True}


@app.put("/api/admin/users/{user_id}/memory")
def admin_upsert_memory(user_id: int, data: MemoryInput, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    from .ai import ALLOWED_MEMORY
    if not db.get(User, user_id):
        raise HTTPException(404, "Клиент не найден")
    if data.key not in ALLOWED_MEMORY.get(data.category, set()):
        raise HTTPException(422, "Недопустимый тип предпочтения")
    fact = db.scalar(select(MemoryFact).where(MemoryFact.user_id == user_id, MemoryFact.category == data.category, MemoryFact.fact_key == data.key))
    if fact:
        fact.value, fact.status, fact.updated_at, fact.source = data.value, "ACTIVE", now_utc(), "ADMIN_EDIT"
    else:
        fact = MemoryFact(user_id=user_id, category=data.category, fact_key=data.key, value=data.value, source="ADMIN_EDIT")
        db.add(fact)
    db.flush()
    audit(db, admin.id, "ADMIN_MEMORY_UPSERT", "memory_fact", fact.id, {"user_id": user_id})
    db.commit()
    return fact_payload(fact)


@app.post("/api/admin/users/{user_id}/memberships", status_code=201)
def admin_add_membership(user_id: int, data: MembershipCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user, plan = db.get(User, user_id), db.get(Plan, data.plan_id)
    if not user or user.role != "CLIENT" or not plan:
        raise HTTPException(404, "Клиент или тариф не найден")
    if active_membership(db, user_id):
        raise HTTPException(409, "У клиента уже есть действующий абонемент")
    membership = Membership(user_id=user_id, plan_id=plan.id, starts_at=now_utc(), ends_at=now_utc() + timedelta(days=data.duration_days), status="ACTIVE")
    db.add(membership)
    db.flush()
    audit(db, admin.id, "MEMBERSHIP_CREATE", "membership", membership.id, {"user_id": user_id, "plan_id": plan.id})
    db.commit()
    return membership_payload(membership)


@app.patch("/api/admin/plans/{plan_id}")
def admin_update_plan(plan_id: int, data: PlanUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    plan = db.get(Plan, plan_id)
    if not plan:
        raise HTTPException(404, "Тариф не найден")
    plan.price_rub, plan.description, plan.active = data.price_rub, data.description, data.active
    audit(db, admin.id, "PLAN_UPDATE", "plan", plan.id)
    db.commit()
    return plan_payload(plan)


@app.post("/api/admin/classes", status_code=201)
def admin_create_class(data: ClassCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    from datetime import datetime, timezone
    service = db.get(Service, data.service_id)
    trainer = db.get(Trainer, data.trainer_id) if data.trainer_id else None
    if not service or (data.trainer_id and not trainer):
        raise HTTPException(404, "Услуга или тренер не найдены")
    try:
        parsed = datetime.fromisoformat(data.starts_at)
        if parsed.tzinfo is None:
            raise ValueError()
        start = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(422, "Укажите starts_at с часовым поясом")
    if start <= now_utc():
        raise HTTPException(422, "Занятие должно быть в будущем")
    item = ClassSession(service_id=service.id, trainer_id=trainer.id if trainer else None, starts_at=start, ends_at=start + timedelta(minutes=service.duration_minutes), capacity=data.capacity)
    db.add(item)
    db.flush()
    audit(db, admin.id, "CLASS_CREATE", "class_session", item.id)
    db.commit()
    return class_payload(db, item)


@app.patch("/api/admin/classes/{class_id}")
def admin_update_class(class_id: int, data: ClassUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.get(ClassSession, class_id)
    if not item:
        raise HTTPException(404, "Занятие не найдено")
    if data.status not in {"OPEN", "CANCELLED"}:
        raise HTTPException(422, "Недопустимый статус")
    if data.capacity < item.booked_count:
        raise HTTPException(409, "Вместимость меньше числа активных записей")
    if data.status == "CANCELLED" and item.booked_count:
        raise HTTPException(409, "Сначала отмените активные записи")
    item.capacity, item.status = data.capacity, data.status
    audit(db, admin.id, "CLASS_UPDATE", "class_session", item.id)
    db.commit()
    return class_payload(db, item)


@app.get("/api/admin/audit")
def admin_audit(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(100))
    return [{"id": a.id, "actor_user_id": a.actor_user_id, "action": a.action, "target_type": a.target_type, "target_id": a.target_id, "details": a.details, "created_at": iso_utc(a.created_at)} for a in rows]


FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
