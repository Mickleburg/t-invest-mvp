from decimal import Decimal, InvalidOperation

def decimal_value(raw) -> Decimal | None:
    if not isinstance(raw, dict):
        return None
    try:
        if "value" in raw:
            value = Decimal(str(raw["value"]))
        elif "units" in raw and "nano" in raw:
            value = Decimal(str(raw["units"])) + Decimal(str(raw["nano"])) / Decimal(10**9)
        else:
            return None
        return value if value.is_finite() and value >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None
