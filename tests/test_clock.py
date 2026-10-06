"""Single clock/timezone helpers (app/clock.py)."""
from datetime import UTC, date, datetime

import pytest

import app.core.clock as clock
import app.core.config as config


def _freeze(monkeypatch, when: datetime):
    monkeypatch.setattr(clock, "utcnow", lambda: when)


def test_utcnow_is_aware_and_naive_variant_is_naive_utc():
    assert clock.utcnow().tzinfo is not None
    assert clock.utcnow().utcoffset().total_seconds() == 0
    assert clock.utcnow_naive().tzinfo is None


def test_utcnow_naive_follows_utcnow(monkeypatch):
    _freeze(monkeypatch, datetime(2026, 3, 1, 0, 30, tzinfo=UTC))
    assert clock.utcnow_naive() == datetime(2026, 3, 1, 0, 30)  # noqa: DTZ001 - naive on purpose


def test_local_today_same_date_case(monkeypatch):
    monkeypatch.setattr(config.settings, "app_timezone", "Europe/Athens")
    _freeze(monkeypatch, datetime(2026, 3, 1, 0, 30, tzinfo=UTC))
    assert clock.local_today() == date(2026, 3, 1)


def test_local_today_crosses_midnight_in_athens(monkeypatch):
    """23:30 UTC on Feb 28 is already 01:30 on Mar 1 in Athens (UTC+2)."""
    monkeypatch.setattr(config.settings, "app_timezone", "Europe/Athens")
    _freeze(monkeypatch, datetime(2026, 2, 28, 23, 30, tzinfo=UTC))
    assert clock.local_today() == date(2026, 3, 1)


def test_unknown_timezone_falls_back_to_utc(monkeypatch):
    monkeypatch.setattr(config.settings, "app_timezone", "Not/AZone")
    _freeze(monkeypatch, datetime(2026, 2, 28, 23, 30, tzinfo=UTC))
    assert clock.tz() is UTC
    assert clock.local_today() == date(2026, 2, 28)


def test_new_transaction_form_defaults_to_local_date(client, authed, monkeypatch):
    monkeypatch.setattr(config.settings, "app_timezone", "Europe/Athens")
    _freeze(monkeypatch, datetime(2026, 2, 28, 23, 30, tzinfo=UTC))
    r = client.get("/transactions/new")
    assert r.status_code == 200
    assert "2026-03-01" in r.text
    assert "2026-02-28" not in r.text


@pytest.mark.parametrize("module", ["app.scheduler"])
def test_scheduler_today_local_delegates_to_clock(module, monkeypatch):
    import app.scheduler as scheduler
    monkeypatch.setattr(config.settings, "app_timezone", "Europe/Athens")
    _freeze(monkeypatch, datetime(2026, 2, 28, 23, 30, tzinfo=UTC))
    assert scheduler.today_local() == date(2026, 3, 1)
