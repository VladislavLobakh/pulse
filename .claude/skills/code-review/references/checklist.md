# PULSE Code Review Checklist

Load during SKILL.md **pass 2**, after `pytest` and `ruff check`.
Apply against the diff and touched source files. Mark each section **Pass / Fail / N/A**.

Walk sections **in order** — blocking areas first. Skip N/A; do not invent findings.

## A. Scope & intent

- [ ] Diff matches the stated task or PR intent
- [ ] No unrelated refactors or scope creep
- [ ] New files are justified (not duplicates of existing modules)

## B. Module layout

Per `CLAUDE.md` § Module layout:

- [ ] `src/pulse/` for code; `tests/` mirrors structure
- [ ] Collectors own fetch + parse; agents orchestrate only — **agents never fetch directly**
- [ ] Shared types → `models.py`; CLI output → `display.py`; utilities → `scripts/`
- [ ] New data source → `collectors/<name>.py`

## C. Conventions

Verify rules in `CLAUDE.md` (read the file — do not duplicate):

- [ ] Critical imports (`create_agent`, `FastMCP` — not deprecated paths)
- [ ] Version pins unchanged
- [ ] LLM output → Pydantic via Instructor; LangGraph → `recursion_limit=10`
- [ ] Qdrant: upsert only; commands use `uv run python -m …`

## D. Correctness & corner cases

- [ ] Happy path matches documented run command / expected output
- [ ] Missing env vars fail clearly (e.g. `TAVILY_API_KEY not set`)
- [ ] Empty API responses handled without crash
- [ ] Threshold / warning logic: correct trigger and order
- [ ] External errors surfaced or retried appropriately
- [ ] No secrets committed; `.env` not in diff

## E. Tests & quality

- [ ] `uv run pytest` passes
- [ ] `uv run ruff check` passes
- [ ] New behavior has meaningful tests under `tests/`

## F. Architecture & docs

**N/A** unless `docs/architecture/` changed or a container/external integration landed.
Full rules: `docs/architecture.md`.

- [ ] Structurizr = structure (`workspace.dsl`); Mermaid = behavior (`flows/*.mmd`) — no overlap
- [ ] In-process agents / graph nodes → Mermaid only, not new L2 containers
- [ ] New external → `softwareSystem` in DSL + Mermaid flow; new container → DSL + table in `architecture.md`
- [ ] Status flip `Planned → Implemented`: **element tag AND every relationship tag** on its edges
- [ ] Container table matches `workspace.dsl`; Mermaid titles mark Implemented vs Planned
- [ ] Sequence diagrams match code (participants, call order, run commands)

---

## Self-critique pass (pass 3 — mandatory)

Run against every draft finding before reporting:

- [ ] `file:line` exists in the diff or file read during review
- [ ] Evidence quote is verbatim from diff or file
- [ ] Claim does not depend on uninspected code or assumed runtime
- [ ] must-fix findings have **high** confidence
- [ ] No duplicate findings for the same root cause
- [ ] No requested rewrite beyond the diff scope

## Severity & confidence

Must match SKILL.md — use when calibrating findings:

| Severity | When |
|---|---|
| **must-fix** | Bug, regression, security, broken boundary, secrets, implemented-path diagram drift |
| **should-fix** | Clear impact, not blocking |
| **nice-to-have** | Polish only |

| Confidence | When |
|---|---|
| **high** | Quoted evidence from diff |
| **medium** | Diff + nearby context inspected |
| **low** | → open question, not must-fix |
