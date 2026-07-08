from app.sms_text import sms_segments


def test_short_gsm7_message_is_one_segment():
    assert sms_segments("How satisfied are you? Reply 1-5.") == 1


def test_160_chars_is_one_segment_and_161_is_two():
    assert sms_segments("a" * 160) == 1
    assert sms_segments("a" * 161) == 2


def test_multipart_uses_153_char_segments():
    assert sms_segments("a" * 306) == 2
    assert sms_segments("a" * 307) == 3


def test_non_gsm7_drops_to_70_char_segments():
    assert sms_segments("Umeme 😀" + "a" * 63) == 1
    assert sms_segments("Umeme 😀" + "a" * 64) == 2
