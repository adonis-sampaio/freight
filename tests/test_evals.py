"""The eval scenarios from the assessment, run as tests.

These are the deliverable: they show that the agent takes the right action at
each step of the situation, including the case where the right action is to do
nothing.
"""

from __future__ import annotations

import pytest

from freight_agent.evals.runner import ScenarioRunner, check
from freight_agent.evals.scenarios import ALL_SCENARIOS, all_scenarios


@pytest.mark.parametrize("factory", ALL_SCENARIOS, ids=lambda f: f().key)
def test_scenario(factory, runner: ScenarioRunner) -> None:
    scenario = factory()
    transcript = runner.run(scenario)
    problems = check(transcript)
    assert not problems, "\n".join(problems)


def test_the_assessment_situation_step_by_step(runner: ScenarioRunner) -> None:
    """The assessment's timeline, asserted step by step rather than as a whole."""
    scenario = next(s for s in all_scenarios() if s.key == "client_a_escalation")
    transcript = runner.run(scenario)
    steps = transcript.steps

    # 07:01 - the first rung: one SMS to the driver.
    first = steps[0]
    assert [a.action_type for a in first.actions] == ["send_sms", "set_timer"]
    assert first.actions[0].body == "What time will you arrive at Riverbend plant?"
    assert first.actions[0].target == "drv_20931"
    assert first.state.open_requests["eta"].status == "open"

    # 07:13 - the driver asked a question, not an ETA.
    second = steps[1]
    assert [a.action_type for a in second.actions] == ["send_sms"]
    assert second.actions[0].body == "The PO number for load 481207 is 55821."
    assert second.state.open_requests["eta"].status == "open", (
        "answering a question must not close the ETA request"
    )

    # 07:31 - the second rung: ask again.
    third = steps[2]
    assert [a.action_type for a in third.actions] == ["send_sms", "set_timer"]
    assert third.state.open_requests["eta"].attempts == 2

    # 08:01 - the third rung: email the dispatcher and open a Hero task.
    fourth = steps[3]
    assert [a.action_type for a in fourth.actions] == ["send_email", "create_hero_task"]
    assert fourth.actions[0].target == "dsp_4410"
    assert fourth.actions[0].thread_id == "thread-northline-481207"
    assert "has not answered two requests" in fourth.actions[0].body


def test_doing_nothing_is_recorded(runner: ScenarioRunner) -> None:
    """Doing nothing must be a recorded decision, not an absence."""
    scenario = next(s for s in all_scenarios() if s.key == "client_a_do_nothing")
    transcript = runner.run(scenario)

    actions = transcript.all_actions
    assert [a.action_type for a in actions] == ["no_action"]
    assert transcript.sent == [], "nothing may be sent"
    assert actions[0].reason


def test_no_dispatcher_contact_for_client_b(runner: ScenarioRunner) -> None:
    scenario = next(s for s in all_scenarios() if s.key == "client_b_broker_alert")
    transcript = runner.run(scenario)

    sent_kinds = [item["kind"] for item in transcript.sent]
    assert "send_slack" in sent_kinds
    assert "send_email" not in sent_kinds
    assert sent_kinds.count("send_sms") == 1, "Client B gets exactly one SMS"


def test_the_ladder_stops_when_the_driver_gives_an_eta(runner: ScenarioRunner) -> None:
    scenario = next(s for s in all_scenarios() if s.key == "client_a_eta_stops_the_ladder")
    transcript = runner.run(scenario)

    assert transcript.final_state.open_requests["eta"].status == "answered"
    assert [item["kind"] for item in transcript.sent] == ["send_sms"]
