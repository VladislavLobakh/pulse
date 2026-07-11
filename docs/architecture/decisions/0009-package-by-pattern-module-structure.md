# 9. Package-by-pattern module structure

Date: 2026-07-11

## Status

Accepted

## Context

The layout from ADR 0006 placed the generic ReAct engine (`react_loop.py`)
inside `agents/` next to the one concrete agent, and `models.py` mixed three
layers: shared domain types (`Source`, `SourceItem`), the ReAct pattern's LLM
contracts (`ReasonDecision`, `SourceBatchScore`), and its run artifacts
(`ReActResult`, `StopReason`, `TraceEvent`). That held while there was exactly
one agent and one pattern. The roadmap adds more source agents, some using
ReAct and some using other patterns (plan-and-execute, reflection), so pattern
machinery and per-source configs need separate homes before they multiply.

## Decision

- `patterns/` holds one module per agentic pattern: the engine together with
  its Pydantic LLM contracts and run artifacts (`patterns/react.py` owns
  `ReasonDecision`, `SourceBatchScore`, `ReActResult`, `StopReason`,
  `TraceEvent`, `ReActConfig`, and the graph). A pattern's contracts are part
  of the pattern, not shared domain.
- `agents/` holds only per-source business configs, named by source
  (`hn.py`, future `arxiv.py`): prompts, thresholds, model chains, domain,
  collector binding — and the choice of which pattern to run.
- `models.py` shrinks to true shared domain: `Source`, `SourceItem`,
  `SourceItemList`.
- `evals/` is a package for live-model regression evals, one module per
  tested property (`evals/intent_preservation.py`, moved from `scripts/`);
  `scripts/` keeps only plain utilities.
- Tests mirror the new modules: `test_react.py` (engine + its contracts),
  `test_hn.py`.

## Consequences

- A second pattern lands as `patterns/<name>.py` with its own contracts, and
  a second agent as `agents/<name>.py`, without touching each other or
  `models.py`.
- `pulse.agents.hn_agent`, `pulse.agents.react_loop`, and
  `pulse.scripts.eval_intent_preservation` import paths are gone; the eval
  entry point is now `python -m pulse.evals.intent_preservation`. ADRs 0006–
  0008 reference the old paths — they stay as written (historical records);
  this ADR supersedes the layout, not the decisions.
- `step_suffix` became public in `patterns.react`: `display` and `agents.hn`
  both format trace lines with it, and a pattern's trace-formatting is a
  legitimate cross-module contract.

## Alternatives Considered

- Keep the flat layout until a second pattern actually lands: rejected by an
  explicit scaling decision — restructuring now, while one agent exists, is a
  mechanical move; after three agents it is a breaking migration.
- `patterns/react/` as a package (engine.py + contracts.py): more structure
  than ~350 lines warrant; split when a pattern file genuinely outgrows one
  module.
- Keep all LLM contracts in `models.py`: with several patterns it becomes a
  dumping ground where ownership is unreadable; a contract only used by one
  pattern belongs to that pattern.

## Related

- Architecture: [docs/architecture.md](../architecture.md)
- Model: [workspace.dsl](workspace.dsl)
- Supersedes the module layout of:
  [0006 generic ReAct loop engine](0006-generic-react-loop-engine-separate-from-source-agents.md)
