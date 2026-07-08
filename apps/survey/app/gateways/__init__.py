from functools import lru_cache

from ..config import get_settings
from .base import SendResult, SmsGateway


@lru_cache
def get_gateway() -> SmsGateway:
    provider = get_settings().sms_provider
    if provider == "console":
        from .console import ConsoleGateway

        return ConsoleGateway()
    if provider == "twilio":
        from .twilio import TwilioGateway

        return TwilioGateway()
    if provider == "africastalking":
        from .africastalking import AfricasTalkingGateway

        return AfricasTalkingGateway()
    raise ValueError(f"Unknown SMS_PROVIDER: {provider!r}")


__all__ = ["SendResult", "SmsGateway", "get_gateway"]
