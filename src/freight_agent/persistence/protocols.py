"""Storage interfaces.

The engine and the runtime depend on these protocols, not on a database. That
keeps the eval harness free of infrastructure and makes it trivial to swap the
in-memory implementation for Postgres.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from freight_agent.domain.events import Event


@dataclass
class Timer:
    """A scheduled wake-up."""

    id: str
    load_id: str
    request_key: str
    fires_at: datetime
    reason: str = ""
    status: str = "scheduled"  # scheduled | fired | cancelled
    created_at: datetime | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class StoredAction:
    """An action as recorded in the ledger."""

    id: str
    load_id: str
    event_id: str
    action_type: str
    status: str
    idempotency_key: str
    target: str | None = None
    to_role: str | None = None
    channel: str | None = None
    body: str | None = None
    subject: str | None = None
    thread_id: str | None = None
    template: str | None = None
    reason: str = ""
    rationale: str = ""
    predicate: str = ""
    policy_key: str | None = None
    step_id: str | None = None
    gate: dict[str, Any] | None = None
    effects: list[dict[str, Any]] = field(default_factory=list)
    cost_usd: float = 0.0
    created_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "load_id": self.load_id,
            "event_id": self.event_id,
            "action_type": self.action_type,
            "status": self.status,
            "idempotency_key": self.idempotency_key,
            "target": self.target,
            "to_role": self.to_role,
            "channel": self.channel,
            "body": self.body,
            "subject": self.subject,
            "thread_id": self.thread_id,
            "template": self.template,
            "reason": self.reason,
            "rationale": self.rationale,
            "predicate": self.predicate,
            "policy_key": self.policy_key,
            "step_id": self.step_id,
            "gate": self.gate,
            "cost_usd": round(self.cost_usd, 6),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EventStore(Protocol):
    def append(self, event: Event) -> bool:
        """Append an event. Returns False when it was a duplicate."""

    def load(self, load_id: str) -> list[Event]:
        """Every event for a load, in order."""

    def has_provider_event(self, provider_event_id: str) -> bool:
        ...


class ActionStore(Protocol):
    def record(self, action: StoredAction) -> bool:
        """Record an action. Returns False when the idempotency key already exists."""

    def list(self, load_id: str) -> list[StoredAction]:
        ...

    def find_by_key(self, idempotency_key: str) -> StoredAction | None:
        ...


class TimerStore(Protocol):
    def schedule(self, timer: Timer) -> Timer:
        ...

    def due(self, now: datetime) -> list[Timer]:
        ...

    def mark_fired(self, timer_id: str) -> None:
        ...

    def cancel_for(self, load_id: str, request_key: str) -> None:
        ...

    def list(self, load_id: str) -> list[Timer]:
        ...
