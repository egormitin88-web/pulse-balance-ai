from __future__ import annotations

import os
import secrets
from pathlib import Path

import keyring
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .db import DATA_DIR


KEYRING_SERVICE = "pulse-balance-demo"
KEYRING_USERNAME = "openai-api-key"
SESSION_FILE = DATA_DIR / ".session-secret"
ph = PasswordHasher()
_memory_openai_key: str | None = None


def _session_secret() -> str:
    if SESSION_FILE.exists():
        return SESSION_FILE.read_text(encoding="utf-8").strip()
    secret = secrets.token_urlsafe(48)
    try:
        fd = os.open(SESSION_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return SESSION_FILE.read_text(encoding="utf-8").strip()
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(secret)
    return secret


serializer = URLSafeTimedSerializer(_session_secret())


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return ph.verify(password_hash, password)
    except (VerifyMismatchError, ValueError):
        return False


def sign_user(user_id: int) -> str:
    return serializer.dumps({"type": "user", "id": user_id}, salt="auth")


def read_user(token: str | None) -> int | None:
    if not token:
        return None
    try:
        payload = serializer.loads(token, salt="auth", max_age=7 * 86400)
        return int(payload["id"]) if payload.get("type") == "user" else None
    except (BadSignature, SignatureExpired, ValueError, KeyError, TypeError):
        return None


def sign_anonymous(value: str) -> str:
    return serializer.dumps({"type": "anonymous", "id": value}, salt="anonymous")


def read_anonymous(token: str | None) -> str | None:
    if not token:
        return None
    try:
        payload = serializer.loads(token, salt="anonymous", max_age=24 * 3600)
        return str(payload["id"]) if payload.get("type") == "anonymous" else None
    except (BadSignature, SignatureExpired, ValueError, KeyError, TypeError):
        return None


def save_openai_key(value: str) -> str:
    global _memory_openai_key
    if not value.startswith("sk-") or len(value) < 24:
        raise ValueError("Ожидается ключ OpenAI API, начинающийся с sk-.")
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, value)
    except Exception:
        # Some local launch contexts have no Windows logon session for CredWrite.
        # Keep the key only in this server process; never fall back to plaintext disk.
        _memory_openai_key = value
        return "memory"
    _memory_openai_key = None
    return "system"


def read_openai_key() -> str | None:
    if _memory_openai_key is not None:
        return _memory_openai_key
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception:
        return None


def openai_key_storage_mode() -> str | None:
    if _memory_openai_key is not None:
        return "memory"
    return "system" if read_openai_key() else None


def delete_openai_key() -> None:
    global _memory_openai_key
    was_in_memory = _memory_openai_key is not None
    _memory_openai_key = None
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass
    except Exception:
        if not was_in_memory:
            raise
