"""The command line interface.

Four commands, all of which work without an API key:

    freight demo       replay the assessment's situation and print the transcript
    freight eval       run the eval scenarios
    freight validate   check the SOP corpus
    freight sop        show the procedures that apply to a client

`freight demo` and `freight eval` use the fake model, so they are deterministic.
Add `--real-llm` to talk to OpenAI instead (it needs `OPENAI_API_KEY`).
"""

from __future__ import annotations

import json
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from freight_agent.config import Settings, get_settings, resolve_sop_dir
from freight_agent.domain.events import Event
from freight_agent.evals.runner import ScenarioRunner, Transcript, check
from freight_agent.evals.scenarios import all_scenarios
from freight_agent.llm.gateway import LlmGateway
from freight_agent.runtime import action_time
from freight_agent.sop.resolver import SopCatalog
from freight_agent.sop.validator import (
    resolve_catalog_issues,
    template_names,
    validate_catalog,
)

app = typer.Typer(add_completion=False, help="Freight load agent.")
console = Console()

DEMO_SCENARIO = "client_a_escalation"


def _settings() -> Settings:
    return get_settings()


def _runner(real_llm: bool) -> ScenarioRunner:
    settings = _settings()
    if real_llm:
        from openai import OpenAI

        gateway = LlmGateway(settings, client=OpenAI(api_key=settings.openai_api_key))
        return ScenarioRunner(settings=settings, gateway=gateway)
    return ScenarioRunner(settings=settings)


def _print_transcript(transcript: Transcript) -> None:
    scenario = transcript.scenario
    console.print(f"[bold]{scenario.title}[/bold]  (load {scenario.metadata['load_id']})")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Time", no_wrap=True)
    table.add_column("Event")
    table.add_column("Decision")
    table.add_column("Message")

    for step in transcript.steps:
        for outcome in step.outcomes:
            event = outcome.event
            decisions = [
                decision
                for decision in outcome.decisions
                if decision.action is None or decision.action.type.value != "set_timer"
            ]
            if not decisions:
                table.add_row(
                    event.occurred_at.strftime("%H:%M"),
                    event.type.value,
                    "[yellow]no policy matched[/yellow]",
                    "",
                )
                continue
            for decision in decisions:
                action = decision.action
                message = (action.body if action else "") or ""
                if action is not None and action.type.value == "no_action":
                    message = "(nothing sent - the decision was to do nothing)"
                table.add_row(
                    action_time(event, 60).strftime("%H:%M"),
                    event.type.value,
                    f"{decision.policy_key} / {decision.step_id}",
                    message.replace("\n", " "),
                )

    console.print(table)

    if transcript.llm_calls:
        cost = sum(call.cost_usd for call in transcript.llm_calls)
        console.print(
            f"[dim]{len(transcript.llm_calls)} model call(s), "
            f"${cost:.4f} (the fake model bills nothing)[/dim]"
        )


@app.command()
def demo(
    real_llm: bool = typer.Option(False, help="Use the real OpenAI API instead of the fake model."),
) -> None:
    """Replay the assessment's situation, step by step."""
    runner = _runner(real_llm)
    scenario = next(s for s in all_scenarios() if s.key == DEMO_SCENARIO)
    transcript = runner.run(scenario)
    _print_transcript(transcript)

    problems = check(transcript)
    if problems:
        console.print("\n[red]Problems:[/red]")
        for problem in problems:
            console.print(f"  - {problem}")
        raise typer.Exit(code=1)


@app.command()
def eval(
    real_llm: bool = typer.Option(False, help="Use the real OpenAI API instead of the fake model."),
) -> None:
    """Run every eval scenario."""
    runner = _runner(real_llm)
    failures = 0

    for scenario in all_scenarios():
        transcript = runner.run(scenario)
        problems = check(transcript)
        if problems:
            failures += 1
            console.print(f"[red]FAIL[/red] {scenario.key}")
            for problem in problems:
                console.print(f"       {problem}")
        else:
            console.print(f"[green]PASS[/green] {scenario.key}  {scenario.title}")

    total = len(all_scenarios())
    console.print(f"\n{total - failures}/{total} scenarios passed.")
    if failures:
        raise typer.Exit(code=1)


@app.command()
def validate() -> None:
    """Check that every SOP file is valid and consistent."""
    settings = _settings()
    sop_dir = resolve_sop_dir(settings.sop_dir)
    catalog = SopCatalog.from_dir(sop_dir)
    result = validate_catalog(catalog, template_names(sop_dir))
    issues = list(result.issues) + resolve_catalog_issues(catalog)

    console.print(f"[dim]{len(catalog.documents)} SOP files in {sop_dir}[/dim]")
    if issues:
        for issue in issues:
            console.print(f"[red]  - {issue}[/red]")
        raise typer.Exit(code=1)
    console.print("[green]All SOP files are valid.[/green]")


@app.command()
def sop(
    client: str = typer.Argument(..., help="The client id, for example client_a."),
    load_type: str = typer.Option(None, help="The load type, for example refrigerated."),
) -> None:
    """Show the procedures that apply to a client."""
    settings = _settings()
    sop_dir = resolve_sop_dir(settings.sop_dir)
    catalog = SopCatalog.from_dir(sop_dir)

    for policy in catalog.resolve_all(client, load_type):
        console.print(f"[bold]{policy.key}[/bold] - {policy.title}")
        console.print(f"[dim]priority {policy.priority}, steps:[/dim]")
        for step in policy.steps:
            source = policy.provenance.get(step.id, "")
            console.print(f"  - {step.id}  [dim]{source}[/dim]")
        console.print()


@app.command()
def event(payload: str = typer.Argument(..., help="A JSON event to handle.")) -> None:
    """Handle a single event, given as JSON, and print what the agent did."""
    settings = _settings()
    runner = ScenarioRunner(settings=settings)
    parsed: dict[str, Any] = json.loads(payload)
    event_obj = Event.model_validate(parsed)
    outcome = runner.runtime.handle_event(event_obj)

    for decision in outcome.decisions:
        action = decision.action
        console.print(
            f"[bold]{decision.policy_key}[/bold] / {decision.step_id}: {decision.rationale}"
        )
        if action is not None:
            console.print(f"  {action.type.value} -> {action.target or action.channel}")
            if action.body:
                console.print(f"  {action.body}")
    if not outcome.decisions:
        console.print("[yellow]Nothing to do.[/yellow]")


def main() -> None:  # pragma: no cover - console entry point
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
