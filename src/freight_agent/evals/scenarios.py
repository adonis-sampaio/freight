"""The eval scenarios.

These are the test cases the assessment asks for: the agent has to take the
right action at each step of the situation, and there has to be a case where the
right action is to do nothing.
"""

from __future__ import annotations

from freight_agent.evals.fixtures import (
    LOAD_481207,
    LOAD_CLIENT_B,
    LOAD_QUIET,
    LOAD_UNCOVERED,
    at,
    driver_sms,
    ping,
)
from freight_agent.evals.runner import (
    ActionExpectation,
    Scenario,
    Step,
    StepExpectation,
)

DRIVER = "drv_20931"
DISPATCHER = "dsp_4410"

ASK_ETA = ActionExpectation(
    action="send_sms",
    to=DRIVER,
    body_contains="What time will you arrive at",
)
# Client B overrides the wording of the same message.
ASK_ETA_CLIENT_B = ActionExpectation(
    action="send_sms",
    to=DRIVER,
    body_contains="quick ETA check",
)
ANSWER_PO = ActionExpectation(
    action="send_sms",
    to=DRIVER,
    body_contains="55821",
)
EMAIL_DISPATCHER = ActionExpectation(
    action="send_email",
    to=DISPATCHER,
    body_contains="has not answered two requests",
)
HERO_TASK = ActionExpectation(action="create_hero_task")
SLACK_BROKER = ActionExpectation(
    action="send_slack",
    channel="broker",
    body_contains="at risk of missing the appointment",
)
TRAILER_CHECK = ActionExpectation(
    action="send_sms",
    to=DRIVER,
    body_contains="trailer temperature",
)


def client_a_escalation() -> Scenario:
    """The assessment's situation, step by step."""
    return Scenario(
        key="client_a_escalation",
        title="Load 481207: the delay risk goes high and the driver never gives an ETA",
        metadata=LOAD_481207,
        steps=[
            Step(
                at=at(7, 0),
                event=ping("481207", at(7, 0), delay_risk="high", stage="to_pickup"),
                expect=StepExpectation(
                    actions=[ASK_ETA],
                    sent=["send_sms"],
                    open_requests=["eta"],
                    notes="First rung: one SMS to the driver, and the ETA request opens.",
                ),
            ),
            Step(
                at=at(7, 12),
                event=driver_sms("481207", at(7, 12), "What's the PO number?"),
                expect=StepExpectation(
                    actions=[ANSWER_PO],
                    sent=["send_sms"],
                    open_requests=["eta"],
                    notes=(
                        "The driver asked a question, not an ETA. We answer it from the load "
                        "metadata and the ETA request stays open."
                    ),
                ),
            ),
            Step(
                at=at(7, 31),
                expect=StepExpectation(
                    actions=[ASK_ETA],
                    sent=["send_sms"],
                    open_requests=["eta"],
                    notes="Second rung: 30 minutes after the first ask, we ask again.",
                ),
            ),
            Step(
                at=at(8, 1),
                expect=StepExpectation(
                    actions=[EMAIL_DISPATCHER, HERO_TASK],
                    sent=["send_email", "create_hero_task"],
                    open_requests=["eta"],
                    notes=(
                        "Third rung: two asks and no ETA, so the dispatcher is emailed in the "
                        "main thread and the Hero team gets a task."
                    ),
                ),
            ),
        ],
    )


def client_a_driver_gives_eta() -> Scenario:
    """The same load, but the driver answers with an ETA. The ladder stops."""
    return Scenario(
        key="client_a_eta_stops_the_ladder",
        title="Load 481207: the driver gives an ETA, so the ladder stops",
        metadata=LOAD_481207,
        steps=[
            Step(
                at=at(7, 0),
                event=ping("481207", at(7, 0), delay_risk="high", stage="to_pickup"),
                expect=StepExpectation(
                    actions=[ASK_ETA], sent=["send_sms"], open_requests=["eta"]
                ),
            ),
            Step(
                at=at(7, 12),
                event=driver_sms("481207", at(7, 12), "I'll be there at 9:30"),
                expect=StepExpectation(
                    actions=[],
                    sent=[],
                    answered_requests=["eta"],
                    notes="The ETA closes the request, so no reply is needed and the ladder stops.",
                ),
            ),
            Step(
                at=at(7, 31),
                expect=StepExpectation(
                    actions=[],
                    sent=[],
                    answered_requests=["eta"],
                    notes="The timer fires but the request is answered, so nothing happens.",
                ),
            ),
        ],
    )


