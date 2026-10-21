# ADR 001: Record architectural decisions as ADRs

* **Status:** accepted
* **Slug:** `record-decisions-as-adrs`

## Context

The assessment asks for documented architectural decisions, and a portfolio
reviewer has to be able to check a decision without reading 1,200 lines of prose.
A reviewer also asks "why not the obvious alternative?", and a prose document
answers that question unevenly depending on who wrote it.

## Decision

Every decision that shapes the system gets its own file in `docs/adr/`,
numbered, immutable, and written in the standard Context / Decision /
Consequences / Alternatives format. `docs/ADRs.md` is the index; the files are
the record. A decision that is later reversed gets a new ADR that supersedes
the old one, rather than an edit.

## Consequences

A reviewer can read one decision, see what it cost, and disagree with it
in isolation. The decision log is also the honest record of what was *not*
built and why, which matters more than a polished architecture diagram.

The cost is writing: twenty decisions is twenty small documents, and they can
drift from the code. The mitigation is that the index in `docs/ADRs.md` names
the file that implements each decision, so a stale ADR is visible.

## Alternatives considered

A single "Design" document (hard to review a single change, and the
alternatives get flattened into one paragraph) or a wiki page (no versioning,
no immutability).
