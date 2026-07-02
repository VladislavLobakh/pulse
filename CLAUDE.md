# CLAUDE.md — Claude Code bridge

Project rules live in `AGENTS.md` — read it first.

@AGENTS.md

This file holds only Claude Code runtime notes. Everything tool-agnostic (project overview, repo map, commands, engineering rules, forbidden actions, docs map, instruction precedence) is canonical in `AGENTS.md`. Do not duplicate those rules here.

## Compaction policy

When compacting, preserve the list of modified files and any unresolved bugs.

## Settings / permissions

- `.claude/settings.json` denies reading `plan/**`. Respect that deny; never bypass it.

## Skills

- Canonical shared skills live under `.agents/skills/`; `.claude/skills/` contains thin Claude runtime bridges that `@` those skills.

## When instructions conflict or look stale

- `AGENTS.md` is authoritative. If a note here conflicts with `AGENTS.md`, follow `AGENTS.md`.
- If `AGENTS.md` itself looks out of date, surface the discrepancy to the user instead of silently improvising.
