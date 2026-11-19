"""Shared wire-format validation. Money is stored as decimal strings."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
import re


class BusinessError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.status = code, status


def require(condition, code, message, status=400):
    if not condition:
        raise BusinessError(code, message, status)


def identifier(value, field="user_id"):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value),
            "invalid_identifier", f"{field} must be 1-64 ASCII letters, digits, _ or -")
    return value


def number(value, field, *, positive=False, maximum="1000000000000"):
    require(not isinstance(value, bool) and isinstance(value, (str, int, float, Decimal)),
            "invalid_number", f"{field} must be a decimal string or number")
    raw = str(value)
    require(len(raw) <= 50, "invalid_number", f"{field} is too long")
    try:
        result = Decimal(raw)
    except InvalidOperation:
        raise BusinessError("invalid_number", f"{field} is not a decimal") from None
    require(result.is_finite() and result >= 0 and result <= Decimal(maximum),
            "invalid_number", f"{field} is outside the supported range")
    require(not positive or result > 0, "invalid_number", f"{field} must be positive")
    require(result == 0 or result.as_tuple().exponent >= -8,
            "invalid_precision", f"{field} supports at most 8 decimal places")
    return result


def amount(value):
    with localcontext() as context:
        context.prec = 60
        value = value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_EVEN)
    return format(value, "f").rstrip("0").rstrip(".") if value else "0"


def asset(value):
    require(isinstance(value, str), "invalid_asset", "asset must be a string")
    result = value.strip().upper()
    require(re.fullmatch(r"[A-Z0-9]{1,20}", result), "invalid_asset", "invalid asset code")
    return result


def pair(value):
    require(isinstance(value, str), "invalid_symbol", "symbol must be BASE/QUOTE")
    parts = re.split(r"[/_-]", value.strip().upper())
    require(len(parts) == 2, "invalid_symbol", "symbol must be BASE/QUOTE")
    base, quote = map(asset, parts)
    require(base != quote, "invalid_symbol", "base and quote must differ")
    return f"{base}/{quote}"


def timestamp(value):
    require(isinstance(value, str) and re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:[0-5]\d)", value),
        "invalid_timestamp", "as_of must be an RFC 3339 timestamp with a timezone")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        raise BusinessError("invalid_timestamp", "invalid as_of date") from None


def iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def text(value, field, maximum=500):
    require(isinstance(value, str) and 1 <= len(value.strip()) <= maximum,
            "invalid_text", f"{field} must contain 1-{maximum} characters")
    return value.strip()
