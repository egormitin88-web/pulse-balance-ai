from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.orm import Session

from .business import MOSCOW
from .models import Booking, ClassSession, Conversation, MemoryFact, Membership, Message, Plan, Service, Trainer, User, now_utc


DEMO_USERS = [
    ("anna@demo.pulsebalance.ru", "Анна Соколова", "Баланс", "training", "favorite_class", "йога"),
    ("boris@demo.pulsebalance.ru", "Борис Орлов", "Премиум", "goal", "fitness_goal", "силовые тренировки"),
    ("vera@demo.pulsebalance.ru", "Вера Миронова", "Старт", "budget", "monthly_budget_rub", "3500"),
    ("gleb@demo.pulsebalance.ru", "Глеб Кузнецов", "Актив", "training", "favorite_class", "плавание"),
    ("dina@demo.pulsebalance.ru", "Дина Белова", None, "schedule", "preferred_time", "вечер"),
]


def seed(db: Session) -> None:
    if db.scalar(select(User.id).limit(1)) is not None:
        return
    ph = PasswordHasher()
    plans = [
        Plan(name="Старт", price_rub=2900, duration_days=30, description="Зал по будням до 17:00", benefits={"gym": "будни 07:00–17:00", "groups_per_30_days": 0, "pool_per_30_days": 0, "services": ["gym"]}, freeze_days=0),
        Plan(name="Баланс", price_rub=4900, duration_days=30, description="Зал без ограничения по времени и 4 групповых занятия", benefits={"gym": "ежедневно", "groups_per_30_days": 4, "pool_per_30_days": 0, "services": ["gym", "yoga", "pilates", "boxing", "functional", "stretch", "dance"]}, freeze_days=7),
        Plan(name="Актив", price_rub=6900, duration_days=30, description="Зал, групповые занятия без лимита, бассейн 8 раз", benefits={"gym": "ежедневно", "groups_per_30_days": "безлимит", "pool_per_30_days": 8, "sauna": True, "services": ["gym", "yoga", "pilates", "boxing", "functional", "stretch", "dance", "pool", "aqua", "sauna"]}, freeze_days=14),
        Plan(name="Премиум", price_rub=9900, duration_days=30, description="Все зоны без лимита и одна персональная тренировка", benefits={"gym": "ежедневно", "groups_per_30_days": "безлимит", "pool_per_30_days": "безлимит", "sauna": True, "personal_per_30_days": 1, "services": ["gym", "yoga", "pilates", "boxing", "functional", "stretch", "dance", "pool", "aqua", "sauna", "personal"]}, freeze_days=30),
    ]
    db.add_all(plans)
    services = [
        Service(code="gym", name="Тренажёрный зал", description="Кардио и силовая зоны, самостоятельные тренировки", price_rub=700, duration_minutes=120, requires_booking=False),
        Service(code="yoga", name="Йога", description="Мягкая практика и дыхание", price_rub=800, duration_minutes=60, requires_booking=True),
        Service(code="pilates", name="Пилатес", description="Контроль движения и работа с корпусом", price_rub=800, duration_minutes=60, requires_booking=True),
        Service(code="boxing", name="Бокс", description="Техника и выносливость", price_rub=900, duration_minutes=60, requires_booking=True),
        Service(code="functional", name="Функциональный тренинг", description="Силовая и кардио нагрузка", price_rub=900, duration_minutes=60, requires_booking=True),
        Service(code="stretch", name="Растяжка", description="Мобильность и восстановление", price_rub=700, duration_minutes=60, requires_booking=True),
        Service(code="dance", name="Танцы", description="Танцевальная фитнес программа", price_rub=800, duration_minutes=60, requires_booking=True),
        Service(code="pool", name="Свободное плавание", description="Сеанс бассейна по записи", price_rub=900, duration_minutes=60, requires_booking=True),
        Service(code="aqua", name="Аквааэробика", description="Групповое занятие в бассейне", price_rub=950, duration_minutes=45, requires_booking=True),
        Service(code="sauna", name="Сауна", description="Зона восстановления 10:00–21:00", price_rub=600, duration_minutes=30, requires_booking=False),
        Service(code="personal", name="Персональная тренировка", description="Индивидуальная работа с тренером по согласованию", price_rub=2500, duration_minutes=60, requires_booking=True),
    ]
    db.add_all(services)
    trainers = [
        Trainer(full_name="Мария Лебедева", specialty="йога, пилатес, растяжка"),
        Trainer(full_name="Илья Романов", specialty="бокс, функциональный тренинг"),
        Trainer(full_name="Ольга Сергеева", specialty="танцы, аквааэробика"),
    ]
    db.add_all(trainers)
    users = []
    for email, name, *_ in DEMO_USERS:
        user = User(email=email, full_name=name, password_hash=ph.hash("Demo2026!"), role="CLIENT")
        users.append(user)
        db.add(user)
    db.add(User(email="admin@demo.pulsebalance.ru", full_name="Администратор", password_hash=ph.hash("Admin2026!"), role="ADMIN"))
    db.flush()

    for index, (_, _, plan_name, category, key, value) in enumerate(DEMO_USERS):
        user = users[index]
        if plan_name:
            plan = next(p for p in plans if p.name == plan_name)
            db.add(Membership(user_id=user.id, plan_id=plan.id, starts_at=now_utc() - timedelta(days=5), ends_at=now_utc() + timedelta(days=25), status="ACTIVE"))
        db.add(MemoryFact(user_id=user.id, category=category, fact_key=key, value=value, source="DEMO_SEED"))
        db.add(MemoryFact(user_id=user.id, category="schedule", fact_key="preferred_days", value=["вторник", "четверг", "суббота", "понедельник", "среда"][index], source="DEMO_SEED"))
        conversation = Conversation(user_id=user.id, title="Знакомство с клубом")
        db.add(conversation)
        db.flush()
        db.add_all([
            Message(conversation_id=conversation.id, role="user", content=f"Мне подходит {value}. Что посоветуете?"),
            Message(conversation_id=conversation.id, role="assistant", content="Учту это при подборе занятий и абонемента."),
        ])

    service_by_code = {s.code: s for s in services}
    schedule = [
        (0, 9, 0, "pool", None, 12), (0, 19, 0, "yoga", 0, 14),
        (1, 8, 0, "pilates", 0, 14), (1, 18, 30, "boxing", 1, 12), (1, 20, 0, "pool", None, 12),
        (2, 9, 0, "aqua", 2, 10), (2, 19, 0, "functional", 1, 16),
        (3, 8, 0, "yoga", 0, 14), (3, 18, 30, "dance", 2, 16), (3, 20, 0, "pool", None, 12),
        (4, 19, 0, "boxing", 1, 12), (4, 20, 0, "stretch", 0, 14),
        (5, 10, 0, "pool", None, 12), (5, 11, 30, "pilates", 0, 14), (5, 13, 0, "aqua", 2, 10),
        (6, 10, 0, "functional", 1, 16), (6, 12, 0, "dance", 2, 16), (6, 16, 0, "pool", None, 12),
    ]
    today = datetime.now(MOSCOW).date()
    monday = today - timedelta(days=today.weekday())
    classes = []
    for week in range(5):
        for weekday, hour, minute, code, trainer_index, capacity in schedule:
            local_start = datetime.combine(monday + timedelta(days=weekday + 7 * week), datetime.min.time(), MOSCOW).replace(hour=hour, minute=minute)
            if local_start <= datetime.now(MOSCOW):
                continue
            start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
            service = service_by_code[code]
            item = ClassSession(service_id=service.id, trainer_id=trainers[trainer_index].id if trainer_index is not None else None, starts_at=start, ends_at=start + timedelta(minutes=service.duration_minutes), capacity=capacity)
            classes.append(item)
            db.add(item)
    db.flush()
    for user, wanted in [(users[0], "yoga"), (users[1], "boxing"), (users[3], "pool")]:
        target = next((c for c in classes if c.service_id == service_by_code[wanted].id), None)
        if target:
            db.add(Booking(user_id=user.id, class_id=target.id, status="ACTIVE"))
            target.booked_count += 1
    db.commit()
