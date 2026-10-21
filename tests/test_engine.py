"""The engine: templates, gates, guardrails and the policy engine."""

from __future__ import annotations

from datetime import datetime

import pytest

from freight_agent.config import resolve_sop_dir
from freight_agent.domain.actions import ActionType
from freight_agent.domain.events import ContactRole, Event, EventType
from freight_agent.domain.state import LoadState, Stage
from freight_agent.engine.action_builder import ActionBuilder
from freight_agent.engine.gates import condition_matches
from freight_agent.engine.guardrails import suppression_reason
from freight_agent.engine.templates import TemplateError, TemplateRenderer

NOW = datetime.fromisoformat("2026-10-13T07:00:00")


@pytest.fixture
def templates() -> TemplateRenderer:
    return TemplateRenderer(resolve_sop_dir())


def test_a_template_is_rendered_with_the_load_facts(templates) -> None:
    body = templates.render("ask_eta", "client_a", {"next_stop_name": "Riverbend plant"})
    assert body == "What time will you arrive at Riverbend plant?"


def test_a_client_can_override_the_wording(templates) -> None:
    body = templates.render(
        "ask_eta", "client_b", {"load_id": "481208", "next_stop_name": "Riverbend plant"}
    )
    assert body.startswith("Hi, quick ETA check")
    assert "481208" in body


def test_a_missing_value_fails_the_render(templates) -> None:
    with pytest.raises(TemplateError, match="missing values"):
        templates.render("answer_from_facts", "client_a", {"load_id": "1"})


def test_an_unknown_template_is_an_error(templates) -> None:
    with pytest.raises(TemplateError, match="not found"):
        templates.render("no_such_template", "client_a", {})


# -- gates -----------------------------------------------------------------


def test_a_boolean_gate_condition() -> None:
    assert condition_matches("$gate.has_eta", {"has_eta": True}) is True
    assert condition_matches("$gate.has_eta", {"has_eta": False}) is False


def test_a_comparison_gate_condition() -> None:
    assert condition_matches("$gate.kind == 'question'", {"kind": "question"}) is True
    assert condition_matches("$gate.kind == 'question'", {"kind": "eta"}) is False


def test_conditions_can_be_combined() -> None:
    output = {"is_question": True, "kind": "question"}
    assert condition_matches("$gate.is_question and $gate.kind == 'question'", output) is True
    assert condition_matches("$gate.is_question and $gate.kind == 'eta'", output) is False
    assert condition_matches("$gate.is_question or $gate.kind == 'eta'", output) is True


def test_the_topic_fact_conditions_need_the_load_state() -> None:
    state = LoadState(load_id="1", facts={"po_number": "55821"})
    output = {"topic": "po_number"}

    assert condition_matches("$gate.topic_fact_present", output, state) is True
    assert condition_matches("$gate.topic_fact_missing", output, state) is False
    assert condition_matches("$gate.topic_fact_present", {"topic": "gate_code"}, state) is False
    assert condition_matches("$gate.topic_fact_present", {}, state) is False


# -- the action builder ----------------------------------------------------


def test_the_action_builder_resolves_the_contact_and_the_body(templates) -> None:
    builder = ActionBuilder(templates)
    state = LoadState(
        load_id="481207",
        client_id="client_a",
        stage=Stage.TO_PICKUP,
        contacts={"drv_1": {"role": "driver", "channels": ["sms"]}},
        stops=[{"type": "pickup", "name": "Riverbend plant"}],
    )
    action, reason = builder.build(
        {
            "action": "send_sms",
            "to_role": "driver",
            "template": "ask_eta",
            "reason": "We need an ETA.",
        },
        state=state,
        event=Event(load_id="1", type=EventType.SMS, occurred_at=NOW),
        now=NOW,
        policy_key="delay_risk.high",
        step_id="ask_driver_first",
    )

    assert reason is None
    assert action is not None
    assert action.type is ActionType.SEND_SMS
    assert action.target == "drv_1"
    assert action.body == "What time will you arrive at Riverbend plant?"


def test_an_action_without_a_contact_is_not_built(templates) -> None:
    builder = ActionBuilder(templates)
    state = LoadState(load_id="481207", client_id="client_a")
    action, reason = builder.build(
        {"action": "send_sms", "to_role": "driver", "template": "ask_eta"},
        state=state,
        event=Event(load_id="1", type=EventType.SMS, occurred_at=NOW),
        now=NOW,
        policy_key="p",
        step_id="s",
    )
    assert action is None
    assert "no contact" in reason.lower()


def test_an_email_in_the_main_thread_needs_the_thread_id(templates) -> None:
    builder = ActionBuilder(templates)
    state = LoadState(
        load_id="481207",
        client_id="client_a",
        contacts={"dsp_1": {"role": "dispatcher", "channels": ["email"]}},
    )
    action, reason = builder.build(
        {
            "action": "send_email",
            "to_role": "dispatcher",
            "in_thread": "main",
            "template": "dispatcher_no_eta",
        },
        state=state,
        event=Event(load_id="1", type=EventType.SMS, occurred_at=NOW),
        now=NOW,
        policy_key="p",
        step_id="s",
    )
    assert action is None
    assert "main email thread" in reason


# -- guardrails ------------------------------------------------------------


def test_the_guardrail_stops_a_reply_to_an_unasked_message() -> None:
    state = LoadState(load_id="1")
    event = Event(
        load_id="1",
        type=EventType.SMS,
        occurred_at=NOW,
        source_role=ContactRole.DRIVER,
        body="ok",
    )
    from freight_agent.domain.actions import Action

    action = Action(type=ActionType.SEND_SMS, to_role="driver", body="Thanks!")

    reason = suppression_reason(action, state, event, {})
    assert reason is not None
    assert "nothing to answer" in reason


def test_the_guardrail_allows_a_reply_to_a_question() -> None:
    state = LoadState(load_id="1")
    event = Event(
        load_id="1",
        type=EventType.SMS,
        occurred_at=NOW,
        source_role=ContactRole.DRIVER,
        body="What's the PO number?",
    )
    from freight_agent.domain.actions import Action

    action = Action(type=ActionType.SEND_SMS, to_role="driver", body="It is 55821")

    signals = {"message_signals": {"is_question": True}}
    assert suppression_reason(action, state, event, signals) is None
