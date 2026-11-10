from __future__ import annotations

import os
import tempfile
from pathlib import Path
from dotenv import load_dotenv

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker


BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env.local", override=False)

IS_VERCEL = os.getenv("VERCEL") == "1"
DATA_DIR = Path(os.getenv("FITNESS_DATA_DIR", Path(tempfile.gettempdir()) / "pulse-balance" if IS_VERCEL else BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

if IS_VERCEL and not os.getenv("DATABASE_URL"):
    raise RuntimeError("Set DATABASE_URL in Vercel before starting the application")

DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{(DATA_DIR / 'fitness.sqlite3').as_posix()}"

if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://", "postgresql+psycopg://", 1
    )
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://", "postgresql+psycopg://", 1
    )

database_address = make_url(DATABASE_URL)
transport = os.getenv("FITNESS_NEON_TRANSPORT", "auto")
if (
    not IS_VERCEL
    and database_address.drivername.startswith("postgresql")
    and database_address.host
    and database_address.host.endswith(".neon.tech")
    and transport != "tcp"
):
    from .neon_tunnel import tcp_available, websocket_database_url

    if transport == "websocket" or not tcp_available(database_address.host, database_address.port or 5432):
        DATABASE_URL = websocket_database_url(database_address).render_as_string(hide_password=False)


class Base(DeclarativeBase):
    pass


engine = create_engine(
    DATABASE_URL,
    connect_args=(
        {"check_same_thread": False, "timeout": 15}
        if DATABASE_URL.startswith("sqlite")
        else {"connect_timeout": 10}
    ),
    pool_pre_ping=True,
    pool_recycle=300,
)


if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_config(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.close()


SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as session:
        yield session
