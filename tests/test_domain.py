"""The domain layer: the fold, the predicates and the state effects."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from freight_agent.domain.actions import ActionType
from freight_agent.domain.events import ContactRole, Event, EventType
from freight_agent.domain.loads import extract_facts, state_from_metadata
from freight_agent.domain.predicates import PredicateContext, describe, evaluate
from freight_agent.domain.state import LoadState, Stage, apply_effect, fold, fold_all

NOW = datetime.fromisoformat("2026-10-13T07:00:00")


def make_event(**kwargs) -> Event:
    defaults = dict(
        load_id="481207",
        type=EventType.SMS,
        occurred_at=NOW,
        source_role=ContactRole.DRIVER,
        body="ok",
    )
    defaults.update(kwargs)
    return Event(**defaults)


def test_fold_tracks_the_last_inbound_message() -> None:
    state = LoadState(load_id="481207")
    folded = fold(state, make_event(body="What's the PO number?"))

    assert folded.last_inbound_body == "What's the PO number?"
    assert folded.last_inbound_role is ContactRole.DRIVER
    assert state.last_inbound_body is None, "the fold must not mutate the input state"


def test_fold_records_the_delay_risk_change() -> None:
    state = LoadState(load_id="481207", delay_risk="low")
    ping = make_event(
        type=EventType.LOCATION_PING, source_role=ContactRole.SYSTEM, payload={"delay_risk": "high"}
    )
    folded = fold(state, ping)

    assert folded.delay_risk == "high"
    assert folded.previous_delay_risk == "low"


def test_open_request_effect_opens_and_counts() -> None:
    state = LoadState(load_id="481207")
    apply_effect(
        state,
        {
            "open_request": {
                "key": "eta",
                "kind": "eta",
                "addressed_to_role": "driver",
                "attempts": 1,
            }
        },
        NOW,
    )
    assert state.open_requests["eta"].status == "open"
    assert state.open_requests["eta"].attempts == 1
    assert state.open_requests["eta"].last_asked_at == NOW


def test_increment_attempts_effect() -> None:
    state = LoadState(load_id="481207")
    apply_effect(state, {"open_request": {"key": "eta", "attempts": 1}}, NOW)
    apply_effect(state, {"increment_attempts": "eta"}, NOW + timedelta(minutes=30))

    assert state.open_requests["eta"].attempts == 2
    assert state.open_requests["eta"].last_asked_at == NOW + timedelta(minutes=30)


def test_close_request_effect() -> None:
    state = LoadState(load_id="481207")
    apply_effect(state, {"open_request": {"key": "eta", "attempts": 1}}, NOW)
    apply_effect(
        state,
        {"close_request": {"key": "eta", "answer": "9:30"}},
        NOW + timedelta(minutes=12),
    )

    request = state.open_requests["eta"]
    assert request.status == "answered"
    assert request.answer == "9:30"


def test_set_timer_effect_parses_the_timestamp() -> None:
    state = LoadState(load_id="481207")
    apply_effect(state, {"open_request": {"key": "eta", "attempts": 1}}, NOW)
    apply_effect(
        state,
        {"set_timer": {"request_key": "eta", "fires_at": "2026-10-13T07:30:00"}},
        NOW,
    )

    assert state.open_requests["eta"].timer_fires_at == datetime(2026, 10, 13, 7, 30)


def test_agent_action_event_replays_its_effects() -> None:
    state = LoadState(load_id="481207")
    action_event = make_event(
        type=EventType.AGENT_ACTION,
        payload={
            "action_type": ActionType.SEND_SMS.value,
            "signature": "send_sms:driver:ask_eta",
            "effects": [{"open_request": {"key": "eta", "attempts": 1}}],
        },
    )
    folded = fold(state, action_event)

    assert folded.open_requests["eta"].status == "open"
    assert "send_sms:driver:ask_eta" in folded.acted_signatures


def test_fold_all_is_equivalent_to_folding_one_by_one() -> None:
    events = [
        make_event(occurred_at=NOW),
        make_event(occurred_at=NOW + timedelta(minutes=1), body="second"),
    ]
    state = LoadState(load_id="481207")
    assert fold_all(state, events).last_inbound_body == fold(
        fold(state, events[0]), events[1]
    ).last_inbound_body


# -- predicates ------------------------------------------------------------


def test_open_request_predicate_requires_an_open_request() -> None:
    state = LoadState(load_id="481207")
    apply_effect(state, {"open_request": {"key": "eta", "attempts": 1}}, NOW)
    apply_effect(state, {"close_request": {"key": "eta"}}, NOW)
    ctx = PredicateContext(now=NOW + timedelta(minutes=30))

    spec = {"open_request": {"key": "eta", "attempts": 1}}
    assert evaluate(spec, state, ctx) is False, "an answered request is not an open request"


def test_open_request_predicate_checks_the_elapsed_time() -> None:
    state = LoadState(load_id="481207")
    apply_effect(state, {"open_request": {"key": "eta", "attempts": 1}}, NOW)
    spec = {"open_request": {"key": "eta", "elapsed_since_last_ask_minutes": ">=30"}}

    assert evaluate(spec, state, PredicateContext(now=NOW + timedelta(minutes=29))) is False
    assert evaluate(spec, state, PredicateContext(now=NOW + timedelta(minutes=30))) is True


def test_delay_risk_changed_only_applies_to_the_event_that_changed_it() -> None:
    state = LoadState(load_id="481207", delay_risk="high")
    spec = {"delay_risk_changed": "high"}

    without_payload = PredicateContext(now=NOW)
    assert evaluate(spec, state, without_payload) is False

    with_payload = PredicateContext(now=NOW, event_payload={"delay_risk": "high"})
    assert evaluate(spec, state, with_payload) is True


def test_unknown_predicate_key_is_an_error() -> None:
    with pytest.raises(ValueError, match="Unknown predicate key"):
        evaluate({"nonsense": 1}, LoadState(load_id="1"), PredicateContext(now=NOW))


def test_describe_is_human_readable() -> None:
    assert describe({"delay_risk": "high"}) == "delay_risk == high"
    assert describe(None) == "always"


# -- load metadata ---------------------------------------------------------


def test_facts_are_extracted_from_the_instructions() -> None:
    facts = extract_facts(
        {"instructions": "Call 1 hr before arrival. PO 55821 required at gate."}
    )
    assert facts["po_number"] == "55821"
    assert facts["call_ahead_minutes"] == "60"


def test_state_from_metadata_keeps_the_contacts_and_the_main_thread() -> None:
    state = state_from_metadata(
        {
            "load_id": "481207",
            "broker": {"id": "client_a"},
            "stage": "to_pickup",
            "email_thread_id": "thread-1",
            "contacts": [{"id": "drv_1", "role": "driver", "channels": ["sms"]}],
            "stops": [{"type": "pickup", "name": "Riverbend plant"}],
        }
    )
    assert state.client_id == "client_a"
    assert state.stage is Stage.TO_PICKUP
    assert state.main_thread_id == "thread-1"
    assert state.role_contact_id("driver") == "drv_1"
    assert state.role_contact_id("dispatcher") is None
