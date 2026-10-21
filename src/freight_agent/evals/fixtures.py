"""The eval fixtures.

The main scenario is the one from the assessment: load #481207, Client A, the
delay risk goes high, and the agent has to work up the escalation ladder while
the driver sends a question instead of the ETA.

The load metadata is the assessment's example, with two additions that the
design needs and the assessment explicitly allows:

* `broker.id` is the client id. The assessment's example uses the broker's own
  id ("northline"); here the broker id is the client id ("client_a").
* `email_thread_id` identifies the load's main email thread. The assessment
  states that every load has exactly one main email thread, so the agent needs
  a way to find it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from freight_agent.domain.events import ContactRole, Event, EventType

DAY = "2026-10-13"

LOAD_481207: dict[str, Any] = {
    "load_id": "481207",
    "broker": {"id": "client_a", "name": "Northline Logistics"},
    "shipper": "Riverbend Foods",
    "carrier": {"name": "Prairie Haul LLC", "mc_number": "778120"},
    "commodity": "Canned tomato sauce, 38,000 lb, dry van",
    "load_type": "dry_van",
    "stage": "to_pickup",
    "delay_risk": "low",
    "email_thread_id": "thread-northline-481207",
    "contacts": [
        {"id": "drv_20931", "role": "driver", "channels": ["sms"]},
        {"id": "dsp_4410", "role": "dispatcher", "channels": ["email"]},
        {"id": "brk_0087", "role": "broker", "channels": ["email", "slack"]},
    ],
    "stops": [
        {
            "sequence": 1,
            "type": "pickup",
            "name": "Riverbend plant",
            "address": "Stockton, CA",
            "timezone": "America/Los_Angeles",
            "appointment": {
                "type": "window",
                "start": "2026-10-13T06:00",
                "end": "2026-10-13T14:00",
            },
        },
        {
            "sequence": 2,
            "type": "delivery",
            "name": "Valley DC",
            "address": "Reno, NV",
            "timezone": "America/Los_Angeles",
            "appointment": {"type": "fixed", "time": "2026-10-14T09:30"},
        },
    ],
    "instructions": "Call 1 hr before arrival. PO 55821 required at gate.",
}

# Client B, same lane, so the difference in the procedure is the only variable.
LOAD_CLIENT_B: dict[str, Any] = {
    **LOAD_481207,
    "load_id": "481208",
    "broker": {"id": "client_b", "name": "Cascade Freight Brokers"},
    "load_type": "refrigerated",
    "commodity": "Frozen berries, 40,000 lb, refrigerated",
    "email_thread_id": "thread-cascade-481208",
}

# A quiet load, used for the "the driver says ok" case.
LOAD_QUIET: dict[str, Any] = {
    **LOAD_481207,
    "load_id": "481209",
}

# A load for the fallback case: an event no procedure covers.
LOAD_UNCOVERED: dict[str, Any] = {
    **LOAD_481207,
    "load_id": "481210",
}


def at(hour: int, minute: int, day: str = DAY) -> datetime:
    return datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00")


def ping(load_id: str, when: datetime, **payload: Any) -> Event:
    """A location ping, optionally carrying a new delay risk."""
    body = {"lat": 37.9577, "lng": -121.2908, **payload}
    return Event(
        load_id=load_id,
        type=EventType.LOCATION_PING,
        occurred_at=when,
        received_at=when,
        source_role=ContactRole.SYSTEM,
        channel="tms",
        payload=body,
        provider_event_id=f"ping-{load_id}-{when.isoformat()}",
    )


def driver_sms(load_id: str, when: datetime, text: str, **kwargs: Any) -> Event:
    return Event(
        load_id=load_id,
        type=EventType.SMS,
        occurred_at=when,
        received_at=when,
        source_contact_id="drv_20931",
        source_role=ContactRole.DRIVER,
        channel="sms",
        body=text,
        provider_event_id=kwargs.pop(
            "provider_event_id", f"sms-{load_id}-{when.isoformat()}-{text[:12]}"
        ),
        **kwargs,
    )
