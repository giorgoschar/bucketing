"""One canonical reading of the Authorization header (review: parser
differential). The auth dependency, the rate-limit key and the recorders agree,
so spelling the header differently never buys a fresh rate-limit bucket."""

from types import SimpleNamespace

import pytest

from app.models import Bucket, BucketType, IngestAttempt
from app.services import issue_personal_token

URL = "/api/v1/ingest/apple-pay"


@pytest.fixture()
def ctx(app, db, make_household):
    hh = make_household()
    db.get(Bucket, hh.bucket_id).type = BucketType.day2day
    _, raw = issue_personal_token(
        db, user_id=hh.user_id, household_id=hh.household_id, name="iPhone"
    )
    db.commit()
    return SimpleNamespace(hh=hh, raw=raw)


SPELLINGS = [
    "Bearer {t}",
    "bearer {t}",
    "BEARER {t}",
    "Bearer   {t}",
    "Bearer {t} ",
    "  Bearer {t}",
    "Bearer\t{t}",
]


def _post(client, header, i=0, **kw):
    headers = {"Authorization": header} if header is not None else {}
    return client.post(URL, json={"merchant": f"S{i}", "amount": "1"}, headers=headers, **kw)


def test_varied_spellings_of_one_valid_token_share_one_limit(client, db, ctx):
    codes = [
        _post(client, SPELLINGS[i % len(SPELLINGS)].format(t=ctx.raw), i).status_code
        for i in range(70)
    ]
    assert codes[:60] == [201] * 60
    assert set(codes[60:]) == {429}


def test_varied_spellings_of_bad_bodies_share_that_limit_too(client, ctx):
    codes = []
    for i in range(70):
        header = SPELLINGS[i % len(SPELLINGS)].format(t=ctx.raw)
        r = client.post(
            URL,
            content="[1]",
            headers={"Authorization": header, "content-type": "application/json"},
        )
        codes.append(r.status_code)
    assert codes[:60] == [422] * 60 and set(codes[60:]) == {429}


def test_a_bare_token_without_the_scheme_is_not_authenticated(client, ctx):
    assert _post(client, ctx.raw).status_code == 401
    assert _post(client, f"Token {ctx.raw}").status_code == 401
    assert _post(client, f"Bearer {ctx.raw}XYZ").status_code == 401
    assert _post(client, f"Bearer {ctx.raw} extra").status_code == 401


def test_variants_of_an_invalid_token_share_the_per_ip_limit(client, ctx):
    bad = "pat_" + "x" * 32
    forms = SPELLINGS + [bad, f"Bearer {bad}x", f"Bearer {bad}y"]
    codes = [_post(client, forms[i % len(forms)].format(t=bad), i).status_code for i in range(30)]
    assert codes[:20] == [401] * 20 and set(codes[20:]) == {429}


def test_unauthenticated_requests_do_not_use_the_tokens_bucket(client, ctx):
    for i in range(25):
        _post(client, None, i)  # no header: per-IP failures, past 20 -> 429
    # The valid token is untouched by them.
    assert _post(client, f"Bearer {ctx.raw}", 99).status_code == 201


def test_more_than_one_authorization_header_is_400(client, db, ctx):
    r = client.post(
        URL,
        json={"merchant": "x", "amount": "1"},
        headers=[("authorization", f"Bearer {ctx.raw}"), ("authorization", f"Bearer {ctx.raw}")],
    )
    assert r.status_code == 400
    r = client.post(
        URL,
        content="[1]",
        headers=[
            ("authorization", f"Bearer {ctx.raw}"),
            ("authorization", "Bearer other"),
            ("content-type", "application/json"),
        ],
    )
    assert r.status_code == 400
    r = client.post(
        URL,
        content="{",  # not JSON: refused before the auth dependency runs
        headers=[
            ("authorization", f"Bearer {ctx.raw}"),
            ("authorization", f"Bearer {ctx.raw}"),
            ("content-type", "application/json"),
        ],
    )
    assert r.status_code == 400
    assert db.query(IngestAttempt).filter(IngestAttempt.household_id.isnot(None)).count() == 0


def test_the_limiter_key_comes_from_the_authenticated_token_not_the_header(ctx):
    from app.core.ratelimit import ingest_token_key

    def req(state_id, header):
        return SimpleNamespace(
            state=SimpleNamespace(**({"ingest_token_id": state_id} if state_id else {})),
            headers={"authorization": header},
            client=SimpleNamespace(host="9.9.9.9"),
        )

    assert ingest_token_key(req("tid", "Bearer a")) == ingest_token_key(req("tid", "bearer  b "))
    assert ingest_token_key(req("tid", "x")) != ingest_token_key(req("other", "x"))
    assert ingest_token_key(req(None, "Bearer a")) == ingest_token_key(req(None, "Bearer b"))
    assert "9.9.9.9" in ingest_token_key(req(None, "Bearer a"))


def test_one_canonical_reader():
    from app.api.ingest import bearer_token
    from app.api_auth import bearer_credential

    def req(*values):
        return SimpleNamespace(
            headers=SimpleNamespace(getlist=lambda name: list(values), get=lambda *a: None)
        )

    assert bearer_credential(req("Bearer  tok ")) == "tok"
    assert bearer_credential(req("bearer tok")) == "tok"
    assert bearer_credential(req("tok")) is None
    assert bearer_credential(req("Bearer a b")) is None
    assert bearer_credential(req()) is None
    assert bearer_token(req("Bearer  tok ")) == "tok"
    assert bearer_token(req("Bearer a", "Bearer b")) is None  # recorders never raise
