"""The background worker.

Two jobs, both of them scheduled work rather than reaction to an inbound
message:

* fire the timers that have come due - the escalation ladder's waits live
  here;
* drain the event queue, when a real queue is in use.

    python -m freight_agent.workers.timer_worker

The worker owns its own runtime, and shares the storage with the API through
the persistence protocols. With the in-memory stores it is a single process;
in production the timer scan is a claim-based loop over a database table
(ADR-0012).
"""

from __future__ import annotations

import argparse
import logging
import signal
import time
from datetime import UTC, datetime

from freight_agent.config import Settings, get_settings
from freight_agent.runtime import AgentRuntime, RunOutcome

logger = logging.getLogger(__name__)


class TimerWorker:
    """Scans for due timers and fires them."""

    def __init__(self, runtime: AgentRuntime, *, poll_seconds: int = 30) -> None:
        self.runtime = runtime
        self.poll_seconds = poll_seconds
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def tick(self, now: datetime | None = None) -> list[RunOutcome]:
        """Fire everything that is due. Returns the runs it produced."""
        now = now or datetime.now(UTC)
        outcomes = self.runtime.fire_due_timers(now)
        for outcome in outcomes:
            for decision in outcome.decisions:
                logger.info(
                    "timer fired for load %s: %s / %s",
                    outcome.event.load_id,
                    decision.policy_key,
                    decision.step_id,
                )
        return outcomes

    def run_forever(self) -> None:
        logger.info("timer worker started, polling every %ss", self.poll_seconds)
        while not self._stop:
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - a bad timer must not kill the worker
                logger.exception("timer scan failed")
            time.sleep(self.poll_seconds)


def main() -> None:  # pragma: no cover - process entry point
    parser = argparse.ArgumentParser(description="Fire the agent's due timers.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scan and exit. Used by the scheduled job.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=30,
        help="How often to scan for due timers.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    settings: Settings = get_settings()
    runtime = AgentRuntime.create(settings)
    worker = TimerWorker(runtime, poll_seconds=args.poll_seconds)

    if args.once:
        worker.tick()
        return

    def _handle_signal(signum, frame) -> None:  # noqa: ANN001
        logger.info("signal %s received, stopping", signum)
        worker.stop()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    worker.run_forever()


if __name__ == "__main__":  # pragma: no cover
    main()
