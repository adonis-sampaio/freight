"""The ingest API.

A small FastAPI service that accepts events from the outside world and hands
them to the runtime. It is deliberately thin: validate the envelope, check the
provider signature, call `handle_event`, report what happened.

    uvicorn freight_agent.api.app:app --port 8000

The service holds one runtime per process. In production the runtime is backed
by Postgres and Redis; the in-memory stores used here are the reference
implementation of the same protocols (ADR-0003, ADR-0012).
"""

from __future__ import annotations

import hmac
import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from freight_agent.config import Settings, get_settings, resolve_sop_dir
from freight_agent.domain.events import Event, EventType
from freight_agent.runtime import AgentRuntime
from freight_agent.sop.resolver import SopCatalog
from freight_agent.workers.timer_worker import TimerWorker

logger = logging.getLogger(__name__)

_runtime: AgentRuntime | None = None


def get_runtime() -> AgentRuntime:
    """The process-wide runtime. Built lazily so imports stay cheap."""
    global _runtime
    if _runtime is None:
        _runtime = build_runtime(get_settings())
    return _runtime


def build_runtime(settings: Settings) -> AgentRuntime:
    sop_dir = resolve_sop_dir(settings.sop_dir)
    catalog = SopCatalog.from_dir(sop_dir)
    return AgentRuntime.create(settings, catalog=catalog)


class LoadRegistration(BaseModel):
    """The load metadata the agent needs to reason about a load.

    The shape is the TMS's own: a list of contacts, each with an id, a role
    and the channels we may use to reach them.
    """

    load_id: str
    client_id: str = Field(..., description="The client's id, e.g. client_a.")
    load_type: str = "dry_van"
    stage: str = "dispatched"
    delay_risk: str = "low"
    facts: dict[str, Any] = Field(default_factory=dict)
    contacts: list[dict[str, Any]] = Field(default_factory=list)
    stops: list[dict[str, Any]] = Field(default_factory=list)
    instructions: str = ""


class DecisionView(BaseModel):
    policy_key: str
    step_id: str
    status: str
    rationale: str
    action_type: str | None = None
    body: str | None = None


class OutcomeView(BaseModel):
    event_id: str
    load_id: str
    duplicate: bool
    fallback_used: bool
    cost_usd: float
    decisions: list[DecisionView]


def create_app(settings: Settings | None = None, runtime: AgentRuntime | None = None) -> FastAPI:
    settings = settings or get_settings()

    def runtime_for() -> AgentRuntime:
        if runtime is not None:
            return runtime
        return get_runtime()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """Run the timer worker alongside the API.

        The stores are in-memory and therefore per-process. The timers the API
        arms are only visible to a worker that shares its memory, so the worker
        runs here, on a thread of this process, rather than as a separate
        service. When the Postgres stores land (ADR-0012) the worker moves out
        into its own service and this turns itself off.
        """
        if not settings.timer_worker_enabled:
            yield
            return

        worker = TimerWorker(
            runtime_for(),
            poll_seconds=settings.timer_worker_poll_seconds,
        )
        thread = threading.Thread(target=worker.run_forever, name="timer-worker", daemon=True)
        thread.start()
        logger.info("timer worker started in-process, polling every %ss", worker.poll_seconds)
        try:
            yield
        finally:
            worker.stop()
            thread.join(timeout=5)

    app = FastAPI(
        title="Freight load agent",
        version="0.1.0",
        description="Ingest events, get decisions. The agent is the runtime.",
        lifespan=lifespan,
    )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        runtime_for()
        return {"status": "ready"}

    @app.post("/loads", status_code=status.HTTP_201_CREATED)
    def register_load(payload: LoadRegistration) -> dict[str, Any]:
        runtime = runtime_for()
        state = runtime.register_load(payload.model_dump())
        return {
            "load_id": state.load_id,
            "client_id": state.client_id,
            "stage": state.stage.value,
            "facts": state.facts,
        }

    @app.post("/webhooks/{provider}", status_code=status.HTTP_202_ACCEPTED)
    async def ingest(
        provider: str,
        request: Request,
        response: Response,
        x_signature: str | None = Header(default=None, alias="X-Signature"),
    ) -> OutcomeView:
        raw = await request.body()
        if (
            settings.webhook_secret
            and settings.webhook_secret != "change-me"
            and not _signature_matches(raw, x_signature or "", settings.webhook_secret)
        ):
            raise HTTPException(status_code=401, detail="bad signature")

        try:
            payload = await request.json()
        except Exception as exc:  # noqa: BLE001 - the body is not JSON
            raise HTTPException(status_code=400, detail="body is not JSON") from exc

        event = _event_from(provider, payload)
        outcome = runtime_for().handle_event(event)
        return _outcome_view(outcome)

    @app.get("/loads/{load_id}")
    def load_state(load_id: str) -> dict[str, Any]:
        runtime = runtime_for()
        state = runtime.state_for(load_id)
        return {
            "load_id": state.load_id,
            "client_id": state.client_id,
            "stage": state.stage.value,
            "delay_risk": state.delay_risk,
            "facts": state.facts,
            "open_requests": {
                key: {
                    "kind": request.kind,
                    "status": request.status,
                    "attempts": request.attempts,
                    "last_asked_at": request.last_asked_at.isoformat()
                    if request.last_asked_at
                    else None,
                }
                for key, request in state.open_requests.items()
            },
        }

    @app.get("/loads/{load_id}/events")
    def load_events(load_id: str) -> list[dict[str, Any]]:
        runtime = runtime_for()
        return [event.model_dump(mode="json") for event in runtime.event_store.load(load_id)]

    @app.get("/loads/{load_id}/actions")
    def load_actions(load_id: str) -> list[dict[str, Any]]:
        """The audit trail: what the agent did, and why."""
        runtime = runtime_for()
        return [action.as_dict() for action in runtime.action_store.list(load_id)]

    @app.get("/sops")
    def sops(client: str, load_type: str | None = None) -> list[dict[str, Any]]:
        settings_ = settings
        sop_dir = resolve_sop_dir(settings_.sop_dir)
        catalog = SopCatalog.from_dir(sop_dir)
        return [
            {
                "policy_key": policy.key,
                "title": policy.title,
                "steps": [
                    {
                        "id": step.id,
                        "description": step.description,
                        "source": policy.provenance.get(step.id),
                    }
                    for step in policy.steps
                ],
            }
            for policy in catalog.resolve_all(client, load_type)
        ]

    return app


