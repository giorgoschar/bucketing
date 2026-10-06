"""Scheduler leader election: only one process may run the scheduler."""
import os
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text

import app.scheduler as sched


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(sched, "_lock_conn", None)
    yield
    sched._release_scheduler_lock()


def _fake_engine(got):
    conn = MagicMock()
    conn.execute.return_value.scalar.return_value = got
    eng = MagicMock()
    eng.dialect.name = "postgresql"
    eng.connect.return_value = conn
    return eng, conn


def test_sqlite_always_runs(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path/'x.db'}")
    assert sched._acquire_scheduler_lock(eng) is True
    assert sched._lock_conn is None


def test_postgres_lock_acquired_keeps_connection():
    eng, conn = _fake_engine(True)
    assert sched._acquire_scheduler_lock(eng) is True
    assert sched._lock_conn is conn
    conn.close.assert_not_called()
    sched._release_scheduler_lock()
    conn.close.assert_called_once()
    assert sched._lock_conn is None


def test_postgres_lock_connection_is_autocommit():
    """B7: the lock connection must not sit idle-in-transaction (autobegin),
    or idle_in_transaction_session_timeout could kill it and drop the lock."""
    eng, conn = _fake_engine(True)
    assert sched._acquire_scheduler_lock(eng) is True
    conn.execution_options.assert_called_once_with(isolation_level="AUTOCOMMIT")
    first = [c[0] for c in conn.mock_calls if c[0] in ("execution_options", "execute")]
    assert first[0] == "execution_options"


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="needs Postgres")
def test_real_postgres_lock_connection_not_idle_in_transaction():
    eng = create_engine(os.environ["TEST_DATABASE_URL"])
    other = eng.connect()
    try:
        assert sched._acquire_scheduler_lock(eng) is True
        pid = sched._lock_conn.execute(text("SELECT pg_backend_pid()")).scalar()
        state = other.execute(
            text("SELECT state FROM pg_stat_activity WHERE pid = :p"), {"p": pid}
        ).scalar()
        assert state == "idle"
    finally:
        sched._release_scheduler_lock()
        other.close()
        eng.dispose()


def test_postgres_lock_not_acquired_closes_connection():
    eng, conn = _fake_engine(False)
    assert sched._acquire_scheduler_lock(eng) is False
    conn.close.assert_called_once()
    assert sched._lock_conn is None


def test_start_scheduler_skips_when_lock_not_acquired(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "enable_scheduler", True)
    monkeypatch.setattr(sched, "_acquire_scheduler_lock", lambda engine=None: False)
    started = MagicMock()
    monkeypatch.setattr(sched.scheduler, "start", started)
    sched.start_scheduler()
    started.assert_not_called()


def test_start_scheduler_runs_when_lock_acquired(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "enable_scheduler", True)
    monkeypatch.setattr(sched, "_acquire_scheduler_lock", lambda engine=None: True)
    monkeypatch.setattr(sched.scheduler, "start", MagicMock())
    monkeypatch.setattr(sched.scheduler, "add_job", MagicMock())
    monkeypatch.setattr(sched.scheduler, "configure", MagicMock())
    sched.start_scheduler()
    sched.scheduler.start.assert_called_once()


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="needs Postgres")
def test_real_postgres_second_connection_cannot_take_lock():
    eng = create_engine(os.environ["TEST_DATABASE_URL"])
    other = eng.connect()
    try:
        assert sched._acquire_scheduler_lock(eng) is True
        got = other.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": sched.SCHEDULER_LOCK_KEY}).scalar()
        assert got is False
        # A second process trying the same thing is refused.
        assert sched._acquire_scheduler_lock(eng) is False
        sched._release_scheduler_lock()
        got = other.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": sched.SCHEDULER_LOCK_KEY}).scalar()
        assert got is True
        other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": sched.SCHEDULER_LOCK_KEY})
    finally:
        other.close()
        eng.dispose()
