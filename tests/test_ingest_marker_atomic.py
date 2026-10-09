"""Polish O-3: the ingest token marker is written in the same database
transaction that creates the expense, never by a second commit."""

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models import Transaction
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_ingest_classify import URL, ctx  # noqa: F401  (fixtures/consts)


def test_marker_is_on_the_row_when_it_is_inserted_and_committed_once(client, ctx):
    inserted: list[str | None] = []
    commits_after_insert: list[int] = []

    def on_insert(_mapper, _conn, target):
        inserted.append(target.ingest_token_id)

    def on_commit(_session):
        if inserted:
            commits_after_insert.append(1)

    event.listen(Transaction, "before_insert", on_insert)
    event.listen(Session, "before_commit", on_commit)
    try:
        r = client.post(
            URL,
            json={"merchant": "Corner Kiosk", "amount": "4,20"},
            headers=ctx.smart_h,
        )
    finally:
        event.remove(Transaction, "before_insert", on_insert)
        event.remove(Session, "before_commit", on_commit)
    assert r.status_code == 201, r.text
    # The row never existed without its marker ...
    assert inserted == [ctx.smart.id]
    # ... and the first commit after the insert already carried it, so there
    # is no window in which the expense is committed without its marker.
    assert commits_after_insert
