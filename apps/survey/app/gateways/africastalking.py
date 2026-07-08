"""Africa's Talking gateway — Kenya production.

Direct connectivity to Safaricom/Airtel/Telkom. Use the sandbox environment
(AT_ENVIRONMENT=sandbox) with the simulator at
https://developers.africastalking.com/simulator before going live.
"""

import httpx

from ..config import get_settings
from .base import SendResult

HOSTS = {
    "sandbox": "https://api.sandbox.africastalking.com",
    "production": "https://api.africastalking.com",
}


class AfricasTalkingGateway:
    name = "africastalking"

    def __init__(self) -> None:
        s = get_settings()
        if not s.at_api_key:
            raise RuntimeError("Africa's Talking gateway needs AT_API_KEY set")
        if s.at_environment not in HOSTS:
            raise RuntimeError("AT_ENVIRONMENT must be 'sandbox' or 'production'")
        self._username = s.at_username
        self._api_key = s.at_api_key
        self._sender_id = s.at_sender_id
        self._url = f"{HOSTS[s.at_environment]}/version1/messaging"

    def send(self, to: str, body: str) -> SendResult:
        data = {"username": self._username, "to": to, "message": body}
        if self._sender_id:
            data["from"] = self._sender_id
        resp = httpx.post(
            self._url,
            data=data,
            headers={"apiKey": self._api_key, "Accept": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        recipients = resp.json().get("SMSMessageData", {}).get("Recipients", [])
        if not recipients:
            return SendResult(provider=self.name, message_id=None, status="no-recipient")
        first = recipients[0]
        return SendResult(
            provider=self.name,
            message_id=first.get("messageId"),
            status=first.get("status", "unknown"),
        )
