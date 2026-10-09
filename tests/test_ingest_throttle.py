"""Attempt recording is throttled and cannot evict anyone's log (review I-2)."""

import logging
from types import SimpleNamespace

import pytest

from app.core.clock import utcnow_naive
from app.models import Bucket, BucketType, HouseholdMember, IngestAttempt
from app.services import issue_personal_token, record_ingest_attempt, revoke_personal_token

URL = "/api/v1/ingest/apple-pay"


def _token(db, hh, user_id=None, name="iPhone"):
    record, raw = issue_personal_token(
        db, user_id=user_id or hh.user_id, household_id=hh.household_id, name=name
    )
    db.commit()
    return SimpleNamespace(record=record, raw=raw, headers={"Authorization": f"Bearer {raw}"})


@pytest.fixture()
def ctx(app, db, make_household):
    hh = make_household()
    db.get(Bucket, hh.bucket_id).type = BucketType.day2day
    db.commit()
    return SimpleNamespace(hh=hh, tok=_token(db, hh))


def _rows(db, **filters):
    return db.query(IngestAttempt).filter_by(**filters).all()


# ------------------------------------------------------------------ dead tokens


def test_a_revoked_token_flood_leaves_the_households_log_alone(client, db, ctx):
    r = client.post(URL, json={"merchant": "Shop", "amount": "3"}, headers=ctx.tok.headers)
    assert r.status_code == 201
    dead = _token(db, ctx.hh, name="dead")
    revoke_personal_token(
        db, token_id=dead.record.id, user_id=ctx.hh.user_id, household_id=ctx.hh.household_id
    )
    db.commit()
    codes = [
        client.post(URL, json={"merchant": "x", "amount": "1"}, headers=dead.headers).status_code
        for _ in range(110)
    ]
    assert codes.count(401) == 20 and codes.count(429) == 90
    db.expire_all()
    mine = _rows(db, household_id=ctx.hh.household_id)
    assert [a.status for a in mine] == [201]  # nothing of the flood is attributed
    assert len(_rows(db, household_id=None)) <= 20  # per source IP, per hour


def test_a_removed_members_token_is_not_attributed(client, db, ctx, make_household):
    from tests.test_household_settlement import _add_member

    member = _add_member(db, ctx.hh.household_id, "leaver")
    db.commit()
    tok = _token(db, ctx.hh, user_id=member.id, name="leaver")
    db.query(HouseholdMember).filter_by(user_id=member.id).delete()
    db.commit()
    assert client.post(URL, json={"amount": "1"}, headers=tok.headers).status_code == 401
    assert _rows(db, household_id=ctx.hh.household_id) == []
    assert len(_rows(db, household_id=None)) == 1


def test_unattributed_attempts_are_limited_per_source_ip(app, db, caplog):
    caplog.set_level(logging.INFO)
    for i in range(30):
        record_ingest_attempt(
            status=401,
            detail="Invalid ingest token",
            raw_token=f"pat_{i:08d}x",
            client_ip="1.2.3.4",
        )
    record_ingest_attempt(status=401, detail="x", raw_token="pat_other", client_ip="5.6.7.8")
    assert len(_rows(db, household_id=None)) == 21
    suppressed = [r for r in caplog.records if "suppressed" in r.getMessage()]
    assert len(suppressed) == 1  # one fixed line per minute
    assert "1.2.3.4" not in caplog.text and "pat_0" not in suppressed[0].getMessage()
    lines = [r for r in caplog.records if r.getMessage().startswith("ingest: /api")]
    assert len(lines) == 21  # past the cap not even the full log line


def test_the_global_unattributed_cap_still_holds(app, db, monkeypatch):
    import app.services.ingest as mod

    monkeypatch.setattr(mod, "KEEP_UNATTRIBUTED", 3)
    for i in range(10):
        record_ingest_attempt(status=401, raw_token=f"pat_{i:08d}", client_ip=f"10.0.0.{i}")
    assert len(_rows(db, household_id=None)) == 3


# ------------------------------------------------------------------ before authentication


def test_unauthenticated_invalid_json_stops_being_recorded(client, db, ctx):
    codes = [
        client.post(URL, content="{", headers={"content-type": "application/json"}).status_code
        for _ in range(60)
    ]
    assert codes[:20] == [422] * 20 and set(codes[20:]) == {429}
    assert len(_rows(db)) <= 20
    assert _rows(db, household_id=ctx.hh.household_id) == []


# ------------------------------------------------------------------ the token's own budget


def test_bad_bodies_count_toward_the_tokens_hourly_limit(client, db, ctx):
    codes = [
        client.post(
            URL, content="[1]", headers={**ctx.tok.headers, "content-type": "application/json"}
        ).status_code
        for _ in range(70)
    ]
    assert codes[:60] == [422] * 60 and set(codes[60:]) == {429}
    rows = _rows(db, household_id=ctx.hh.household_id)
    assert sorted(a.status for a in rows).count(429) == 1  # one "rate limited" row an hour
    assert sorted(a.status for a in rows).count(422) == 60


def test_valid_and_bad_requests_share_one_budget(client, db, ctx):
    for i in range(30):
        assert (
            client.post(
                URL, json={"merchant": f"S{i}", "amount": "1"}, headers=ctx.tok.headers
            ).status_code
            == 201
        )
    for _ in range(30):
        client.post(
            URL, content="[1]", headers={**ctx.tok.headers, "content-type": "application/json"}
        )
    r = client.post(URL, json={"merchant": "late", "amount": "1"}, headers=ctx.tok.headers)
    assert r.status_code == 429


def test_the_over_limit_429_is_recorded_once_per_token_per_hour(client, db, ctx):
    for i in range(60):
        client.post(URL, json={"merchant": f"S{i}", "amount": "1"}, headers=ctx.tok.headers)
    for _ in range(10):
        assert (
            client.post(
                URL, json={"merchant": "x", "amount": "1"}, headers=ctx.tok.headers
            ).status_code
            == 429
        )
    statuses = [a.status for a in _rows(db, household_id=ctx.hh.household_id)]
    assert statuses.count(429) == 1 and statuses.count(201) == 60


# ------------------------------------------------------------------ pruning is per token


def test_one_token_cannot_evict_anothers_rows(db, ctx, monkeypatch):
    import app.services.ingest as mod

    monkeypatch.setattr(mod, "KEEP_PER_SCOPE", 5)
    other = _token(db, ctx.hh, name="other")
    for _ in range(3):
        record_ingest_attempt(status=201, detail="created", token=other.record)
    for _ in range(12):
        record_ingest_attempt(status=422, detail="bad", token=ctx.tok.record)
    assert len(_rows(db, token_id=other.record.id)) == 3
    assert len(_rows(db, token_id=ctx.tok.record.id)) == 5


# ------------------------------------------------------------------ the event loop


def test_async_handlers_hand_the_database_work_to_a_thread(client, db, ctx, monkeypatch):
    import app.main as main_mod

    calls = []
    real = main_mod.run_in_threadpool

    async def spy(fn, *a, **k):
        calls.append(fn.__name__)
        return await real(fn, *a, **k)

    monkeypatch.setattr(main_mod, "run_in_threadpool", spy)
    client.post(URL, content="[1]", headers={**ctx.tok.headers, "content-type": "application/json"})
    for i in range(61):
        client.post(URL, json={"merchant": f"S{i}", "amount": "1"}, headers=ctx.tok.headers)
    assert len(calls) >= 2 and utcnow_naive()
