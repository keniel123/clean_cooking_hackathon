"""Normalise phone numbers to E.164, with strict rules for Kenyan and UK mobiles.

Kenyan mobiles:  +2547XXXXXXXX or +2541XXXXXXXX (Safaricom, Airtel, Telkom)
UK mobiles:      +447XXXXXXXXX (for testing from Europe)
Other countries: accepted as-is if they look like plausible E.164.
"""

import re


class PhoneError(ValueError):
    """Raised when a phone number cannot be normalised to E.164."""


_KE_MOBILE = re.compile(r"^\+254[17]\d{8}$")
_UK_MOBILE = re.compile(r"^\+447\d{9}$")
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone(raw: str, default_country: str = "KE") -> str:
    if not raw or not raw.strip():
        raise PhoneError("empty phone number")
    cleaned = re.sub(r"[\s\-().]", "", raw.strip())
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]

    if not cleaned.startswith("+"):
        if cleaned.startswith("254"):
            cleaned = "+" + cleaned
        elif cleaned.startswith("44") and len(cleaned) == 12:
            cleaned = "+" + cleaned
        elif cleaned.startswith("0"):
            rest = cleaned[1:]
            # Local formats are distinguishable by length: KE mobiles are
            # 0 + 9 digits, UK mobiles are 0 + 10 digits.
            if len(rest) == 9 and rest[0] in "17":
                cleaned = "+254" + rest
            elif len(rest) == 10 and rest[0] == "7":
                cleaned = "+44" + rest
            else:
                raise PhoneError(f"unrecognised local number: {raw!r}")
        elif len(cleaned) == 9 and cleaned[0] in "17" and default_country == "KE":
            cleaned = "+254" + cleaned
        elif len(cleaned) == 10 and cleaned[0] == "7" and default_country == "GB":
            cleaned = "+44" + cleaned
        else:
            raise PhoneError(f"cannot interpret phone number: {raw!r}")

    if not re.fullmatch(r"\+\d+", cleaned):
        raise PhoneError(f"invalid characters in phone number: {raw!r}")

    if cleaned.startswith("+254"):
        if not _KE_MOBILE.match(cleaned):
            raise PhoneError(f"not a valid Kenyan mobile number: {raw!r}")
    elif cleaned.startswith("+44"):
        if not _UK_MOBILE.match(cleaned):
            raise PhoneError(f"not a valid UK mobile number: {raw!r}")
    elif not _E164.match(cleaned):
        raise PhoneError(f"not a valid E.164 number: {raw!r}")

    return cleaned
