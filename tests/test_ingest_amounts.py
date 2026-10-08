"""Polish S4: the Apple Pay ingest reads the amount iOS's Transaction trigger
sends, a locale currency string ("12,50 €", "€1.234,56"), not just a plain
number. Ingest only: the shared parse_amount is unchanged."""

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models import Transaction
from app.services.ingest import parse_ingest_amount
from app.validators import parse_amount
from tests.test_ingest import URL, _post, ingest  # noqa: F401  (fixture)

D = Decimal
NBSP, NNBSP = " ", " "


@pytest.mark.parametrize(
    "raw,value,currency",
    [
        ("€12,50", "12.50", "EUR"),
        ("12,50 €", "12.50", "EUR"),
        ("EUR 12.50", "12.50", "EUR"),
        ("12.50EUR", "12.50", "EUR"),
        ("eur 12,50", "12.50", "EUR"),
        (f"12,50{NBSP}€", "12.50", "EUR"),
        (f"12,50{NNBSP}€", "12.50", "EUR"),
        ("  12,50  ", "12.50", None),
        ("1 2 , 5 0", "12.50", None),
        ("$12.50", "12.50", "USD"),
        ("£3", "3", "GBP"),
        ("12.50 USD", "12.50", "USD"),
        ("1.234,56", "1234.56", None),
        ("1,234.56", "1234.56", None),
        ("1 234,56", "1234.56", None),
        (f"1{NBSP}234,56 €", "1234.56", "EUR"),
        (f"1{NNBSP}234,56", "1234.56", None),
        ("€1.234,56", "1234.56", "EUR"),
        ("1.234.567,89", "1234567.89", None),
        ("1,234,567.89", "1234567.89", None),
        ("1.234.567", "1234567", None),
        ("1'234.56", "1234.56", None),
        ("1.234", "1234", None),
        ("1,234", "1234", None),
        ("12.345 €", "12345", "EUR"),
        ("12,5", "12.5", None),
        ("12.5", "12.5", None),
        ("0,5", "0.5", None),
        ("12.3456", "12.3456", None),
        ("12", "12", None),
        (12.5, "12.5", None),
        (7, "7", None),
        (D("3.20"), "3.2", None),
    ],
)
def test_amounts_ios_sends(raw, value, currency):
    got, detected = parse_ingest_amount(raw)
    assert got == D(value), raw
    assert detected == currency, raw


@pytest.mark.parametrize("raw", ["0.500", "0,125", ".500", ",125"])
def test_a_zero_whole_part_is_never_a_thousands_group(raw):
    assert parse_ingest_amount(raw)[0] == D(raw.replace(",", "."))


def test_three_digits_ending_in_two_zeros_are_a_padded_decimal():
    """ "12.500" is 12.50 written to three places (a pinned production
    behaviour: it must dedupe with "12,50"), not twelve thousand five hundred."""
    assert parse_ingest_amount("12.500")[0] == D("12.5")
    assert parse_ingest_amount("12,500")[0] == D("12.5")


@pytest.mark.parametrize("currency", ["BHD", "KWD", "OMR", "JOD", "TND", "bhd"])
def test_three_digits_are_decimals_for_three_decimal_currencies(currency):
    assert parse_ingest_amount("1.234", currency)[0] == D("1.234")
    assert parse_ingest_amount("1,234", currency)[0] == D("1.234")


def test_a_code_in_the_string_decides_the_three_digit_rule():
    assert parse_ingest_amount("KWD 1.234") == (D("1.234"), "KWD")
    assert parse_ingest_amount("1.234 EUR", "KWD") == (D("1234"), "EUR")
    assert parse_ingest_amount("1.234", "EUR")[0] == D("1234")


@pytest.mark.parametrize("raw", ["-3", "-€12,50", "€-12,50", "−12,50 €", "- 5", "0", "€0,00"])
def test_negative_refund_and_zero_amounts_stay_rejected(raw):
    with pytest.raises(HTTPException) as exc:
        parse_ingest_amount(raw)
    assert exc.value.status_code == 400
    assert exc.value.detail == "Amount must be greater than zero."


