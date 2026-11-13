import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from validation import normalise_phone, parse_date, parse_decimal, normalise_timestamp


def test_phone_formats_and_invalid_values():
    assert normalise_phone("91-77187-50036") == "+917718750036"
    assert normalise_phone("07718750036") == "+917718750036"
    assert normalise_phone("+91 77187 50036") == "+917718750036"
    assert normalise_phone("5718750036") is None


def test_day_first_dates_and_impossible_date():
    assert parse_date("01-Dec-2026") == "2026-12-01"
    assert parse_date("03/10/2026") == "2026-10-03"
    assert parse_date("31/02/2026") is None


def test_decimal_currency_and_rounding():
    assert parse_decimal("₹ 1,234.567") == "1234.57"
    assert parse_decimal("Rs. 10") == "10.00"
    assert parse_decimal("-1") is None


def test_naive_timestamp_means_ist():
    value = normalise_timestamp("2026-10-03 10:01:00")
    assert value.isoformat() == "2026-10-03T10:01:00+05:30"
