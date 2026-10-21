"""Actions the agent can take, and the state effects they carry.

An `Action` is a *description* of an effect. It becomes a row in the `actions`
table and, once executed, is recorded back into the event log as an
`AGENT_ACTION` event so the load state can be folded from it.

The `effects` list is the bridge between "what we did" and "what the world
now looks like". It is intentionally a tiny, declarative vocabulary so that an
SOP author never has to write code to change state.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ActionType(StrEnum):
    """Every external or internal effect the agent can produce."""

    # External
    SEND_SMS = "send_sms"
    SEND_EMAIL = "send_email"
    SEND_SLACK = "send_slack"
    TMS_NOTE = "tms_note"
    SET_TIMER = "set_timer"
    # Internal
    CREATE_HERO_TASK = "create_hero_task"
    UPDATE_LOAD_STAGE = "update_load_stage"
    UPDATE_LOAD_STATE = "update_load_state"
    INTERNAL_SLACK = "internal_slack"
    # Explicit non-action. Logging this is how "doing nothing" becomes an
    # auditable decision instead of an absence.
    NO_ACTION = "no_action"


class Action(BaseModel):
    """A single, idempotent effect."""

    type: ActionType
    reason: str = ""
    # Targeting
    target: str | None = None  # contact id, channel name, or load id
    to_role: str | None = None
    channel: str | None = None
    thread_id: str | None = None
    # Content
    template: str | None = None
    body: str | None = None
    subject: str | None = None
    # Timer specifics
    request_key: str | None = None
    after_minutes: int | None = None
    fires_at: datetime | None = None
    # Misc
    urgent: bool = False
    stage: str | None = None
    # Provenance: which SOP clause produced this action.
    policy_key: str | None = None
    step_id: str | None = None
    # State effects to apply when this action is recorded.
    effects: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def signature(self) -> str:
        """Stable identity of the action, used for `never_acted` predicates."""
        return f"{self.type}:{self.to_role or self.channel or self.target}:{self.template or ''}"
