"""SOP validation.

The assessment requires that an AI engineer is *not* necessary to change an SOP.
That only works if mistakes are caught automatically and explained in plain
language, so this module is the safety net for non-technical editors.

Two entry points:

* `validate_catalog(catalog, template_names)` — every file, every rule.
* `validate_document(doc)` — a single file, used by the CLI and by CI.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from freight_agent.sop.models import VALID_ACTION_TYPES, PolicyDocument
from freight_agent.sop.resolver import SopCatalog, SopResolveError

KNOWN_PREDICATE_KEYS = {
    "delay_risk",
    "delay_risk_changed",
    "stage",
    "load_type",
    "client_id",
    "event_type",
    "no_open_request",
    "open_request",
    "never_acted",
    "last_inbound_from",
    "last_inbound_contains",
    "all",
    "any",
    "not",
}

KNOWN_STAGES = {
    "dispatched",
    "to_pickup",
    "at_pickup",
    "to_delivery",
    "at_delivery",
    "delivered",
}

KNOWN_EVENT_TYPES = {
    "email",
    "sms",
    "slack",
    "location_ping",
    "timer_fired",
    "attachment",
}

KNOWN_EFFECT_KEYS = {
    "open_request",
    "increment_attempts",
    "close_request",
    "cancel_request",
    "set_timer",
    "set_delay_risk",
    "set_stage",
    "record_fact",
}


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass(frozen=True)
class ValidationResult:
    issues: list[ValidationIssue]

    @property
    def ok(self) -> bool:
        return not self.issues

    def render(self) -> str:
        if self.ok:
            return "All SOP files are valid."
        return "\n".join(f"  - {issue}" for issue in self.issues)


def validate_document(doc: PolicyDocument) -> list[ValidationIssue]:
    """Validate one SOP document."""
    issues: list[ValidationIssue] = []
    where = str(doc.path)

    if doc.scope not in {"base", "client", "client_load_type"}:
        issues.append(
            ValidationIssue(
                where,
                f"scope must be 'base', 'client' or 'client_load_type' (found {doc.scope!r})",
            )
        )
    if doc.scope == "client" and not doc.client_id:
        issues.append(ValidationIssue(where, "scope 'client' requires a client_id"))
    if doc.scope == "client_load_type" and not doc.client_id:
        issues.append(ValidationIssue(where, "scope 'client_load_type' requires a client_id"))

    for stage in doc.stages:
        if stage not in KNOWN_STAGES:
            issues.append(
                ValidationIssue(
                    where,
                    f"unknown stage {stage!r}. Known stages: {sorted(KNOWN_STAGES)}",
                )
            )
    for event_type in doc.event_types:
        if event_type not in KNOWN_EVENT_TYPES:
            issues.append(
                ValidationIssue(
                    where,
                    f"unknown event type {event_type!r}. "
                    f"Known types: {sorted(KNOWN_EVENT_TYPES)}",
                )
            )

    seen_ids: set[str] = set()
    for step in doc.steps:
        step_where = f"{where} [{step.id}]"

        if step.id in seen_ids:
            issues.append(ValidationIssue(step_where, "duplicate step id in this file"))
        seen_ids.add(step.id)

        for key in step.when:
            if key not in KNOWN_PREDICATE_KEYS:
                issues.append(
                    ValidationIssue(
                        step_where,
                        f"unknown condition {key!r}. "
                        f"Known conditions: {sorted(KNOWN_PREDICATE_KEYS)}",
                    )
                )

        for action_spec in step.all_actions:
            action_type = action_spec.get("action")
            if action_type not in VALID_ACTION_TYPES:
                issues.append(
                    ValidationIssue(
                        step_where,
                        f"unknown action {action_type!r}. "
                        f"Known actions: {sorted(VALID_ACTION_TYPES)}",
                    )
                )
            if action_type == "set_timer":
                if not action_spec.get("request_key"):
                    issues.append(
                        ValidationIssue(step_where, "a set_timer action needs a request_key")
                    )
                if not action_spec.get("after_minutes"):
                    issues.append(
                        ValidationIssue(step_where, "a set_timer action needs after_minutes")
                    )
            if action_type == "send_email" and not action_spec.get("template") and not (
                action_spec.get("body")
            ):
                issues.append(
                    ValidationIssue(step_where, "a send_email action needs a template or a body")
                )
            if action_type in {"send_sms", "send_email"} and not (
                action_spec.get("template") or action_spec.get("body")
            ):
                issues.append(
                    ValidationIssue(
                        step_where,
                        f"a {action_type} action needs a template or a body",
                    )
                )
            if action_type == "send_slack" and not action_spec.get("to_channel"):
                issues.append(
                    ValidationIssue(step_where, "a send_slack action needs a to_channel")
                )

        if step.effect:
            for key in step.effect:
                if key not in KNOWN_EFFECT_KEYS:
                    issues.append(
                        ValidationIssue(
                            step_where,
                            f"unknown effect {key!r}. Known effects: {sorted(KNOWN_EFFECT_KEYS)}",
                        )
                    )

    return issues


def validate_catalog(
    catalog: SopCatalog,
    template_names: set[str] | None = None,
) -> ValidationResult:
    """Validate the whole catalog, including cross-document consistency."""
    issues: list[ValidationIssue] = []

    for doc in catalog.documents:
        issues.extend(validate_document(doc))

        if template_names is not None:
            for step in doc.steps:
                for action_spec in step.all_actions:
                    template = action_spec.get("template")
                    if template and template not in template_names:
                        issues.append(
                            ValidationIssue(
                                f"{doc.path} [{step.id}]",
                                f"template {template!r} does not exist. "
                                f"Available templates: {sorted(template_names)}",
                            )
                        )

    # Override references must point at steps that actually exist in the base.
    by_key: dict[str, list[PolicyDocument]] = {}
    for doc in catalog.documents:
        by_key.setdefault(doc.policy_key, []).append(doc)

    all_keys = sorted(by_key)
    for policy_key, docs in by_key.items():
        base_docs = [doc for doc in docs if doc.scope == "base"]
        if not base_docs:
            # A client may legitimately define a situation that no other client
            # has. Only flag it when another key looks a lot like it, which is
            # what a typo looks like.
            close = difflib.get_close_matches(
                policy_key,
                [k for k in all_keys if k != policy_key],
                n=1,
                cutoff=0.7,
            )
            if close:
                issues.append(
                    ValidationIssue(
                        str(docs[0].path),
                        f"policy key {policy_key!r} has no base document. "
                        f"Did you mean {close[0]!r}?",
                    )
                )
            continue
        base_step_ids = {step.id for step in base_docs[0].steps}
        for doc in docs:
            if doc.scope == "base":
                continue
            for step in doc.steps:
                if step.merge_into and step.merge_into not in base_step_ids:
                    issues.append(
                        ValidationIssue(
                            f"{doc.path} [{step.id}]",
                            f"merge_into {step.merge_into!r} does not exist in the base policy "
                            f"{policy_key!r}. Base steps: {sorted(base_step_ids)}",
                        )
                    )
                if step.disable and step.id not in base_step_ids:
                    issues.append(
                        ValidationIssue(
                            f"{doc.path} [{step.id}]",
                            f"cannot disable {step.id!r}: it does not exist in the base policy "
                            f"{policy_key!r}",
                        )
                    )

    # A client document may not define a policy key the base does not know.
    for docs in by_key.values():
        if not any(doc.scope == "base" for doc in docs):
            continue
        base = next(doc for doc in docs if doc.scope == "base")
        for doc in docs:
            if doc.scope == "base":
                continue
            if doc.policy_key != base.policy_key:
                issues.append(
                    ValidationIssue(
                        str(doc.path),
                        f"policy key {doc.policy_key!r} does not match base {base.policy_key!r}",
                    )
                )

    return ValidationResult(issues=issues)


def resolve_catalog_issues(catalog: SopCatalog) -> list[ValidationIssue]:
    """Try resolving every client document; report resolution failures."""
    issues: list[ValidationIssue] = []
    clients = {doc.client_id for doc in catalog.documents if doc.client_id}
    load_types = sorted({"refrigerated"}) + [None]
    for client_id in sorted(c for c in clients if c):
        for load_type in load_types:
            try:
                catalog.resolve_all(client_id, load_type)
            except SopResolveError as exc:
                issues.append(ValidationIssue(f"client {client_id!r}", str(exc)))
    return issues


def template_names(sop_dir: Path) -> set[str]:
    """Names of all message templates available under `sop_dir`."""
    names: set[str] = set()
    for path in sop_dir.rglob("*.md"):
        if "templates" in path.relative_to(sop_dir).parts:
            names.add(path.stem)
    return names
