from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Booking, ClassSession, Membership, Plan, now_utc


MOSCOW = ZoneInfo("Europe/Moscow")
STATIC_KNOWLEDGE = """Фитнес-центр «Пульс & Баланс» — городской клуб тренировок и восстановления.
Адрес (вымышленный): Москва, ул. Примерная, 14. Телефон: +7 (495) 000-14-14.
Почта: hello@pulse-balance.example. Часы работы: пн–пт 07:00–23:00, сб–вс 08:00–22:00.
В праздничные дни 09:00–20:00; точный график уточняйте у администратора.
Вход в зал с 16 лет; до 18 лет требуется согласие законного представителя.
На групповые занятия и сеансы бассейна нужна запись. Отмена не позднее 2 часов до начала.
Срок заморозки зависит от тарифа и берётся из актуальной базы тарифов.
Продление возможно через администратора; абонемент сам не продлевается и покупка через чат не оформляется.
В бассейне обязательны шапочка, душ и сменная обувь. Дети до 16 лет не допускаются без специальной программы.
Сауна работает ежедневно 10:00–21:00 для подходящих тарифов; при плохом самочувствии посещение не рекомендуется.
Стоимость, состав тарифов, расписание и свободные места — динамические данные из инструментов, их нельзя выдумывать.
"""


def iso_utc(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") + "Z" if value else None


def utc_to_local(value: datetime) -> str:
    return value.replace(tzinfo=ZoneInfo("UTC")).astimezone(MOSCOW).isoformat(timespec="minutes")


def active_membership(db: Session, user_id: int) -> Membership | None:
    now = now_utc()
    return db.scalar(
        select(Membership)
        .where(Membership.user_id == user_id, Membership.status == "ACTIVE", Membership.starts_at <= now, Membership.ends_at > now)
        .order_by(Membership.ends_at.desc())
    )


def remaining_places(db: Session, class_id: int, capacity: int) -> int:
    item = db.get(ClassSession, class_id)
    return max(capacity - item.booked_count, 0) if item else 0


def membership_allows(db: Session, membership: Membership, service_code: str, class_id: int | None = None) -> bool:
    plan = db.get(Plan, membership.plan_id)
    if not plan or service_code not in plan.benefits.get("services", []):
        return False
    group_limit = plan.benefits.get("groups_per_30_days")
    if isinstance(group_limit, int) and service_code not in {"gym", "pool", "aqua", "sauna", "personal"} and class_id is not None:
        from .models import ClassSession, Service
        since = max(membership.starts_at, now_utc() - timedelta(days=30))
        used = db.scalar(
            select(func.count(Booking.id))
            .join(ClassSession, Booking.class_id == ClassSession.id)
            .join(Service, ClassSession.service_id == Service.id)
            .where(Booking.user_id == membership.user_id, Booking.status == "ACTIVE", ClassSession.starts_at >= since, ClassSession.starts_at < membership.ends_at, Service.code.not_in(["gym", "pool", "aqua", "sauna", "personal"]))
        ) or 0
        return used < group_limit
    pool_limit = plan.benefits.get("pool_per_30_days")
    if isinstance(pool_limit, int) and service_code in {"pool", "aqua"} and class_id is not None:
        from .models import ClassSession, Service
        since = max(membership.starts_at, now_utc() - timedelta(days=30))
        used = db.scalar(
            select(func.count(Booking.id))
            .join(ClassSession, Booking.class_id == ClassSession.id)
            .join(Service, ClassSession.service_id == Service.id)
            .where(Booking.user_id == membership.user_id, Booking.status == "ACTIVE", ClassSession.starts_at >= since, ClassSession.starts_at < membership.ends_at, Service.code.in_(["pool", "aqua"]))
        ) or 0
        return used < pool_limit
    return True


def class_payload(db: Session, item: ClassSession) -> dict:
    return {
        "id": item.id,
        "service": item.service.name,
        "service_code": item.service.code,
        "trainer": item.trainer.full_name if item.trainer else None,
        "starts_at": utc_to_local(item.starts_at),
        "ends_at": utc_to_local(item.ends_at),
        "capacity": item.capacity,
        "free_places": remaining_places(db, item.id, item.capacity),
        "status": item.status,
    }


def plan_payload(item: Plan) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "price_rub": item.price_rub,
        "duration_days": item.duration_days,
        "description": item.description,
        "benefits": item.benefits,
        "freeze_days": item.freeze_days,
        "services": item.benefits.get("services", []),
    }
