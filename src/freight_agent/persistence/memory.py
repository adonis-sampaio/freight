"""In-memory implementations of the storage protocols.

Used by the eval harness, the demo command and the unit tests. The behaviour
matches the SQL implementation: the event store deduplicates on
`provider_event_id`, and the action store deduplicates on the idempotency key.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from freight_agent.domain.events import Event
from freight_agent.persistence.protocols import (
    StoredAction,
    Timer,
)


class InMemoryEventStore:
    def __init__(self) -> None:
        self._events: list[Event] = []
        self._provider_ids: set[str] = set()

    def append(self, event: Event) -> bool:
        if event.provider_event_id:
            if event.provider_event_id in self._provider_ids:
                return False
            self._provider_ids.add(event.provider_event_id)
        self._events.append(event)
        return True

    def load(self, load_id: str) -> list[Event]:
        return [event for event in self._events if event.load_id == load_id]

    def has_provider_event(self, provider_event_id: str) -> bool:
        return provider_event_id in self._provider_ids

    def all(self) -> list[Event]:
        return list(self._events)


class InMemoryActionStore:
    def __init__(self) -> None:
        self._actions: dict[str, StoredAction] = {}

    def record(self, action: StoredAction) -> bool:
        if action.idempotency_key in self._actions:
            return False
        self._actions[action.idempotency_key] = action
        return True

    def list(self, load_id: str) -> list[StoredAction]:
        return [a for a in self._actions.values() if a.load_id == load_id]

    def find_by_key(self, idempotency_key: str) -> StoredAction | None:
        return self._actions.get(idempotency_key)


class InMemoryTimerStore:
    def __init__(self) -> None:
        self._timers: dict[str, Timer] = {}

    def schedule(self, timer: Timer) -> Timer:
        if not timer.id:
            timer.id = str(uuid.uuid4())
        if timer.created_at is None:
            timer.created_at = datetime.now(UTC)
        self._timers[timer.id] = timer
        return timer

    def due(self, now: datetime) -> list[Timer]:
        due = (
            timer
            for timer in self._timers.values()
            if timer.status == "scheduled" and timer.fires_at <= now
        )
        return sorted(due, key=lambda timer: timer.fires_at)

    def mark_fired(self, timer_id: str) -> None:
        timer = self._timers.get(timer_id)
        if timer:
            timer.status = "fired"

    def cancel_for(self, load_id: str, request_key: str) -> None:
        for timer in self._timers.values():
            if (
                timer.load_id == load_id
                and timer.request_key == request_key
                and timer.status == "scheduled"
            ):
                timer.status = "cancelled"

    def list(self, load_id: str) -> list[Timer]:
        return [timer for timer in self._timers.values() if timer.load_id == load_id]
