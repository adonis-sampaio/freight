"""Load state: a deterministic fold over the event log.

This module is the answer to "how does the agent remember what happened?".
The answer is: it does not remember — it *recomputes*. `LoadState` is derived
by folding the append-only event log, so memory can never disagree with
history, and any state can be rebuilt by replaying events.

Two fields carry most of the weight:

* `open_requests` — the requests the agent has made and is waiting on
  (e.g. the ETA request). A request is opened by a state effect and closed
  only by a gate that positively detects the answer. That is why a driver
  asking an unrelated question does not close the ETA request.
* `acted_signatures` — the agent's own action history, so a policy can ask
  "have I already done this?".
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from freight_agent.domain.actions import ActionType
from freight_agent.domain.events import ContactRole, Event, EventType


class Stage(StrEnum):
    DISPATCHED = "dispatched"
    TO_PICKUP = "to_pickup"
    AT_PICKUP = "at_pickup"
    TO_DELIVERY = "to_delivery"
    AT_DELIVERY = "at_delivery"
    DELIVERED = "delivered"


RequestStatus = Literal["open", "answered", "cancelled"]


class OpenRequest(BaseModel):
    """A question the agent asked and is still waiting on."""

    key: str
    kind: str
    status: RequestStatus = "open"
    addressed_to_role: str | None = None
    attempts: int = 0
    opened_at: datetime
    last_asked_at: datetime | None = None
    timer_fires_at: datetime | None = None
    responses_seen: int = 0
    answered_at: datetime | None = None
    answer: str | None = None


class LoadState(BaseModel):
    """Everything the decision engine needs to know about a load."""

    load_id: str
    client_id: str = "default"
    load_type: str | None = None
    stage: Stage = Stage.DISPATCHED
    delay_risk: str = "low"
    previous_delay_risk: str | None = None
    facts: dict[str, str] = Field(default_factory=dict)
    stops: list[dict[str, Any]] = Field(default_factory=list)
    contacts: dict[str, dict[str, Any]] = Field(default_factory=dict)
    main_thread_id: str | None = None

    open_requests: dict[str, OpenRequest] = Field(default_factory=dict)
    acted_signatures: list[str] = Field(default_factory=list)

    last_inbound_at: datetime | None = None
    last_inbound_role: ContactRole = ContactRole.UNKNOWN
    last_inbound_body: str | None = None
    last_inbound_event_id: str | None = None
    last_ping_at: datetime | None = None
    last_location: dict[str, Any] | None = None
    attachment_ids: list[str] = Field(default_factory=list)

    # ---- helpers ---------------------------------------------------------

    def role_contact_id(self, role: str) -> str | None:
        for contact_id, contact in self.contacts.items():
            if contact.get("role") == role:
                return contact_id
        return None

    def open_request(self, key: str) -> OpenRequest | None:
        request = self.open_requests.get(key)
        if request and request.status == "open":
            return request
        return None

    def minutes_since_last_ask(self, key: str, now: datetime) -> float | None:
        request = self.open_requests.get(key)
        if request is None or request.last_asked_at is None:
            return None
        return (now - request.last_asked_at).total_seconds() / 60.0


def initial_state(load_id: str, **kwargs: Any) -> LoadState:
    return LoadState(load_id=load_id, **kwargs)


# ---------------------------------------------------------------------------
# The fold
# ---------------------------------------------------------------------------


def fold(state: LoadState, event: Event) -> LoadState:
    """Return a new state with `event` applied. Pure function."""
    new = state.model_copy(deep=True)

    if event.type is EventType.LOCATION_PING:
        _apply_ping(new, event)
    elif event.type in (EventType.EMAIL, EventType.SMS, EventType.SLACK):
        _apply_inbound_message(new, event)
    elif event.type is EventType.TIMER_FIRED:
        _apply_timer_fired(new, event)
    elif event.type is EventType.ATTACHMENT:
        for attachment_id in event.attachment_ids:
            if attachment_id not in new.attachment_ids:
                new.attachment_ids.append(attachment_id)
    elif event.type is EventType.AGENT_ACTION:
        _apply_agent_action(new, event)

    return new


def fold_all(state: LoadState, events: list[Event]) -> LoadState:
    for event in events:
        state = fold(state, event)
    return state


def _apply_ping(state: LoadState, event: Event) -> None:
    payload = event.payload
    if "delay_risk" in payload:
        new_risk = str(payload["delay_risk"])
        if new_risk != state.delay_risk:
            state.previous_delay_risk = state.delay_risk
        state.delay_risk = new_risk
    if "stage" in payload:
        state.stage = Stage(str(payload["stage"]))
    if "lat" in payload and "lng" in payload:
        state.last_location = {"lat": payload["lat"], "lng": payload["lng"]}
    state.last_ping_at = event.occurred_at


def _apply_inbound_message(state: LoadState, event: Event) -> None:
    state.last_inbound_at = event.occurred_at
    state.last_inbound_role = event.source_role
    state.last_inbound_body = event.body
    state.last_inbound_event_id = event.id

    # A response only counts for the request it is addressed to. A message from
    # the dispatcher is not a response to a request we sent to the driver.
    for request in state.open_requests.values():
        if request.status != "open":
            continue
        if request.addressed_to_role and request.addressed_to_role == event.source_role:
            request.responses_seen += 1


def _apply_timer_fired(state: LoadState, event: Event) -> None:
    request_key = event.payload.get("request_key")
    if not request_key:
        return
    request = state.open_requests.get(request_key)
    if request is not None:
        request.timer_fires_at = None


def _apply_agent_action(state: LoadState, event: Event) -> None:
    payload = event.payload
    action_type = payload.get("action_type")
    signature = payload.get("signature")
    if signature and signature not in state.acted_signatures:
        state.acted_signatures.append(signature)

    for effect in payload.get("effects", []):
        apply_effect(state, effect, event.occurred_at)

    if action_type == ActionType.UPDATE_LOAD_STAGE and payload.get("stage"):
        state.stage = Stage(str(payload["stage"]))


def _as_datetime(value: Any) -> datetime | None:
    """Effects carry timestamps as ISO strings, so they survive a JSON round trip."""
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def apply_effect(state: LoadState, effect: dict[str, Any], now: datetime) -> None:
    if "open_request" in effect:
        spec = effect["open_request"]
        key = spec["key"]
        existing = state.open_requests.get(key)
        if existing is None:
            state.open_requests[key] = OpenRequest(
                key=key,
                kind=spec.get("kind", key),
                addressed_to_role=spec.get("addressed_to_role"),
                attempts=int(spec.get("attempts", 0)),
                opened_at=now,
                last_asked_at=spec.get("last_asked_at") or now,
            )
        else:
            existing.status = "open"
            existing.attempts = int(spec.get("attempts", existing.attempts))
            existing.last_asked_at = spec.get("last_asked_at") or now
            existing.answered_at = None
            existing.answer = None

    if "increment_attempts" in effect:
        spec = effect["increment_attempts"]
        key, by = (spec, 1) if isinstance(spec, str) else (spec["key"], int(spec.get("by", 1)))
        request = state.open_requests.get(key)
        if request is not None:
            request.attempts += by
            request.last_asked_at = now

    if "close_request" in effect:
        spec = effect["close_request"]
        key = spec if isinstance(spec, str) else spec["key"]
        request = state.open_requests.get(key)
        if request is not None:
            request.status = "answered"
            request.answered_at = now
            request.timer_fires_at = None
            request.answer = spec.get("answer") if isinstance(spec, dict) else None

    if "cancel_request" in effect:
        spec = effect["cancel_request"]
        key = spec if isinstance(spec, str) else spec["key"]
        request = state.open_requests.get(key)
        if request is not None:
            request.status = "cancelled"
            request.timer_fires_at = None

    if "set_timer" in effect:
        spec = effect["set_timer"]
        key = spec.get("request_key")
        if key:
            request = state.open_requests.get(key)
            if request is not None:
                request.timer_fires_at = _as_datetime(spec.get("fires_at"))

    if "set_delay_risk" in effect:
        state.delay_risk = str(effect["set_delay_risk"])

    if "set_stage" in effect:
        state.stage = Stage(str(effect["set_stage"]))

    if "record_fact" in effect:
        spec = effect["record_fact"]
        state.facts[spec["key"]] = str(spec["value"])
