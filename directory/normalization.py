import re
import unicodedata

from django.core.exceptions import ValidationError


def clean_display_text(value):
    if value is None:
        return ""
    return " ".join(unicodedata.normalize("NFKC", str(value)).split())


def canonical_key(value):
    return clean_display_text(value).casefold()


def normalize_phone_number(value):
    raw_phone = clean_display_text(value)
    if not raw_phone:
        raise ValidationError("Patient mobile number is required.")
    if raw_phone.endswith(".0"):
        raw_phone = raw_phone[:-2]
    has_international_prefix = raw_phone.startswith(("+", "00"))
    digits = re.sub(r"\D", "", raw_phone)
    if raw_phone.startswith("00"):
        digits = digits[2:]
    if not 7 <= len(digits) <= 15:
        raise ValidationError("Enter a phone number containing 7 to 15 digits.")
    return f"+{digits}" if has_international_prefix else digits
