"""The fallback agent.

The compiled policies cover the situations we know about. The assessment is
explicit that we do not know all situations before they occur, so the agent
needs a way to behave sensibly when nothing matches.

The fallback agent is a *reasoner over the procedure text*, not a second
decision engine:

* it sees the load state, the recent events and the prose of the procedures
  that apply to this client;
* it may only choose a template that already exists - it never writes message
  text (ADR-004);
* it may take at most one outbound action per event;
* when it is not confident, it escalates to a human instead of improvising.

Its output is a structured decision, so it is validated, recorded and auditable
exactly like every other action.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from freight_agent.domain.actions import Action, ActionType
from freight_agent.domain.events import Event
from freight_agent.domain.state import LoadState
from freight_agent.engine.action_builder import ActionBuilder
from freight_agent.engine.context import state_context
from freight_agent.engine.templates import TemplateRenderer
from freight_agent.llm.gateway import LlmError, LlmGateway, LlmUnavailable
from freight_agent.llm.prompts import FALLBACK_SYSTEM, FALLBACK_USER
from freight_agent.llm.schemas import FallbackDecision
from freight_agent.llm.tiers import ModelTier
from freight_agent.sop.resolver import SopCatalog

logger = logging.getLogger(__name__)

# The fallback reads a lot of text. This keeps the prompt inside a sane budget.
_MAX_PROSE_CHARS = 12_000
_MAX_HISTORY = 12


@dataclass
class FallbackOutcome:
    decision: FallbackDecision
    actions: list[Action] = field(default_factory=list)
    cost_usd: float = 0.0
    reasoning: str = ""


class FallbackAgent:
    def __init__(
        self,
        gateway: LlmGateway,
        catalog: SopCatalog,
        templates: TemplateRenderer,
        action_builder: ActionBuilder,
    ) -> None:
        self.gateway = gateway
        self.catalog = catalog
        self.templates = templates
        self.action_builder = action_builder

    def decide(
        self,
        state: LoadState,
        event: Event,
        history: list[Event],
        now: datetime,
    ) -> FallbackOutcome | None:
        """Ask the model what to do, or None when that is not possible."""
        try:
            response = self.gateway.structured(
                tier=ModelTier.BALANCED,
                purpose="fallback_decision",
                system=FALLBACK_SYSTEM,
                user=self._user_prompt(state, event, history),
                schema_model=FallbackDecision,
                cache_key="fallback_decision",
                load_id=state.load_id,
            )
        except LlmUnavailable:
            logger.warning("Fallback agent unavailable for load %s", state.load_id)
            return None
        except LlmError as exc:
            logger.warning("Fallback agent failed for load %s: %s", state.load_id, exc)
            return None

        decision = FallbackDecision.model_validate(response.value)
        outcome = FallbackOutcome(
            decision=decision,
            cost_usd=response.call.cost_usd,
            reasoning=decision.reasoning,
        )

        if decision.needs_human:
            outcome.actions = self._escalate(state, event, now, decision.reasoning)
            return outcome

        for proposed in decision.actions:
            action = self._build(proposed, state, event, now)
            if action is not None:
                outcome.actions.append(action)
            # One outbound message per event. This is the last guard against a
            # chatty model.
            if action is not None and action.type not in {
                ActionType.NO_ACTION,
                ActionType.UPDATE_LOAD_STATE,
                ActionType.UPDATE_LOAD_STAGE,
            }:
                break

        return outcome

    # -- internals ---------------------------------------------------------

    def _build(
        self,
        proposed: Any,
        state: LoadState,
        event: Event,
        now: datetime,
    ) -> Action | None:
        spec: dict[str, Any] = {
            "action": proposed.action,
            "to_role": proposed.to_role,
            "to_channel": proposed.to_channel,
            "template": proposed.template,
            "reason": proposed.reason,
            "urgent": proposed.urgent,
        }
        if proposed.request_key:
            spec["request_key"] = proposed.request_key
        if proposed.after_minutes:
            spec["after_minutes"] = proposed.after_minutes

        action, reason = self.action_builder.build(
            spec,
            state=state,
            event=event,
            now=now,
            policy_key="fallback",
            step_id="fallback_decision",
        )
        if action is None:
            logger.info("Fallback action skipped: %s", reason)
            return None
        return action

    def _escalate(
        self, state: LoadState, event: Event, now: datetime, reasoning: str
    ) -> list[Action]:
        """Turn "I am not sure" into a task for a person."""
        spec = {
            "action": "create_hero_task",
            "template": "hero_fallback_review",
            "reason": reasoning or "The fallback agent was not confident about this event.",
        }
        action, _ = self.action_builder.build(
            spec,
            state=state,
            event=event,
            now=now,
            policy_key="fallback",
            step_id="fallback_escalation",
        )
        return [action] if action is not None else []

    def _user_prompt(self, state: LoadState, event: Event, history: list[Event]) -> str:
        context = state_context(state)
        template_names = self.templates.available(state.client_id)

        prose_parts: list[str] = []
        for document in self.catalog.documents:
            if document.scope != "base" and not document.matches_client(
                state.client_id, state.load_type
            ):
                continue
            if document.prose:
                prose_parts.append(f"### {document.title}\n{document.prose}")
        sop_text = "\n\n".join(prose_parts)[:_MAX_PROSE_CHARS]

        history_lines = []
        for item in history[-_MAX_HISTORY:]:
            history_lines.append(
                f"- {item.occurred_at:%Y-%m-%d %H:%M} {item.type.value} "
                f"from {item.source_role.value}: {(item.body or '')[:200]}"
            )
        history_text = "\n".join(history_lines) or "(no earlier events)"

        event_text = (
            f"- type: {event.type.value}\n"
            f"- at: {event.occurred_at:%Y-%m-%d %H:%M}\n"
            f"- from: {event.source_role.value}\n"
            f"- body: {event.body or ''}"
        )

        load_text = (
            f"load {state.load_id}, client {state.client_id}, "
            f"type {state.load_type or 'any'}, stage {state.stage.value}, "
            f"delay risk {state.delay_risk}, next stop {context.get('next_stop_name', '')}"
        )

        templates_text = "\n".join(f"- {name}" for name in template_names) or "(none)"

        return FALLBACK_USER.format(
            load=load_text,
            state=self._state_text(state, context),
            sop=sop_text,
            templates=templates_text,
            history=history_text,
            event=event_text,
        )

    @staticmethod
    def _state_text(state: LoadState, context: dict[str, str]) -> str:
        lines = [
            f"- delay risk: {state.delay_risk}",
            f"- stage: {state.stage.value}",
            f"- next stop: {context.get('next_stop_name', '')}",
            f"- facts: {', '.join(f'{k}={v}' for k, v in sorted(state.facts.items())) or 'none'}",
        ]
        for key, request in state.open_requests.items():
            lines.append(
                f"- open request {key}: {request.status}, {request.attempts} attempt(s) so far"
            )
        if state.acted_signatures:
            lines.append(f"- actions already taken: {', '.join(state.acted_signatures)}")
        return "\n".join(lines)
