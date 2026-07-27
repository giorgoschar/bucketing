"""
Shared pytest fixtures.

Each test gets a fresh SQLite database created from the ORM metadata, with the
app's get_db dependency pointed at it. Tests never touch the developer's real
expenses.db.
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

# Configure the app before importing it: settings are read at import time.
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-at-least-32-chars-long!!")
# DEBUG=true keeps session cookies non-Secure so TestClient (plain http) can
# round-trip them, and disables the production secret-strength guard.
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("ENABLE_SCHEDULER", "false")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyotp  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Clear rate-limit counters between tests.

    The limiter is a module-level singleton with in-process storage, so without
    this the login limit (10 per 15 minutes) is consumed by earlier tests and
    later ones fail with 429 rather than for any real reason.
    """
    from app.ratelimit import limiter

    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture()
def engine(tmp_path):
    """A throwaway SQLite database per test, with FK enforcement on."""
    url = f"sqlite:///{tmp_path/'test.db'}"
    eng = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _fk(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    from app.database import Base
    import app.models  # noqa: F401  (register the tables)
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def SessionLocal(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture()
def db(SessionLocal):
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def app(engine, SessionLocal, monkeypatch):
    """The FastAPI app wired to the test database."""
    import app.database as database
    from app.main import app as fastapi_app

    monkeypatch.setattr(database, "engine", engine, raising=False)
    monkeypatch.setattr(database, "SessionLocal", SessionLocal, raising=False)

    def _get_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    fastapi_app.dependency_overrides[database.get_db] = _get_db
    yield fastapi_app
    fastapi_app.dependency_overrides.clear()


@pytest.fixture()
def client(app):
    return TestClient(app, follow_redirects=False)


# ---------------------------------------------------------------------------
# Data factories
# ---------------------------------------------------------------------------

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture()
def make_household(db):
    """Create a household with an enrolled owner. Returns a simple namespace."""
    from types import SimpleNamespace

    from app.auth import hash_password
    from app.models import Bucket, Household, HouseholdMember, MemberRole, User

    created = {"n": 0}

    def _make(name="Test Household", username=None, with_bucket=True):
        created["n"] += 1
        username = username or f"user{created['n']}"
        hh = Household(name=name, default_currency="EUR")
        db.add(hh)
        db.flush()

        secret = pyotp.random_base32()
        user = User(
            username=username,
            display_name=username.title(),
            email=f"{username}@example.com",
            password_hash=hash_password(PASSWORD),
            totp_secret=secret,
            totp_enabled=True,
            session_version=0,
        )
        db.add(user)
        db.flush()
        db.add(HouseholdMember(household_id=hh.id, user_id=user.id, role=MemberRole.owner))

        bucket = None
        if with_bucket:
            bucket = Bucket(household_id=hh.id, name=f"{name} Bucket")
            db.add(bucket)
            db.flush()

        db.commit()
        return SimpleNamespace(
            household_id=hh.id,
            user_id=user.id,
            username=username,
            secret=secret,
            bucket_id=bucket.id if bucket else None,
        )

    return _make


@pytest.fixture()
def login(client):
    """Log a user in through the real password + TOTP flow. Returns CSRF headers."""

    def _login(username, secret):
        r = client.post("/login", data={"username": username, "password": PASSWORD})
        assert r.status_code == 302, f"login failed: {r.status_code}"
        r = client.post("/login/verify", data={"code": pyotp.TOTP(secret).now()})
        assert r.status_code == 302, f"totp verify failed: {r.status_code}"
        token = client.cookies.get("csrf_token")
        assert token, "no CSRF cookie issued after login"
        return {"X-CSRF-Token": token}

    return _login


@pytest.fixture()
def authed(client, make_household, login):
    """A logged-in owner with a household and one bucket."""
    hh = make_household()
    hh.headers = login(hh.username, hh.secret)
    return hh


@pytest.fixture()
def make_bill(db):
    """Create a recurring bill (+ optional occurrence) for a household."""
    from app.models import BillOccurrence, OccurrenceStatus, RecurringBill

    def _make(household_id, bucket_id=None, *, amount=45, auto_pay=True,
              due=None, paid_by=None, occurrence=True, name="Internet",
              interval_months=1, occ_amount=None):
        bill = RecurringBill(
            household_id=household_id,
            bucket_id=bucket_id,
            name=name,
            amount=amount,
            currency="EUR",
            start_date=due or date.today(),
            interval_months=interval_months,
            is_auto_pay=auto_pay,
            is_active=True,
            paid_by_default=paid_by,
        )
        db.add(bill)
        db.flush()
        occ = None
        if occurrence:
            occ = BillOccurrence(
                bill_id=bill.id,
                due_date=due or date.today(),
                amount=occ_amount,
                status=OccurrenceStatus.unpaid,
            )
            db.add(occ)
            db.flush()
        db.commit()
        return bill, occ

    return _make
