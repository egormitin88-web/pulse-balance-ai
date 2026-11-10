"""Never allow ordinary tests to use a developer's .env.local / production database."""

import os
import tempfile
from pathlib import Path

import pytest

_test_directory = tempfile.TemporaryDirectory(prefix="pulse-balance-tests-")
os.environ["FITNESS_DATA_DIR"] = _test_directory.name
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(_test_directory.name) / "tests.sqlite3").as_posix()
# An explicit empty value prevents dotenv from loading a real API key into tests.
os.environ["OPENAI_API_KEY"] = ""
os.environ.pop("VERCEL", None)


@pytest.fixture(scope="session", autouse=True)
def close_database_after_tests():
    yield
    from app.db import engine
    engine.dispose()
    _test_directory.cleanup()
