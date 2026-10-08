"""Polish R5: save first, then ask. The Shortcut may classify a purchase it
just added, but only with a token created with the ``classify`` scope."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.core.clock import utcnow_naive
from app.models import (
    Bucket,
    BucketType,
    Category,
    CategoryRule,
    IngestAttempt,
    Transaction,
)
from app.services import issue_personal_token
from app.services.category_rules import learn_rule
from tests.test_api import api  # noqa: F401  (fixture)

URL = "/api/v1/ingest/apple-pay"
OLD_KEYS = {
    "id",
    "amount",
    "currency",
    "category",
    "category_id",
    "bucket",
    "bucket_id",
    "transaction_date",
}


def classify_url(txn_id):
    return f"{URL}/{txn_id}/classify"


def _bearer(raw):
    return {"Authorization": f"Bearer {raw}"}


@pytest.fixture()
def ctx(db, make_household):
    hh = make_household()
    main = db.get(Bucket, hh.bucket_id)
    main.type = BucketType.day2day
    other_bucket = Bucket(household_id=hh.household_id, name="Fun money", type=BucketType.day2day)
    groceries = Category(household_id=hh.household_id, name="Groceries", icon="🛒")
    coffee = Category(household_id=hh.household_id, name="Coffee", icon="☕")
    db.add_all([other_bucket, groceries, coffee])
    db.flush()
    learn_rule(db, hh.household_id, "Sklavenitis", groceries.id, created_by=hh.user_id)
    plain, raw_plain = issue_personal_token(
        db, user_id=hh.user_id, household_id=hh.household_id, name="plain"
    )
    smart, raw_smart = issue_personal_token(
        db, user_id=hh.user_id, household_id=hh.household_id, name="smart", allow_classify=True
    )
    db.commit()
    return SimpleNamespace(
        hh=hh,
        main=main,
        fun=other_bucket,
        groceries=groceries,
        coffee=coffee,
        plain=plain,
        smart=smart,
        plain_h=_bearer(raw_plain),
        smart_h=_bearer(raw_smart),
    )


def _add(client, headers, merchant="Corner Kiosk", amount="4,20", **extra):
    body = {"merchant": merchant, "amount": amount, **extra}
    r = client.post(URL, json=body, headers=headers)
    assert r.status_code in (200, 201), r.text
    return r.json()


# ---------------------------------------------------------------- ingest response


def test_rule_match_has_no_category_list(client, ctx):
    body = _add(client, ctx.smart_h, merchant="Sklavenitis")
    assert body["needs_category"] is False
    assert body["category"] == "Groceries"
    assert "categories" not in body and "category_names" not in body
    assert body["buckets"][0]["id"] == ctx.main.id


def test_no_match_lists_categories_and_buckets_chosen_first(client, ctx):
    body = _add(client, ctx.smart_h)
    assert body["needs_category"] is True
    assert {c["name"] for c in body["categories"]} >= {"Groceries", "Coffee"}
    assert body["category_names"] == [c["name"] for c in body["categories"]]
    assert body["buckets"][0]["id"] == body["bucket_id"]
    assert {b["name"] for b in body["buckets"]} == {ctx.main.name, "Fun money"}
    assert body["bucket_names"] == [b["name"] for b in body["buckets"]]


def test_existing_keys_are_unchanged(client, ctx):
    body = _add(client, ctx.plain_h, merchant="Sklavenitis")
    assert set(body) == OLD_KEYS | {"needs_category"}


def test_ingest_only_token_gets_no_lists(client, ctx):
    body = _add(client, ctx.plain_h)
    assert body["needs_category"] is True
    assert set(body) == OLD_KEYS | {"needs_category"}


def test_duplicate_carries_the_same_additions(client, ctx):
    at = "2026-10-01T12:34:00Z"
    _add(client, ctx.smart_h, occurred_at=at)
    again = _add(client, ctx.smart_h, occurred_at=at)
    assert again["duplicate"] is True
    assert again["needs_category"] is True and again["categories"]


# ---------------------------------------------------------------- classify


def test_classify_by_name_trimmed_and_case_insensitive(client, db, ctx):
    tid = _add(client, ctx.smart_h)["id"]
    r = client.post(classify_url(tid), json={"category": "  coFFee "}, headers=ctx.smart_h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["needs_category"] is False
    assert body["category"] == "Coffee" and body["category_id"] == ctx.coffee.id
    assert "categories" not in body
    assert db.get(Transaction, tid).category_id == ctx.coffee.id


def test_classify_by_id_and_bucket_by_name(client, db, ctx):
    tid = _add(client, ctx.smart_h)["id"]
    r = client.post(
        classify_url(tid),
        json={"category": ctx.groceries.id, "bucket": "fun MONEY"},
        headers=ctx.smart_h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["bucket_id"] == ctx.fun.id
    assert r.json()["buckets"][0]["id"] == ctx.fun.id
    db.expire_all()
    txn = db.get(Transaction, tid)
    assert (txn.category_id, txn.bucket_id) == (ctx.groceries.id, ctx.fun.id)


def test_bucket_only_by_id(client, db, ctx):
    tid = _add(client, ctx.smart_h)["id"]
    r = client.post(classify_url(tid), json={"bucket": ctx.fun.id}, headers=ctx.smart_h)
    assert r.status_code == 200, r.text
    assert r.json()["needs_category"] is False or r.json()["category_id"] is None


def test_list_and_dict_values_are_accepted(client, db, ctx):
    tid = _add(client, ctx.smart_h)["id"]
    r = client.post(classify_url(tid), json={"category": ["Coffee"]}, headers=ctx.smart_h)
    assert r.status_code == 200, r.text
    assert r.json()["category"] == "Coffee"
    r = client.post(
        classify_url(tid),
        json={
            "category": {"name": "Groceries", "id": "ignored"},
            "bucket": [{"name": "Fun money"}],
        },
        headers=ctx.smart_h,
    )
    assert r.status_code == 200, r.text
    assert (r.json()["category"], r.json()["bucket"]) == ("Groceries", "Fun money")


def test_unknown_names_are_422(client, ctx):
    tid = _add(client, ctx.smart_h)["id"]
    r = client.post(classify_url(tid), json={"category": "Nope"}, headers=ctx.smart_h)
    assert r.status_code == 422
    assert r.json()["detail"] == "Unknown category 'Nope'"
    r = client.post(classify_url(tid), json={"bucket": "Nope"}, headers=ctx.smart_h)
    assert r.status_code == 422
    assert r.json()["detail"] == "Unknown bucket 'Nope'"


@pytest.mark.parametrize("body", [{}, {"remember": True}, {"category": "  "}, {"category": None}])
def test_needs_a_category_or_a_bucket(client, ctx, body):
    tid = _add(client, ctx.smart_h)["id"]
    assert client.post(classify_url(tid), json=body, headers=ctx.smart_h).status_code == 422


def test_another_category_of_another_household_is_unknown(client, db, ctx, make_household):
    other = make_household()
    foreign = Category(household_id=other.household_id, name="Foreign", icon="x")
    db.add(foreign)
    db.commit()
    tid = _add(client, ctx.smart_h)["id"]
    r = client.post(classify_url(tid), json={"category": foreign.id}, headers=ctx.smart_h)
    assert r.status_code == 422


# ---------------------------------------------------------------- authorization


def _bare_404(r):
    assert r.status_code == 404, r.text
    assert r.json() == {"detail": "Not Found"}


def test_another_tokens_transaction_is_404(client, db, ctx):
    tid = _add(client, ctx.plain_h)["id"]  # made by the other token of the same member
    _bare_404(client.post(classify_url(tid), json={"category": "Coffee"}, headers=ctx.smart_h))
    assert db.get(Transaction, tid).category_id is None


def test_another_households_transaction_is_404(client, db, ctx, make_household):
    other = make_household()
    db.get(Bucket, other.bucket_id).type = BucketType.day2day
    _, raw = issue_personal_token(
        db, user_id=other.user_id, household_id=other.household_id, name="x", allow_classify=True
    )
    db.commit()
    tid = _add(client, _bearer(raw))["id"]
    _bare_404(client.post(classify_url(tid), json={"category": "Coffee"}, headers=ctx.smart_h))


def test_unknown_id_is_404(client, ctx):
    _bare_404(client.post(classify_url("nope"), json={"category": "x"}, headers=ctx.smart_h))
    _bare_404(client.post(classify_url("n" * 200), json={"category": "x"}, headers=ctx.smart_h))


def test_older_than_15_minutes_is_404(client, db, ctx):
    tid = _add(client, ctx.smart_h)["id"]
    db.get(Transaction, tid).created_at = utcnow_naive() - timedelta(minutes=16)
    db.commit()
    _bare_404(client.post(classify_url(tid), json={"category": "Coffee"}, headers=ctx.smart_h))


def test_deleted_is_404(client, db, ctx):
    tid = _add(client, ctx.smart_h)["id"]
    db.get(Transaction, tid).deleted_at = utcnow_naive()
    db.commit()
    _bare_404(client.post(classify_url(tid), json={"category": "Coffee"}, headers=ctx.smart_h))


def test_a_manually_added_transaction_is_404(client, db, ctx):
    # Same household, recent, but no ingest attempt of this token made it.
    tid = _add(client, ctx.smart_h)["id"]
    db.query(IngestAttempt).filter_by(transaction_id=tid).delete()
    db.commit()
    _bare_404(client.post(classify_url(tid), json={"category": "Coffee"}, headers=ctx.smart_h))


def test_a_user_jwt_cannot_classify(client, api, ctx):  # noqa: F811
    headers, _ = api
    tid = _add(client, ctx.smart_h)["id"]
    assert (
        client.post(classify_url(tid), json={"category": "Coffee"}, headers=headers).status_code
        == 401
    )


# ---------------------------------------------------------------- scope


def test_ingest_only_token_cannot_classify(client, db, ctx):
    tid = _add(client, ctx.plain_h)["id"]
    r = client.post(classify_url(tid), json={"category": "Coffee"}, headers=ctx.plain_h)
    assert r.status_code == 403
    assert r.json()["detail"] == (
        "This token cannot classify. Create a token with the category prompt enabled."
    )
    assert db.get(Transaction, tid).category_id is None
    last = db.query(IngestAttempt).order_by(IngestAttempt.created_at.desc()).first()
    assert last.status == 403 and "cannot classify" in last.detail


def test_classify_scope_is_opt_in_at_creation(db, ctx):
    assert ctx.plain.scope_list == ["ingest"]
    assert ctx.smart.scope_list == ["ingest", "classify"]


# ---------------------------------------------------------------- no rules from a token


def _rules(db, ctx):
    return sorted(
        (r.id, r.pattern, r.category_id)
        for r in db.query(CategoryRule).filter_by(household_id=ctx.hh.household_id)
    )


@pytest.mark.parametrize("remember", [True, "true", 1, {"x": 1}])
def test_remember_is_ignored_and_creates_no_rule(client, db, ctx, remember):
    before = _rules(db, ctx)
    tid = _add(client, ctx.smart_h)["id"]
    r = client.post(
        classify_url(tid), json={"category": "Coffee", "remember": remember}, headers=ctx.smart_h
    )
    assert r.status_code == 200, r.text
    assert r.json()["category"] == "Coffee"
    assert "remembered" not in r.json() and "remember_skipped" not in r.json()
    assert _rules(db, ctx) == before
    # So the next purchase there is asked about again.
    assert _add(client, ctx.smart_h, amount="9")["needs_category"] is True


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/v1/settings/category-rules"),
        ("patch", "/api/v1/settings/category-rules/x"),
        ("put", "/api/v1/settings/category-rules/x"),
        ("delete", "/api/v1/settings/category-rules/x"),
        ("post", "/settings/category-rules"),
    ],
)
def test_a_token_cannot_touch_rules_by_any_path(client, db, ctx, method, path):
    before = _rules(db, ctx)
    for headers in (ctx.plain_h, ctx.smart_h):
        r = client.request(method, path, headers=headers, json={"pattern": "x"})
        assert not 200 <= r.status_code < 300, (path, r.status_code)
    assert _rules(db, ctx) == before


# ---------------------------------------------------------------- log, limits, powers


def test_classification_is_logged_and_listed(client, db, api, ctx):  # noqa: F811
    tid = _add(client, ctx.smart_h)["id"]
    client.post(
        classify_url(tid), json={"category": "Coffee", "bucket": "Fun money"}, headers=ctx.smart_h
    )
    last = db.query(IngestAttempt).order_by(IngestAttempt.created_at.desc()).first()
    assert last.status == 200 and last.transaction_id == tid
    assert last.detail.startswith("classified: ")
    assert "Coffee" in last.detail and "Fun money" in last.detail
    headers, hh = api
    # (The listing is the caller's own: the api fixture is another user.)
    assert client.get("/api/v1/ingest/attempts", headers=headers).json() == {"items": []}


def test_classification_outcome_in_attempts_endpoint(client, db, ctx):
    import pyotp

    from tests.conftest import PASSWORD

    r = client.post("/api/v1/auth/login", json={"username": ctx.hh.username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    r = client.post(
        "/api/v1/auth/totp/verify",
        json={"pending_token": r.json()["pending_token"], "code": pyotp.TOTP(ctx.hh.secret).now()},
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    tid = _add(client, ctx.smart_h)["id"]
    client.post(classify_url(tid), json={"category": "Coffee"}, headers=ctx.smart_h)
    client.post(classify_url(tid), json={"category": "Nope"}, headers=ctx.smart_h)
    items = client.get("/api/v1/ingest/attempts", headers=headers).json()["items"]
    assert [i["outcome"] for i in items] == ["rejected", "classified", "created"]
    assert items[1]["status"] == 200


def test_classify_is_rate_limited_like_ingest(client, ctx):
    for _ in range(60):
        assert (
            client.post(classify_url("x"), json={"category": "a"}, headers=ctx.smart_h).status_code
            == 404
        )
    r = client.post(classify_url("x"), json={"category": "a"}, headers=ctx.smart_h)
    assert r.status_code == 429


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v1/buckets"),
        ("get", "/api/v1/settings/category-rules"),
        ("get", "/api/v1/transactions"),
        ("get", "/api/v1/settings/tokens"),
        ("get", "/api/v1/ingest/attempts"),
        ("post", "/api/v1/settings/tokens"),
    ],
)
def test_tokens_cannot_call_any_other_api(client, ctx, method, path):
    for headers in (ctx.plain_h, ctx.smart_h):
        assert getattr(client, method)(path, headers=headers).status_code == 401


# ---------------------------------------------------------------- token creation


def test_api_token_creation_with_and_without_the_flag(client, db, api):  # noqa: F811
    headers, _ = api
    r = client.post("/api/v1/settings/tokens", headers=headers, json={"name": "plain"})
    assert r.status_code == 201, r.text
    assert r.json()["scopes"] == ["ingest"] and r.json()["can_classify"] is False
    r = client.post(
        "/api/v1/settings/tokens", headers=headers, json={"name": "smart", "allow_classify": True}
    )
    assert r.status_code == 201, r.text
    assert r.json()["scopes"] == ["ingest", "classify"] and r.json()["can_classify"] is True
    listed = {t["name"]: t for t in client.get("/api/v1/settings/tokens", headers=headers).json()}
    assert listed["plain"]["can_classify"] is False
    assert listed["smart"]["can_classify"] is True
    assert "token" not in listed["smart"]


def test_existing_ingest_only_tokens_behave_as_before(db, ctx):
    assert ctx.plain.can_classify is False


def test_html_form_checkbox_sets_the_scope(client, db, authed):
    r = client.get("/settings/automations")
    assert "allow_classify" in r.text and "shares your category and budget names" in r.text
    client.post("/settings/automations/tokens", headers=authed.headers, data={"name": "A"})
    client.post(
        "/settings/automations/tokens",
        headers=authed.headers,
        data={"name": "B", "allow_classify": "1"},
    )
    from app.models import PersonalApiToken

    scopes = {t.name: t.scopes for t in db.query(PersonalApiToken).all()}
    assert scopes == {"A": "ingest", "B": "ingest,classify"}


def test_guide_has_the_ask_for_a_category_recipe(client, authed):
    text = client.get("/settings/automations").text
    assert "Ask for a category" in text
    assert "needs_category" in text and "category_names" in text and "/classify" in text