def _signature_matches(raw: bytes, signature: str, secret: str) -> bool:
    """Providers sign the raw body with HMAC-SHA256; we compare in constant time."""
    expected = hmac.new(secret.encode("utf-8"), raw, sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def _event_from(provider: str, payload: dict[str, Any]) -> Event:
    """Map a provider's webhook body onto the canonical envelope."""
    event_type = payload.get("type") or _event_type_for(provider, payload)
    data = payload.get("data", payload)

    body = data.get("body") or data.get("text") or data.get("message")
    occurred_at = data.get("occurred_at") or data.get("timestamp")
    if isinstance(occurred_at, str):
        occurred_at = datetime.fromisoformat(occurred_at)
    elif not isinstance(occurred_at, datetime):
        occurred_at = datetime.now(UTC)

    return Event(
        load_id=str(data.get("load_id") or payload.get("load_id") or ""),
        type=EventType(event_type),
        occurred_at=occurred_at,
        source_contact_id=data.get("contact_id") or data.get("from"),
        source_role=data.get("role", "unknown"),
        channel=data.get("channel") or provider,
        thread_id=data.get("thread_id"),
        body=body,
        payload=data.get("payload", {}),
        provider_event_id=data.get("id") or payload.get("provider_event_id"),
    )


def _event_type_for(provider: str, payload: dict[str, Any]) -> str:
    mapping = {
        "twilio": "sms",
        "sms": "sms",
        "sendgrid": "email",
        "email": "email",
        "slack": "slack",
        "tms": "location_ping",
    }
    return mapping.get(provider.lower(), "email")


def _outcome_view(outcome) -> OutcomeView:
    decisions = []
    for decision in outcome.decisions:
        action = decision.action
        decisions.append(
            DecisionView(
                policy_key=decision.policy_key,
                step_id=decision.step_id,
                status=decision.status,
                rationale=decision.rationale,
                action_type=action.type.value if action else None,
                body=action.body if action else None,
            )
        )
    return OutcomeView(
        event_id=outcome.event.id,
        load_id=outcome.event.load_id,
        duplicate=outcome.duplicate,
        fallback_used=outcome.fallback_used,
        cost_usd=round(outcome.cost_usd, 6),
        decisions=decisions,
    )


app = create_app()


def main() -> None:  # pragma: no cover - process entry point
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "freight_agent.api.app:app",
        host="0.0.0.0",
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":  # pragma: no cover
    main()
