"""Domain layer: events, load state, actions, predicates.

Nothing in this package imports infrastructure (SQLAlchemy, OpenAI, FastAPI).
That keeps the decision logic testable in isolation and makes the eval harness
able to replay a timeline with zero external dependencies.
"""

from freight_agent.domain.actions import Action, ActionType
from freight_agent.domain.events import ContactRole, Event, EventType
from freight_agent.domain.state import LoadState, OpenRequest, Stage

__all__ = [
    "Action",
    "ActionType",
    "ContactRole",
    "Event",
    "EventType",
    "LoadState",
    "OpenRequest",
    "Stage",
]
