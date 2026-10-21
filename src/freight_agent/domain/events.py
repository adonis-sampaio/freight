"""The canonical event envelope.

Every input the agent can receive — an email, an SMS, a location ping, a timer
it armed itself — becomes an `Event`. The agent's own outbound effects are
recorded as `AGENT_ACTION` events so that a single append-only log can be
folded into the complete load state (see ADR-003).

Design notes
------------
* `occurred_at` is when the thing happened in the world; `received_at` is when
  we learned about it. Ordering decisions use `occurred_at`; latency metrics
  use the difference.
* `provider_event_id` is the deduplication key. Integrations retry, so the
  same message can arrive twice; we must be able to tell.
* `payload` holds type-specific data (lat/lng/delay_risk for a ping, timer
  context for a fired timer). It is deliberately a plain dict so the event
  table stays schema-light.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EventType(StrEnum):
    """The kind of thing that happened."""

    EMAIL = "email"
    SMS = "sms"
    SLACK = "slack"
    LOCATION_PING = "location_ping"
    TIMER_FIRED = "timer_fired"
    ATTACHMENT = "attachment"
    # The agent's own outbound effect. Recorded in the same log so that the
    # load state (which knows "the ETA request is still open") can be folded
    # from one authoritative source.
    AGENT_ACTION = "agent_action"


class ContactRole(StrEnum):
    DRIVER = "driver"
    DISPATCHER = "dispatcher"
    BROKER = "broker"
    HERO = "hero"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class Event(BaseModel):
    """An immutable fact about a load."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    load_id: str
    type: EventType
    occurred_at: datetime
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_contact_id: str | None = None
    source_role: ContactRole = ContactRole.UNKNOWN
    channel: str | None = None
    thread_id: str | None = None
    body: str | None = None
    attachment_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    provider_event_id: str | None = None

    @property
    def is_inbound(self) -> bool:
        return self.type is not EventType.AGENT_ACTION

    def with_id(self, event_id: str) -> Event:
        return self.model_copy(update={"id": event_id})
