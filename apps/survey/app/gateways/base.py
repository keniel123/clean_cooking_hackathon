from dataclasses import dataclass
from typing import Protocol


@dataclass
class SendResult:
    provider: str
    message_id: str | None
    status: str


class SmsGateway(Protocol):
    name: str

    def send(self, to: str, body: str) -> SendResult:
        """Send one SMS to an E.164 number. Raises on transport failure."""
        ...
