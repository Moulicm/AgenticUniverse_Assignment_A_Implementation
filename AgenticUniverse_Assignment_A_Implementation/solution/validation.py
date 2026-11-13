from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def normalise_header(value: str) -> str:
    return re.sub(r"[_\s]+", " ", (value or "").strip().lower())


def normalise_phone(value: str) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] not in "6789":
        return None
    return "+91" + digits


def parse_date(value: str) -> str | None:
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def parse_decimal(value: str) -> str | None:
    text = (value or "").strip()
    text = re.sub(r"^(?:₹|rs\.?|inr)\s*", "", text, flags=re.IGNORECASE)
    text = text.replace(",", "")
    try:
        number = Decimal(text)
        if not number.is_finite() or number < 0:
            return None
        return str(number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None


def normalise_timestamp(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    from datetime import timezone, timedelta
    ist = timezone(timedelta(hours=5, minutes=30))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ist)
    return parsed.astimezone(ist)


def validate_value(field: dict, raw: str) -> tuple[object | None, str | None]:
    value = (raw or "").strip()
    if not value:
        return None, "missing"
    kind = field["type"]
    if kind == "string":
        return value, None
    if kind == "phone":
        phone = normalise_phone(value)
        return (phone, None) if phone else (None, "invalid_phone")
    if kind == "date":
        result = parse_date(value)
        return (result, None) if result else (None, "invalid")
    if kind == "decimal":
        result = parse_decimal(value)
        return (result, None) if result is not None else (None, "invalid")
    if kind == "enum":
        lowered = value.lower()
        allowed = {str(v).lower() for v in field.get("values", [])}
        return (lowered, None) if lowered in allowed else (None, "invalid")
    return value, None
