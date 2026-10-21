"""Shared test fixtures."""

from __future__ import annotations

import pytest

from freight_agent.config import Settings, resolve_sop_dir
from freight_agent.evals.fake_llm import FakeResponsesClient
from freight_agent.evals.runner import ScenarioRunner


@pytest.fixture
def settings() -> Settings:
    return Settings(
        sop_dir=resolve_sop_dir(),
        llm_enabled=True,
        openai_api_key="test-key",
        agent_reaction_seconds=60,
    )


@pytest.fixture
def fake_llm() -> FakeResponsesClient:
    return FakeResponsesClient()


@pytest.fixture
def runner(settings: Settings, fake_llm: FakeResponsesClient) -> ScenarioRunner:
    return ScenarioRunner(settings=settings, llm_client=fake_llm)
