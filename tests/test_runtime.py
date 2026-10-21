"""The runtime: deduplication, idempotency, timers and the action ledger."""

from __future__ import annotations

from datetime import datetime

import pytest

from freight_agent.domain.actions import Action, ActionType
from freight_agent.domain.events import Event, EventType
from freight_agent.evals.fake_llm import FakeResponsesClient
from freight_agent.evals.fixtures import LOAD_481207, at, driver_sms, ping
from freight_agent.evals.runner import ScenarioRunner
from freight_agent.runtime import AgentRuntime, action_time, idempotency_key

NOW = datetime.fromisoformat("2026-10-13T07:00:00")


@pytest.fixture
def runtime(settings) -> AgentRuntime:
    runner = ScenarioRunner(settings=settings)
    runtime = runner.runtime
    runtime.register_load(LOAD_481207)
    return runtime


def test_a_duplicate_event_is_ignored(runtime: AgentRuntime) -> None:
    event = driver_sms("481207", at(7, 12), "What's the PO number?")
    runtime.handle_event(event)
    before = len(runtime.event_store.load("481207"))

    outcome = runtime.handle_event(event)
    assert outcome.duplicate is True
    assert len(runtime.event_store.load("481207")) == before
    assert len(runtime.integration.sent) == 1


def test_a_retried_event_does_not_send_twice(runtime: AgentRuntime) -> None:
    """The provider redelivers the same message. We must answer only once."""
    event = driver_sms("481207", at(7, 12), "What's the PO number?")
    runtime.handle_event(event)
    before = len(runtime.integration.sent)

    runtime.handle_event(event.model_copy(update={"provider_event_id": None}))
    assert len(runtime.integration.sent) == before


def test_a_new_message_from_the_driver_is_answered_again(runtime: AgentRuntime) -> None:
    """A genuinely new question is a new event, and gets its own answer."""
    runtime.handle_event(driver_sms("481207", at(7, 12), "What's the PO number?"))
    before = len(runtime.integration.sent)

    runtime.handle_event(driver_sms("481207", at(7, 13), "What's the PO number?"))
    assert len(runtime.integration.sent) == before + 1


def test_the_idempotency_key_is_stable_for_the_same_event(runtime: AgentRuntime) -> None:
    event = driver_sms("481207", at(7, 12), "What's the PO number?")
    action = Action(type=ActionType.SEND_SMS, to_role="driver", body="hello")

    assert idempotency_key(action, event) == idempotency_key(action, event)
    assert idempotency_key(action, event) != idempotency_key(
        action, event.model_copy(update={"id": "other"})
    )


def test_a_timer_fires_once(runtime: AgentRuntime) -> None:
    runtime.handle_event(ping("481207", at(7, 0), delay_risk="high", stage="to_pickup"))

    timers = runtime.timer_store.list("481207")
    assert len(timers) == 1
    assert timers[0].fires_at == at(7, 31)

    outcomes = runtime.fire_due_timers(at(7, 31))
    assert len(outcomes) == 1
    assert runtime.fire_due_timers(at(7, 31)) == []


def test_the_state_is_folded_from_the_event_log(runtime: AgentRuntime) -> None:
    runtime.handle_event(ping("481207", at(7, 0), delay_risk="high", stage="to_pickup"))

    state = runtime.state_for("481207")
    assert state.delay_risk == "high"
    assert state.open_requests["eta"].status == "open"

    # Rebuilding the state from scratch gives the same answer.
    rebuilt = runtime.state_for("481207")
    assert rebuilt.open_requests["eta"].attempts == state.open_requests["eta"].attempts


def test_the_action_ledger_records_every_decision(runtime: AgentRuntime) -> None:
    runtime.handle_event(ping("481207", at(7, 0), delay_risk="high", stage="to_pickup"))

    actions = runtime.action_store.list("481207")
    assert [a.action_type for a in actions] == ["send_sms", "set_timer"]
    assert actions[0].policy_key == "delay_risk.high"
    assert actions[0].step_id == "ask_driver_first"
    assert actions[0].idempotency_key


def test_an_inbound_event_is_handled_a_moment_later() -> None:
    event = Event(load_id="1", type=EventType.SMS, occurred_at=NOW)
    assert action_time(event, 60) == datetime(2026, 10, 13, 7, 1)


def test_a_timer_is_handled_without_the_reaction_delay() -> None:
    event = Event(load_id="1", type=EventType.TIMER_FIRED, occurred_at=NOW)
    assert action_time(event, 60) == NOW


def test_the_gateway_accounting_is_per_load(settings) -> None:
    from freight_agent.evals.scenarios import client_a_escalation

    runner = ScenarioRunner(settings=settings, llm_client=FakeResponsesClient())
    transcript = runner.run(client_a_escalation())

    assert transcript.llm_calls, "the gate must have called the model"
    assert all(call.purpose for call in transcript.llm_calls)
    assert all(call.load_id == "481207" for call in transcript.llm_calls)
