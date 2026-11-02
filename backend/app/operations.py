from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from .business import active_membership, membership_allows
from .models import AuditLog, Booking, ClassSession, PendingAction, User, now_utc


def audit(db: Session, actor_id: int | None, action: str, target_type: str, target_id: str | int, details: dict | None = None) -> None:
    db.add(AuditLog(actor_user_id=actor_id, action=action, target_type=target_type, target_id=str(target_id), details=details or {}))


def propose_action(db: Session, user: User, action: str, target_id: int) -> PendingAction:
    if action not in {"BOOK", "CANCEL"}:
        raise HTTPException(400, "Неизвестное действие")
    target = db.get(ClassSession if action == "BOOK" else Booking, target_id)
    if not target or (action == "CANCEL" and (target.user_id != user.id or target.status != "ACTIVE")):
        raise HTTPException(404, "Объект не найден")
    pending = PendingAction(id=str(uuid4()), user_id=user.id, action=action, target_id=target_id, expires_at=now_utc() + timedelta(minutes=10))
    db.add(pending)
    db.flush()
    return pending


def book_class(db: Session, user: User, class_id: int) -> Booking:
    # Serialize this user's booking decisions before checking monthly limits.
    try:
        db.execute(update(User).where(User.id == user.id).values(full_name=User.full_name))
    except OperationalError:
        db.rollback()
        raise HTTPException(409, "Идёт другая запись. Повторите запрос")
    item = db.get(ClassSession, class_id)
    if not item or item.status != "OPEN":
        raise HTTPException(404, "Занятие не найдено")
    if item.starts_at <= now_utc():
        raise HTTPException(409, "Занятие уже началось")
    existing = db.query(Booking).filter_by(user_id=user.id, class_id=class_id).first()
    if existing and existing.status == "ACTIVE":
        raise HTTPException(409, "Вы уже записаны")
    membership = active_membership(db, user.id)
    if not membership or not membership_allows(db, membership, item.service.code, class_id):
        raise HTTPException(403, "Для записи нужен подходящий абонемент или доступный лимит")
    updated = db.execute(
        update(ClassSession)
        .where(ClassSession.id == class_id, ClassSession.booked_count < ClassSession.capacity, ClassSession.status == "OPEN")
        .values(booked_count=ClassSession.booked_count + 1)
    )
    if updated.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Свободных мест больше нет")
    if existing:
        existing.status = "ACTIVE"
        booking = existing
    else:
        booking = Booking(user_id=user.id, class_id=class_id, status="ACTIVE")
        db.add(booking)
    try:
        db.flush()
        audit(db, user.id, "BOOK_CLASS", "booking", booking.id, {"class_id": class_id})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Запись уже существует")
    return booking


def cancel_booking(db: Session, user: User, booking_id: int) -> Booking:
    try:
        db.execute(update(User).where(User.id == user.id).values(full_name=User.full_name))
    except OperationalError:
        db.rollback()
        raise HTTPException(409, "Идёт другое изменение записи. Повторите запрос")
    booking = db.get(Booking, booking_id)
    if not booking or booking.user_id != user.id:
        raise HTTPException(404, "Запись не найдена")
    if booking.status != "ACTIVE":
        raise HTTPException(409, "Запись уже отменена")
    if booking.class_session.starts_at - now_utc() < timedelta(hours=2):
        raise HTTPException(409, "Отмена возможна не позднее чем за 2 часа")
    booking.status = "CANCELLED"
    db.execute(update(ClassSession).where(ClassSession.id == booking.class_id, ClassSession.booked_count > 0).values(booked_count=ClassSession.booked_count - 1))
    audit(db, user.id, "CANCEL_BOOKING", "booking", booking.id)
    db.commit()
    return booking


def confirm_action(db: Session, user: User, action_id: str) -> dict:
    pending = db.get(PendingAction, action_id)
    if not pending or pending.user_id != user.id:
        raise HTTPException(404, "Действие не найдено")
    if pending.status != "PENDING" or pending.expires_at <= now_utc():
        raise HTTPException(409, "Подтверждение устарело")
    # A second confirmation cannot reuse the same action after commit.
    pending.status = "CONFIRMED"
    db.flush()
    if pending.action == "BOOK":
        result = book_class(db, user, pending.target_id)
        return {"status": "BOOKED", "booking_id": result.id}
    result = cancel_booking(db, user, pending.target_id)
    return {"status": "CANCELLED", "booking_id": result.id}
