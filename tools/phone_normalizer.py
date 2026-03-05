"""
phone_normalizer.py — Normalize phone numbers to E.164 format.

Handles Mexican numbers (including the pre/post-2020 +52 vs +521 quirk)
and international numbers. Uses the phonenumbers library.
"""

import phonenumbers
from phonenumbers import PhoneNumberFormat, NumberParseException


DEFAULT_REGION = "MX"


def normalize_to_e164(raw_phone: str, default_region: str = DEFAULT_REGION) -> str | None:
    """
    Parse and normalize a phone number to E.164 format.

    Examples:
        "331 234 5678"       → "+523312345678"
        "+52 33 1234 5678"   → "+523312345678"
        "+1 555 123 4567"    → "+15551234567"

    Returns None if the number cannot be parsed or is invalid.
    """
    if not raw_phone:
        return None
    raw_phone = raw_phone.strip()
    # WhatsApp sends Mexican mobiles as 521XXXXXXXXXX (13 digits without +).
    # The phonenumbers library expects +52XXXXXXXXXX (10 digits after country code).
    # Strip the legacy mobile '1' prefix for MX numbers.
    if raw_phone.startswith("+521") and len(raw_phone) == 14:
        raw_phone = "+52" + raw_phone[4:]
    elif raw_phone.startswith("521") and len(raw_phone) == 13:
        raw_phone = "+52" + raw_phone[3:]
    try:
        parsed = phonenumbers.parse(raw_phone, default_region)
        if not phonenumbers.is_valid_number(parsed):
            return None
        return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
    except NumberParseException:
        return None


def to_whatsapp_format(e164_phone: str) -> str:
    """
    Convert E.164 to WhatsApp API format (E.164 without the leading '+').

    "+523312345678" → "523312345678"
    """
    return e164_phone.lstrip("+")


def is_international(e164_phone: str) -> bool:
    """
    Return True if the number is NOT a Mexican number.
    Used to decide escalation handling for foreign clients.
    """
    try:
        parsed = phonenumbers.parse(e164_phone)
        return parsed.country_code != 52
    except NumberParseException:
        return False


def normalize_for_whatsapp(raw_phone: str, default_region: str = DEFAULT_REGION) -> str | None:
    """
    Convenience: normalize raw phone string directly to WhatsApp format.
    Returns None if invalid.
    """
    e164 = normalize_to_e164(raw_phone, default_region)
    if not e164:
        return None
    return to_whatsapp_format(e164)
