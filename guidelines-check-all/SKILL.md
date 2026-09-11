---
name: guidelines-check-all
description: Check and fix the WHOLE codebase against the project's API_GUIDELINES.md and ARCHITECTURE.md. First run distills the docs into cached checker/fixer scripts; later runs use only the cache (cheap). Use when asked to audit or enforce project guidelines/architecture compliance repo-wide.
---

# Guidelines & architecture compliance — whole project

Enforces the rules written in the project's `API_GUIDELINES.md` and `ARCHITECTURE.md`
the same way clang-tidy enforces its checks: a generated `check_guidelines.py` finds
violations, a generated `fix_guidelines.py` auto-fixes the mechanical ones, and the AI
fixes the rest. Everything derived from the docs is cached in
`<repo-root>/.guidelines-cache/` and reused verbatim until the `guidelines-clear` skill
deletes it. The cache is shared with the sibling skill `guidelines-check-diff`
(same scripts, run with `--diff`); whichever skill runs first builds it.

**Token economy — follow strictly:** if the cache exists, NEVER read the original
guideline documents. Read only `GUIDELINES_COMPACT.md` and the checker output.

## 0. Decide cold vs warm

`ROOT=$(git rev-parse --show-toplevel)`; cache dir is `$ROOT/.guidelines-cache/`.
If `GUIDELINES_COMPACT.md`, `check_guidelines.py` and `fix_guidelines.py` all exist
there → go to **Warm run**. Otherwise do **First run** once, then continue with Warm.

## First run (cache build — the only expensive run)

1. Find the docs at any depth, submodules included - a first-party submodule is part of the
   project - skipping `.git`, build dirs, `external/`, `third_party/`, `vendor/`, `_deps/` and
   every path listed in `third_party_paths` of `$ROOT/.agent-skills.json` (code the project
   does not own):
   `find "$ROOT" \( -iname 'API_GUIDELINES.md' -o -iname 'ARCHITECTURE.md' \) -not -path '*/.git/*' -not -path '*/build*' -not -path '*/external/*' -not -path '*/third_party/*' -not -path '*/vendor/*' -not -path '*/_deps/*'`
   then drop any result under a `third_party_paths` entry.
   If none exist, tell the user and stop. If only one exists, proceed with that one.
2. Read the found docs in full — this is the only time they are ever read.
3. Write `$ROOT/.guidelines-cache/GUIDELINES_COMPACT.md`: every enforceable rule as one
   entry — stable ID (`API-1…`, `ARC-1…`), rule statement (≤2 lines), and a tag:
   - `[fix]`  — mechanically detectable AND mechanically fixable
   - `[check]` — mechanically detectable, needs judgment to fix
   - `[ai]`   — needs judgment even to detect (design/layering intent)
   Also record the source-scope globs (which dirs/extensions the rules apply to).
   Drop prose that isn't a rule (motivation, history, diagrams).
4. Write `$ROOT/.guidelines-cache/check_guidelines.py` — Python 3, stdlib only:
   - Config block at the top: `SOURCE_GLOBS`, `EXCLUDE_DIRS`, `SUPPRESSIONS` (list of
     `path:RuleID` accepted exceptions). Third-party paths are NOT baked in: at every run,
     read `third_party_paths` from `$ROOT/.agent-skills.json` (if present) and skip those
     paths too, so a change to that file needs no cache rebuild.
   - Submodules are part of the project. No args = scan all files matching `SOURCE_GLOBS`,
     submodules included; `--diff` = scan only git-changed files (working tree + staged vs
     HEAD; if clean, merge-base vs origin/main|origin/master|main|master), where a changed
     submodule path is replaced, recursively, by the files changed inside it. Both modes
     skip `EXCLUDE_DIRS` and third-party paths, then intersect with `SOURCE_GLOBS`.
   - One function per `[check]`/`[fix]` rule, named after the rule ID, with the rule
     text as its docstring.
   - Output one line per violation: `path:line: [RULE-ID] message`; then a summary of
     counts per rule. Exit 0 when clean, 1 when violations exist.
   - Prefer precise-but-simple detection (regex / light parsing). A rule that cannot be
     detected reliably stays `[ai]`-tagged and is NOT implemented — no noisy guessing.
5. Write `$ROOT/.guidelines-cache/fix_guidelines.py` — same config block and same
   `--diff` flag; implements only the `[fix]` rules with safe, idempotent textual edits;
   prints each file it modifies; never touches `EXCLUDE_DIRS`.
6. Write `$ROOT/.guidelines-cache/manifest.json`: source doc paths, their sha256, and
   the generation date.
7. Sanity-check: run the checker once. If a rule produces an obvious flood of false
   positives, refine that rule's function (or demote it to `[ai]` in the compact file)
   before continuing.

## Warm run (every time)

1. Optional staleness note: if `shasum -a 256` of the source docs differs from
   `manifest.json`, warn the user that the docs changed and that `guidelines-clear`
   would rebuild the cache — but continue with the cache (only an explicit clear
   rebuilds).
2. **Reuse a fresh report if one exists**: if `$ROOT/guidelines_report.md` (or `.xml`)
   from `guidelines-check-report` exists, covers the whole project (not `--diff` scope),
   and is newer than both `manifest.json` and the latest local change (`git status`
   clean since, or the report postdates the last commit/uncommitted edit), read its
   violations instead of re-running the checker and skip straight to step 3. Otherwise:
   `python3 $ROOT/.guidelines-cache/check_guidelines.py`
   (If the script itself crashes, repair it in place — it is cache, editable.)
3. If violations: `python3 $ROOT/.guidelines-cache/fix_guidelines.py`, then re-run the
   checker.
4. Read the remaining checker output **and** `GUIDELINES_COMPACT.md`. Fix the remaining
   `[check]` violations by editing code, opening only the reported regions. For genuine,
   justified exceptions, add a `SUPPRESSIONS` entry with a comment instead of weakening
   the rule. If the count is very large, fix the highest-count rules first and give the
   user a prioritized summary of what remains.
5. `[ai]` rules: review the files the checker flagged (plus any the user named) against
   the `[ai]`-tagged entries of the compact file; fix what violates them. A full-repo
   `[ai]` review is expensive — do it only if the user explicitly asked for a deep
   audit, and summarize findings per rule rather than per file.
6. Re-run the checker to confirm exit 0, then report: violations auto-fixed, fixed by
   AI, suppressed (with reasons), and any `[ai]` findings.

## Notes

- The cache may be committed to git so teammates/other agents skip the first run too;
  follow the project's existing convention if one is visible.
- Portable: copy this folder (with `guidelines-check-diff` and `guidelines-clear`) into
  any project that has an `API_GUIDELINES.md` and/or `ARCHITECTURE.md`; the cache is
  regenerated per project.
