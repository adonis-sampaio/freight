"""The runtime: the piece that turns events into effects.

This is the orchestration layer. It owns the sequence:

    receive event -> dedupe -> append to the log -> fold the state ->
    decide -> execute the actions idempotently -> record everything

Everything it needs is injected, so the same runtime runs against in-memory
stores in the eval harness and against Postgres in production.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from freight_agent.config import Settings, resolve_sop_dir
from freight_agent.domain.actions import Action, ActionType
from freight_agent.domain.events import ContactRole, Event, EventType
from freight_agent.domain.loads import state_from_metadata
from freight_agent.domain.state import LoadState, fold_all
from freight_agent.engine.action_builder import ActionBuilder
from freight_agent.engine.fallback_agent import FallbackAgent
from freight_agent.engine.gates import GateRunner
from freight_agent.engine.policy_engine import Decision, EngineResult, PolicyEngine
from freight_agent.engine.templates import TemplateRenderer
from freight_agent.integrations.base import IntegrationAdapter, MockAdapter
from freight_agent.llm.gateway import LlmGateway
from freight_agent.persistence.memory import (
    InMemoryActionStore,
    InMemoryEventStore,
    InMemoryTimerStore,
)
from freight_agent.persistence.protocols import (
    ActionStore,
    EventStore,
    StoredAction,
    Timer,
    TimerStore,
)
from freight_agent.sop.resolver import SopCatalog

logger = logging.getLogger(__name__)

# Events a person or a system sent us. Only these can need the fallback agent.
_INBOUND_EVENT_TYPES = {
    EventType.EMAIL,
    EventType.SMS,
    EventType.SLACK,
    EventType.LOCATION_PING,
    EventType.ATTACHMENT,
}


class InMemoryLoadRegistry:
    """The load metadata, keyed by load id."""

    def __init__(self) -> None:
        self._loads: dict[str, dict[str, Any]] = {}

    def put(self, load_id: str, metadata: dict[str, Any]) -> None:
        self._loads[load_id] = metadata

    def get(self, load_id: str) -> dict[str, Any] | None:
        return self._loads.get(load_id)


@dataclass
class RunOutcome:
    """What one agent run did."""

    event: Event
    state_before: LoadState | None = None
    state_after: LoadState | None = None
    decisions: list[Decision] = field(default_factory=list)
    actions: list[StoredAction] = field(default_factory=list)
    duplicate: bool = False
    fallback_used: bool = False
    cost_usd: float = 0.0

    @property
    def sent(self) -> list[StoredAction]:
        return [a for a in self.actions if a.status == "executed"]


class AgentRuntime:
    def __init__(
        self,
        *,
        settings: Settings,
        catalog: SopCatalog,
        engine: PolicyEngine,
        gateway: LlmGateway,
        event_store: EventStore,
        action_store: ActionStore,
        timer_store: TimerStore,
        integration: IntegrationAdapter,
        load_registry: InMemoryLoadRegistry | None = None,
        fallback: FallbackAgent | None = None,
    ) -> None:
        self.settings = settings
        self.catalog = catalog
        self.engine = engine
        self.gateway = gateway
        self.event_store = event_store
        self.action_store = action_store
        self.timer_store = timer_store
        self.integration = integration
        self.load_registry = load_registry or InMemoryLoadRegistry()
        self.fallback = fallback
        # The API serves requests on a thread pool while the timer worker
        # scans on its own thread, and both drive this runtime. The lock keeps
        # a decision and its idempotency check together, so an event cannot be
        # handled twice - which would mean two SMS to a driver.
        self._lock = threading.RLock()

    # -- construction ------------------------------------------------------

    @classmethod
    def create(
        cls,
        settings: Settings,
        *,
        catalog: SopCatalog | None = None,
        gateway: LlmGateway | None = None,
        event_store: EventStore | None = None,
        action_store: ActionStore | None = None,
        timer_store: TimerStore | None = None,
        integration: IntegrationAdapter | None = None,
        load_registry: InMemoryLoadRegistry | None = None,
    ) -> AgentRuntime:
        sop_dir = resolve_sop_dir(settings.sop_dir)
        catalog = catalog or SopCatalog.from_dir(sop_dir)
        gateway = gateway or LlmGateway(settings)
        templates = TemplateRenderer(sop_dir)
        gates = GateRunner(gateway)
        action_builder = ActionBuilder(templates)
        engine = PolicyEngine(catalog, gates, action_builder)
        runtime = cls(
            settings=settings,
            catalog=catalog,
            engine=engine,
            gateway=gateway,
            event_store=event_store or InMemoryEventStore(),
            action_store=action_store or InMemoryActionStore(),
            timer_store=timer_store or InMemoryTimerStore(),
            integration=integration or MockAdapter(),
            load_registry=load_registry,
        )
        runtime.fallback = FallbackAgent(gateway, catalog, templates, action_builder)
        return runtime

    # -- loads -------------------------------------------------------------

    def register_load(self, metadata: dict[str, Any]) -> LoadState:
        """Register a load's metadata so that state can be folded for it."""
        with self._lock:
            load_id = str(metadata.get("load_id"))
            self.load_registry.put(load_id, metadata)
            return state_from_metadata(metadata)

    def state_for(self, load_id: str) -> LoadState:
        """The current state of a load, folded from its metadata and event log."""
        metadata = self.load_registry.get(load_id)
        base = state_from_metadata(metadata) if metadata else LoadState(load_id=load_id)
        events = self.event_store.load(load_id)
        return fold_all(base, events)

    # -- the run loop ------------------------------------------------------

    def handle_event(self, event: Event) -> RunOutcome:
        """Process one event end to end."""
        with self._lock:
            return self._handle_event(event)

    def _handle_event(self, event: Event) -> RunOutcome:
        """Process one event end to end. The caller holds the lock."""
        if event.provider_event_id and self.event_store.has_provider_event(
            event.provider_event_id
        ):
            logger.info("Duplicate event %s ignored", event.provider_event_id)
            return RunOutcome(event=event, duplicate=True)

        self.event_store.append(event)
        state_before = self.state_for(event.load_id)

        now = action_time(event, self.settings.agent_reaction_seconds)

        cost_before = self.gateway.total_cost_usd()
        result = self.engine.run(state_before, event, now=now)

        if not result.decisions and self._should_fall_back(state_before, event):
            self._run_fallback(result, state_before, event, now)

        outcome = RunOutcome(
            event=event,
            state_before=state_before,
            decisions=result.decisions,
            cost_usd=self.gateway.total_cost_usd() - cost_before,
            fallback_used=any(d.policy_key == "fallback" for d in result.decisions),
        )

        action_events, produced = self._execute(result, event, now)
        outcome.actions = produced
        outcome.state_after = self.state_for(event.load_id)
        return outcome

    def _should_fall_back(self, state: LoadState, event: Event) -> bool:
        """Should the fallback agent take over?

        Only for inbound events that no policy covered at all, and only while
        there is budget left for the load. A timer firing is our own work, so
        there is nothing to fall back to.
        """
        if event.type not in _INBOUND_EVENT_TYPES:
            return False
        if self.fallback is None:
            return False
        if not self.gateway.available:
            return False
        spent = sum(call.cost_usd for call in self.gateway.calls_by_load(state.load_id))
        return spent < self.settings.per_load_budget_usd

    def _run_fallback(
        self,
        result: EngineResult,
        state: LoadState,
        event: Event,
        now: datetime,
    ) -> None:
        fallback = self.fallback
        if fallback is None:
            return
        history = self.event_store.load(state.load_id)[-25:]
        outcome = fallback.decide(state, event, history, now)
        if outcome is None:
            return
        for action in outcome.actions:
            result.decisions.append(
                Decision(
                    policy_key="fallback",
                    step_id="fallback_decision",
                    status="no_action" if action.type is ActionType.NO_ACTION else "executed",
                    rationale=outcome.reasoning or "No compiled policy covered this event.",
                    predicate="fallback",
                    action=action,
                    source="fallback agent",
                )
            )

    def _execute(
        self, result: EngineResult, event: Event, now: datetime
    ) -> tuple[list[Event], list[StoredAction]]:
        """Run the decided actions, idempotently, and record them."""
        action_events: list[Event] = []
        produced: list[StoredAction] = []

        for decision in result.decisions:
            action = decision.action
            if action is None:
                continue

            key = idempotency_key(action, event)
            if self.action_store.find_by_key(key) is not None:
                logger.info("Action %s already recorded, skipping", key)
                continue

            stored = StoredAction(
                id=str(uuid.uuid4()),
                load_id=event.load_id,
                event_id=event.id,
                action_type=action.type.value,
                status=decision.status,
                idempotency_key=key,
                target=action.target,
                to_role=action.to_role,
                channel=action.channel,
                body=action.body,
                subject=action.subject,
                thread_id=action.thread_id,
                template=action.template,
                reason=action.reason,
                rationale=decision.rationale,
                predicate=decision.predicate,
                policy_key=decision.policy_key,
                step_id=decision.step_id,
                gate=decision.gate,
                effects=list(action.effects),
                cost_usd=0.0,
                created_at=now,
            )
            if not self.action_store.record(stored):
                continue
            produced.append(stored)

            if decision.status == "executed":
                self._dispatch(action, stored, key)

            action_events.append(
                Event(
                    load_id=event.load_id,
                    type=EventType.AGENT_ACTION,
                    occurred_at=now,
                    received_at=now,
                    payload={
                        "action_type": action.type.value,
                        "signature": action.signature,
                        "effects": action.effects,
                        "policy_key": decision.policy_key,
                        "step_id": decision.step_id,
                        "body": action.body,
                        "stage": action.stage,
                    },
                )
            )

        for action_event in action_events:
            self.event_store.append(action_event)
        return action_events, produced

    def _dispatch(self, action: Action, stored: StoredAction, key: str) -> None:
        """Send the action to the outside world, or schedule it."""
        if action.type in {ActionType.NO_ACTION, ActionType.UPDATE_LOAD_STATE}:
            return
        if action.type is ActionType.UPDATE_LOAD_STAGE:
            return
        if action.type is ActionType.SET_TIMER:
            timer = Timer(
                id=str(uuid.uuid4()),
                load_id=stored.load_id,
                request_key=action.request_key or "",
                fires_at=action.fires_at or event_time(stored),
                reason=action.reason,
                payload={"event_id": stored.event_id, "policy_key": action.policy_key},
            )
            self.timer_store.schedule(timer)
            return

        if action.type is ActionType.SEND_SMS:
            self.integration.send_sms(action.target or "", action.body or "", key)
        elif action.type is ActionType.SEND_EMAIL:
            self.integration.send_email(
                action.target or "",
                action.subject or "",
                action.body or "",
                action.thread_id,
                key,
            )
        elif action.type is ActionType.SEND_SLACK:
            self.integration.send_slack(action.channel or "", action.body or "", key)
        elif action.type is ActionType.INTERNAL_SLACK:
            self.integration.internal_slack(action.channel or "", action.body or "", key)
        elif action.type is ActionType.TMS_NOTE:
            self.integration.tms_note(action.target or "", action.body or "", key)
        elif action.type is ActionType.CREATE_HERO_TASK:
            self.integration.create_hero_task(
                action.target or "",
                action.subject or action.reason,
                action.body or "",
                action.urgent,
                key,
            )

    # -- timers ------------------------------------------------------------

    def fire_due_timers(self, now: datetime) -> list[RunOutcome]:
        """Turn every due timer into a `timer_fired` event and process it."""
        with self._lock:
            outcomes = []
            for timer in self.timer_store.due(now):
                self.timer_store.mark_fired(timer.id)
                event = Event(
                    load_id=timer.load_id,
                    type=EventType.TIMER_FIRED,
                    occurred_at=timer.fires_at,
                    received_at=now,
                    source_role=ContactRole.SYSTEM,
                    payload={
                        "timer_id": timer.id,
                        "request_key": timer.request_key,
                        "reason": timer.reason,
                        "policy_key": timer.payload.get("policy_key"),
                    },
                )
                outcomes.append(self._handle_event(event))
            return outcomes


def action_time(event: Event, reaction_seconds: int) -> datetime:
    """When the agent actually acts on an event.

    An inbound event is handled a moment after it arrives, and the timers we
    arm are counted from that moment. A timer that fires is our own scheduled
    work, so it is handled without the delay.
    """
    if event.type is EventType.TIMER_FIRED:
        return event.occurred_at
    return event.occurred_at + timedelta(seconds=reaction_seconds)


def idempotency_key(action: Action, event: Event) -> str:
    """Content-addressed key so a retried event cannot send twice."""
    material = "|".join(
        [
            event.load_id,
            event.id,
            action.policy_key or "",
            action.step_id or "",
            action.type.value,
            action.target or "",
            action.body or "",
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def event_time(stored: StoredAction) -> datetime:
    return stored.created_at or datetime.now()