@pytest.mark.parametrize(
    "raw,echo",
    [
        ("abc", "abc"),
        ("12,50 euros please", "12,50 euros please"),
        ("twelve", "twelve"),
        ("1.2.3,4,5", "1.2.3,4,5"),
        ("(12,50)", "(12,50)"),
        ("12,50 € and a very long tail of text", "12,50 € and a very l"),
        ("€", "€"),
        ("1e5", "1e5"),
        ("NaN", "NaN"),
        ("Infinity", "Infinity"),
        ("12,50 € $", "12,50 € $"),
    ],
)
def test_non_numeric_is_a_400_that_echoes_the_start(raw, echo):
    with pytest.raises(HTTPException) as exc:
        parse_ingest_amount(raw)
    assert exc.value.status_code == 400
    assert exc.value.detail == f"Amount must be a number like 12,50 (got: '{echo}')"


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_blank_is_required(raw):
    with pytest.raises(HTTPException) as exc:
        parse_ingest_amount(raw)
    assert (exc.value.status_code, exc.value.detail) == (400, "Amount is required.")


def test_too_large_is_rejected():
    with pytest.raises(HTTPException) as exc:
        parse_ingest_amount("99.999.999.999.999,00 €")
    assert exc.value.status_code == 400


def test_the_shared_parser_is_unchanged():
    assert parse_amount("12,50") == D("12.5")
    assert parse_amount("1.234") == D("1.234")
    for raw in ("€12,50", "1.234,56", "12,50 €"):
        with pytest.raises(HTTPException) as exc:
            parse_amount(raw)
        assert exc.value.detail == "Amount must be a number."


# ---------------------------------------------------------------- endpoint


@pytest.mark.parametrize(
    "amount,stored,currency",
    [
        ("12,50 €", "12.5", "EUR"),
        ("€12,50", "12.5", "EUR"),
        (f"1{NBSP}234,56{NBSP}€", "1234.56", "EUR"),
        ("1.234,56", "1234.56", "EUR"),
        ("$7.25", "7.25", "USD"),
        ("GBP 3", "3", "GBP"),
    ],
)
def test_endpoint_accepts_locale_amounts(client, db, ingest, amount, stored, currency):  # noqa: F811
    r = _post(client, ingest, amount=amount)
    assert r.status_code == 201, r.text
    t = db.get(Transaction, r.json()["id"])
    assert (t.amount, t.currency) == (D(stored), currency)


def test_an_explicit_currency_wins_over_the_symbol(client, db, ingest):  # noqa: F811
    r = _post(client, ingest, amount="$7.25", currency="GBP")
    assert r.status_code == 201, r.text
    assert db.get(Transaction, r.json()["id"]).currency == "GBP"


def test_no_symbol_keeps_the_household_currency(client, db, ingest):  # noqa: F811
    from app.models import Household

    db.get(Household, ingest.hh.household_id).default_currency = "GBP"
    db.commit()
    r = _post(client, ingest, amount="1.234,56")
    assert db.get(Transaction, r.json()["id"]).currency == "GBP"


def test_locale_and_plain_amounts_dedupe(client, db, ingest):  # noqa: F811
    at = "2026-10-01T12:34:00+03:00"
    assert _post(client, ingest, amount="12,50 €", occurred_at=at).status_code == 201
    for again in ("12.50", 12.5, "€12,50", "EUR 12.50"):
        r = _post(client, ingest, amount=again, occurred_at=at)
        assert r.status_code == 200 and r.json()["duplicate"] is True, again
    assert db.query(Transaction).count() == 1


def test_endpoint_bad_amount_message(client, db, ingest):  # noqa: F811
    r = _post(client, ingest, amount="twelve euros")
    assert r.status_code == 400
    assert r.json() == {"detail": "Amount must be a number like 12,50 (got: 'twelve euros')"}
    r = _post(client, ingest, amount="-€12,50")
    assert r.status_code == 400 and r.json() == {"detail": "Amount must be greater than zero."}
    assert db.query(Transaction).count() == 0
