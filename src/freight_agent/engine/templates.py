"""Message templates.

A template is a Markdown file under `sops/templates/` (or a client override
under `sops/clients/<client_id>/templates/`) containing `{{placeholder}}`
variables. Rendering is deterministic and free - this is the single biggest
lever on the LLM cost budget (ADR-004).

If a template needs a value the load does not have, rendering fails and the
action is skipped rather than sent with a hole in it.
"""

from __future__ import annotations

import re
from pathlib import Path

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


class TemplateError(ValueError):
    """Raised when a template cannot be rendered."""


class TemplateRenderer:
    """Resolves and renders message templates, with a per-client override layer."""

    def __init__(self, sop_dir: Path) -> None:
        self.sop_dir = sop_dir
        self._cache: dict[tuple[str, str], str] = {}

    def _paths_for(self, name: str, client_id: str) -> list[Path]:
        candidates = []
        if client_id and client_id != "default":
            candidates.append(
                self.sop_dir / "clients" / client_id / "templates" / f"{name}.md"
            )
        candidates.append(self.sop_dir / "templates" / f"{name}.md")
        return candidates

    def find(self, name: str, client_id: str = "default") -> Path | None:
        for path in self._paths_for(name, client_id):
            if path.is_file():
                return path
        return None

    def available(self, client_id: str = "default") -> list[str]:
        """Every template name usable for this client, base templates included."""
        names: set[str] = set()
        base = self.sop_dir / "templates"
        if base.is_dir():
            names.update(path.stem for path in base.glob("*.md"))
        if client_id and client_id != "default":
            client = self.sop_dir / "clients" / client_id / "templates"
            if client.is_dir():
                names.update(path.stem for path in client.glob("*.md"))
        return sorted(names)

    def render(self, name: str, client_id: str, context: dict[str, str]) -> str:
        cache_key = (name, client_id)
        if cache_key not in self._cache:
            path = self.find(name, client_id)
            if path is None:
                raise TemplateError(f"Template {name!r} not found for client {client_id!r}")
            self._cache[cache_key] = path.read_text(encoding="utf-8")
        return self.substitute(self._cache[cache_key], context)

    @staticmethod
    def substitute(text: str, context: dict[str, str]) -> str:
        missing: list[str] = []

        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in context:
                missing.append(key)
                return match.group(0)
            return str(context[key])

        rendered = _PLACEHOLDER_RE.sub(replace, text)
        if missing:
            raise TemplateError(
                f"Template is missing values for: {sorted(set(missing))}. "
                "Either add the fact to the load metadata or use a different template."
            )
        return rendered.strip()
