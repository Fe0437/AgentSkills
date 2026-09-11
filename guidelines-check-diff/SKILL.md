---
name: guidelines-check-diff
description: Check and fix only the files in the current git diff against the project's API_GUIDELINES.md and ARCHITECTURE.md. First run distills the docs into cached checker/fixer scripts; later runs use only the cache (cheap). Use when asked to verify the current changes against project guidelines.
---

# Guidelines & architecture compliance — current diff only

Same machinery as `guidelines-check-all`, restricted to the files changed in git
(working tree + staged; falls back to merge-base vs main/master when clean). It shares
the cache in `<repo-root>/.guidelines-cache/` with the sibling skill; whichever skill
runs first builds it.

**Token economy — follow strictly:** if the cache exists, NEVER read the original
guideline documents. Read only `GUIDELINES_COMPACT.md` and the checker output.

## 0. Decide cold vs warm

`ROOT=$(git rev-parse --show-toplevel)`; cache dir is `$ROOT/.guidelines-cache/`.
If `GUIDELINES_COMPACT.md`, `check_guidelines.py` and `fix_guidelines.py` all exist
there → go to **Warm run**. Otherwise do the **First run** exactly as specified in
`../guidelines-check-all/SKILL.md` (the cache build is scope-independent — the
generated scripts must support the `--diff` flag as that spec requires). If this skill
was copied to a project without its sibling, follow the First-run spec below.

<details><summary>First-run spec (only needed when the sibling skill is absent)</summary>

1. Find the docs at any depth, submodules included - a first-party submodule is part of the
   project - skipping `.git`, build dirs, `external/`, `third_party/`, `vendor/`, `_deps/` and
   every path listed in `third_party_paths` of `$ROOT/.agent-skills.json`:
   `find "$ROOT" \( -iname 'API_GUIDELINES.md' -o -iname 'ARCHITECTURE.md' \) -not -path '*/.git/*' -not -path '*/build*' -not -path '*/external/*' -not -path '*/third_party/*' -not -path '*/vendor/*' -not -path '*/_deps/*'`
   then drop any result under a `third_party_paths` entry.
   If none exist, tell the user and stop. If only one exists, proceed with that one.
2. Read the found docs in full — this is the only time they are ever read.
3. Write `$ROOT/.guidelines-cache/GUIDELINES_COMPACT.md`: every enforceable rule as one
   entry — stable ID (`API-1…`, `ARC-1…`), statement (≤2 lines), and a tag: `[fix]`
   (mechanically detectable and fixable), `[check]` (detectable, fixing needs judgment),
   `[ai]` (needs judgment even to detect). Record source-scope globs; drop non-rule prose.
4. Write `$ROOT/.guidelines-cache/check_guidelines.py` — Python 3, stdlib only. Config
   block at top: `SOURCE_GLOBS`, `EXCLUDE_DIRS`, `SUPPRESSIONS` (`path:RuleID` accepted
   exceptions); third-party paths are read from `$ROOT/.agent-skills.json` at every run,
   not baked in. Submodules are part of the project: no args = scan all `SOURCE_GLOBS`
   files, submodules included; `--diff` = only git-changed files (working tree + staged vs
   HEAD; if clean, merge-base vs origin/main|origin/master|main|master), a changed
   submodule replaced recursively by the files changed inside it. Both skip `EXCLUDE_DIRS`
   and third-party paths, then intersect with `SOURCE_GLOBS`. One function
   per `[check]`/`[fix]` rule (rule text as docstring). Output `path:line: [RULE-ID]
   message` + per-rule summary; exit 0 clean / 1 violations. Precise-but-simple
   detection only; undetectable rules stay `[ai]` and are not implemented.
5. Write `$ROOT/.guidelines-cache/fix_guidelines.py` — same config block and `--diff`
   flag; safe, idempotent textual fixes for `[fix]` rules only; prints modified files;
   never touches `EXCLUDE_DIRS`.
6. Write `$ROOT/.guidelines-cache/manifest.json`: doc paths, sha256, generation date.
7. Sanity-check: run the checker once; refine or demote any rule flooding false
   positives.

</details>

## Warm run (every time)

1. Optional staleness note: if `shasum -a 256` of the source docs differs from
   `manifest.json`, warn that the docs changed and `guidelines-clear` would rebuild —
   but continue with the cache (only an explicit clear rebuilds).
2. **Reuse a fresh report if one exists**: if `$ROOT/guidelines_report.md` (or `.xml`)
   from `guidelines-check-report` exists, was generated for `--diff` scope, and is newer
   than both `manifest.json` and the current diff's last edit, read its violations
   instead of re-running the checker and skip straight to step 3. Otherwise:
   `python3 $ROOT/.guidelines-cache/check_guidelines.py --diff`
   (If the script itself crashes, repair it in place — it is cache, editable.)
3. If violations: `python3 $ROOT/.guidelines-cache/fix_guidelines.py --diff`, then
   re-run the checker with `--diff`.
4. Read the remaining checker output **and** `GUIDELINES_COMPACT.md`. Fix the remaining
   `[check]` violations by editing code, opening only the reported regions. For genuine,
   justified exceptions, add a `SUPPRESSIONS` entry with a comment instead of weakening
   the rule.
5. `[ai]` rules: review the files in the current git diff against the `[ai]`-tagged
   entries of the compact file; fix what violates them.
6. Re-run the checker (`--diff`) to confirm exit 0, then report: violations auto-fixed,
   fixed by AI, suppressed (with reasons), and any `[ai]` findings.

## Notes

- The cache may be committed to git so teammates/other agents skip the first run too.
- Portable: copy this folder (ideally with `guidelines-check-all` and
  `guidelines-clear`) into any project that has an `API_GUIDELINES.md` and/or
  `ARCHITECTURE.md`; the cache is regenerated per project.
