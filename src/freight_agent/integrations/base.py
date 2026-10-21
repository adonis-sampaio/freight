"""Integration adapters.

The engine never talks to the outside world directly. It produces an `Action`
and the runtime hands it to an adapter (ADR-014, ADR-015).

v1 ships a mock adapter, which records what *would* have been sent. A real
adapter (Twilio, SendGrid, Slack, the TMS) implements the same protocol and
needs no change anywhere else.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass
class DeliveryResult:
    delivered: bool
    provider_id: str | None = None
    detail: str = ""


class IntegrationAdapter(Protocol):
    """Everything the agent can do outside its own process."""

    def send_sms(self, contact_id: str, body: str, idempotency_key: str) -> DeliveryResult:
        ...

    def send_email(
        self,
        contact_id: str,
        subject: str,
        body: str,
        thread_id: str | None,
        idempotency_key: str,
    ) -> DeliveryResult:
        ...

    def send_slack(self, channel: str, body: str, idempotency_key: str) -> DeliveryResult:
        ...

    def tms_note(self, load_id: str, note: str, idempotency_key: str) -> DeliveryResult:
        ...

    def create_hero_task(
        self, load_id: str, title: str, body: str, urgent: bool, idempotency_key: str
    ) -> DeliveryResult:
        ...

    def internal_slack(self, channel: str, body: str, idempotency_key: str) -> DeliveryResult:
        ...


@dataclass
class MockAdapter:
    """Records what would have been sent instead of sending it."""

    sent: list[dict[str, Any]] = field(default_factory=list)

    def _record(self, kind: str, payload: dict[str, Any]) -> DeliveryResult:
        self.sent.append({"kind": kind, **payload})
        logger.info("[mock] %s %s", kind, payload)
        return DeliveryResult(delivered=True, provider_id=f"mock-{len(self.sent)}", detail="mock")

    def send_sms(self, contact_id: str, body: str, idempotency_key: str) -> DeliveryResult:
        return self._record("send_sms", {"contact_id": contact_id, "body": body})

    def send_email(
        self,
        contact_id: str,
        subject: str,
        body: str,
        thread_id: str | None,
        idempotency_key: str,
    ) -> DeliveryResult:
        return self._record(
            "send_email",
            {
                "contact_id": contact_id,
                "subject": subject,
                "body": body,
                "thread_id": thread_id,
            },
        )

    def send_slack(self, channel: str, body: str, idempotency_key: str) -> DeliveryResult:
        return self._record("send_slack", {"channel": channel, "body": body})

    def tms_note(self, load_id: str, note: str, idempotency_key: str) -> DeliveryResult:
        return self._record("tms_note", {"load_id": load_id, "note": note})

    def create_hero_task(
        self, load_id: str, title: str, body: str, urgent: bool, idempotency_key: str
    ) -> DeliveryResult:
        return self._record(
            "create_hero_task",
            {"load_id": load_id, "title": title, "body": body, "urgent": urgent},
        )

    def internal_slack(self, channel: str, body: str, idempotency_key: str) -> DeliveryResult:
        return self._record("internal_slack", {"channel": channel, "body": body})
