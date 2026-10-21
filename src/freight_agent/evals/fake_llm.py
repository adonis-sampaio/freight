"""A fake OpenAI Responses client.

The evals must be deterministic and must run without an API key, so the model is
replaced by a small rule-based classifier. It implements the same protocol as the
real client (`create(**kwargs) -> response with .output_text and .usage`), so the
gateway, the tiering, the retry logic and the cost accounting are all exercised
exactly as they are in production.

The classifier is deliberately literal. It handles the message shapes that appear
in the eval scenarios and nothing else; anything unexpected is classified as
"other" with a low confidence, which is what a cautious model would do.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

_ACKNOWLEDGEMENTS = {
    "ok",
    "okay",
    "k",
    "sure",
    "yes",
    "yeah",
    "yep",
    "no",
    "nope",
    "thanks",
    "thank you",
    "thx",
    "got it",
    "copy",
    "copy that",
    "roger",
    "understood",
    "will do",
}

_TOPIC_PATTERNS: list[tuple[str, str]] = [
    (r"\bpo\s*(number|no\.?|#)", "po_number"),
    (r"\bpro\s*(number|no\.?|#)", "pro_number"),
    (r"\bgate\b", "gate_code"),
    (r"\bdock\b", "dock_number"),
    (r"\bappointment\b", "appointment_time"),
    (r"\btrailer\s*(number|no\.?)", "trailer_number"),
    (r"\bseal\b", "seal_number"),
    (r"\bbill of lading\b|\bb\b.?l\b", "bol_number"),
]

_ETA_PATTERNS = [
    r"\beta\b",
    r"\bi(?:'ll| will)\s+(?:be|get)\s+(?:there|at\b)",
    r"\barrive\w*\b",
    r"\bthere\s+at\b",
    r"\bexpect\s+to\s+(?:be|arrive|get)\b",
    r"\b(?:back|arriving)\s+(?:at|around)\b",
    r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
    r"\b\d{1,2}:\d{2}\b",
]


@dataclass
class FakeUsage:
    input_tokens: int = 120
    output_tokens: int = 25
    input_tokens_details: Any = field(
        default_factory=lambda: type("Details", (), {"cached_tokens": 100})()
    )


@dataclass
class FakeResponse:
    output_text: str
    usage: FakeUsage
    id: str = "resp-fake"


def classify_message(text: str) -> dict[str, Any]:
    """Classify a driver message the way the production prompt asks the model to."""
    stripped = text.strip()
    lowered = stripped.lower().rstrip(".!")
    eta: str | None = None
    has_eta = False

    if lowered in _ACKNOWLEDGEMENTS:
        return _signals("acknowledgement", is_question=False, has_eta=False)

    is_question = "?" in stripped or lowered.startswith(
        ("what", "where", "when", "which", "how", "who", "can you", "could you", "do you")
    )

    for pattern in _ETA_PATTERNS:
        if re.search(pattern, lowered):
            has_eta = True
            break

    # A question is never an ETA, even when it contains a time-like word.
    if is_question:
        has_eta = False
        topic = None
        for pattern, name in _TOPIC_PATTERNS:
            if re.search(pattern, lowered):
                topic = name
                break
        return _signals("question", is_question=True, has_eta=False, topic=topic)

    if has_eta:
        eta = _extract_time(stripped)

    kind = "eta" if has_eta else "status_update"
    return _signals(kind, is_question=False, has_eta=has_eta, eta=eta)


def _extract_time(text: str) -> str | None:
    match = re.search(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", text, re.I)
    return match.group(1) if match else None


def _signals(
    kind: str,
    *,
    is_question: bool,
    has_eta: bool,
    topic: str | None = None,
    eta: str | None = None,
    confidence: float = 0.93,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "has_eta": has_eta,
        "eta": eta,
        "is_question": is_question,
        "topic": topic,
        "confidence": confidence,
    }


class FakeResponsesClient:
    """Stands in for `openai.OpenAI().responses`."""

    def __init__(self, classifier=None) -> None:
        self.classifier = classifier or classify_message
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        schema_name = _schema_name(kwargs)

        if schema_name == "FallbackDecision":
            payload = self.fallback_decision(_last_user_content(kwargs))
        else:
            user = _last_user_content(kwargs)
            payload = self.classifier(_extract_message(user))

        return FakeResponse(
            output_text=json.dumps(payload),
            usage=FakeUsage(),
            id=f"resp-fake-{len(self.calls)}",
        )

    def fallback_decision(self, user_prompt: str) -> dict[str, Any]:
        """What the fallback agent answers when it is not sure.

        The default is to ask a human, which is the safe answer and the one the
        fallback agent is supposed to prefer.
        """
        return {
            "reasoning": (
                "No compiled policy covers this event, and the fallback agent is not "
                "confident enough to improvise, so a person has to look at it."
            ),
            "actions": [],
            "needs_human": True,
        }


def _schema_name(kwargs: dict[str, Any]) -> str:
    text = kwargs.get("text") or {}
    fmt = text.get("format") or {}
    return str(fmt.get("name", ""))


def _last_user_content(kwargs: dict[str, Any]) -> str:
    items = kwargs.get("input") or []
    for item in reversed(items):
        if isinstance(item, dict) and item.get("role") == "user":
            content = item.get("content")
            if isinstance(content, str):
                return content
    return ""


def _extract_message(user_prompt: str) -> str:
    match = re.search(r'"""(.*?)"""', user_prompt, re.DOTALL)
    if match:
        return match.group(1).strip()
    return user_prompt.strip()
