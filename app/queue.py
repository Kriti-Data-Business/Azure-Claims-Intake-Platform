"""Queue abstraction: in-memory for tests and local runs, Azure Service Bus for deployment.

Delivery is at-least-once. A message that fails `max_attempts` times is dead-lettered
instead of retried forever, so a poison document cannot block the worker.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Message:
    id: str
    body: dict
    attempts: int = 0
    raw: object = field(default=None, repr=False)


class Queue(Protocol):
    def send(self, body: dict) -> str: ...
    def receive(self, max_messages: int = 10) -> list[Message]: ...
    def complete(self, msg: Message) -> None: ...
    def abandon(self, msg: Message) -> None: ...
    def dead_letter(self, msg: Message, reason: str) -> None: ...


class InMemoryQueue:
    def __init__(self) -> None:
        self._ids = itertools.count(1)
        self._pending: list[Message] = []
        self.dead_lettered: list[tuple[Message, str]] = []

    def send(self, body: dict) -> str:
        mid = f"m{next(self._ids)}"
        self._pending.append(Message(mid, body))
        return mid

    def receive(self, max_messages: int = 10) -> list[Message]:
        batch, self._pending = self._pending[:max_messages], self._pending[max_messages:]
        for m in batch:
            m.attempts += 1
        return batch

    def complete(self, msg: Message) -> None:
        pass  # already removed on receive

    def abandon(self, msg: Message) -> None:
        self._pending.append(msg)

    def dead_letter(self, msg: Message, reason: str) -> None:
        self.dead_lettered.append((msg, reason))


class ServiceBusQueue:
    """Adapter over azure-servicebus. Pass a ServiceBusClient (or any object with the same
    get_queue_sender/get_queue_receiver methods). Not exercised against a real namespace yet:
    tests use a fake with the same surface."""

    def __init__(self, client, queue_name: str, wait_seconds: int = 5):
        self.sender = client.get_queue_sender(queue_name)
        self.receiver = client.get_queue_receiver(queue_name)
        self.wait = wait_seconds

    @classmethod
    def from_connection_string(cls, conn_str: str, queue_name: str):
        from azure.servicebus import ServiceBusClient  # imported lazily: optional dependency
        return cls(ServiceBusClient.from_connection_string(conn_str), queue_name)

    def send(self, body: dict) -> str:
        from azure.servicebus import ServiceBusMessage  # noqa: F401  (real runs only)
        msg = ServiceBusMessage(json.dumps(body))
        self.sender.send_messages(msg)
        return getattr(msg, "message_id", None) or ""

    def receive(self, max_messages: int = 10) -> list[Message]:
        out = []
        for m in self.receiver.receive_messages(max_message_count=max_messages, max_wait_time=self.wait):
            body = json.loads(b"".join(m.body).decode() if not isinstance(m.body, (bytes, str)) else m.body)
            out.append(Message(str(m.message_id), body, int(getattr(m, "delivery_count", 0) or 0) + 1, raw=m))
        return out

    def complete(self, msg: Message) -> None:
        self.receiver.complete_message(msg.raw)

    def abandon(self, msg: Message) -> None:
        self.receiver.abandon_message(msg.raw)

    def dead_letter(self, msg: Message, reason: str) -> None:
        self.receiver.dead_letter_message(msg.raw, reason=reason[:128])
