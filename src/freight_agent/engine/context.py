"""Turning load state into a flat context that templates and prompts can use.

Templates are the reason outbound wording costs nothing: a template is a
Markdown file with `{{placeholders}}`, and this module supplies the values.
"""

from __future__ import annotations

from typing import Any

from freight_agent.domain.state import LoadState, Stage

_NEXT_STOP_TYPE = {
    Stage.DISPATCHED: "pickup",
    Stage.TO_PICKUP: "pickup",
    Stage.AT_PICKUP: "delivery",
    Stage.TO_DELIVERY: "delivery",
    Stage.AT_DELIVERY: None,
    Stage.DELIVERED: None,
}


def next_stop(state: LoadState) -> dict[str, Any] | None:
    """The stop the truck is heading to next."""
    wanted = _NEXT_STOP_TYPE.get(state.stage)
    if wanted is None:
        return None
    for stop in state.stops:
        if stop.get("type") == wanted:
            return stop
    return None


def state_context(state: LoadState) -> dict[str, str]:
    """A flat mapping of template variables for this load."""
    context: dict[str, str] = {key: str(value) for key, value in state.facts.items()}

    context["load_id"] = state.load_id
    context["client_id"] = state.client_id
    context["stage"] = state.stage.value
    context["delay_risk"] = state.delay_risk
    context["load_type"] = state.load_type or ""

    stop = next_stop(state)
    if stop:
        context["next_stop_name"] = str(stop.get("name", "the next stop"))
        context["next_stop_address"] = str(stop.get("address", ""))
        context["next_stop_type"] = str(stop.get("type", ""))
        appointment = stop.get("appointment") or {}
        context["next_stop_appointment"] = str(
            appointment.get("time") or appointment.get("start") or ""
        )
    else:
        context["next_stop_name"] = "the next stop"
        context["next_stop_address"] = ""
        context["next_stop_type"] = ""
        context["next_stop_appointment"] = ""

    for contact_id, contact in state.contacts.items():
        context[f"contact_{contact.get('role', 'unknown')}"] = contact_id
        if contact.get("name"):
            context[f"name_{contact.get('role', 'unknown')}"] = str(contact["name"])

    return context
