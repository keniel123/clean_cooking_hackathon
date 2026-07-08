"""Development gateway: prints messages instead of sending them, and records
them on .sent so tests and the simulator can inspect outbound traffic."""

from .base import SendResult


class ConsoleGateway:
    name = "console"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, to: str, body: str) -> SendResult:
        self.sent.append((to, body))
        print(f"\n[SMS -> {to}]\n{body}\n")
        return SendResult(provider=self.name, message_id=None, status="sent")
