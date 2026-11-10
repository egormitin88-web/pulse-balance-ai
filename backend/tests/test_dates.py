from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app.business import iso_utc, utc_to_local
from app.models import UTCDateTime, now_utc


@pytest.mark.parametrize("value", [
    datetime(2026, 11, 10, 12),
    datetime(2026, 11, 10, 12, tzinfo=timezone.utc),
    datetime(2026, 11, 10, 15, tzinfo=timezone(timedelta(hours=3))),
])
def test_api_dates_have_one_timezone_and_preserve_instant(value):
    assert iso_utc(value) == "2026-11-10T12:00:00Z"
    assert datetime.fromisoformat(iso_utc(value)) == datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
    assert utc_to_local(value) == "2026-11-10T15:00+03:00"


def test_optional_date():
    assert iso_utc(None) is None


@pytest.mark.parametrize("dialect", [sqlite.dialect(), postgresql.dialect()])
def test_database_date_roundtrip_supports_booking_comparisons(dialect):
    column = UTCDateTime()
    future = now_utc() + timedelta(hours=3)
    stored = column.process_bind_param(future, dialect)
    loaded = column.process_result_value(stored, dialect)
    assert loaded == future
    assert loaded > now_utc()
    assert loaded - now_utc() > timedelta(hours=2)


def test_postgres_date_read_normalizes_non_utc_offset():
    value = datetime(2026, 11, 10, 15, tzinfo=timezone(timedelta(hours=3)))
    assert UTCDateTime().process_result_value(value, postgresql.dialect()) == datetime(2026, 11, 10, 12)
