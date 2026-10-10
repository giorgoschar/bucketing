"""2d §7.6: per-type mutes per member and household, applied inside
create_notification (no row, no push); general can't be muted."""

from app.models import (
    Household,
    HouseholdMember,
    MemberRole,
    Notification,
    NotificationMute,
    NotificationType,
    PushSubscription,
)
from app.services.notification_prefs import ALERT_TYPES
from app.services.notifications import create_notification
from tests.test_api import api  # noqa: F401  (fixture)

URL = "/api/v1/settings/notifications"


def test_catalog_covers_every_type_but_general():
    assert {a.type for a in ALERT_TYPES} == {t.value for t in NotificationType} - {"general"}
    assert len(ALERT_TYPES) == 10


def test_get_lists_types_on_by_default_and_counts_devices(client, db, api):  # noqa: F811
    headers, hh = api
    db.add(
        PushSubscription(
            user_id=hh.user_id,
            household_id=hh.household_id,
            endpoint="https://web.push.apple.com/x",
            p256dh="k",
            auth="a",
        )
    )
    db.commit()
    body = client.get(URL, headers=headers).json()
    assert body["push_devices"] == 1
    assert [t["type"] for t in body["types"]][:3] == ["bill_due", "bill_overdue", "bill_auto_paid"]
    assert all(t["enabled"] for t in body["types"])
    assert {t["group"] for t in body["types"]} == {
        "Bills",
        "Budgets",
        "Pantry",
        "Apple Pay",
        "Insights",
    }


def test_put_replaces_the_set_and_mutes_creation(client, db, api):  # noqa: F811
    headers, hh = api
    r = client.put(URL, headers=headers, json={"disabled": ["bill_due", "price_drop"]})
    assert r.status_code == 200, r.text
    off = {t["type"] for t in r.json()["types"] if not t["enabled"]}
    assert off == {"bill_due", "price_drop"}
    assert (
        create_notification(
            db,
            household_id=hh.household_id,
            user_id=hh.user_id,
            type=NotificationType.bill_due,
            title="Due",
        )
        is None
    )
    assert (
        create_notification(
            db,
            household_id=hh.household_id,
            user_id=hh.user_id,
            type=NotificationType.bill_overdue,
            title="Late",
        )
        is not None
    )
    db.commit()
    # (the api fixture's own sign-in alert is a `general` notification)
    made = db.query(Notification.type).filter(Notification.type != NotificationType.general).all()
    assert [t for (t,) in made] == [NotificationType.bill_overdue]

    r = client.put(URL, headers=headers, json={"disabled": []})
    assert all(t["enabled"] for t in r.json()["types"])


def test_general_and_unknown_cannot_be_muted(client, api):  # noqa: F811
    headers, _ = api
    for bad in (["general"], ["nope"]):
        assert client.put(URL, headers=headers, json={"disabled": bad}).status_code == 400


def test_mutes_are_per_household(client, db, api):  # noqa: F811
    headers, hh = api
    client.put(URL, headers=headers, json={"disabled": ["bill_due"]})
    second = Household(name="Second", default_currency="EUR")
    db.add(second)
    db.flush()
    db.add(HouseholdMember(household_id=second.id, user_id=hh.user_id, role=MemberRole.member))
    db.commit()
    assert (
        create_notification(
            db,
            household_id=second.id,
            user_id=hh.user_id,
            type=NotificationType.bill_due,
            title="Due",
        )
        is not None
    )


def test_a_muted_scheduler_alert_sends_no_push(db, make_household, monkeypatch):
    from app.scheduler import _notify_members
    from app.services.notification_prefs import set_muted

    hh = make_household()
    set_muted(db, hh.user_id, hh.household_id, ["bill_auto_paid"])
    db.commit()
    sent = []
    monkeypatch.setattr(
        "app.services.notifications.send_push_for_notification",
        lambda db, n, target_subs=None: sent.append(n) or 0,
    )
    _notify_members(
        db,
        [hh.user_id],
        household_id=hh.household_id,
        type=NotificationType.bill_auto_paid,
        title="Auto-paid: X",
        body=None,
        link="/bills",
        dedupe_key="bill_auto_paid:x",
    )
    db.commit()
    assert db.query(Notification).count() == 0 and sent == []


def test_set_muted_survives_a_concurrent_insert_conflict(db, make_household, monkeypatch):
    """Two PUTs racing: the other request's row lands between our delete and
    insert, so our insert hits the primary key. We retry once instead of 500."""
    from sqlalchemy import insert

    from app.services.notification_prefs import muted_types, set_muted

    hh = make_household()
    real_add = db.add
    raced = []

    def add_with_race(obj):
        if not raced:
            raced.append(True)
            db.execute(
                insert(NotificationMute).values(
                    user_id=obj.user_id, household_id=obj.household_id, type=obj.type
                )
            )
        return real_add(obj)

    monkeypatch.setattr(db, "add", add_with_race)
    set_muted(db, hh.user_id, hh.household_id, ["bill_due", "stock_low"])
    db.commit()
    assert raced
    assert muted_types(db, hh.user_id, hh.household_id) == {"bill_due", "stock_low"}
