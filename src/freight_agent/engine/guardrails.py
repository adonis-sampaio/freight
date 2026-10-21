"""Guardrails that sit between a decision and the outside world.

The do-not-act gate (ADR-002) answers a single question: *is this message
actually asking for something?* If the agent is about to reply to a role that
did not ask us anything, and we are not waiting on them, we do not reply.

The policies already express most of this. The guardrail is the backstop that
catches a policy that forgets to.
"""

from __future__ import annotations

from freight_agent.domain.actions import Action, ActionType
from freight_agent.domain.events import Event, EventType
from freight_agent.domain.state import LoadState

_REPLY_ACTIONS = {
    ActionType.SEND_SMS,
    ActionType.SEND_EMAIL,
    ActionType.SEND_SLACK,
    ActionType.INTERNAL_SLACK,
}

_INBOUND_MESSAGE_TYPES = {EventType.SMS, EventType.EMAIL, EventType.SLACK}


def suppression_reason(
    action: Action,
    state: LoadState,
    event: Event,
    gate_outputs: dict[str, dict],
) -> str | None:
    """Return why this action must not be sent, or None if it may be sent."""
    if action.type not in _REPLY_ACTIONS:
        return None
    if not action.to_role:
        return None
    if event.type not in _INBOUND_MESSAGE_TYPES:
        return None
    if event.source_role.value != action.to_role:
        return None

    # We are replying to a message from this role. That is fine when we are
    # waiting on them, or when they asked us something.
    for request in state.open_requests.values():
        if request.status == "open" and request.addressed_to_role == action.to_role:
            return None

    for output in gate_outputs.values():
        if output.get("is_question"):
            return None

    return (
        f"the {action.to_role} sent a message we did not ask for and did not ask a "
        "question, so there is nothing to answer"
    )