def client_a_do_nothing() -> Scenario:
    """The canonical do-nothing case: the driver says "ok" and we asked nothing."""
    return Scenario(
        key="client_a_do_nothing",
        title="The driver says 'ok' and the agent did not ask anything",
        metadata=LOAD_QUIET,
        steps=[
            Step(
                at=at(9, 15),
                event=driver_sms("481209", at(9, 15), "ok"),
                expect=StepExpectation(
                    actions=[],
                    sent=[],
                    forbidden_sent=["send_sms", "send_email", "send_slack", "create_hero_task"],
                    notes=(
                        "Nothing is sent. The decision to do nothing is still recorded, so it "
                        "can be audited and tested."
                    ),
                ),
            ),
        ],
    )


def client_a_ack_while_waiting() -> Scenario:
    """The driver acknowledges instead of giving the ETA. The request stays open."""
    return Scenario(
        key="client_a_ack_while_waiting",
        title="The driver says 'ok' while we are waiting for an ETA",
        metadata=LOAD_481207,
        steps=[
            Step(
                at=at(7, 0),
                event=ping("481207", at(7, 0), delay_risk="high", stage="to_pickup"),
                expect=StepExpectation(
                    actions=[ASK_ETA], sent=["send_sms"], open_requests=["eta"]
                ),
            ),
            Step(
                at=at(7, 12),
                event=driver_sms("481207", at(7, 12), "ok"),
                expect=StepExpectation(
                    actions=[],
                    sent=[],
                    open_requests=["eta"],
                    notes=(
                        "An acknowledgement is not an ETA, so we do not reply "
                        "and we keep waiting."
                    ),
                ),
            ),
        ],
    )


def client_b_broker_alert() -> Scenario:
    """Client B wants a Slack alert to the broker, and never a dispatcher email."""
    return Scenario(
        key="client_b_broker_alert",
        title="Client B: one SMS to the driver, then a Slack alert to the broker",
        metadata=LOAD_CLIENT_B,
        steps=[
            Step(
                at=at(7, 0),
                event=ping("481208", at(7, 0), delay_risk="high", stage="to_pickup"),
                expect=StepExpectation(
                    actions=[ASK_ETA_CLIENT_B], sent=["send_sms"], open_requests=["eta"]
                ),
            ),
            Step(
                at=at(7, 31),
                expect=StepExpectation(
                    actions=[SLACK_BROKER],
                    sent=["send_slack", "internal_slack"],
                    forbidden_actions=["send_email"],
                    forbidden_sent=["send_email", "create_hero_task"],
                    open_requests=["eta"],
                    notes=(
                        "Client B: no second SMS, no dispatcher email. The broker is alerted in "
                        "Slack 30 minutes after the first ask."
                    ),
                ),
            ),
        ],
    )


def client_b_refrigerated_trailer_check() -> Scenario:
    """Client B, refrigerated: check the trailer temperature and the seal."""
    return Scenario(
        key="client_b_refrigerated_trailer_check",
        title="Client B, refrigerated: the driver leaves the pickup",
        metadata=LOAD_CLIENT_B,
        steps=[
            Step(
                at=at(11, 40),
                event=ping("481208", at(11, 40), stage="to_delivery"),
                expect=StepExpectation(
                    actions=[TRAILER_CHECK],
                    sent=["send_sms"],
                    open_requests=["trailer_check"],
                    notes=(
                        "The driver left the pickup on a refrigerated load, so we ask for the "
                        "trailer temperature and the seal number in one message."
                    ),
                ),
            ),
        ],
    )


def fallback_when_no_policy_matches() -> Scenario:
    """An event no procedure covers: the fallback agent takes over."""
    return Scenario(
        key="fallback_when_no_policy_matches",
        title="The driver reports a problem that no procedure covers",
        metadata=LOAD_UNCOVERED,
        steps=[
            Step(
                at=at(13, 5),
                event=driver_sms("481210", at(13, 5), "trailer is running 20 minutes late"),
                expect=StepExpectation(
                    actions=[
                        ActionExpectation(
                            action="create_hero_task",
                            body_contains="needs a human",
                        )
                    ],
                    sent=["create_hero_task"],
                    notes=(
                        "No compiled policy covers this event, so the fallback agent reasons over "
                        "the procedure text. It is not confident, so it escalates to a person "
                        "instead of improvising."
                    ),
                ),
            ),
        ],
    )


ALL_SCENARIOS = [
    client_a_escalation,
    client_a_driver_gives_eta,
    client_a_do_nothing,
    client_a_ack_while_waiting,
    client_b_broker_alert,
    client_b_refrigerated_trailer_check,
    fallback_when_no_policy_matches,
]


def all_scenarios() -> list[Scenario]:
    return [factory() for factory in ALL_SCENARIOS]
