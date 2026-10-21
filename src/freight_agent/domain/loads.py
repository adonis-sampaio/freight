"""Turning the TMS load metadata into a starting `LoadState`.

The load metadata JSON is the system of record for the *facts* about a load:
who the contacts are, what the stops are, what the PO number is. This module
reads it once, at the start of a load, and seeds the state from it.

Facts are extracted deterministically with regular expressions rather than by
asking a model. The instructions field is short, structured and repeated by
humans, so a regex is both cheaper and more reliable than an LLM here. When a
fact is not derivable it is simply absent, and the policy that needs it will
escalate instead of guessing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from freight_agent.domain.state import LoadState, Stage

# `PO 55821 required at gate`, `PO#55821`, `PO number 55821`
_PO_RE = re.compile(r"\bPO\s*(?:number|no\.?|#)?\s*[:#]?\s*([A-Z0-9][A-Z0-9\-]{2,})", re.I)
_GATE_RE = re.compile(r"\bgate\s*(?:code\s*)?(?:is\s*)?[:#]?\s*([A-Z0-9\-]{2,})", re.I)
_DOCK_RE = re.compile(r"\bdock\s*(?:number\s*)?(?:is\s*)?[:#]?\s*([A-Z0-9\-]{2,})", re.I)
_CALL_RE = re.compile(r"\bcall\s+(\d+)\s*(?:hour|hr|hours)?\s*(?:before|in advance)", re.I)


def extract_facts(metadata: dict[str, Any]) -> dict[str, str]:
    """Facts we can derive from the load metadata without asking a model."""
    facts: dict[str, str] = {}

    explicit = metadata.get("facts")
    if isinstance(explicit, dict):
        facts.update({str(key): str(value) for key, value in explicit.items()})

    instructions = str(metadata.get("instructions") or "")
    if instructions:
        if (match := _PO_RE.search(instructions)) and "po_number" not in facts:
            facts["po_number"] = match.group(1)
        if (match := _GATE_RE.search(instructions)) and "gate_code" not in facts:
            facts["gate_code"] = match.group(1)
        if (match := _DOCK_RE.search(instructions)) and "dock_number" not in facts:
            facts["dock_number"] = match.group(1)
        if (match := _CALL_RE.search(instructions)) and "call_ahead_minutes" not in facts:
            facts["call_ahead_minutes"] = str(int(match.group(1)) * 60)

    if "commodity" in metadata and "commodity" not in facts:
        facts["commodity"] = str(metadata["commodity"])
    if metadata.get("shipper") and "shipper" not in facts:
        facts["shipper"] = str(metadata["shipper"])

    return facts


def state_from_metadata(metadata: dict[str, Any]) -> LoadState:
    """Seed a `LoadState` from the load metadata JSON."""
    broker = metadata.get("broker") or {}
    client_id = str(broker.get("id") or metadata.get("client_id") or "default")

    contacts: dict[str, dict[str, Any]] = {}
    for contact in metadata.get("contacts") or []:
        contact_id = str(contact.get("id"))
        contacts[contact_id] = {
            "role": contact.get("role", "unknown"),
            "channels": list(contact.get("channels") or []),
            "name": contact.get("name"),
        }

    return LoadState(
        load_id=str(metadata.get("load_id", "")),
        client_id=client_id,
        load_type=metadata.get("load_type"),
        stage=Stage(str(metadata.get("stage", "dispatched"))),
        delay_risk=str(metadata.get("delay_risk", "low")),
        facts=extract_facts(metadata),
        stops=list(metadata.get("stops") or []),
        contacts=contacts,
        main_thread_id=metadata.get("email_thread_id") or metadata.get("thread_id"),
    )


def load_metadata_from_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
