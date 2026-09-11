---
name: clang-tidy-diff
description: Run clang-tidy on the C/C++ files changed in the current git diff - report first, then decide what to fix by hand, what to suppress, and whether clang-tidy's batch auto-fix is worth running at all. Use when asked to lint/tidy the current changes.
---

# clang-tidy on the git diff

Runs clang-tidy (project `.clang-tidy` config) only on translation units affected by
the current git diff, and gives you a compact report to act on.

The report comes first and changes nothing. What to do about it is then a judgement:
a single hand edit often clears more diagnostics than a whole batch pass, some findings
are false positives that want a `NOLINT` and a reason, and clang-tidy's own auto-fix is
worth running only where it is mechanical and reliable. Deciding that before any file is
touched is the point of this skill.

**Token economy — follow strictly:** do NOT read `.clang-tidy`, `compile_commands.json`,
or any source file up front. Run the script; read only its report; open only the exact
file regions the report points at.

**Speed over thoroughness — run once, don't loop.** Get the diagnostic list fast, decide,
fix, verify once — do not re-run the pipeline speculatively "to see if it does better," and
do not stop mid-run to ask permission for routine judgement calls. Decide and keep moving.
If a check's auto-fix is slow or conflicting, abandon it immediately and fix its diagnostics
directly from the report text — that is almost always faster than debugging the batch.

## Steps

The order matters: **report first, decide second, auto-fix last and only where it earns its
place.** clang-tidy's batch auto-fix is one tool among several, not the default move. It has
broken builds here, and a broken batch that gets reverted costs more time than it saves.

### 1. Report, changing nothing

```
python3 <skill-dir>/scripts/run_clang_tidy.py --mode diff --no-fix
```

`--no-fix` makes this step incapable of touching a file, so it is always safe to run and
never needs permission. The script self-discovers the repo root, the clang-tidy binary
(PATH, `$CLANG_TIDY`, Homebrew/apt/Windows LLVM locations) and the newest
`compile_commands.json`. Options if discovery fails: `--build-dir <dir>`, `CLANG_TIDY=<path>`.

Exit codes: `0` clean — report and stop. `2` setup error — relay the message, and offer to
configure CMake with `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON` if no build dir exists. `1`
diagnostics found — continue.

**Submodules are part of the project.** Run once, from the outermost repository. `--mode diff`
follows every changed submodule recursively and analyzes the files that changed inside it, and
`--mode all` covers every submodule's translation units in the compile database. Code the project
does not own is skipped: anything under `external/`, `third_party/`, `vendor/` or `_deps/`, plus
the paths the project lists in `<repo-root>/.agent-skills.json`:

```json
{ "third_party_paths": ["apps/viewer/dependencies/sdl"] }
```

A reverted auto-fix is restored in the repository that owns the file, submodules included. Report
results per repository, so it is clear which one each finding belongs to.

### 2. Triage the report before touching anything

Read the report and sort the diagnostics into these, cheapest-leverage first:

- **One edit, many diagnostics.** A diagnostic inside a macro or a template is reported once
  per expansion. Rewriting one line can clear dozens; look for a single file or line
  dominating the counts before you consider any batch.
- **False positives.** Suppress with `NOLINT`/`NOLINTNEXTLINE` **and a reason on the line**.
  `NOLINTNEXTLINE` applies to the line immediately below it, so put explanatory prose *above*
  it, never between it and the code. Inside a multi-line macro use `/* */` — a `//` comment
  before a `\` continuation swallows the next line.
- **Structural exceptions.** A check whose fix would break the design every time (a fix-it
  that unmakes an aggregate, or a header-oriented check that cannot see C++20 module imports)
  belongs in `.clang-tidy-autofix.json` with its reason — see step 4c.
- **Real defects.** Fix by hand.
- **Bulk-mechanical, low-risk, and boring.** Only this last group is a candidate for
  clang-tidy's own auto-fix.

Analyzer findings (`clang-analyzer-*`) deserve a look at the source before belief. Verify the
claim; if it is a false positive, say so with the reason rather than editing around it.

### 3. Decide whether to auto-fix at all

Often the answer is no, and hand edits from the report text are faster. Auto-fix is worth it
when a check is mechanical, its fix-it is reliable, and it appears many times.

**Before running any fixing pass, check the worktree is safe.** The script reverts a bad
batch by restoring the **worktree only — staged content is never touched**, which cuts both
ways: staged work is protected, unstaged work is what a revert operates on, and a partial
revert can leave a file half-fixed and uncompilable. So either stage the work you care about
first, or be ready to inspect the diff afterwards. Never start a fixing pass on a worktree
holding unstaged changes you cannot reconstruct.

### 4. Fix, in this order

4a. **Hand edits from the report text**, grouped per check across files. Fix the true issue;
   do not suppress a real problem. Never edit files under `external/`, `third_party/`,
   `vendor/`, or build dirs.

4b. **Then, if step 3 said so, the auto-fix pass** — same command without `--no-fix`. Re-read
   the report afterwards: entries marked `needs_ai_review` are fixes that broke the build and
   were reverted. Treat each as its own small task, fix it by hand (not by re-applying the
   fix-it that already failed), and verify with a targeted single-file build.

4c. **Record structural exceptions** in `<repo-root>/.clang-tidy-autofix.json` so a future run
   does not re-break the same build: `clang_tidy_never_autofix_paths`,
   `clang_tidy_never_autofix_checks_add/_remove`, `whole_batch_only_checks_add/_remove` (schema
   in the script's `load_project_config()` docstring). Write the reason next to the entry, and
   only for exceptions you can actually justify — guessing bakes a wrong reason into project
   config. If a check should never fire at all, disable it in the project's `.clang-tidy`
   `Checks:` list instead, and note the reasoning in `AGENTS.md`. Never hardcode
   project-specific paths or checks inside `run_clang_tidy.py`.

### 5. Verify, then confirm

Build and run the tests. **If any fixing pass ran, diff the worktree** and confirm no file was
left half-reverted — a build that fails after a revert is the signature. A build failure may
also be pre-existing breakage (broken submodule, toolchain bug, stale build state) rather than
something you caused; sanity-check an unexpected revert before trusting it. Fix small, obvious,
unambiguous pre-existing breakage you find along the way; for anything bigger, stop and report
it plainly instead of guessing.

Then re-run step 1 once (not in a loop) to confirm the report shrank.

### 6. Report

Per repository: what you fixed by hand and which check it cleared, what auto-fix did, what you
left and why. Pre-existing backlog that the diff merely pulled in is worth naming as such —
`--mode diff` selects every TU *affected by* the change, so editing a widely imported header
selects most of the project, and those diagnostics are not the change's doing.

## Notes

- clang-tidy auto-fixes may touch untouched lines of a changed file; that is expected.
- Long runs: if more than ~30 TUs are selected, run the script in the background and
  continue when it finishes.
- Portable: copy this whole folder into any C/C++ project's skills directory; nothing
  here is project-specific. Project-specific exceptions live in the target project's own
  `.clang-tidy-autofix.json` + `AGENTS.md`, never in this skill's files.
- Once invoked, do not stop mid-run for routine permission questions — make the call and
  proceed, or state the action and keep going. Reserve real questions for genuinely
  irreversible or ambiguous calls outside the skill's normal scope.
