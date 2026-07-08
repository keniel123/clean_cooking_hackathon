import pytest

from app.phone import PhoneError, normalize_phone


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Kenya
        ("0712 345 678", "+254712345678"),
        ("0112345678", "+254112345678"),
        ("254712345678", "+254712345678"),
        ("+254712345678", "+254712345678"),
        ("00254712345678", "+254712345678"),
        ("712345678", "+254712345678"),  # bare, default country KE
        # UK (11-digit local numbers are unambiguous)
        ("07911 123456", "+447911123456"),
        ("+44 7911 123456", "+447911123456"),
        ("447911123456", "+447911123456"),
        ("0044 7911 123456", "+447911123456"),
    ],
)
def test_normalizes(raw, expected):
    assert normalize_phone(raw, "KE") == expected


def test_bare_uk_number_with_gb_default():
    assert normalize_phone("7911123456", "GB") == "+447911123456"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "12345",
        "+2547123",  # too short for KE
        "0812345678",  # KE numbers start 07/01
        "+447811",  # too short for UK
        "hello",
        "+254912345678",  # 9 is not a Kenyan mobile prefix
    ],
)
def test_rejects(raw):
    with pytest.raises(PhoneError):
        normalize_phone(raw, "KE")


def test_other_country_codes_pass_through():
    assert normalize_phone("+4915112345678", "KE") == "+4915112345678"
