"""SOP document model.

An SOP file is Markdown with YAML front matter and an optional fenced ```policy
block. The prose is for humans; the policy block is for the engine. Both live
in the same file so they can never drift apart (ADR-007).

Authoring rules are documented in `sops/schema/sop-authoring-guide.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

VALID_SCOPES = {"base", "client", "client_load_type"}
VALID_ACTION_TYPES = {
    "send_sms",
    "send_email",
    "send_slack",
    "tms_note",
    "set_timer",
    "create_hero_task",
    "update_load_stage",
    "update_load_state",
    "internal_slack",
    "no_action",
}


@dataclass(frozen=True)
class GateSpec:
    """An LLM classifier that must pass before the step's action runs.

    `condition` is a tiny expression over the gate's structured output, e.g.
    `$gate.has_eta` or `$gate.kind == "acknowledgement"`.
    """

    name: str
    condition: str | None = None
    description: str = ""
    input: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyStep:
    """One executable step of a policy."""

    id: str
    when: dict[str, Any] = field(default_factory=dict)
    gate: GateSpec | None = None
    do: dict[str, Any] = field(default_factory=dict)
    also: list[dict[str, Any]] = field(default_factory=list)
    effect: dict[str, Any] | None = None
    # Override semantics, used only in client/load-type scoped documents.
    merge_into: str | None = None
    disable: bool = False
    description: str = ""

    @property
    def all_actions(self) -> list[dict[str, Any]]:
        """The primary action followed by any `also:` actions."""
        actions = []
        if self.do:
            actions.append(self.do)
        actions.extend(self.also)
        return actions


@dataclass(frozen=True)
class PolicyDocument:
    """A parsed SOP file."""

    path: Path
    policy_key: str
    title: str
    scope: str
    client_id: str | None
    load_types: list[str]
    stages: list[str]
    event_types: list[str]
    situations: list[str]
    priority: int
    version: int
    effective_from: date | None
    description: str = ""
    steps: list[PolicyStep] = field(default_factory=list)
    prose: str = ""

    @property
    def specificity(self) -> int:
        """Higher means more specific. Used to order override application."""
        return {"base": 0, "client": 1, "client_load_type": 2}[self.scope]

    def matches_client(self, client_id: str, load_type: str | None) -> bool:
        if self.scope == "base":
            return True
        if self.client_id and self.client_id != client_id:
            return False
        if self.scope == "client_load_type":
            return self.load_types == ["any"] or (load_type in self.load_types)
        return True


@dataclass(frozen=True)
class Policy:
    """A fully resolved policy: what the engine will actually execute."""

    key: str
    title: str
    priority: int
    stages: list[str]
    event_types: list[str]
    situations: list[str]
    load_types: list[str]
    steps: list[PolicyStep]
    sources: list[str] = field(default_factory=list)
    provenance: dict[str, str] = field(default_factory=dict)

    def step(self, step_id: str) -> PolicyStep | None:
        for step in self.steps:
            if step.id == step_id:
                return step
        return None
