---
name: code-review
description: Read-only code review for git diffs — correctness, PULSE architecture, conventions, tests, docs. Use when asked for /code-review, PR/branch review, audit, feedback on a diff, or pre-merge checks.
disable-model-invocation: true
---

# PULSE Code Review

## Purpose

Review code changes and report actionable, evidence-grounded findings before merge. Run a multi-pass review: scope → critique → **mandatory self-verify** → counter-argue draft findings. **Do not fix, commit, or refactor unless the user asks.**

## When NOT to use

- No diff or file target (`git status` clean, no branch delta) → stop
- User wants implementation or fixes, not review
- Mid-implementation debugging

## Inputs

- Diff scope: uncommitted, staged, branch vs `main`, or explicit files
- Optional: stated task/PR intent, focus areas, validation already run
- Non-goals: parts of the diff to skip (if the user specifies)

## Workflow

For tiny diffs (few lines, no shared code, no architecture/contracts), collapse passes 1–2; **always run pass 3**. Run pass 4 only if pass 3 left must-fix or should-fix findings.

### Pass 1 — Triage and scope

```bash
git status
git diff                    # uncommitted
git diff --cached           # staged
git diff main...HEAD        # branch review
```

1. Confirm review target; no diff → stop.
2. Read the diff end-to-end before forming opinions.
3. Note: branch vs uncommitted, changed files, feature area.
4. Classify touched areas (collector, agent, models, tests, docs, architecture, skill/tooling).

### Pass 2 — Context, validate, critique

**Context** — load on demand:

| Always read | Also read if diff touches |
|---|---|
| `AGENTS.md` — canonical project contract (rules, repo map, forbidden actions) | |
| | `docs/architecture.md` — containers, external systems, diagram policy |
| | `docs/patterns.md` — ReAct, HITL, MCP, etc. |

If `.mmd` or `workspace.dsl` changed → § Rendering in `docs/architecture.md`.

Read touched **source files**, not just diff hunks.

**Validate:**

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
```

Apply `.agents/skills/code-review/references/checklist.md` sections **A–F** in order. Drop findings into the [Finding template](#finding-template). Skip N/A sections — do not invent findings.

Priority: blocking risks (correctness, security, module boundaries, secrets) before style or polish.

### Pass 3 — Self-verification (mandatory)

Re-read every draft finding against the diff. Apply [Self-critique](#self-critique) in the checklist. For each finding:

1. File and line exist in the diff or inspected file — else drop.
2. Evidence quote matches contents verbatim — else fix or drop.
3. Claim is provable from the diff or nearby context you read — else downgrade to **open question**.
4. Severity matches [Severity & confidence](#severity--confidence); no must-fix without high confidence.
5. Merge duplicates that share a root cause.

### Pass 4 — Counter-argument (conditional)

For each must-fix and should-fix finding, state the strongest one-line defense. If it holds, downgrade or drop. Low-confidence items → open questions only.

Confirm [Anti-hallucination guardrails](#anti-hallucination-guardrails), then produce [Output format](#output-format).

## Finding template

```text
- [<severity>] <file>:<line> — <one-line summary>
  Category: <A–F letter + name from checklist, or security/docs>
  Evidence: "<verbatim quote from diff or file>"
  Why it matters: <one sentence>
  Recommendation: <smallest concrete fix>
  Confidence: <high | medium | low>
```

Use `question` or `test-gap` instead of severity for open questions and missing coverage.

## Severity & confidence

| Severity | Meaning | Maps to |
|---|---|---|
| **must-fix** | Bug, regression, security, broken boundary, secrets, diagram drift on implemented path | 🔴 |
| **should-fix** | Clear quality issue with concrete impact, not blocking | 🟡 |
| **nice-to-have** | Small polish; easy to drop | 🟢 |

| Confidence | Use when |
|---|---|
| **high** | Provable from diff with quoted evidence |
| **medium** | Likely from diff + inspected nearby context |
| **low** | Unseen code or runtime assumed → **open question**, not must-fix |

## Self-critique

- Every finding has relocatable `file:line` and verbatim evidence.
- No speculation about behavior not in the diff or files you read.
- must-fix requires high confidence.
- No duplicate or redundant suggestions.
- No rewrite/refactor the user did not ask for.

## Anti-hallucination guardrails

- Do not invent line numbers or quotes.
- Downgrade unprovable claims to open questions.
- Do not flag what `ruff` / `pytest` already enforces mechanically.
- Do not echo checklist items if the diff does not exhibit the issue.
- Do not propose unrelated refactors or dependency changes.

## Output format

```markdown
## Code review — [branch | uncommitted | staged]

**Verdict:** Approve | Approve with fixes | Needs rework
**Scope:** [files, feature area]

### Must-fix
- [must-fix] path:line — …
  Evidence: "…"
  Recommendation: …

### Should-fix
…

### Nice-to-have
…

### Test gaps
…

### Open questions
…

**Checklist:** A [P/F/N/A] · B · C · D · E · F

**Confidence summary:** What was reviewed, what was not inspected, residual risk.
```

If clean: state that explicitly; still include checklist scores, test gaps, open questions, and confidence summary.

## PULSE gotchas

Review-specific calibration only — the full rules live in their canonical homes; do not restate them here.

- Module boundary (`AGENTS.md` § Core engineering rules): fetch/parse in `collectors/`, `agents/` orchestrate only — boundary violations are **must-fix**
- Structurizr status flip (`docs/architecture.md`): element tag **and every relationship tag** on its edges — drift on an implemented path is **must-fix**
- Implemented Mermaid flows must match code: participants, call order, run commands
- Tavily JSON `null`: `(r.get("key") or "")`, not `.get("key", "")`
- `fetch_hn_articles()` in `hn_agent`; collector entry is `search_articles()`

## Safety rules

- Prioritize bugs, regressions, and security over style.
- Do not change git state (stage/commit/push) during review unless explicitly asked.
- A request to fix findings is not permission to commit those fixes.
- Do not skip pass 3.

## Red flags — STOP

- Editing code while reviewing
- Skipping `pytest` / `ruff` (including docs-only changes)
- Skipping checklist F on architecture tweaks
- Summarizing the diff without reading touched source files
