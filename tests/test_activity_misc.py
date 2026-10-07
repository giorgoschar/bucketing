"""Counts, duplicates, receipt and history (2c spec §5.1-5.2; §9 item 11)."""

from datetime import timedelta
from decimal import Decimal

from app.core.clock import local_today, utcnow_naive
from app.models import BillOccurrence, OccurrenceStatus, Transaction, TransactionType
from app.services.cash import FROM_BANK, link_take
from tests.test_api import api  # noqa: F401

URL = "/api/v1/transactions"


def add(db, hh, amount, **kw) -> str:
    fields = dict(
        household_id=hh.household_id,
        bucket_id=hh.bucket_id,
        amount=Decimal(amount),
        type=TransactionType.expense,
        paid_by=hh.user_id,
        transaction_date=local_today(),
    )
    fields.update(kw)
    t = Transaction(**fields)
    db.add(t)
    db.commit()
    return t.id


def test_literal_routes_answer_before_txn_id(client, api):  # noqa: F811
    headers, _ = api
    counts = client.get(f"{URL}/counts", headers=headers)
    dups = client.get(f"{URL}/duplicates", headers=headers)
    assert counts.status_code == 200 and counts.json() == {"no_payer": 0, "duplicate_groups": 0}
    assert dups.status_code == 200 and dups.json() == {"groups": []}


def test_counts(client, db, api):  # noqa: F811
    headers, hh = api
    add(db, hh, "5.00", paid_by=None)
    add(db, hh, "6.00", paid_by=None, payer_mode="own_share")  # fully paid by design
    add(db, hh, "7.00", paid_by=None, type=TransactionType.income, bucket_id=None)
    add(db, hh, "9.99")
    add(db, hh, "9.99", transaction_date=local_today() - timedelta(days=2))
    assert client.get(f"{URL}/counts", headers=headers).json() == {
        "no_payer": 1,
        "duplicate_groups": 1,
    }


def test_duplicates_payload(client, db, api):  # noqa: F811
    headers, hh = api
    a, b = add(db, hh, "9.99"), add(db, hh, "9.99")
    [group] = client.get(f"{URL}/duplicates", headers=headers).json()["groups"]
    assert group["amount"] == 9.99
    assert {t["id"] for t in group["transactions"]} == {a, b}
    assert {"has_take", "created_at", "merchant"} <= set(group["transactions"][0])


def test_receipt(client, db, api, make_household, tmp_path, monkeypatch):  # noqa: F811
    import app.api.transactions as module

    monkeypatch.setattr(module, "UPLOADS_DIR", str(tmp_path))
    headers, hh = api
    (tmp_path / "r1.pdf").write_bytes(b"%PDF-1.4 receipt")
    own = add(db, hh, "3.00", receipt_path="r1.pdf")
    r = client.get(f"{URL}/{own}/receipt", headers=headers)
    assert r.status_code == 200 and r.content == b"%PDF-1.4 receipt"

    other = make_household(name="Other", username="other")
    (tmp_path / "r2.pdf").write_bytes(b"%PDF-1.4 theirs")
    foreign = add(db, other, "3.00", receipt_path="r2.pdf")
    deleted = add(db, hh, "3.00", receipt_path="r1.pdf", deleted_at=utcnow_naive())
    missing = add(db, hh, "3.00", receipt_path="gone.pdf")
    none = add(db, hh, "3.00")
    for txn_id in (foreign, deleted, missing, none):
        assert client.get(f"{URL}/{txn_id}/receipt", headers=headers).status_code == 404


def test_history_created_entry_and_cash(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    bill, occ = make_bill(hh.household_id, hh.bucket_id, name="Cosmote")
    pay = add(db, hh, "38.90", payment_method="cash", recurring_bill_id=bill.id)
    occ = db.get(BillOccurrence, occ.id)
    occ.status, occ.transaction_id = OccurrenceStatus.paid, pay
    occ.paid_at, occ.paid_by = utcnow_naive() + timedelta(seconds=1), hh.user_id
    link_take(db, db.get(Transaction, pay), hh.user_id, FROM_BANK, "EUR")
    db.commit()

    events = client.get(f"{URL}/{pay}/history", headers=headers).json()["events"]
    kinds = [e["kind"] for e in events]
    assert set(kinds) == {"created", "entry_linked", "cash_taken"}
    assert kinds[-1] == "created" and events[-1]["by"] is None  # oldest last; no "Added by"
    linked = next(e for e in events if e["kind"] == "entry_linked")
    assert linked["text"].startswith("Paid for Cosmote · ")
    assert client.get(f"{URL}/no-such/history", headers=headers).status_code == 404
