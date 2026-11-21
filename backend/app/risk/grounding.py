"""Check explicit amounts/units without changing the meaning of the user's text."""
import re
from decimal import Decimal


UNIT_PATTERNS = {
    "rub": r"₽|(?<![а-яёa-z])руб(?:л(?:ь|я|ей|ях|ями|ям|ю))?\.?(?![а-яёa-z])|(?<!\w)(?:RUB|RUR)(?!\w)|(?<![а-яёa-z])р(?![а-яёa-z])",
    "usd": r"доллар|\$|(?<!\w)USD(?!\w)",
    "eur": r"евро|€|(?<!\w)EUR(?!\w)",
    "pt": r"пункт|(?<!\w)пт(?!\w)",
    "percent": r"%|процент",
}


def explicit_unit(text: str, unit: str) -> bool:
    return bool(re.search(UNIT_PATTERNS[unit], text, re.I))


def explicit_amounts(text: str) -> set[Decimal]:
    # A space groups exactly three digits; decimal comma remains a decimal separator.
    matches = re.findall(r"(?<!\d)\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?(?!\d)|\d+(?:[.,]\d+)?", text)
    return {Decimal(re.sub(r"[ \u00a0\u202f]", "", amount).replace(",", ".")) for amount in matches}


class PlanValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
