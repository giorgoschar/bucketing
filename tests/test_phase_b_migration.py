"""Phase B S1 (spec §3.1): month_reviews table, month_review notification type."""

import uuid

from sqlalchemy import create_engine, inspect, text

from app.models import NotificationType
from app.services.notification_prefs import ALERT_TYPES
from tests.test_migrations import _alembic, _db_url

PREV_HEAD = "c5d6e7f8a9b0"
NEW = "d6e7f8a9b0c1"


def _unique_cols(insp, table):
    out = [tuple(u["column_names"]) for u in insp.get_unique_constraints(table)]
    out += [tuple(i["column_names"]) for i in insp.get_indexes(table) if i.get("unique")]
    return out


def test_month_reviews_table_and_unique_exist_after_upgrade(tmp_path):
    db_url = _db_url(tmp_path, "pb.db")
    assert _alembic(["upgrade", "head"], db_url).returncode == 0
    insp = inspect(create_engine(db_url))
    assert "month_reviews" in insp.get_table_names()
    cols = {c["name"]: c for c in insp.get_columns("month_reviews")}
    assert set(cols) == {"id", "household_id", "month", "reviewed_at", "reviewed_by"}
    assert not cols["household_id"]["nullable"]
    assert not cols["month"]["nullable"]
    assert not cols["reviewed_at"]["nullable"]
    assert cols["reviewed_by"]["nullable"]
    assert ("household_id", "month") in _unique_cols(insp, "month_reviews")


def test_downgrade_drops_table_and_deletes_month_review_notifications(tmp_path):
    db_url = _db_url(tmp_path, "pbd.db")
    assert _alembic(["upgrade", "head"], db_url).returncode == 0
    engine = create_engine(db_url)
    hh, user = str(uuid.uuid4()), str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO households (id, name, default_currency) VALUES (:i, 'H', 'EUR')"),
            {"i": hh},
        )
        conn.execute(
            text(
                "INSERT INTO users (id, username, display_name, password_hash, session_version, totp_enabled, email_verified) "
                "VALUES (:i, 'u', 'U', 'x', 0, false, false)"
            ),
            {"i": user},
        )
        for t in ("month_review", "general"):
            conn.execute(
                text(
                    "INSERT INTO notifications (id, household_id, user_id, type, title, is_read) "
                    "VALUES (:i, :h, :u, :t, 'x', false)"
                ),
                {"i": str(uuid.uuid4()), "h": hh, "u": user, "t": t},
            )
    down = _alembic(["downgrade", PREV_HEAD], db_url)
    assert down.returncode == 0, down.stderr
    insp = inspect(create_engine(db_url))
    assert "month_reviews" not in insp.get_table_names()
    with engine.connect() as conn:
        types = [r[0] for r in conn.execute(text("SELECT type FROM notifications"))]
    assert types == ["general"]
    assert _alembic(["upgrade", "head"], db_url).returncode == 0


def test_one_head_and_it_is_the_new_revision(tmp_path):
    res = _alembic(["heads"], _db_url(tmp_path, "ph.db"))
    assert res.returncode == 0, res.stderr
    heads = [ln for ln in res.stdout.splitlines() if "(head)" in ln]
    assert len(heads) == 1 and heads[0].startswith(NEW)


def test_month_review_is_a_notification_type_and_a_pref():
    assert NotificationType.month_review.value == "month_review"
    rows = [a for a in ALERT_TYPES if a.type == "month_review"]
    assert [(a.group, a.label) for a in rows] == [("Insights", "Month ready to review")]
