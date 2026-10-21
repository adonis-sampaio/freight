"""The HTTP surface: ingest, inspect, and the worker's timer scan."""

from __future__ import annotations

import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from freight_agent.api.app import create_app
from freight_agent.config import Settings
from freight_agent.evals.fake_llm import FakeResponsesClient
from freight_agent.evals.fixtures import LOAD_481207
from freight_agent.llm.gateway import LlmGateway
from freight_agent.runtime import AgentRuntime
from freight_agent.workers.timer_worker import TimerWorker


@pytest.fixture
def client(settings: Settings) -> TestClient:
    gateway = LlmGateway(settings, client=FakeResponsesClient())
    runtime = AgentRuntime.create(settings, gateway=gateway)
    runtime.register_load(LOAD_481207)
    return TestClient(create_app(settings, runtime=runtime))


def _webhook(client: TestClient, payload: dict, secret: str = "s3cret") -> dict:
    raw = json.dumps(payload).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), raw, sha256).hexdigest()
    response = client.post(
        "/webhooks/twilio",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Signature": signature,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_the_health_check_answers(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_a_webhook_without_a_signature_is_rejected(client: TestClient, settings) -> None:
    settings.webhook_secret = "s3cret"
    response = client.post("/webhooks/twilio", json={"load_id": "481207", "body": "hi"})
    assert response.status_code == 401


def test_a_signed_webhook_is_accepted_and_answered(client: TestClient, settings) -> None:
    settings.webhook_secret = "s3cret"
    body = _webhook(
        client,
        {
            "id": "msg-1",
            "load_id": "481207",
            "body": "What's the PO number?",
            "occurred_at": "2026-10-13T07:12:00",
            "contact_id": "drv_20931",
            "role": "driver",
        },
    )
    assert body["decisions"][0]["policy_key"] == "driver.question"
    assert body["decisions"][0]["body"] == "The PO number for load 481207 is 55821."


def test_the_same_webhook_twice_is_deduplicated(client: TestClient, settings) -> None:
    settings.webhook_secret = "s3cret"
    payload = {
        "id": "msg-1",
        "load_id": "481207",
        "body": "What's the PO number?",
        "occurred_at": "2026-10-13T07:12:00",
        "role": "driver",
        "contact_id": "drv_20931",
    }
    first = _webhook(client, payload)
    second = _webhook(client, payload)

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert len(client.get("/loads/481207/actions").json()) == 1


def test_the_state_endpoint_shows_the_open_request(client: TestClient) -> None:
    _webhook(
        client,
        {
            "id": "msg-2",
            "load_id": "481207",
            "body": "What's the PO number?",
            "occurred_at": "2026-10-13T07:12:00",
            "role": "driver",
            "contact_id": "drv_20931",
        },
    )
    state = client.get("/loads/481207").json()
    assert state["load_id"] == "481207"
    assert state["facts"]["po_number"] == "55821"


def test_the_action_endpoint_is_the_audit_trail(client: TestClient) -> None:
    _webhook(
        client,
        {
            "id": "msg-3",
            "load_id": "481207",
            "body": "What's the PO number?",
            "occurred_at": "2026-10-13T07:12:00",
            "role": "driver",
            "contact_id": "drv_20931",
        },
    )
    actions = client.get("/loads/481207/actions").json()
    assert actions[0]["action_type"] == "send_sms"
    assert actions[0]["policy_key"] == "driver.question"
    assert actions[0]["rationale"]


def test_the_sop_endpoint_lists_the_resolved_procedures(client: TestClient) -> None:
    policies = client.get("/sops", params={"client": "client_b"}).json()
    keys = {policy["policy_key"] for policy in policies}
    assert "delay_risk.high" in keys


def test_the_worker_fires_a_due_timer(settings: Settings) -> None:
    runtime = AgentRuntime.create(settings)
    runtime.register_load(LOAD_481207)
    worker = TimerWorker(runtime)

    from freight_agent.domain.events import Event, EventType
    from freight_agent.domain.state import Stage

    runtime.handle_event(
        Event(
            load_id="481207",
            type=EventType.LOCATION_PING,
            occurred_at=datetime(2026, 10, 13, 7, 0, tzinfo=UTC),
            payload={"delay_risk": "high", "stage": Stage.TO_PICKUP.value},
        )
    )
    assert len(runtime.timer_store.list("481207")) == 1

    outcomes = worker.tick(datetime(2026, 10, 13, 7, 31, tzinfo=UTC))
    assert len(outcomes) == 1
    assert runtime.timer_store.list("481207")[0].status == "fired"


def _delay_risk_ping(minutes_ago: int) -> dict:
    """A location ping that pushes the delay risk high."""
    occurred_at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return {
        "id": f"ping-{minutes_ago}",
        "type": "location_ping",
        "load_id": "481207",
        "occurred_at": occurred_at.isoformat(),
        "payload": {"delay_risk": "high", "stage": "to_pickup"},
    }


def test_the_in_process_worker_advances_the_escalation_ladder(settings: Settings) -> None:
    """The deployed service runs the timer worker inside the API process.

    This is the property the deployment depends on. The stores are in-memory,
    so the worker has to share a process with the API to see the timers the
    API armed - and the escalation ladder has to keep climbing.
    """
    settings.timer_worker_enabled = True
    settings.timer_worker_poll_seconds = 1

    gateway = LlmGateway(settings, client=FakeResponsesClient())
    runtime = AgentRuntime.create(settings, gateway=gateway)
    runtime.register_load(LOAD_481207)

    with TestClient(create_app(settings, runtime=runtime)) as client:
        # The ping is 35 minutes old, so the timer it arms is already due and
        # the second rung's "30 minutes since we asked" condition holds.
        _webhook(client, _delay_risk_ping(minutes_ago=35))

        deadline = time.monotonic() + 15
        step_ids: list[str] = []
        while time.monotonic() < deadline:
            step_ids = [a.step_id for a in runtime.action_store.list("481207")]
            if "ask_driver_again" in step_ids:
                break
            time.sleep(0.1)

    assert "ask_driver_first" in step_ids, "the first rung never fired"
    assert "ask_driver_again" in step_ids, "the worker never fired the timer"


def test_a_worker_in_another_process_cannot_see_the_api_timers(settings: Settings) -> None:
    """Why the deployed service is one process, and not three.

    The stores are in-memory, so a second runtime - a second container, a
    second process - starts with an empty timer store. The timers the API
    armed are invisible to it, and the escalation ladder stops after the
    first rung.
    """
    api_runtime = AgentRuntime.create(settings)
    api_runtime.register_load(LOAD_481207)

    from freight_agent.domain.events import Event, EventType
    from freight_agent.domain.state import Stage

    api_runtime.handle_event(
        Event(
            load_id="481207",
            type=EventType.LOCATION_PING,
            occurred_at=datetime.now(UTC) - timedelta(minutes=35),
            payload={"delay_risk": "high", "stage": Stage.TO_PICKUP.value},
        )
    )
    assert len(api_runtime.timer_store.list("481207")) == 1

    other_runtime = AgentRuntime.create(settings)
    assert other_runtime.timer_store.list("481207") == []
    assert other_runtime.fire_due_timers(datetime.now(UTC)) == []
