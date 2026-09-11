---
name: clang-tidy-report
description: Generate a standalone clang-tidy report (Markdown for a human, or custom-schema XML for another AI/agent session to parse) over the whole project, with no auto-fix and no code changes. Use when asked to (re)generate/produce a clang-tidy report, not to fix anything.
---

# clang-tidy report (read-only)

Produces a report of every clang-tidy diagnostic in the project, in one of two formats.
**Applies no fixes and changes no files** — this is strictly the report-generation half of
`clang-tidy-all`, split out because "show me the state" and "fix everything" are different
requests with different risk profiles (report generation is always safe to run without
asking; auto-fix rewrites files and should not be launched silently — see
`clang-tidy-all`/`clang-tidy-diff` for that workflow).

**Token economy — follow strictly:** do NOT read `.clang-tidy`, `compile_commands.json`,
or any source file up front. Run the script; it writes the report to disk; only echo its
own summary back to the user (or open the file for them) — do not re-read the whole
report into your own context unless asked to discuss specific findings.

## Pick a format

- **`--format md`** (default choice for a human-facing request) — Markdown with a
  per-check summary table (linked to per-check sections) and every diagnostic as a
  clickable `` `path:line:col` `` entry. Use when the report is meant to be opened, read,
  or committed by a person.
- **`--format xml`** — compact, attribute-based custom-schema XML: `<clang-tidy-report>`
  with `<checks>` (summary) and `<diagnostics>/<check>/<diag file= line= col= severity=>`
  (findings). The schema is `<skill-dir>/scripts/clang_tidy_report.xsd` — every generated
  report's root element points at it via `xsi:noNamespaceSchemaLocation`, and you can
  validate a report against it with `xmllint --noout --schema clang_tidy_report.xsd
  <report>.xml`. Use `--format xml` when the report is meant to be handed off to *another*
  AI/agent session (now or later) to parse programmatically — it doesn't need to re-derive
  structure from prose the way it would from the `.md` or the plain-text form
  `clang-tidy-all`/`clang-tidy-diff` use internally.

If the request doesn't say which, default to `md`.

## Steps

1. Run **in the background** (a full-project run can take many minutes), path relative
   to this SKILL.md's folder:

   ```
   python3 <skill-dir>/scripts/run_clang_tidy.py --mode all --no-fix --format <md|xml> \
       --report <repo-root>/clang_tidy_report.<md|xml>
   ```

   - `--no-fix` is mandatory here — it is what makes this skill read-only. Never drop it,
     even if asked to "regenerate the report," unless the user explicitly asks for fixes
     too (in which case use `clang-tidy-all`/`clang-tidy-diff` instead of this skill).
   - `--mode diff` instead of `--mode all` scopes the report to files touched by the
     current git diff, if that's what was asked for.
   - The script self-discovers the repo root, the clang-tidy binary (PATH, `$CLANG_TIDY`,
     Homebrew/apt/Windows LLVM locations) and the newest `compile_commands.json`.
     Options if discovery fails: `--build-dir <dir>`, `CLANG_TIDY=<path>`.
   - Omitting `--report` writes to a temp file instead of the repo root — pass it
     explicitly so the report lands somewhere findable/committable, with an extension
     matching `--format`.

2. Interpret the exit code:
   - `0` — clean, no diagnostics. Report that plainly.
   - `2` — setup error (no clang-tidy / no compile DB). Relay the script's message and,
     if a build directory simply isn't configured yet, offer to configure CMake with
     `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`. Do not hand-roll compile flags.
   - `1` — diagnostics found and written to the report. This is the expected outcome on
     most runs, not a failure — do not attempt to fix anything in response to it.

3. Tell the user: total diagnostic count, top few checks by count, and the report's path.
   Offer to open it, but do not start editing code from it — that is out of scope for this
   skill. If they then ask for fixes, hand off to `clang-tidy-all` (whole project) or
   `clang-tidy-diff` (current diff only).

## Notes

- Submodules are part of the project: one run from the outermost repository covers every
  submodule, recursively. Code the project does not own is skipped - anything under
  `external/`, `third_party/`, `vendor/` or `_deps/`, plus the `third_party_paths` listed in
  `<repo-root>/.agent-skills.json`.
- Portable: copy this whole folder into any C/C++ project's skills directory; nothing
  here is project-specific. The script is the same runner used by `clang-tidy-all`/
  `clang-tidy-diff`, just invoked with `--no-fix --format md|xml`.
- The generated report is a point-in-time snapshot — regenerate it (re-run step 1) rather
  than trying to diff/patch the old one when asked for a fresh report.
