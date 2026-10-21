"""Loading SOP Markdown files into `PolicyDocument`s.

The format is intentionally minimal:

* YAML front matter delimited by `---` at the top of the file.
* An optional fenced code block tagged ```policy containing a YAML list of steps.

Anything else in the file is prose and is preserved (it is what the SOP editors
read, and it is shown to the LLM during fallback reasoning).
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from freight_agent.sop.models import GateSpec, PolicyDocument, PolicyStep

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_POLICY_BLOCK_RE = re.compile(r"^```policy\s*\n(.*?)^```", re.DOTALL | re.MULTILINE)


class SopParseError(ValueError):
    """Raised when an SOP file cannot be parsed."""


def _parse_front_matter(text: str, path: Path) -> dict[str, Any]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise SopParseError(f"{path}: missing YAML front matter")
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise SopParseError(f"{path}: invalid front matter: {exc}") from exc
    if not isinstance(data, dict):
        raise SopParseError(f"{path}: front matter must be a mapping")
    return data


def _parse_gate(raw: dict[str, Any] | None) -> GateSpec | None:
    if not raw:
        return None
    return GateSpec(
        name=str(raw.get("name", "default")),
        condition=raw.get("condition"),
        description=str(raw.get("description", "")),
        input=dict(raw.get("input") or {}),
    )


def _parse_step(raw: dict[str, Any], path: Path) -> PolicyStep:
    if not isinstance(raw, dict):
        raise SopParseError(f"{path}: each policy step must be a mapping")
    step_id = raw.get("id")
    if not step_id:
        raise SopParseError(f"{path}: every policy step needs an 'id'")
    return PolicyStep(
        id=str(step_id),
        when=dict(raw.get("when") or {}),
        gate=_parse_gate(raw.get("gate")),
        do=dict(raw.get("do") or {}),
        also=[dict(item) for item in (raw.get("also") or [])],
        effect=dict(raw["effect"]) if raw.get("effect") else None,
        merge_into=raw.get("merge_into"),
        disable=bool(raw.get("disable", False)),
        description=str(raw.get("description", "")),
    )


def parse_sop_file(path: Path) -> PolicyDocument:
    text = path.read_text(encoding="utf-8")
    front = _parse_front_matter(text, path)

    missing = [key for key in ("policy_key", "scope") if key not in front]
    if missing:
        raise SopParseError(f"{path}: front matter missing {missing}")

    block_match = _POLICY_BLOCK_RE.search(text)
    steps: list[PolicyStep] = []
    if block_match:
        try:
            raw_steps = yaml.safe_load(block_match.group(1)) or []
        except yaml.YAMLError as exc:
            raise SopParseError(f"{path}: invalid policy block: {exc}") from exc
        if not isinstance(raw_steps, list):
            raise SopParseError(f"{path}: policy block must be a YAML list of steps")
        steps = [_parse_step(raw, path) for raw in raw_steps]

    effective_from = front.get("effective_from")
    if isinstance(effective_from, str):
        effective_from = date.fromisoformat(effective_from)

    return PolicyDocument(
        path=path,
        policy_key=str(front["policy_key"]),
        title=str(front.get("title", front["policy_key"])),
        scope=str(front["scope"]),
        client_id=front.get("client_id"),
        load_types=[str(item) for item in (front.get("load_types") or ["any"])],
        stages=[str(item) for item in (front.get("stages") or [])],
        event_types=[str(item) for item in (front.get("event_types") or [])],
        situations=[str(item) for item in (front.get("situations") or [])],
        priority=int(front.get("priority", 50)),
        version=int(front.get("version", 1)),
        effective_from=effective_from,
        description=str(front.get("description", "")),
        steps=steps,
        prose=_strip_blocks(text),
    )


def _strip_blocks(text: str) -> str:
    """Remove front matter and policy blocks, leaving the human prose."""
    body = _FRONTMATTER_RE.sub("", text)
    return _POLICY_BLOCK_RE.sub("", body).strip()


def discover_sop_files(sop_dir: Path) -> list[Path]:
    """All SOP policy Markdown files under `sop_dir`, sorted for deterministic order.

    `templates/` holds message wording, not policies, and `schema/` holds the
    authoring guide; neither is a policy document.
    """
    skip_dirs = {"schema", "templates"}
    return sorted(
        path
        for path in sop_dir.rglob("*.md")
        if path.is_file()
        and not (skip_dirs & set(path.relative_to(sop_dir).parts))
    )
