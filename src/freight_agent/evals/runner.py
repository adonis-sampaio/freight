"""The eval harness.

An eval is a timeline: a list of steps, each with a timestamp and optionally an
event, plus what the agent is expected to do at that step. The harness runs the
timeline against a real `AgentRuntime` (real engine, real SOP files, real
templates) with the model replaced by the fake classifier, and then checks the
resulting transcript.

Nothing here is a mock of the agent. Only the model and the outbound integrations
are replaced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from freight_agent.config import Settings, resolve_sop_dir
from freight_agent.domain.events import Event
from freight_agent.domain.state import LoadState
from freight_agent.evals.fake_llm import FakeResponsesClient
from freight_agent.integrations.base import MockAdapter
from freight_agent.llm.gateway import LlmCall, LlmGateway
from freight_agent.persistence.protocols import StoredAction
from freight_agent.runtime import AgentRuntime, RunOutcome


@dataclass
class ActionExpectation:
    """One outbound action the agent is expected to take."""

    action: str
    to: str | None = None
    channel: str | None = None
    body_contains: str | None = None
    body_equals: str | None = None
    subject_contains: str | None = None

    def matches(self, action: StoredAction) -> bool:
        if action.action_type != self.action:
            return False
        if self.to is not None and action.target != self.to and action.to_role != self.to:
            return False
        if self.channel is not None and action.channel != self.channel:
            return False
        if self.body_equals is not None and (action.body or "").strip() != self.body_equals:
            return False
        if self.body_contains is not None and self.body_contains.lower() not in (
            action.body or ""
        ).lower():
            return False
        if self.subject_contains is not None:
            subject = (action.subject or "").lower()
            if self.subject_contains.lower() not in subject:
                return False
        return True

    def describe(self) -> str:
        parts = [self.action]
        if self.to:
            parts.append(f"to {self.to}")
        if self.channel:
            parts.append(f"on {self.channel}")
        if self.body_equals:
            parts.append(f'body "{self.body_equals}"')
        if self.body_contains:
            parts.append(f'body contains "{self.body_contains}"')
        if self.subject_contains:
            parts.append(f'subject contains "{self.subject_contains}"')
        return ", ".join(parts)


@dataclass
class StepExpectation:
    """What must be true after a step."""

    actions: list[ActionExpectation] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=list)
    sent: list[str] = field(default_factory=list)
    forbidden_sent: list[str] = field(default_factory=list)
    open_requests: list[str] = field(default_factory=list)
    answered_requests: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class Step:
    at: datetime
    event: Event | None = None
    expect: StepExpectation = field(default_factory=StepExpectation)


@dataclass
class Scenario:
    key: str
    title: str
    metadata: dict[str, Any]
    steps: list[Step]


@dataclass
class StepResult:
    step: Step
    outcomes: list[RunOutcome] = field(default_factory=list)
    actions: list[StoredAction] = field(default_factory=list)
    sent: list[dict[str, Any]] = field(default_factory=list)
    state: LoadState | None = None


@dataclass
class Transcript:
    scenario: Scenario
    steps: list[StepResult] = field(default_factory=list)
    final_state: LoadState | None = None
    llm_calls: list[LlmCall] = field(default_factory=list)
    sent: list[dict[str, Any]] = field(default_factory=list)

    @property
    def all_actions(self) -> list[StoredAction]:
        return [action for step in self.steps for action in step.actions]


class ScenarioRunner:
    """Runs a scenario and produces a transcript.

    Every run gets a fresh runtime, so scenarios never see each other's state.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        llm_client: FakeResponsesClient | None = None,
        gateway: LlmGateway | None = None,
    ) -> None:
        self.settings = settings or Settings(
            sop_dir=resolve_sop_dir(), llm_enabled=True, openai_api_key="test-key"
        )
        self.llm_client = llm_client or FakeResponsesClient()
        self.gateway = gateway or LlmGateway(self.settings, client=self.llm_client)
        self.adapter = MockAdapter()
        self.runtime = self._build_runtime()

    def _build_runtime(self) -> AgentRuntime:
        return AgentRuntime.create(
            self.settings,
            catalog=None,
            gateway=self.gateway,
            integration=self.adapter,
        )

    def run(self, scenario: Scenario) -> Transcript:
        self.adapter = MockAdapter()
        self.runtime = self._build_runtime()
        self.runtime.register_load(scenario.metadata)
        transcript = Transcript(scenario=scenario)

        for step in scenario.steps:
            sent_before = len(self.adapter.sent)
            outcomes = self.runtime.fire_due_timers(step.at)
            if step.event is not None:
                outcomes.append(self.runtime.handle_event(step.event))

            step_actions = [action for outcome in outcomes for action in outcome.actions]

            result = StepResult(
                step=step,
                outcomes=outcomes,
                actions=step_actions,
                sent=self.adapter.sent[sent_before:],
                state=self.runtime.state_for(scenario.metadata["load_id"]),
            )
            transcript.steps.append(result)

        transcript.final_state = self.runtime.state_for(scenario.metadata["load_id"])
        transcript.llm_calls = list(self.gateway.calls)
        transcript.sent = list(self.adapter.sent)
        return transcript


class EvalFailure(AssertionError):
    """Raised when a scenario does not behave as expected."""


def check(transcript: Transcript) -> list[str]:
    """Check a transcript against its expectations. Returns a list of problems."""
    problems: list[str] = []

    for index, result in enumerate(transcript.steps, start=1):
        expect = result.step.expect
        where = f"step {index} ({result.step.at:%H:%M})"

        for expected in expect.actions:
            if not any(expected.matches(action) for action in result.actions):
                problems.append(
                    f"{where}: expected an action [{expected.describe()}] but did not find it. "
                    f"Actual actions: {[_describe_action(a) for a in result.actions]}"
                )

        for forbidden in expect.forbidden_actions:
            for action in result.actions:
                if action.action_type == forbidden:
                    problems.append(
                        f"{where}: did not expect a {forbidden} action, but one was taken "
                        f"({action.body!r})"
                    )

        sent_kinds = [item["kind"] for item in result.sent]
        for kind in expect.sent:
            if kind not in sent_kinds:
                problems.append(
                    f"{where}: expected to send {kind!r} but only sent {sent_kinds}"
                )
        for kind in expect.forbidden_sent:
            if kind in sent_kinds:
                problems.append(
                    f"{where}: did not expect to send {kind!r}, but it was sent"
                )

        state = result.state
        if state is not None:
            for key in expect.open_requests:
                request = state.open_requests.get(key)
                if request is None or request.status != "open":
                    problems.append(
                        f"{where}: expected the request {key!r} to be open, but it is "
                        f"{request.status if request else 'missing'}"
                    )
            for key in expect.answered_requests:
                request = state.open_requests.get(key)
                if request is None or request.status != "answered":
                    problems.append(
                        f"{where}: expected the request {key!r} to be answered, but it is "
                        f"{request.status if request else 'missing'}"
                    )

    return problems


def _describe_action(action: StoredAction) -> str:
    target = action.target or action.channel or ""
    body = (action.body or "").replace("\n", " ")
    return f"{action.action_type}->{target}: {body[:60]!r}"


def assert_scenario(transcript: Transcript) -> None:
    problems = check(transcript)
    if problems:
        detail = "\n".join(f"  - {problem}" for problem in problems)
        raise EvalFailure(
            f"Scenario {transcript.scenario.key!r} did not behave as expected:\n{detail}"
        )
