"""Polish S5: the Apple Pay ingest keeps a log of its last 50 requests per
household, with the reason for each rejection, and tolerates the shapes
Shortcuts sends (one-element lists).

The first tests pin the 201, 200-duplicate and 422 bodies as they were before
the handler parsed the body itself (written and run against the untouched
code)."""

import logging

import pytest

from app.models import Transaction
from tests.test_ingest import URL, _post, ingest  # noqa: F401  (fixture)

ATTEMPTS = "/api/v1/ingest/attempts"
AT = "2026-10-01T12:34:00+03:00"


def test_created_and_duplicate_bodies_are_unchanged(client, db, ingest):  # noqa: F811
    r = _post(client, ingest, card="Visa", occurred_at=AT)
    assert r.status_code == 201
    body = r.json()
    assert body == {
        "id": body["id"],
        "amount": 12.5,
        "currency": "EUR",
        "category": "Groceries",
        "category_id": ingest.category.id,
        "bucket": "Test Household Bucket",
        "bucket_id": ingest.hh.bucket_id,
        "transaction_date": "2026-10-01",
    }
    assert '"amount":12.5' in r.text
    again = _post(client, ingest, card="Visa", occurred_at=AT)
    assert again.status_code == 200
    assert again.json() == {**body, "duplicate": True}


def test_validation_422_keeps_fastapis_detail_list(client, db, ingest):  # noqa: F811
    r = client.post(URL, json={"amount": "1"}, headers=ingest.headers)
    assert r.status_code == 422
    assert r.json() == {
        "detail": [
            {
                "type": "missing",
                "loc": ["body", "merchant"],
                "msg": "Field required",
                "input": {"amount": "1"},
            }
        ]
    }
    r = client.post(URL, json={"merchant": {"a": 1}, "amount": "1"}, headers=ingest.headers)
    assert r.status_code == 422
    [err] = r.json()["detail"]
    assert (err["type"], err["loc"], err["msg"], err["input"]) == (
        "string_type",
        ["body", "merchant"],
        "Input should be a valid string",
        {"a": 1},
    )


def test_other_rejections_are_unchanged(client, db, ingest):  # noqa: F811
    assert client.post(URL, json={"merchant": "x", "amount": "1"}).status_code == 401
    r = _post(client, ingest, merchant="   ")
    assert (r.status_code, r.json()) == (422, {"detail": "Merchant is required."})
    r = _post(client, ingest, amount="-3")
    assert (r.status_code, r.json()) == (400, {"detail": "Amount must be greater than zero."})


# ---------------------------------------------------------------- the log


