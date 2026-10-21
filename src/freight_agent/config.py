"""Application settings, loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The SOP corpus ships inside the package, so a deployment never has to guess
# where the procedures live. `SOP_DIR` in the environment still wins.
PACKAGED_SOP_DIR = Path(__file__).parent / "sops"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- LLM ---------------------------------------------------------------
    openai_api_key: str | None = None
    llm_enabled: bool = True
    llm_tier_fast_model: str = "gpt-6-luna"
    llm_tier_balanced_model: str = "gpt-6.1-sol"
    llm_tier_frontier_model: str = "gpt-6-astra"
    llm_tier_fast_reasoning_effort: str = "none"

    # --- Storage -----------------------------------------------------------
    database_url: str = "sqlite:///./freight.db"
    redis_url: str = "redis://localhost:6379/0"
    sop_dir: Path = PACKAGED_SOP_DIR

    # --- Behaviour ---------------------------------------------------------
    run_deadline_seconds: int = 240
    per_load_budget_usd: float = 0.50
    llm_max_tool_iterations: int = 6
    llm_request_timeout_seconds: int = 60
    # How long the agent takes to react to an inbound event. Timers are armed
    # from the moment the message is actually sent, so this delay shifts the
    # whole escalation ladder. A timer that fires is our own scheduled work, so
    # it is handled without the delay.
    agent_reaction_seconds: int = 60

    # --- Integrations ------------------------------------------------------
    integrations_mode: str = "mock"
    webhook_secret: str = "change-me"

    # --- Runtime -----------------------------------------------------------
    # Run the timer worker inside the API process.
    #
    # The stores are in-memory and therefore per-process: a worker in its own
    # container cannot see the timers the API armed, so the escalation ladder
    # would stop after the first rung. One process owns both until the
    # Postgres stores land (ADR-0012, docs/PROPOSAL.md section 16).
    timer_worker_enabled: bool = True
    timer_worker_poll_seconds: int = 30

    # --- API ---------------------------------------------------------------
    api_port: int = 8000
    log_level: str = "INFO"

    @property
    def llm_available(self) -> bool:
        return bool(self.llm_enabled and self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def resolve_sop_dir(configured: Path | None = None) -> Path:
    """The SOP directory to use, falling back to the packaged corpus."""
    if configured is not None and configured.is_dir():
        return configured
    return PACKAGED_SOP_DIR
