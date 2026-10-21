"""Gates: the LLM classifiers that guard a policy step.

A gate answers one narrow question about the current event ("does this message
contain an ETA?") and returns a structured result. It is the only place the
model touches the hot path, and it is deliberately boring:

* one call per (event, gate) pair, cached for the lifetime of the run;
* a cheap model by default;
* a second, more capable model only when the cheap one is unsure;
* a tiny condition language so policies can say "only if the ETA is missing".
"""

from __future__ import annotations

import contextlib
import logging
import re
from typing import Any

from freight_agent.domain.state import LoadState
from freight_agent.engine.context import state_context
from freight_agent.llm.gateway import LlmError, LlmGateway, LlmUnavailable
from freight_agent.llm.prompts import MESSAGE_SIGNALS_SYSTEM, MESSAGE_SIGNALS_USER
from freight_agent.llm.schemas import MessageSignals
from freight_agent.llm.tiers import ModelTier
from freight_agent.sop.models import GateSpec

logger = logging.getLogger(__name__)

LOW_CONFIDENCE_THRESHOLD = 0.65

_CONDITION_RE = re.compile(
    r"^\$gate\.(?P<field>\w+)\s*(?:(?P<op>==|!=|>=|<=|>|<)\s*(?P<value>.+))?$"
)


def condition_matches(
    condition: str | None,
    gate_output: dict[str, Any],
    state: LoadState | None = None,
) -> bool:
    """Evaluate a gate condition such as `$gate.has_eta` or `$gate.kind == 'question'`.

    Conditions may be combined with `and` and `or`:

        $gate.is_question and $gate.topic_fact_present

    Two conditions need the load state and not just the gate output:

    * `$gate.topic_fact_present` - the load metadata has the fact the driver asked about;
    * `$gate.topic_fact_missing` - it does not, so we must escalate instead of guessing.
    """
    if not condition:
        return True
    condition = condition.strip()

    if " or " in condition:
        return any(
            condition_matches(part, gate_output, state) for part in condition.split(" or ")
        )
    if " and " in condition:
        return all(
            condition_matches(part, gate_output, state) for part in condition.split(" and ")
        )

    if condition in {"$gate.topic_fact_present", "$gate.topic_fact_missing"}:
        present = _topic_fact_present(gate_output, state)
        return present if condition.endswith("present") else not present

    match = _CONDITION_RE.match(condition)
    if not match:
        raise ValueError(f"Cannot parse gate condition {condition!r}")

    field = match.group("field")
    operator = match.group("op")
    raw_value = match.group("value")

    if field not in gate_output:
        return False
    actual = gate_output[field]

    if operator is None:
        return bool(actual)

    expected: Any = raw_value
    if raw_value is not None:
        expected = raw_value.strip()
        if len(expected) >= 2 and expected[0] == expected[-1] and expected[0] in "\"'":
            expected = expected[1:-1]
        else:
            with contextlib.suppress(ValueError):
                expected = float(expected)

    if operator == "==":
        return actual == expected
    if operator == "!=":
        return actual != expected
    if actual is None or not isinstance(actual, (int, float)):
        return False
    if operator == ">=":
        return actual >= expected
    if operator == "<=":
        return actual <= expected
    if operator == ">":
        return actual > expected
    if operator == "<":
        return actual < expected
    raise ValueError(f"Unsupported gate operator {operator!r}")


def _topic_fact_present(
    gate_output: dict[str, Any], state: LoadState | None
) -> bool:
    """Does the load metadata contain the fact the driver asked about?

    The gate names the topic ("po_number", "gate_code", ...); the topic is also
    the key of the fact in the load metadata. If the fact is not there, the agent
    must not guess the answer.
    """
    if state is None:
        return False
    topic = gate_output.get("topic")
    if not topic:
        return False
    return str(topic) in state.facts


class GateRunner:
    """Runs gates and caches their results for the lifetime of one agent run."""

    def __init__(self, gateway: LlmGateway) -> None:
        self.gateway = gateway
        self._cache: dict[str, dict[str, Any]] = {}

    def run(
        self,
        gate: GateSpec,
        *,
        event_id: str,
        state: LoadState,
        load_id: str,
    ) -> dict[str, Any] | None:
        """Run a gate and return its structured output, or None if it could not run."""
        cache_key = f"{event_id}:{gate.name}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        if gate.name != "message_signals":
            raise ValueError(f"Unknown gate {gate.name!r}")

        payload = self._build_message_payload(state)
        try:
            response = self.gateway.structured(
                tier=ModelTier.FAST,
                purpose=gate.name,
                system=MESSAGE_SIGNALS_SYSTEM,
                user=MESSAGE_SIGNALS_USER.format(**payload),
                schema_model=MessageSignals,
                cache_key="message_signals",
                load_id=load_id,
            )
        except LlmUnavailable:
            logger.warning("Gate %s skipped: no LLM available", gate.name)
            return None
        except LlmError as exc:
            logger.warning("Gate %s failed: %s", gate.name, exc)
            return None

        result = response.value.model_dump()

        # The cheap model is right most of the time. When it is unsure, pay for
        # the more capable model once.
        if result["confidence"] < LOW_CONFIDENCE_THRESHOLD:
            try:
                escalated = self.gateway.structured(
                    tier=ModelTier.BALANCED,
                    purpose=f"{gate.name}:escalated",
                    system=MESSAGE_SIGNALS_SYSTEM,
                    user=MESSAGE_SIGNALS_USER.format(**payload),
                    schema_model=MessageSignals,
                    cache_key="message_signals",
                    load_id=load_id,
                )
                result = escalated.value.model_dump()
            except LlmError:
                pass

        self._cache[cache_key] = result
        return result

    @staticmethod
    def _build_message_payload(state: LoadState) -> dict[str, str]:
        context = state_context(state)
        facts = ", ".join(f"{key}={value}" for key, value in sorted(state.facts.items())) or "none"
        return {
            "next_stop_name": context.get("next_stop_name", ""),
            "next_stop_appointment": context.get("next_stop_appointment", ""),
            "delay_risk": state.delay_risk,
            "stage": state.stage.value,
            "facts": facts,
            "message": state.last_inbound_body or "",
        }
