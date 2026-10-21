"""The single choke point for every LLM call.

Responsibilities (see ADR-009 and ADR-010):

* pick the model for a tier;
* request strict structured output and validate it;
* reuse a stable prompt prefix so the provider can serve it from cache;
* retry transient failures with backoff;
* record tokens, cost and latency for every call.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from freight_agent.config import Settings
from freight_agent.llm.schemas import to_strict_json_schema
from freight_agent.llm.tiers import ModelTier, cost_usd, tier_models

logger = logging.getLogger(__name__)


class LlmError(RuntimeError):
    """Raised when a call could not be completed."""


class LlmUnavailable(LlmError):
    """Raised when the LLM layer is disabled or has no API key."""


@dataclass
class LlmCall:
    """The audit record of one model call."""

    id: str
    purpose: str
    tier: ModelTier
    model: str
    load_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    response_id: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "purpose": self.purpose,
            "tier": self.tier.value,
            "model": self.model,
            "load_id": self.load_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "latency_ms": self.latency_ms,
            "response_id": self.response_id,
            "error": self.error,
        }


@dataclass
class LlmResponse:
    """A validated structured response plus its audit record."""

    value: BaseModel
    call: LlmCall
    raw_text: str = ""


class ResponsesClient(Protocol):
    """The slice of the OpenAI SDK that the gateway uses.

    Either `openai.OpenAI().responses` or anything else with a compatible
    `create(**kwargs)` method - the fake client in the evaluation harness is
    one.
    """

    def create(self, **kwargs: Any) -> Any: ...


def _responses_resource(client: Any) -> ResponsesClient:
    """Accept either the SDK client or its `responses` resource.

    `OpenAI(...).responses.create(...)` is the real call; the fake client
    implements `create` directly. Normalising here means the gateway, the
    tiering and the tests all use one shape.
    """
    responses = getattr(client, "responses", None)
    if responses is not None:
        return responses
    return client


@dataclass
class LlmGateway:
    settings: Settings
    client: Any | None = None
    calls: list[LlmCall] = field(default_factory=list)
    _owns_client: bool = False

    @property
    def available(self) -> bool:
        return self.client is not None or self.settings.llm_available

    def _ensure_client(self) -> Any:
        if self.client is not None:
            return self.client
        if not self.settings.llm_available:
            raise LlmUnavailable(
                "The LLM layer is disabled or OPENAI_API_KEY is not set. "
                "The deterministic policy path does not need it."
            )
        from openai import OpenAI

        self.client = OpenAI(
            api_key=self.settings.openai_api_key,
            timeout=self.settings.llm_request_timeout_seconds,
        )
        self._owns_client = True
        return self.client

    def structured(
        self,
        *,
        tier: ModelTier,
        purpose: str,
        system: str,
        user: str,
        schema_model: type[BaseModel],
        cache_key: str | None = None,
        reasoning_effort: str | None = None,
        load_id: str | None = None,
    ) -> LlmResponse:
        """Call the model and return a validated structured response."""
        client = self._ensure_client()
        model = tier_models(self.settings)[tier]

        kwargs: dict[str, Any] = {
            "model": model,
            "input": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_model.__name__,
                    "schema": to_strict_json_schema(schema_model),
                    "strict": True,
                }
            },
            "store": False,
        }
        if cache_key:
            # A stable key routes the request to the same cache shard, so the
            # repeated prefix is served from cache instead of being re-billed.
            kwargs["prompt_cache_key"] = cache_key
        effort = reasoning_effort
        if effort is None and tier is ModelTier.FAST:
            effort = self.settings.llm_tier_fast_reasoning_effort
        if effort and _supports_reasoning(model):
            kwargs["reasoning"] = {"effort": effort}

        call = LlmCall(
            id=str(uuid.uuid4()),
            purpose=purpose,
            tier=tier,
            model=model,
            load_id=load_id,
        )
        started = time.monotonic()
        response = self._call_with_retries(_responses_resource(client), kwargs, call)
        call.latency_ms = int((time.monotonic() - started) * 1000)

        usage = getattr(response, "usage", None)
        if usage is not None:
            call.input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
            call.output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
            details = getattr(usage, "input_tokens_details", None)
            call.cached_tokens = int(getattr(details, "cached_tokens", 0) or 0)
        call.response_id = getattr(response, "id", None)
        call.cost_usd = cost_usd(
            model, call.input_tokens, call.output_tokens, call.cached_tokens
        )

        raw_text = getattr(response, "output_text", "") or ""
        value = self._parse(raw_text, schema_model, call)
        self.calls.append(call)
        return LlmResponse(value=value, call=call, raw_text=raw_text)

    def _call_with_retries(
        self, client: ResponsesClient, kwargs: dict[str, Any], call: LlmCall
    ) -> Any:
        attempts = 3
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return client.create(**kwargs)
            except Exception as exc:  # noqa: BLE001 - provider raises many types
                last_error = exc
                if attempt == attempts - 1:
                    break
                delay = 0.5 * (2**attempt)
                logger.warning(
                    "LLM call %s failed (attempt %d/%d): %s",
                    call.purpose,
                    attempt + 1,
                    attempts,
                    exc,
                )
                time.sleep(delay)
        call.error = str(last_error)
        raise LlmError(f"LLM call {call.purpose!r} failed: {last_error}") from last_error

    def _parse(
        self, raw_text: str, schema_model: type[BaseModel], call: LlmCall
    ) -> BaseModel:
        import json

        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise LlmError(
                f"LLM returned invalid JSON for {call.purpose!r}: {raw_text[:400]!r}"
            ) from exc
        try:
            return schema_model.model_validate(payload)
        except ValidationError as exc:
            raise LlmError(
                f"LLM response for {call.purpose!r} did not match {schema_model.__name__}: {exc}"
            ) from exc

    # -- accounting --------------------------------------------------------

    def total_cost_usd(self) -> float:
        return sum(call.cost_usd for call in self.calls)

    def calls_by_load(self, load_id: str) -> list[LlmCall]:
        return [call for call in self.calls if call.load_id == load_id]


def _supports_reasoning(model: str) -> bool:
    return model.startswith(("gpt-6", "gpt-5", "o1", "o3", "o4"))
