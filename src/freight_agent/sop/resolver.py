"""Layered SOP resolution.

The assessment states that 60-70% of the procedure is shared, that the rest is
per client and sometimes per load type, and that clients change their procedure
often. The resolution model reflects that directly:

    base  ->  client  ->  client + load_type

Each layer may override individual *steps*, not whole files. A client that only
changes the escalation target of one situation writes one short file.

Override semantics inside an overriding document:

* a step whose `id` matches an existing step **replaces** it, in place;
* a step with `merge_into: <id>` **merges** its fields into that step;
* a step with `disable: true` **removes** that step.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from freight_agent.domain.state import LoadState
from freight_agent.sop.loader import discover_sop_files, parse_sop_file
from freight_agent.sop.models import Policy, PolicyDocument, PolicyStep


class SopResolveError(ValueError):
    """Raised when an SOP override references something that does not exist."""


@dataclass
class SopCatalog:
    """All SOP documents for one deployment, indexed by policy key."""

    documents: list[PolicyDocument]

    @classmethod
    def from_dir(cls, sop_dir: Path) -> SopCatalog:
        docs = [parse_sop_file(path) for path in discover_sop_files(sop_dir)]
        return cls(documents=docs)

    def documents_for(self, policy_key: str) -> list[PolicyDocument]:
        return [doc for doc in self.documents if doc.policy_key == policy_key]

    # -- resolution --------------------------------------------------------

    def resolve(self, client_id: str, load_type: str | None, policy_key: str) -> Policy | None:
        """Resolve one policy for one client/load type, or None if undefined."""
        candidates = [
            doc
            for doc in self.documents_for(policy_key)
            if doc.matches_client(client_id, load_type)
        ]
        if not candidates:
            return None

        candidates.sort(key=lambda doc: doc.specificity)
        seed = candidates[0]
        policy = _policy_from_document(seed)
        for doc in candidates[1:]:
            policy = _apply_document(policy, doc)
        return policy

    def resolve_all(self, client_id: str, load_type: str | None) -> list[Policy]:
        """Every policy that applies to this client and load type."""
        keys = sorted({doc.policy_key for doc in self.documents})
        policies = []
        for key in keys:
            policy = self.resolve(client_id, load_type, key)
            if policy is not None:
                policies.append(policy)
        return policies

    # -- matching ----------------------------------------------------------

    def candidates(
        self,
        client_id: str,
        load_type: str | None,
        state: LoadState,
        event_type: str,
        situations: set[str],
    ) -> list[Policy]:
        """Policies whose front-matter scope matches the current situation.

        This is the cheap, structured filter: it runs before any LLM work and
        removes the overwhelming majority of the corpus (ADR-008).
        """
        matches = []
        for policy in self.resolve_all(client_id, load_type):
            if policy.event_types and event_type not in policy.event_types:
                continue
            if policy.stages and state.stage.value not in policy.stages:
                continue
            if (
                policy.load_types
                and "any" not in policy.load_types
                and load_type not in policy.load_types
            ):
                continue
            if policy.situations and not set(policy.situations).issubset(situations):
                continue
            matches.append(policy)
        # Highest priority first, then by key for determinism.
        matches.sort(key=lambda policy: (-policy.priority, policy.key))
        return matches


def _policy_from_document(doc: PolicyDocument) -> Policy:
    return Policy(
        key=doc.policy_key,
        title=doc.title,
        priority=doc.priority,
        stages=list(doc.stages),
        event_types=list(doc.event_types),
        situations=list(doc.situations),
        load_types=list(doc.load_types),
        steps=list(doc.steps),
        sources=[str(doc.path)],
        provenance={step.id: str(doc.path) for step in doc.steps},
    )


def _apply_document(policy: Policy, doc: PolicyDocument) -> Policy:
    steps = list(policy.steps)

    for step in doc.steps:
        if step.disable:
            steps = [existing for existing in steps if existing.id != step.id]
            continue

        if step.merge_into:
            index = _index_of(steps, step.merge_into)
            if index is None:
                raise SopResolveError(
                    f"{doc.path}: merge_into references unknown step {step.merge_into!r}"
                )
            steps[index] = _merge_steps(steps[index], step)
            continue

        index = _index_of(steps, step.id)
        if index is None:
            steps.append(step)
        else:
            steps[index] = step

    sources = [*policy.sources, str(doc.path)]
    provenance = dict(policy.provenance)
    for step in doc.steps:
        provenance[step.id] = str(doc.path)

    return replace(
        policy,
        steps=steps,
        sources=sources,
        provenance=provenance,
        priority=max(policy.priority, doc.priority),
        title=doc.title if doc.scope != "base" else policy.title,
    )


def _index_of(steps: list[PolicyStep], step_id: str) -> int | None:
    for index, step in enumerate(steps):
        if step.id == step_id:
            return index
    return None


def _merge_steps(base: PolicyStep, override: PolicyStep) -> PolicyStep:
    """Field-level merge. Nested blocks (`when`, `do`, `gate`) replace wholesale."""
    return replace(
        base,
        when=dict(override.when) if override.when else base.when,
        gate=override.gate if override.gate is not None else base.gate,
        do=dict(override.do) if override.do else base.do,
        also=list(override.also) if override.also else base.also,
        effect=dict(override.effect) if override.effect is not None else base.effect,
        description=override.description or base.description,
    )
