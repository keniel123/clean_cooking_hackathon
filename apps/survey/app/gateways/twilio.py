"""Twilio gateway — used for testing from Europe with UK numbers.

Sends via the Messages REST API with basic auth; no SDK dependency.
Inbound webhook authenticity is checked with validate_twilio_signature
(HMAC-SHA1 of the URL plus sorted form params, per Twilio's spec).
"""

import base64
import hashlib
import hmac

import httpx

from ..config import get_settings
from .base import SendResult

API_BASE = "https://api.twilio.com/2010-04-01"


class TwilioGateway:
    name = "twilio"

    def __init__(self) -> None:
        s = get_settings()
        if not (s.twilio_account_sid and s.twilio_auth_token and s.twilio_from_number):
            raise RuntimeError(
                "Twilio gateway needs TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN "
                "and TWILIO_FROM_NUMBER set in the environment or .env"
            )
        self._sid = s.twilio_account_sid
        self._token = s.twilio_auth_token
        self._from = s.twilio_from_number

    def send(self, to: str, body: str) -> SendResult:
        resp = httpx.post(
            f"{API_BASE}/Accounts/{self._sid}/Messages.json",
            data={"To": to, "From": self._from, "Body": body},
            auth=(self._sid, self._token),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return SendResult(
            provider=self.name,
            message_id=data.get("sid"),
            status=data.get("status", "queued"),
        )


def validate_twilio_signature(
    url: str, params: dict[str, str], signature: str, auth_token: str
) -> bool:
    payload = url + "".join(k + v for k, v in sorted(params.items()))
    digest = hmac.new(auth_token.encode(), payload.encode("utf-8"), hashlib.sha1).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, signature)
