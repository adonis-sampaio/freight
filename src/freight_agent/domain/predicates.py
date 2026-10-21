"""The declarative predicate vocabulary.

A policy step says *when* it applies using a small dictionary. This module
evaluates that dictionary against the load state.

The vocabulary is deliberately tiny and closed. There is no expression
language and no `eval`: an SOP author can only choose from documented
conditions, which is what makes SOP editing safe for non-technical people
(ADR-007).

Supported keys
--------------
delay_risk                str | list[str]          current delay risk
stage                     str | list[str]          current load stage
load_type                 str | list[str]          "refrigerated", "any"
client_id                 str | list[str]
event_type                str | list[str]          type of the event being handled
no_open_request           str | list[str]           request key with no open request
open_request              dict                     conditions on an open request
never_acted               str                      action signature that never happened
last_inbound_from         str | list[str]          role of the last inbound message
last_inbound_contains     str                      substring of the last inbound body
all / any                 list[dict]               boolean combinators
"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime
from typing import Any

from freight_agent.domain.state import LoadState

_COMPARATORS = {
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
    "==": operator.eq,
    "!=": operator.ne,
}


@dataclass(frozen=True)
class PredicateContext:
    """Everything a predicate may look at besides the load state."""

    now: datetime
    event_type: str | None = None
    gate: dict[str, Any] | None = None
    # The payload of the event being handled. A predicate such as
    # `delay_risk_changed` is about *this* event, not about the state as a whole.
    event_payload: dict[str, Any] = dataclass_field(default_factory=dict)


def _match_value(actual: Any, expected: Any) -> bool:
    """Compare one state value against one expected value (or list of them)."""
    if isinstance(expected, list):
        return any(_match_value(actual, item) for item in expected)
    if expected == "any":
        return True
    if actual is None:
        return False
    return str(actual).lower() == str(expected).lower()


def _compare(actual: float | int | None, expected: Any) -> bool:
    """Compare against a numeric threshold, supporting '>=30' style operators."""
    if actual is None:
        return False
    if isinstance(expected, str):
        for symbol, compare in _COMPARATORS.items():
            if expected.startswith(symbol):
                try:
                    threshold = float(expected[len(symbol) :].strip())
                except ValueError:
                    return False
                return compare(actual, threshold)
        try:
            expected = float(expected)
        except ValueError:
            return False
    if isinstance(expected, (int, float)):
        return actual == expected
    return False


def _check_open_request(spec: dict[str, Any], state: LoadState, ctx: PredicateContext) -> bool:
    key = spec.get("key")
    if key is None:
        return False
    request = state.open_requests.get(key)
    if request is None:
        return False

    # A request that has been answered or cancelled is not open any more, so
    # steps that wait for an answer must not fire on it.
    expected_status = spec.get("status", "open")
    if not _match_value(request.status, expected_status):
        return False

    if "attempts" in spec:
        expected = spec["attempts"]
        if isinstance(expected, str):
            if not _compare(request.attempts, expected):
                return False
        elif request.attempts != int(expected):
            return False

    if "min_attempts" in spec and request.attempts < int(spec["min_attempts"]):
        return False

    if "max_attempts" in spec and request.attempts > int(spec["max_attempts"]):
        return False

    if "elapsed_since_last_ask_minutes" in spec:
        elapsed = state.minutes_since_last_ask(key, ctx.now)
        if not _compare(elapsed, spec["elapsed_since_last_ask_minutes"]):
            return False

    return "responses_seen" not in spec or request.responses_seen == int(spec["responses_seen"])


def evaluate(spec: dict[str, Any] | None, state: LoadState, ctx: PredicateContext) -> bool:
    """Evaluate a predicate specification against the load state."""
    if not spec:
        return True

    return all(_evaluate_key(key, expected, state, ctx) for key, expected in spec.items())


def _evaluate_key(
    key: str, expected: Any, state: LoadState, ctx: PredicateContext
) -> bool:
    match key:
        case "delay_risk":
            return _match_value(state.delay_risk, expected)

        case "delay_risk_changed":
            # True when *this* event moved the delay risk to the expected value.
            # The state alone cannot answer that: the risk stays high long after
            # it changed.
            payload_risk = ctx.event_payload.get("delay_risk")
            if payload_risk is None:
                return False
            return str(payload_risk).lower() == str(expected).lower()

        case "stage":
            return _match_value(state.stage.value, expected)

        case "load_type":
            return _match_value(state.load_type, expected)

        case "client_id":
            return _match_value(state.client_id, expected)

        case "event_type":
            return _match_value(ctx.event_type, expected)

        case "no_open_request":
            keys = expected if isinstance(expected, list) else [expected]
            for request_key in keys:
                if request_key == "any":
                    if not any(r.status == "open" for r in state.open_requests.values()):
                        return True
                elif state.open_request(str(request_key)) is None:
                    return True
            return False

        case "open_request":
            return _check_open_request(expected, state, ctx)

        case "never_acted":
            return expected not in state.acted_signatures

        case "last_inbound_from":
            return _match_value(state.last_inbound_role.value, expected)

        case "last_inbound_contains":
            body = state.last_inbound_body or ""
            needle = str(expected).lower()
            return needle in body.lower()

        case "all":
            return all(evaluate(item, state, ctx) for item in expected)

        case "any":
            return any(evaluate(item, state, ctx) for item in expected)

        case "not":
            return not evaluate(expected, state, ctx)

        case _:
            raise ValueError(f"Unknown predicate key: {key!r}")


def describe(spec: dict[str, Any] | None) -> str:
    """Render a predicate as a short human-readable string (for audit trails)."""
    if not spec:
        return "always"
    parts = []
    for key, expected in spec.items():
        if isinstance(expected, list):
            parts.append(f"{key} in {expected}")
        else:
            parts.append(f"{key} == {expected}")
    return ", ".join(parts)
