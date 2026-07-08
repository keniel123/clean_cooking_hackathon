"""SMS length accounting. Messages outside the GSM-7 charset are sent as UCS-2,
which cuts the per-segment limit from 160 to 70 characters — each segment is
billed separately, which matters at minigrid-fleet scale."""

GSM7_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM7_EXTENDED = set("^{}\\[~]|€")


def sms_segments(body: str) -> int:
    """Number of SMS segments this message will be billed as."""
    if all(c in GSM7_BASIC or c in GSM7_EXTENDED for c in body):
        length = sum(2 if c in GSM7_EXTENDED else 1 for c in body)
        return 1 if length <= 160 else -(-length // 153)
    length = len(body)
    return 1 if length <= 70 else -(-length // 67)
