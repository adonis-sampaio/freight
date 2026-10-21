"""Building actions from policy specifications.

An action specification is the small dictionary an SOP author writes:

```yaml
do:
  action: send_sms
  to_role: driver
  template: ask_eta
  reason: We need an ETA.
```

This module turns that into a fully resolved `Action`: contact ids resolved,
message templates rendered, timer deadlines computed, and state effects
attached.

If something is missing (no contact for the role, a template that needs a value
the load does not have), the action is *not* built and the reason is returned.
A half-formed message is never sent.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from freight_agent.domain.actions import Action, ActionType
from freight_agent.domain.events import Event
from freight_agent.domain.state import LoadState
from freight_agent.engine.context import state_context
from freight_agent.engine.templates import TemplateError, TemplateRenderer

# Actions that talk to somebody and therefore need a body.
_NEEDS_BODY = {
    ActionType.SEND_SMS,
    ActionType.SEND_EMAIL,
    ActionType.SEND_SLACK,
    ActionType.INTERNAL_SLACK,
    ActionType.TMS_NOTE,
    ActionType.CREATE_HERO_TASK,
}

# How a question topic is written for a human. The topic itself is a machine
# key ("po_number"); the message needs words ("PO number").
_TOPIC_LABELS = {
    "po_number": "PO number",
    "pro_number": "PRO number",
    "gate_code": "gate code",
    "dock_number": "dock number",
    "call_ahead_minutes": "call-ahead time",
    "trailer_number": "trailer number",
    "seal_number": "seal number",
}


class ActionBuilder:
    def __init__(self, templates: TemplateRenderer) -> None:
        self.templates = templates

    def build(
        self,
        spec: dict[str, Any],
        *,
        state: LoadState,
        event: Event,
        now: datetime,
        policy_key: str,
        step_id: str,
        gate_output: dict[str, Any] | None = None,
        effect: dict[str, Any] | None = None,
    ) -> tuple[Action | None, str | None]:
        """Return (action, skip_reason). Exactly one of the two is not None."""
        raw_type = str(spec.get("action") or "")
        try:
            action_type = ActionType(raw_type)
        except ValueError:
            return None, f"Unknown action {raw_type!r}"

        action = Action(
            type=action_type,
            reason=str(spec.get("reason", "")),
            template=spec.get("template"),
            policy_key=policy_key,
            step_id=step_id,
        )

        context = state_context(state)
        if gate_output:
            context.update({str(k): str(v) for k, v in gate_output.items() if v is not None})
            _add_answer_context(context, state, gate_output)

        # --- body ------------------------------------------------------------
        if action_type in _NEEDS_BODY:
            body, error = self._render_body(spec, state, context)
            if error:
                return None, error
            action.body = body

        # --- targeting -------------------------------------------------------
        if spec.get("to_role"):
            role = str(spec["to_role"])
            action.to_role = role
            contact_id = state.role_contact_id(role)
            if contact_id is None:
                return None, f"No contact with role {role!r} on this load"
            action.target = contact_id

        if spec.get("to_channel"):
            action.channel = str(spec["to_channel"])
            action.target = action.target or action.channel

        if action_type in {
            ActionType.SEND_SMS,
            ActionType.SEND_EMAIL,
            ActionType.TMS_NOTE,
            ActionType.CREATE_HERO_TASK,
        } and action.target is None:
            action.target = state.load_id

        if action_type is ActionType.SEND_EMAIL:
            subject, error = self._render_optional(spec.get("subject"), state, context)
            if error:
                return None, error
            action.subject = subject
            if spec.get("in_thread") == "main":
                action.thread_id = state.main_thread_id
                if not action.thread_id:
                    return None, "The load has no main email thread id"

        if action_type is ActionType.UPDATE_LOAD_STAGE:
            action.stage = str(spec.get("stage", ""))
            if action.stage:
                action.effects.append({"set_stage": action.stage})

        action.urgent = bool(spec.get("urgent", False))

        # --- timers ----------------------------------------------------------
        if action_type is ActionType.SET_TIMER:
            request_key = spec.get("request_key")
            if not request_key:
                return None, "A set_timer action needs a request_key"
            after_minutes = spec.get("after_minutes")
            if not after_minutes:
                return None, "A set_timer action needs after_minutes"
            action.request_key = str(request_key)
            action.after_minutes = int(after_minutes)
            action.fires_at = now + timedelta(minutes=action.after_minutes)
            action.target = state.load_id

        # --- effects ---------------------------------------------------------
        if effect:
            action.effects.append(_substitute_gate_values(effect, gate_output))

        return action, None

    def _render_body(
        self, spec: dict[str, Any], state: LoadState, context: dict[str, str]
    ) -> tuple[str | None, str | None]:
        template = spec.get("template")
        if template:
            try:
                return self.templates.render(str(template), state.client_id, context), None
            except TemplateError as exc:
                return None, str(exc)
        literal = spec.get("body")
        if literal:
            try:
                return TemplateRenderer.substitute(str(literal), context), None
            except TemplateError as exc:
                return None, str(exc)
        return None, "The action has neither a template nor a body"

    def _render_optional(
        self, value: Any, state: LoadState, context: dict[str, str]
    ) -> tuple[str | None, str | None]:
        if not value:
            return None, None
        try:
            return TemplateRenderer.substitute(str(value), context), None
        except TemplateError as exc:
            return None, str(exc)


def _add_answer_context(
    context: dict[str, str], state: LoadState, gate_output: dict[str, Any]
) -> None:
    """Put the answer to the driver's question into the template context.

    The gate names the topic of the question ("po_number"). The topic is also
    the key of the fact in the load metadata, so the answer is a lookup, not a
    guess. If the fact is missing the template render fails and the action is
    skipped, which is exactly what we want.
    """
    topic = gate_output.get("topic")
    if not topic:
        return
    topic = str(topic)
    context.setdefault("topic", topic)
    context.setdefault("topic_label", _TOPIC_LABELS.get(topic, topic.replace("_", " ")))
    fact = state.facts.get(topic)
    if fact is not None:
        context.setdefault("value", str(fact))
        context.setdefault("question_answer", str(fact))


def _substitute_gate_values(
    effect: dict[str, Any], gate_output: dict[str, Any] | None
) -> dict[str, Any]:
    """Replace `$gate.<field>` inside an effect with the gate's value."""
    if not gate_output:
        return effect
    resolved: dict[str, Any] = {}
    for key, value in effect.items():
        if isinstance(value, str) and value.startswith("$gate."):
            resolved[key] = gate_output.get(value.removeprefix("$gate."))
        elif isinstance(value, dict):
            resolved[key] = _substitute_gate_values(value, gate_output)
        else:
            resolved[key] = value
    return resolved
