"""Structured output schemas for every LLM call in the system.

Every call the agent makes declares a Pydantic model. The model's JSON schema is
handed to the API with strict structured output enabled, so the response is
guaranteed to have the right shape and the gate can be evaluated with plain
Python instead of by parsing prose.

Strict mode requires every field to be required and `additionalProperties` to be
false, so the models below deliberately have no field defaults.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class MessageSignals(BaseModel):
    """What a driver message actually contains.

    This is the single most important schema in the system. `has_eta` decides
    whether the escalation ladder advances, so the field descriptions are
    deliberately explicit about the difference between *containing a time* and
    *giving us an ETA*.
    """

    kind: Literal[
        "eta",
        "question",
        "acknowledgement",
        "status_update",
        "other",
    ] = Field(
        description=(
            "eta: the driver states when they will arrive. "
            "question: the driver asks us something. "
            "acknowledgement: a bare confirmation such as 'ok', 'sure', 'yes', 'thanks'. "
            "status_update: the driver reports progress without giving an arrival time. "
            "other: anything else."
        )
    )
    has_eta: bool = Field(
        description=(
            "True only if the message states a time of arrival at the next stop. "
            "False for questions, acknowledgements, complaints, and mentions of times "
            "that are not arrival times."
        )
    )
    eta: str | None = Field(
        description=(
            "The arrival time exactly as the driver stated it, or null when there is no ETA."
        )
    )
    is_question: bool = Field(
        description="True if the driver is asking us for information."
    )
    topic: str | None = Field(
        description=(
            "If the driver asked a question, the short snake_case name of what they asked "
            "about, for example 'po_number' or 'gate_code'. Null otherwise."
        )
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="How confident you are in this classification.",
    )


class DocumentType(BaseModel):
    """Which kind of freight document is this?"""

    document_type: Literal["bol", "pod", "rate_confirmation", "receipt", "other"]
    confidence: float = Field(ge=0.0, le=1.0)


class BillOfLading(BaseModel):
    """Key values from a Bill of Lading."""

    bol_number: str | None = None
    pro_number: str | None = None
    scac: str | None = None
    shipper: str | None = None
    carrier: str | None = None
    commodity: str | None = None
    weight_lbs: int | None = None
    seal_number: str | None = None
    pickup_date: str | None = None
    signed: bool = False
    confidence: float = Field(ge=0.0, le=1.0)


class ProofOfDelivery(BaseModel):
    """Key values from a Proof of Delivery."""

    pod_number: str | None = None
    trailer_number: str | None = None
    signed_by: str | None = None
    signed_at: str | None = None
    stop_name: str | None = None
    pieces: int | None = None
    exceptions: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class RateConfirmation(BaseModel):
    """Key values from a rate confirmation."""

    rate_confirm_number: str | None = None
    agreed_rate_usd: float | None = None
    shipper: str | None = None
    carrier: str | None = None
    mc_number: str | None = None
    stops_count: int | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class FallbackDecision(BaseModel):
    """The fallback agent's decision when no compiled policy matched."""

    reasoning: str = Field(description="Why this is the right action, in one or two sentences.")
    actions: list[FallbackAction] = Field(default_factory=list)
    needs_human: bool = Field(
        description="True if a person should handle this instead of the agent."
    )


class FallbackAction(BaseModel):
    """One action proposed by the fallback agent.

    The model never writes message text. It picks an existing template, and the
    engine renders it. That keeps the "no generated prose" rule of ADR-004 true
    even on the fallback path, and it keeps the cost of the fallback low.
    """

    action: Literal[
        "send_sms",
        "send_email",
        "send_slack",
        "tms_note",
        "create_hero_task",
        "internal_slack",
        "set_timer",
        "no_action",
    ]
    to_role: str | None = Field(default=None, description="driver, dispatcher, broker or hero.")
    to_channel: str | None = Field(default=None)
    template: str | None = Field(
        default=None,
        description=(
            "The name of one of the templates that were offered. Never write message text "
            "yourself. Use null when the action does not send a message."
        ),
    )
    request_key: str | None = Field(default=None)
    after_minutes: int | None = Field(default=None)
    urgent: bool = Field(default=False)
    reason: str = Field(default="", description="Why this action is needed.")


FallbackDecision.model_rebuild()

_SCHEMA_REGISTRY: dict[str, type[BaseModel]] = {
    "MessageSignals": MessageSignals,
    "DocumentType": DocumentType,
    "BillOfLading": BillOfLading,
    "ProofOfDelivery": ProofOfDelivery,
    "RateConfirmation": RateConfirmation,
    "FallbackDecision": FallbackDecision,
}


def schema_by_name(name: str) -> type[BaseModel]:
    try:
        return _SCHEMA_REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"Unknown output schema {name!r}") from exc


def to_strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic schema -> strict JSON schema for the structured output API."""
    schema = model.model_json_schema()
    schema["additionalProperties"] = False
    # Strict mode rejects optional fields: every property must be listed in
    # `required`. Pydantic omits fields that have defaults; we make them
    # required here and let the model fill them with null.
    properties = schema.get("properties", {})
    schema["required"] = list(properties)
    return schema
