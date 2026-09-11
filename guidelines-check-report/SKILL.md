---
name: guidelines-check-report
description: Generate a standalone report of API_GUIDELINES.md/ARCHITECTURE.md violations (Markdown for a human, or custom-schema XML for another AI/agent session to parse), with no auto-fix and no code changes. Use when asked to (re)generate/produce a guidelines/architecture compliance report, not to fix anything.
---

# Guidelines & architecture compliance report (read-only)

Produces a report of every guideline/architecture violation in the project (or just the
current git diff), in one of two formats. **Applies no fixes and changes no source
files** — this is strictly the report-generation half of `guidelines-check-all` /
`guidelines-check-diff`, split out because "show me the state" and "fix everything" are
different requests with different risk profiles (report generation is always safe to run
without asking; auto-fix rewrites files and should not be launched silently — see
`guidelines-check-all`/`guidelines-check-diff` for that workflow).

It shares the cache in `<repo-root>/.guidelines-cache/` with those two skills (compact
rule list + generated `check_guidelines.py`/`fix_guidelines.py`); whichever skill runs
first builds it. This skill only ever *runs* the checker, never the fixer.

**Token economy — follow strictly:** if the cache exists, NEVER read the original
`API_GUIDELINES.md`/`ARCHITECTURE.md`. Read only `GUIDELINES_COMPACT.md` and the
checker's own output.

## 0. Decide cold vs warm

`ROOT=$(git rev-parse --show-toplevel)`; cache dir is `$ROOT/.guidelines-cache/`.
If `GUIDELINES_COMPACT.md`, `check_guidelines.py` and `fix_guidelines.py` all exist
there → go to **Warm run**. Otherwise do the **First run** exactly as specified in
`../guidelines-check-all/SKILL.md` (the cache build is scope-independent; the generated
`check_guidelines.py` already supports `--diff` as that spec requires — nothing about
report-only mode changes how the cache is built).

## Pick a scope and format

- **Scope** — `all` (default) scans every file matched by `SOURCE_GLOBS`; `diff` scans
  only the current git diff (`check_guidelines.py --diff`). Both cover first-party
  submodules recursively and skip the `third_party_paths` in `.agent-skills.json`. Use `diff` when the user
  says "current changes"/"this diff", `all` otherwise.
- **Format**
  - **`md`** (default for a human-facing request) — Markdown: a summary table
    (rule ID, tag, violation count) followed by one section per violated rule listing
    every `` `path:line` `` hit. Use when the report will be opened/read/committed by a
    person.
  - **`xml`** — compact, attribute-based: `<guidelines-report scope="…" generated="…">`
    with `<rules><rule id=".." tag=".." count=".."/></rules>` (summary) and
    `<violations><violation rule=".." file=".." line="..">message</violation></violations>`
    (findings), plus `<ai-findings>` if step 3 below ran. No checked-in XSD for this one
    — the shape is simple enough to hold in your head; don't build tooling to validate it.
    Use when the report is meant to be handed off to *another* AI/agent session to parse
    programmatically.

If the request doesn't say, default to `all` + `md`.

## Warm run (every time)

1. Optional staleness note: if `shasum -a 256` of `API_GUIDELINES.md`/`ARCHITECTURE.md`
   differs from `manifest.json`, warn that the docs changed and `guidelines-clear` would
   rebuild the cache — but continue with the cache (only an explicit clear rebuilds).
2. `python3 $ROOT/.guidelines-cache/check_guidelines.py [--diff]`. This output — already
   grouped per rule with counts — *is* the mechanical part of the report; no separate
   formatting script is needed. (If the script itself crashes, repair it in place — it
   is cache, editable.)
3. `[ai]`-tagged rules (from `GUIDELINES_COMPACT.md`) are never covered by step 2 — they
   need judgment even to detect. Only spend the tokens reviewing them if the user asked
   for a **deep**/thorough report:
   - **Deep**: review the in-scope files (diff scope, or — for `all` — only if the user
     explicitly accepts a full-repo pass, since that is expensive) against each `[ai]`
     entry; note file:line findings per rule, same shape as step 2's output.
   - **Not deep** (default): skip the review; the report just lists how many `[ai]`
     rules exist and says they weren't evaluated this run.
4. Write the report to `$ROOT/guidelines_report.<md|xml>` combining step 2's violations
   (and step 3's findings, if any) in the format chosen above. Do not edit any other
   file.
5. Tell the user: total violation count, top few rules by count, whether `[ai]` rules
   were reviewed, and the report's path. Offer to open it, but do not start editing code
   from it — that is out of scope for this skill. If they then ask for fixes, hand off
   to `guidelines-check-all` (whole project) or `guidelines-check-diff` (current diff
   only) — both can reuse this report instead of re-running the checker, see their notes.

## Notes

- Portable: copy this folder (with `guidelines-check-all`, `guidelines-check-diff` and
  `guidelines-clear`) into any project that has an `API_GUIDELINES.md` and/or
  `ARCHITECTURE.md`; the cache is regenerated per project.
- The generated report is a point-in-time snapshot — regenerate it (re-run step 2)
  rather than trying to diff/patch the old one when asked for a fresh report.
- If `guidelines-check-all`/`guidelines-check-diff` are run afterward and find
  `$ROOT/guidelines_report.<md|xml>` still fresh for the scope they need, they reuse its
  violations instead of re-invoking the checker — see the "reuse a fresh report" note in
  their SKILL.md files. Not essential, just avoids a redundant run.
