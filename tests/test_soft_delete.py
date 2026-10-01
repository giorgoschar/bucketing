"""Soft-deleted transactions, receipt trash, and archived households.

Data must be preserved: deleting a transaction only hides it, the receipt file
is moved (not removed), and the last member leaving archives the household.
"""
import os
import time
from datetime import timedelta

import pyotp
import pytest

from app.clock import local_today, utcnow_naive
from app.models import (
    Bucket,
    Household,
    HouseholdMember,
    Transaction,
    TransactionSplit,
    TransactionType,
    User,
)
from app.services import (
    base_ctx,
    delete_transaction,
    get_all_time_summary,
    get_bucket_balance,
    get_household_settlement,
    get_insights_summary,
    get_month_summary,
)
from tests.conftest import PASSWORD
from tests.test_household_settlement import _add_member, _shared_expense


@pytest.fixture(autouse=True)
def uploads_cwd(tmp_path, monkeypatch):
    """Receipts live in ./uploads; keep each test's files in its own dir."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _txn(db, hh, notes, amount=10, **kw):
    t = Transaction(
        bucket_id=hh.bucket_id, household_id=hh.household_id, amount=amount,
        currency="EUR", exchange_rate=1, type=TransactionType.expense,
        transaction_date=kw.pop("transaction_date", local_today()),
        paid_by=hh.user_id, notes=notes, **kw,
    )
    db.add(t)
    db.commit()
    return t


def _receipt(name="r1.jpg", content=b"img"):
    os.makedirs("uploads", exist_ok=True)
    path = os.path.join("uploads", name)
    with open(path, "wb") as f:
        f.write(content)
    return path


# ---- service ---------------------------------------------------------------

def test_delete_sets_deleted_at_and_keeps_row_and_splits(db, make_household):
    hh = make_household()
    t = _txn(db, hh, "shared")
    db.add(TransactionSplit(transaction_id=t.id, user_id=hh.user_id, amount=10))
    db.commit()

    delete_transaction(db, t)
    db.commit()

    row = db.query(Transaction).filter_by(id=t.id).one()
    assert row.deleted_at is not None
    assert db.query(TransactionSplit).filter_by(transaction_id=t.id).count() == 1


def test_delete_moves_receipt_to_trash(db, make_household):
    hh = make_household()
    _receipt("r1.jpg")
    t = _txn(db, hh, "with receipt", receipt_path="r1.jpg")

    delete_transaction(db, t)
    db.commit()

    assert not os.path.exists("uploads/r1.jpg")
    assert os.path.exists("uploads/.trash/r1.jpg")
    assert db.get(Transaction, t.id).receipt_path == "r1.jpg"


def test_delete_with_missing_receipt_file_still_works(db, make_household):
    hh = make_household()
    t = _txn(db, hh, "ghost", receipt_path="gone.jpg")
    delete_transaction(db, t)
    db.commit()
    assert db.get(Transaction, t.id).deleted_at is not None


# ---- exclusion from every read ---------------------------------------------

def test_deleted_absent_from_summaries_and_insights(db, make_household):
    hh = make_household()
    _txn(db, hh, "keep", 10)
    gone = _txn(db, hh, "gone", 90)
    delete_transaction(db, gone)
    db.commit()
    today = local_today()

    assert get_month_summary(db, hh.household_id, today.year, today.month)["total_spent"] == 10
    assert get_all_time_summary(db, hh.household_id)["total_spent"] == 10
    assert get_insights_summary(db, hh.household_id, None, None)["total_spent"] == 10
    assert get_bucket_balance(db, hh.bucket_id)["expenses"] == 10


def test_deleted_absent_from_settlement(db, make_household):
    hh = make_household()
    partner = _add_member(db, hh.household_id, "partner")
    bucket = db.get(Bucket, hh.bucket_id)
    bucket.enable_settlement = True
    db.commit()
    members = [hh.user_id, partner.id]
    _shared_expense(db, hh.bucket_id, hh.household_id, hh.user_id, members, 100)
    gone = _shared_expense(db, hh.bucket_id, hh.household_id, hh.user_id, members, 500)
    db.commit()
    delete_transaction(db, gone)
    db.commit()

    debts = get_household_settlement(db, hh.household_id)
    assert [round(d["amount"]) for d in debts] == [50]


def test_deleted_absent_from_bucket_view_and_search(client, db, authed):
    _txn(db, authed, "needle-visible", 5)
    gone = _txn(db, authed, "needle-hidden", 7)
    r = client.post(f"/transactions/{gone.id}/delete", headers=authed.headers)
    assert r.status_code in (200, 302)

    page = client.get(f"/buckets/{authed.bucket_id}").text
    assert "needle-visible" in page and "needle-hidden" not in page
    page = client.get(f"/buckets/{authed.bucket_id}?all_time=1").text
    assert "needle-hidden" not in page

    body = client.get("/transactions/search?q=needle").text
    assert "needle-visible" in body and "needle-hidden" not in body

    db.expire_all()
    assert db.get(Transaction, gone.id).deleted_at is not None


def test_deleted_transaction_edit_receipt_and_redelete_404(client, db, authed):
    _receipt("rr.jpg")
    gone = _txn(db, authed, "x", receipt_path="rr.jpg")
    client.post(f"/transactions/{gone.id}/delete", headers=authed.headers)
    assert client.get(f"/transactions/{gone.id}/edit").status_code == 404
    assert client.get("/transactions/files/rr.jpg").status_code == 404
    assert client.post(f"/transactions/{gone.id}/delete", headers=authed.headers).status_code == 404


def test_api_list_get_delete(client, db, make_household):
    hh = make_household(username="apiuser")
    r = client.post("/api/v1/auth/login", json={"username": hh.username, "password": PASSWORD})
    r = client.post("/api/v1/auth/totp/verify", json={
        "pending_token": r.json()["pending_token"], "code": pyotp.TOTP(hh.secret).now()})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    keep = _txn(db, hh, "keep")
    gone = _txn(db, hh, "gone")

    assert client.delete(f"/api/v1/transactions/{gone.id}", headers=h).status_code == 204
    body = client.get("/api/v1/transactions", headers=h).json()
    ids = [i["id"] for i in body["items"]]
    assert keep.id in ids and gone.id not in ids
    assert body["total"] == 1
    assert client.get(f"/api/v1/transactions/{gone.id}", headers=h).status_code == 404
    db.expire_all()
    assert db.get(Transaction, gone.id).deleted_at is not None


def test_client_id_of_deleted_txn_is_a_clear_error(client, db, authed):
    url = "/transactions"
    data = {"bucket_id": authed.bucket_id, "amount": "5", "type": "expense",
            "client_id": "abc", "transaction_date": local_today().isoformat()}
    r = client.post(url, headers=authed.headers, data=data)
    assert r.status_code in (200, 302), r.text[:200]
    t = db.query(Transaction).filter_by(client_id="abc").one()
    client.post(f"/transactions/{t.id}/delete", headers=authed.headers)
    r = client.post(url, headers=authed.headers, data=data)
    assert r.status_code == 409
    db.expire_all()
    assert db.query(Transaction).filter_by(client_id="abc").count() == 1


# ---- trash purge -----------------------------------------------------------

def test_purge_trash_removes_only_old_files(db):
    from app.scheduler import _purge_trash, today_local
    os.makedirs("uploads/.trash")
    old, new, live = "uploads/.trash/old.jpg", "uploads/.trash/new.jpg", "uploads/live.jpg"
    for p in (old, new, live):
        with open(p, "wb") as f:
            f.write(b"x")
    past = time.time() - 31 * 86400
    os.utime(old, (past, past))
    os.utime(live, (past, past))

    _purge_trash(db, today_local())

    assert not os.path.exists(old)
    assert os.path.exists(new)
    assert os.path.exists(live)


def test_purge_trash_never_touches_db_rows(db, make_household):
    from app.scheduler import _purge_trash, today_local
    hh = make_household()
    t = _txn(db, hh, "x")
    t.deleted_at = utcnow_naive() - timedelta(days=90)
    db.commit()
    _purge_trash(db, today_local())
    assert db.query(Transaction).count() == 1


def test_purge_trash_registered_in_job():
    import inspect

    import app.scheduler as s
    assert "_purge_trash" in inspect.getsource(s.auto_mark_paid_job)


# ---- archive instead of delete household -----------------------------------

def test_leave_last_member_requires_confirm_name(client, db, authed):
    _txn(db, authed, "keepme")
    for data in ({}, {"confirm_name": "wrong"}):
        r = client.post("/settings/leave-household", headers=authed.headers, data=data)
        assert r.status_code in (200, 422), r.status_code
        db.expire_all()
        assert db.get(Household, authed.household_id).archived_at is None
        assert db.query(HouseholdMember).filter_by(household_id=authed.household_id).count() == 1


def test_leave_last_member_archives_and_preserves_data(client, db, authed):
    _txn(db, authed, "keepme")
    name = db.get(Household, authed.household_id).name
    r = client.post("/settings/leave-household", headers=authed.headers,
                    data={"confirm_name": name})
    assert r.status_code == 302
    db.expire_all()
    hh = db.get(Household, authed.household_id)
    assert hh is not None and hh.archived_at is not None
    assert db.query(Transaction).filter_by(household_id=authed.household_id).count() == 1
    assert db.query(Bucket).filter_by(household_id=authed.household_id).count() == 1


def test_archived_household_hidden_from_switcher(db, make_household):
    a = make_household(name="Alive", username="u_alive")
    b = make_household(name="Dead", username="u_dead")
    db.add(HouseholdMember(household_id=b.household_id, user_id=a.user_id))
    db.get(Household, b.household_id).archived_at = utcnow_naive()
    db.commit()
    ctx = base_ctx(db, db.get(User, a.user_id), a.household_id)
    assert [h.name for h in ctx["households"]] == ["Alive"]


# ---- purge script ----------------------------------------------------------

def _purge_module():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "scripts" / "purge_household.py"
    spec = importlib.util.spec_from_file_location("purge_household", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_purge_script_refuses_non_archived(db, make_household):
    hh = make_household()
    assert _purge_module().purge(db, hh.household_id, execute=True) != 0
    assert db.get(Household, hh.household_id) is not None


def test_purge_script_dry_run_deletes_nothing(db, make_household, capsys):
    hh = make_household()
    _txn(db, hh, "x")
    db.get(Household, hh.household_id).archived_at = utcnow_naive()
    db.commit()
    assert _purge_module().purge(db, hh.household_id, execute=False) == 0
    assert db.get(Household, hh.household_id) is not None
    assert db.query(Transaction).count() == 1
    assert "transactions" in capsys.readouterr().out


def test_purge_script_executes_on_archived(db, make_household):
    hh = make_household()
    _txn(db, hh, "x")
    db.get(Household, hh.household_id).archived_at = utcnow_naive()
    db.commit()
    assert _purge_module().purge(db, hh.household_id, execute=True) == 0
    db.expire_all()
    assert db.get(Household, hh.household_id) is None
    assert db.query(Transaction).count() == 0


def test_purge_script_cli_requires_explicit_flag():
    mod = _purge_module()
    assert mod.parse_args(["abc"]).execute is False
    assert mod.parse_args(["abc", "--yes-delete-abc"]).execute is True
    assert mod.parse_args(["abc", "--yes-delete-other"]).execute is False


# ---- review fixes ----------------------------------------------------------

def test_trash_retention_counts_from_deletion_not_upload(db, make_household):
    from app.scheduler import _purge_trash, today_local
    hh = make_household()
    path = _receipt("old.jpg")
    old = time.time() - 90 * 86400
    os.utime(path, (old, old))
    t = _txn(db, hh, "x", receipt_path="old.jpg")

    delete_transaction(db, t)
    _purge_trash(db, today_local())
    assert os.path.exists("uploads/.trash/old.jpg")

    os.utime("uploads/.trash/old.jpg", (old, old))
    _purge_trash(db, today_local())
    assert not os.path.exists("uploads/.trash/old.jpg")


def test_move_failure_keeps_row_deleted_and_file_in_uploads(db, make_household, monkeypatch):
    import app.services.transactions as services
    hh = make_household()
    _receipt("keep.jpg")
    t = _txn(db, hh, "x", receipt_path="keep.jpg")

    def boom(*a, **k):
        raise OSError("disk")
    monkeypatch.setattr(services.shutil, "move", boom)
    delete_transaction(db, t)

    db.expire_all()
    assert db.get(Transaction, t.id).deleted_at is not None
    assert os.path.exists("uploads/keep.jpg")


def test_commit_failure_does_not_move_receipt(db, make_household, monkeypatch):
    hh = make_household()
    _receipt("stay.jpg")
    t = _txn(db, hh, "x", receipt_path="stay.jpg")

    def bad_commit():
        raise RuntimeError("commit failed")
    monkeypatch.setattr(db, "commit", bad_commit)
    with pytest.raises(RuntimeError):
        delete_transaction(db, t)
    assert os.path.exists("uploads/stay.jpg")
    assert not os.path.exists("uploads/.trash/stay.jpg")


def test_api_refuses_to_delete_bucket_with_transactions(client, db, make_household):
    hh = make_household(username="bk1")
    r = client.post("/api/v1/auth/login", json={"username": hh.username, "password": PASSWORD})
    r = client.post("/api/v1/auth/totp/verify", json={
        "pending_token": r.json()["pending_token"], "code": pyotp.TOTP(hh.secret).now()})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    t = _txn(db, hh, "x")
    delete_transaction(db, t)  # even a soft-deleted txn blocks deletion

    r = client.delete(f"/api/v1/buckets/{hh.bucket_id}", headers=h)
    assert r.status_code == 409
    assert "Archive" in r.json()["detail"]
    db.expire_all()
    assert db.get(Bucket, hh.bucket_id) is not None
    assert db.get(Transaction, t.id) is not None

    empty = Bucket(household_id=hh.household_id, name="Empty")
    db.add(empty)
    db.commit()
    assert client.delete(f"/api/v1/buckets/{empty.id}", headers=h).status_code == 204
