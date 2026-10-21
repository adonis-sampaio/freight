"""The policy engine.

This is the deterministic heart of the system. Given a load state and an event
it:

1. derives the situation tags;
2. asks the SOP catalog which policies apply (a cheap metadata filter);
3. evaluates each step's predicate against the state;
4. runs the step's LLM gate, if it has one;
5. builds the actions, applies the guardrails, and applies the state effects.

Everything here is a pure function of (state, event, catalog). The LLM appears
only inside gates, and the fallback agent is called only when no policy matched
at all.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from freight_agent.domain.actions import Action, ActionType
from freight_agent.domain.events import Event
from freight_agent.domain.predicates import PredicateContext, describe, evaluate
from freight_agent.domain.state import LoadState, apply_effect
from freight_agent.engine.action_builder import ActionBuilder
from freight_agent.engine.gates import GateRunner, condition_matches
from freight_agent.engine.guardrails import suppression_reason
from freight_agent.sop.models import Policy
from freight_agent.sop.resolver import SopCatalog

logger = logging.getLogger(__name__)


def situation_tags(state: LoadState, event: Event) -> set[str]:
    """The situation vocabulary a policy can match on."""
    tags = {
        f"stage_{state.stage.value}",
        f"event_{event.type.value}",
        f"delay_risk_{state.delay_risk}",
    }
    if event.source_role is not None:
        tags.add(f"from_{event.source_role.value}")
    for key, request in state.open_requests.items():
        if request.status == "open":
            tags.add(f"open_request_{key}")
    return tags


@dataclass
class Decision:
    """One decision the engine made, with everything needed to audit it."""

    policy_key: str
    step_id: str
    status: str  # executed | no_action | skipped | suppressed
    rationale: str
    predicate: str
    action: Action | None = None
    gate: dict[str, Any] | None = None
    source: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy_key": self.policy_key,
            "step_id": self.step_id,
            "status": self.status,
            "rationale": self.rationale,
            "predicate": self.predicate,
            "gate": self.gate,
            "source": self.source,
            "action": self.action.model_dump(mode="json") if self.action else None,
        }


@dataclass
class EngineResult:
    decisions: list[Decision] = field(default_factory=list)
    state_before: LoadState | None = None
    state_after: LoadState | None = None
    gate_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    matched_policies: list[str] = field(default_factory=list)

    @property
    def actions(self) -> list[Action]:
        return [
            decision.action
            for decision in self.decisions
            if decision.action is not None and decision.status == "executed"
        ]

    @property
    def no_actions(self) -> list[Decision]:
        return [d for d in self.decisions if d.status in {"no_action", "suppressed"}]


class PolicyEngine:
    def __init__(
        self,
        catalog: SopCatalog,
        gates: GateRunner,
        action_builder: ActionBuilder,
    ) -> None:
        self.catalog = catalog
        self.gates = gates
        self.action_builder = action_builder

    def run(
        self,
        state: LoadState,
        event: Event,
        *,
        now: datetime | None = None,
    ) -> EngineResult:
        now = now or event.occurred_at
        working = state.model_copy(deep=True)
        result = EngineResult(state_before=state, state_after=working)

        tags = situation_tags(working, event)
        candidates = self.catalog.candidates(
            working.client_id,
            working.load_type,
            working,
            event.type.value,
            tags,
        )
        result.matched_policies = [policy.key for policy in candidates]

        context = PredicateContext(
            now=now, event_type=event.type.value, event_payload=event.payload
        )

        for policy in candidates:
            self._run_policy(policy, working, event, now, context, result)

        result.state_after = working
        return result

    def _run_policy(
        self,
        policy: Policy,
        working: LoadState,
        event: Event,
        now: datetime,
        context: PredicateContext,
        result: EngineResult,
    ) -> None:
        for step in policy.steps:
            if step.disable:
                continue

            if not evaluate(step.when, working, context):
                continue

            gate_output: dict[str, Any] | None = None
            if step.gate is not None:
                gate_output = self.gates.run(
                    step.gate,
                    event_id=event.id,
                    state=working,
                    load_id=working.load_id,
                )
                if gate_output is None:
                    result.decisions.append(
                        Decision(
                            policy_key=policy.key,
                            step_id=step.id,
                            status="skipped",
                            rationale="The gate could not be evaluated, so the step was not run.",
                            predicate=describe(step.when),
                            source=policy.provenance.get(step.id),
                        )
                    )
                    continue
                result.gate_outputs[step.gate.name] = gate_output
                if not condition_matches(step.gate.condition, gate_output, working):
                    continue

            specs = step.all_actions
            if not specs:
                continue

            for index, spec in enumerate(specs):
                effect = step.effect if index == 0 else None
                action, skip_reason = self.action_builder.build(
                    spec,
                    state=working,
                    event=event,
                    now=now,
                    policy_key=policy.key,
                    step_id=step.id,
                    gate_output=gate_output,
                    effect=effect,
                )

                if action is None:
                    result.decisions.append(
                        Decision(
                            policy_key=policy.key,
                            step_id=step.id,
                            status="skipped",
                            rationale=skip_reason or "The action could not be built.",
                            predicate=describe(step.when),
                            gate=gate_output,
                            source=policy.provenance.get(step.id),
                        )
                    )
                    continue

                if action.type is ActionType.SET_TIMER:
                    action.effects.append(
                        {
                            "set_timer": {
                                "request_key": action.request_key,
                                "fires_at": action.fires_at.isoformat()
                                if action.fires_at
                                else None,
                            }
                        }
                    )

                reason = suppression_reason(action, working, event, result.gate_outputs)
                if reason:
                    result.decisions.append(
                        Decision(
                            policy_key=policy.key,
                            step_id=step.id,
                            status="suppressed",
                            rationale=f"Not sending: {reason}.",
                            predicate=describe(step.when),
                            gate=gate_output,
                            action=action,
                            source=policy.provenance.get(step.id),
                        )
                    )
                    continue

                status = "no_action" if action.type is ActionType.NO_ACTION else "executed"
                result.decisions.append(
                    Decision(
                        policy_key=policy.key,
                        step_id=step.id,
                        status=status,
                        rationale=action.reason,
                        predicate=describe(step.when),
                        gate=gate_output,
                        action=action,
                        source=policy.provenance.get(step.id),
                    )
                )

                # State effects are applied immediately so that later steps in
                # the same run see the updated state. This is what stops the
                # escalation rung from firing in the same run as the ask.
                for effect_spec in action.effects:
                    apply_effect(working, effect_spec, now)
