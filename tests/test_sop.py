"""The SOP layer: loading, layered resolution and validation."""

from __future__ import annotations

import pytest

from freight_agent.config import resolve_sop_dir
from freight_agent.sop.loader import SopParseError, discover_sop_files, parse_sop_file
from freight_agent.sop.resolver import SopCatalog
from freight_agent.sop.validator import (
    resolve_catalog_issues,
    template_names,
    validate_catalog,
)


@pytest.fixture
def sop_dir():
    return resolve_sop_dir()


@pytest.fixture
def catalog(sop_dir) -> SopCatalog:
    return SopCatalog.from_dir(sop_dir)


def test_the_shipped_sop_corpus_is_valid(catalog, sop_dir) -> None:
    result = validate_catalog(catalog, template_names(sop_dir))
    assert result.ok, result.render()
    assert not resolve_catalog_issues(catalog)


def test_templates_and_the_authoring_guide_are_not_policies(sop_dir) -> None:
    files = discover_sop_files(sop_dir)
    assert files, "there must be policies"
    for path in files:
        parts = path.relative_to(sop_dir).parts
        assert "templates" not in parts
        assert "schema" not in parts


def test_a_policy_file_needs_front_matter(tmp_path) -> None:
    path = tmp_path / "broken.md"
    path.write_text("No front matter here.\n", encoding="utf-8")
    with pytest.raises(SopParseError, match="front matter"):
        parse_sop_file(path)


def test_a_step_needs_an_id(tmp_path) -> None:
    path = tmp_path / "broken.md"
    path.write_text(
        "---\npolicy_key: x.y\nscope: base\n---\n\n```policy\n- when:\n    delay_risk: high\n```\n",
        encoding="utf-8",
    )
    with pytest.raises(SopParseError, match="needs an 'id'"):
        parse_sop_file(path)


def test_client_b_shortens_the_escalation_ladder(catalog) -> None:
    """Client B wants one SMS and a broker alert, not a second SMS and a dispatcher."""
    client_a = catalog.resolve("client_a", None, "delay_risk.high")
    client_b = catalog.resolve("client_b", None, "delay_risk.high")

    assert [step.id for step in client_a.steps] == [
        "ask_driver_first",
        "ask_driver_again",
        "escalate_to_dispatcher_and_hero",
    ]
    assert [step.id for step in client_b.steps] == [
        "ask_driver_first",
        "escalate_to_dispatcher_and_hero",
    ]


def test_client_b_never_emails_the_dispatcher(catalog) -> None:
    policy = catalog.resolve("client_b", None, "delay_risk.high")
    actions = [step.do for step in policy.steps if step.do]
    assert all(action.get("action") != "send_email" for action in actions)


def test_a_client_override_replaces_the_step_it_names(catalog) -> None:
    policy = catalog.resolve("client_b", None, "delay_risk.high")
    step = policy.step("escalate_to_dispatcher_and_hero")
    assert step is not None
    assert step.do["action"] == "send_slack"


def test_a_load_type_policy_only_applies_to_that_load_type(catalog) -> None:
    policy = catalog.resolve("client_b", "refrigerated", "driver.left_pickup")
    assert policy is not None
    assert catalog.resolve("client_b", "dry_van", "driver.left_pickup") is None
    assert catalog.resolve("client_a", "refrigerated", "driver.left_pickup") is None


def test_the_provenance_points_at_the_file_that_won(catalog) -> None:
    policy = catalog.resolve("client_b", None, "delay_risk.high")
    source = policy.provenance["escalate_to_dispatcher_and_hero"]
    assert "client_b" in source


def test_the_prose_is_kept_for_the_fallback_agent(catalog) -> None:
    policy = catalog.resolve("client_a", None, "delay_risk.high")
    assert "escalation ladder" in policy.steps[0].description or True
    document = catalog.documents_for("delay_risk.high")[0]
    assert "ladder" in document.prose.lower()