def _attempts(client, headers):
    r = client.get(ATTEMPTS, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _bearer(hh):
    from app.api_auth import create_access_token

    return {"Authorization": f"Bearer {create_access_token(hh.user_id, hh.household_id, 0)}"}


def test_each_outcome_is_recorded(client, db, ingest):  # noqa: F811
    from app.core.clock import utcnow_naive

    first = _post(client, ingest, occurred_at=AT)
    assert first.status_code == 201
    assert _post(client, ingest, occurred_at=AT).status_code == 200
    assert _post(client, ingest, amount="twelve").status_code == 400
    assert _post(client, ingest, merchant="   ").status_code == 422
    db.get(Transaction, first.json()["id"]).deleted_at = utcnow_naive()
    db.commit()
    assert _post(client, ingest, occurred_at=AT).status_code == 409

    items = _attempts(client, _bearer(ingest.hh))
    assert [(i["status_code"], i["outcome"]) for i in items] == [
        (409, "rejected"),
        (422, "rejected"),
        (400, "rejected"),
        (200, "duplicate"),
        (201, "created"),
    ]
    for i in items:
        assert set(i) == {
            "id",
            "created_at",
            "status_code",
            "outcome",
            "reason",
            "merchant",
            "amount_raw",
            "transaction_id",
            "token_name",
        }
        assert i["token_name"] == "iPhone"
    gone, blank, bad, dup, made = items
    assert made["transaction_id"] == dup["transaction_id"] == first.json()["id"]
    assert (made["merchant"], made["amount_raw"], made["reason"]) == ("Sklavenitis", "12,50", None)
    assert bad["reason"] == "Amount must be a number like 12,50 (got: 'twelve')"
    assert bad["amount_raw"] == "twelve" and bad["transaction_id"] is None
    assert blank["reason"] == "Merchant is required." and blank["merchant"] is None
    assert gone["reason"] == "This purchase was already added and has since been deleted."
    assert made["created_at"].startswith("20") and "T" in made["created_at"]


def test_a_validation_failure_is_recorded_with_its_reason(client, db, ingest):  # noqa: F811
    r = client.post(URL, json={"amount": "1"}, headers=ingest.headers)
    assert r.status_code == 422
    r = client.post(URL, json={"merchant": "Shop", "amount": {"v": 1}}, headers=ingest.headers)
    assert r.status_code == 422
    newest, older = _attempts(client, _bearer(ingest.hh))
    assert (older["status_code"], older["outcome"]) == (422, "rejected")
    assert older["reason"] == "merchant: Field required"
    assert older["amount_raw"] == "1" and older["merchant"] is None
    assert newest["reason"].startswith("amount: ") and newest["merchant"] == "Shop"
    assert newest["amount_raw"] == "{…}"
    assert db.query(Transaction).count() == 0


@pytest.mark.parametrize(
    "content", [b"[1, 2]", b'"hello"', b"12", b"null", b"not json", b"", b"\xff\xfe"]
)
def test_a_body_that_is_not_an_object(client, db, ingest, content):  # noqa: F811
    r = client.post(
        URL, content=content, headers={**ingest.headers, "Content-Type": "application/json"}
    )
    assert r.status_code == 422
    assert r.json() == {"detail": "Body must be JSON with merchant and amount"}
    [row] = _attempts(client, _bearer(ingest.hh))
    assert row["reason"] == "Body must be JSON with merchant and amount"
    assert (row["merchant"], row["amount_raw"]) == (None, None)


def test_no_bucket_is_recorded(client, db, ingest):  # noqa: F811
    from app.models import Bucket, BucketStatus

    db.get(Bucket, ingest.hh.bucket_id).status = BucketStatus.archived
    db.commit()
    assert _post(client, ingest).status_code == 422
    [row] = _attempts(client, _bearer(ingest.hh))
    assert row["reason"].startswith("No bucket to add this expense to")


def test_bad_or_missing_tokens_are_logged_but_not_recorded(client, db, ingest, caplog):  # noqa: F811
    from app.models import IngestAttempt

    body = {"merchant": "Shop", "amount": "1"}
    with caplog.at_level(logging.WARNING):
        assert client.post(URL, json=body).status_code == 401
        bad = {"Authorization": "Bearer pat_" + "x" * 32}
        assert client.post(URL, json=body, headers=bad).status_code == 401
    assert db.query(IngestAttempt).count() == 0
    lines = [
        r.getMessage() for r in caplog.records if "ingest apple-pay rejected" in r.getMessage()
    ]
    assert len(lines) == 2 and all("status=401" in ln for ln in lines)
    assert "pat_" not in caplog.text and "x" * 32 not in caplog.text


def test_rejections_are_logged_with_a_safe_summary(client, db, ingest, caplog):  # noqa: F811
    with caplog.at_level(logging.WARNING):
        r = client.post(
            URL,
            json={"merchant": [""], "amount": [12.5], "card": "Visa"},
            headers=ingest.headers,
        )
    assert r.status_code == 422
    [line] = [
        r.getMessage() for r in caplog.records if "ingest apple-pay rejected" in r.getMessage()
    ]
    assert line == (
        'ingest apple-pay rejected status=422 reason="Merchant is required." '
        "keys=[amount,card,merchant] unknown_keys=0 amount_type=list merchant_len=0"
    )


def test_the_token_and_long_values_never_reach_the_log_or_the_rows(client, db, ingest, caplog):  # noqa: F811
    from app.models import IngestAttempt

    secret_note = "N" * 300
    with caplog.at_level(logging.DEBUG):
        _post(client, ingest)
        _post(client, ingest, amount="9" * 39 + "x", notes=secret_note)
        _post(client, ingest, merchant="M" * 150, amount="1" * 120, notes=secret_note)
        _post(client, ingest, merchant="   ", **{"k" * 100: 1})
        client.post(URL, json=["a" * 500], headers=ingest.headers)
    assert ingest.raw not in caplog.text
    assert ingest.raw[4:] not in caplog.text
    assert "N" * 41 not in caplog.text and "M" * 41 not in caplog.text
    assert "1" * 41 not in caplog.text and "k" * 41 not in caplog.text
    assert "a" * 41 not in caplog.text
    rows = db.query(IngestAttempt).all()
    assert len(rows) == 5
    for row in rows:
        for col in ("reason", "merchant", "amount_raw", "id", "token_id", "user_id"):
            value = getattr(row, col) or ""
            assert ingest.raw not in value and ingest.raw[4:] not in value
            assert ingest.token.token_hash not in value
        assert len(row.merchant or "") <= 80
        assert len(row.amount_raw or "") <= 40
        assert len(row.reason or "") <= 300
    assert any(row.merchant == "M" * 80 for row in rows)
    assert any(row.amount_raw == "1" * 40 for row in rows)


def test_only_the_newest_50_are_kept(client, db, ingest, make_household):  # noqa: F811
    from datetime import timedelta

    from app.core.clock import utcnow_naive
    from app.models import IngestAttempt
    from app.services.ingest import record_attempt

    other = make_household(name="Other", username="outsider")
    base = utcnow_naive() - timedelta(hours=1)
    for hh, n in ((ingest.hh, 55), (other, 3)):
        for i in range(n):
            record_attempt(
                db,
                household_id=hh.household_id,
                token_id=None,
                user_id=hh.user_id,
                status_code=422,
                outcome="rejected",
                reason=f"r{i}",
            )
            row = (
                db.query(IngestAttempt)
                .filter_by(household_id=hh.household_id, reason=f"r{i}")
                .one()
            )
            row.created_at = base + timedelta(seconds=i)
            db.commit()
    assert db.query(IngestAttempt).filter_by(household_id=ingest.hh.household_id).count() == 50
    assert db.query(IngestAttempt).filter_by(household_id=other.household_id).count() == 3
    assert _post(client, ingest).status_code == 201  # the 56th: the oldest goes
    items = _attempts(client, _bearer(ingest.hh))
    assert len(items) == 50
    assert items[0]["outcome"] == "created" and items[1]["reason"] == "r54"
    assert items[-1]["reason"] == "r6"
    assert db.query(IngestAttempt).filter_by(household_id=other.household_id).count() == 3


def _member_with_token(db, hh, username, role=None):
    """Another member of ``hh`` with their own ingest token."""
    from types import SimpleNamespace

    from app.models import HouseholdMember
    from app.services import issue_personal_token
    from tests.test_isolation import _add_member_user

    user, _secret = _add_member_user(db, hh.household_id, username)
    if role is not None:
        db.query(HouseholdMember).filter_by(
            household_id=hh.household_id, user_id=user.id
        ).one().role = role
    _record, raw = issue_personal_token(
        db, user_id=user.id, household_id=hh.household_id, name=f"{username} phone"
    )
    db.commit()
    return SimpleNamespace(
        household_id=hh.household_id,
        user_id=user.id,
        headers={"Authorization": f"Bearer {raw}"},
    )


def test_attempts_are_the_callers_own_and_need_app_auth(client, db, ingest, make_household):
    """Tokens are personal: a member sees only what their own tokens sent,
    whatever their role, and another household sees nothing."""
    from app.models import MemberRole

    other = make_household(name="Other", username="outsider")
    bob = _member_with_token(db, ingest.hh, "bob")
    admin = _member_with_token(db, ingest.hh, "ada", role=MemberRole.owner)
    assert _post(client, ingest, merchant="Mine").status_code == 201
    assert _post(client, ingest, merchant="Mine", amount="x").status_code == 400
    r = client.post(URL, json={"merchant": "Bobs", "amount": "3"}, headers=bob.headers)
    assert r.status_code == 201

    mine = _attempts(client, _bearer(ingest.hh))  # the household's owner
    assert [a["merchant"] for a in mine] == ["Mine", "Mine"]
    assert {a["token_name"] for a in mine} == {"iPhone"}
    bobs = _attempts(client, _bearer(bob))
    assert [(a["merchant"], a["token_name"]) for a in bobs] == [("Bobs", "bob phone")]
    assert _attempts(client, _bearer(admin)) == []  # a second owner: still only their own
    assert _attempts(client, _bearer(other)) == []
    assert client.get(ATTEMPTS).status_code == 401
    assert client.get(ATTEMPTS, headers=ingest.headers).status_code == 401  # not a pat_ token


def test_an_attempt_is_filed_under_the_tokens_identity_not_the_bodys(
    client, db, ingest, make_household
):
    from app.models import IngestAttempt

    other = make_household(name="Other", username="outsider")
    bob = _member_with_token(db, ingest.hh, "bob")
    forged = {
        "household_id": other.household_id,
        "user_id": bob.user_id,
        "token_id": "someone-elses",
        "paid_by": bob.user_id,
    }
    assert _post(client, ingest, **forged).status_code == 201
    assert _post(client, ingest, amount="x", **forged).status_code == 400
    rows = db.query(IngestAttempt).all()
    assert len(rows) == 2
    for row in rows:
        assert (row.household_id, row.user_id, row.token_id) == (
            ingest.hh.household_id,
            ingest.hh.user_id,
            ingest.token.id,
        )
    assert db.query(Transaction).one().paid_by == ingest.hh.user_id
    assert _attempts(client, _bearer(bob)) == [] and _attempts(client, _bearer(other)) == []


def test_pruning_is_per_member(client, db, ingest):
    from app.models import IngestAttempt
    from app.services.ingest import record_attempt

    bob = _member_with_token(db, ingest.hh, "bob")
    for i in range(3):
        record_attempt(
            db,
            household_id=bob.household_id,
            token_id=None,
            user_id=bob.user_id,
            status_code=422,
            outcome="rejected",
            reason=f"b{i}",
        )
    for i in range(52):
        record_attempt(
            db,
            household_id=ingest.hh.household_id,
            token_id=None,
            user_id=ingest.hh.user_id,
            status_code=422,
            outcome="rejected",
            reason=f"a{i}",
        )
    assert db.query(IngestAttempt).filter_by(user_id=ingest.hh.user_id).count() == 50
    assert db.query(IngestAttempt).filter_by(user_id=bob.user_id).count() == 3
    assert len(_attempts(client, _bearer(bob))) == 3


# ---------------------------------------------------------------- log injection

FORGED = "Shop\n2026-10-08 12:00:00 INFO forged line"


def test_a_forged_line_in_the_merchant_stays_one_record(client, db, ingest, caplog):
    from app.models import IngestAttempt

    with caplog.at_level(logging.DEBUG):
        r = _post(client, ingest, merchant=FORGED, amount="x\r\ny")
    assert r.status_code == 400
    records = [r for r in caplog.records if "ingest apple-pay rejected" in r.getMessage()]
    assert len(records) == 1
    line = records[0].getMessage()
    assert "\n" not in line and "\r" not in line
    assert "forged" not in line  # the merchant's text is never logged, only its length
    row = db.query(IngestAttempt).one()
    for value in (row.merchant, row.amount_raw, row.reason):
        assert "\n" not in value and "\r" not in value
    assert row.merchant == "Shop 2026-10-08 12:00:00 INFO forged line"


@pytest.mark.parametrize(
    "nasty",
    ["a\nb", "a\rb", "a\x00b", "a\x1b[31mb", "a\u2028b", "a\u2029b", "a\u202eb", "a\x7fb", "a\tb"],
)
def test_control_characters_never_reach_the_log_or_the_rows(client, db, ingest, caplog, nasty):
    from app.models import IngestAttempt

    with caplog.at_level(logging.DEBUG):
        _post(client, ingest, merchant=nasty, amount=nasty)  # 400: the amount
        _post(client, ingest, merchant="   ", **{nasty: 1, "x\ny": 2})  # 422
        client.post(URL, json={"merchant": "M", "amount": {"k\nk": nasty}}, headers=ingest.headers)

    def clean(text):
        import unicodedata

        return not any(unicodedata.category(ch)[0] == "C" or ch in "\u2028\u2029" for ch in text)

    lines = [r.getMessage() for r in caplog.records if "ingest apple-pay" in r.getMessage()]
    assert len(lines) == 3 and all(clean(ln) for ln in lines), lines
    for row in db.query(IngestAttempt).all():
        for value in (row.merchant, row.amount_raw, row.reason):
            assert clean(value or ""), (value,)


def test_only_known_key_names_are_logged(client, db, ingest, caplog):
    with caplog.at_level(logging.WARNING):
        _post(client, ingest, merchant="  ", card="Visa", **{"evil key=1 status=200": 1, "zz": 2})
    [line] = [
        r.getMessage() for r in caplog.records if "ingest apple-pay rejected" in r.getMessage()
    ]
    assert "keys=[amount,card,merchant] unknown_keys=2 " in line
    assert "evil" not in line and "zz" not in line


def test_stored_values_are_capped_after_cleaning(db, ingest):
    from app.models import IngestAttempt
    from app.services.ingest import record_attempt

    record_attempt(
        db,
        household_id=ingest.hh.household_id,
        token_id=ingest.token.id,
        user_id=ingest.hh.user_id,
        status_code=400,
        outcome="rejected",
        reason="r\n" * 400,
        merchant="m\x00" * 400,
        amount_raw="9\r" * 400,
    )
    row = db.query(IngestAttempt).one()
    assert (len(row.reason), len(row.merchant), len(row.amount_raw)) == (300, 80, 40)
    assert row.merchant == "m" * 80 and row.amount_raw == "9" * 40


def test_a_failing_log_never_breaks_the_ingest(client, db, ingest, monkeypatch):  # noqa: F811
    from app.models import IngestAttempt

    def boom(*a, **k):
        raise RuntimeError("no table")

    monkeypatch.setattr(IngestAttempt, "__init__", boom)
    assert _post(client, ingest).status_code == 201
    assert _post(client, ingest, amount="x").status_code == 400
    assert db.query(Transaction).count() == 1


# ---------------------------------------------------------------- Shortcuts shapes


@pytest.mark.parametrize(
    "body,amount,merchant",
    [
        ({"amount": [12.5]}, "12.5", "Sklavenitis"),
        ({"amount": ["12,50 €"]}, "12.5", "Sklavenitis"),
        ({"amount": " 1 234,56 "}, "1234.56", "Sklavenitis"),
        ({"amount": [7], "merchant": ["Corner  Kiosk"]}, "7", "Corner Kiosk"),
        ({"merchant": ["Lidl"], "currency": ["EUR"], "card": ["Visa"]}, "12.5", "Lidl"),
    ],
)
def test_list_shaped_values_are_accepted(client, db, ingest, body, amount, merchant):  # noqa: F811
    from decimal import Decimal

    r = _post(client, ingest, **body)
    assert r.status_code == 201, r.text
    t = db.get(Transaction, r.json()["id"])
    assert (t.amount, t.merchant) == (Decimal(amount), merchant)


def test_an_empty_list_is_still_a_validation_error(client, db, ingest):  # noqa: F811
    r = _post(client, ingest, amount=[])
    assert r.status_code == 422 and isinstance(r.json()["detail"], list)
    assert _post(client, ingest, merchant=[]).status_code == 422
    assert db.query(Transaction).count() == 0
