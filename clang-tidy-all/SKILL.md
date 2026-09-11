---
name: clang-tidy-all
description: Run clang-tidy on every C/C++ translation unit in the project, apply its automatic fixes, then fix the remaining diagnostics with AI edits. Use when asked to lint/tidy the whole codebase.
---

# clang-tidy on the whole project

Same workflow as `clang-tidy-diff`, but over every translation unit in the compile
database (external/vendor/build dirs excluded).

**Token economy — follow strictly:** do NOT read `.clang-tidy`, `compile_commands.json`,
or any source file up front. Run the script; read only its report; open only the exact
file regions the report points at.

**Speed over thoroughness — run once, don't loop.** This skill's job is to get you a
diagnostic list fast, not to converge on a perfectly auto-fixed tree through repeated
fix→build→revert cycles. One auto-fix attempt, one build-verify, then switch straight to
AI edits for whatever remains — including things the auto-fixer *could* theoretically
handle if run again. Do not re-run the whole script/pipeline speculatively "to see if it
does better this time," and do not stop mid-run to ask the user permission for routine
judgment calls (see clang-tidy-diff's SKILL.md notes on this) — decide and keep moving.
If a single check's auto-fix pass is clearly slow or is producing conflicts, abandon
auto-fix for that check immediately and fix its diagnostics directly from the report text
instead — that is almost always faster than debugging the batch.

## Steps

1. Run **in the background** (a full-project run can take many minutes), path relative
   to this SKILL.md's folder:

   ```
   python3 <skill-dir>/scripts/run_clang_tidy.py --mode all
   ```

   The script self-discovers the repo root, the clang-tidy binary (PATH, `$CLANG_TIDY`,
   Homebrew/apt/Windows LLVM locations) and the newest `compile_commands.json`.
   Options if discovery fails: `--build-dir <dir>`, `CLANG_TIDY=<path>`.

2. Interpret the exit code:
   - `0` — clean. Report the summary (files auto-fixed, nothing remaining). Done.
   - `2` — setup error (no clang-tidy / no compile DB). Relay the script's message and,
     if a build directory simply isn't configured yet, offer to configure CMake with
     `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`. Do not hand-roll compile flags.
   - `1` — diagnostics remain → step 3.

3. Read the report file printed at the end (`full report: ...`). It is deduplicated and
   grouped by check, and may contain a `needs_ai_review` section — see step 3b. Fix the
   remaining diagnostics **directly from the report's diagnostic text** by editing the
   code — do not re-invoke clang-tidy per check to "try auto-fix again unless you have
   a specific, fast, isolated reason to (e.g. one mechanical check with a reliable fixit
   and no known conflicts). Default to AI edits from the diagnostic message:
   - Fix the true issue; do not suppress warnings with `// NOLINT` unless it is a genuine
     false positive or intentional design, and then add a brief reason on the NOLINT line.
   - Group your edits per check across files (cheaper and more consistent).
   - If the count is very large (hundreds+), fix the highest-count checks first and give
     the user a prioritized summary of what remains instead of grinding through all of it
     silently. It is fine to leave a long tail of low-value diagnostics unfixed and say so.
   - Never edit files under `external/`, `third_party/`, `vendor/`, or build dirs.
   - Parallelize independent checks/file-groups across subagents rather than fixing
     everything serially yourself.

3b. **`needs_ai_review` entries** are diagnostics the script *did* try to auto-fix, but the
   fix broke the build, so it was reverted (worktree only — staged content is never
   touched). Treat each one as its own small task, fixed directly from the diagnostic —
   don't re-run the auto-fixer on it:
   - Fix it by hand with an AI edit (don't just re-apply clang-tidy's fix-it verbatim —
     that's the fix that already broke the build).
   - Verify the specific touched file(s) compile (a targeted `ninja <file>.o`/single-TU
     `clang++ -fsyntax-only` build is enough — you do not need a full project rebuild
     per fix) before moving to the next.
   - If there are several independent `needs_ai_review` entries (different files, no
     shared symbol), delegate each to a separate subagent in parallel.
   - If entries share a symbol/rename across files, fix them together in one pass (not
     split across subagents) to avoid reintroducing the same stale-reference break.
   - If a `needs_ai_review` entry (or a build break you catch by hand) turns out to be a
     *structural* exception — this file is also consumed by a non-C++ toolchain, this
     check is unsafe project-wide, etc. — don't fix it once and let it recur on every
     future run. Add it to the project's `.clang-tidy-autofix.json` (create it at the
     repo root if missing; see step 3c) so future runs skip it automatically.

3c. **Project-specific settings do not belong in this skill.** If you need to exclude a
   path or check beyond what the script's generic defaults handle, write it to
   `<repo-root>/.clang-tidy-autofix.json` (auto-discovered by the script; create the file
   if it doesn't exist yet — see the script's `load_project_config()` docstring for the
   schema: `clang_tidy_never_autofix_paths`, `clang_tidy_never_autofix_checks_add/_remove`,
   `whole_batch_only_checks_add/_remove`). If a whole check should never even fire (not
   just never auto-fix), disable it in the project's `.clang-tidy` `Checks:` list instead
   — that's a stronger, more permanent statement than excluding it from auto-fix only.
   Then also note *why* in the project's `AGENTS.md` (create a short section there if none
   exists) so a human or future agent understands the reasoning, not just the mechanism.
   Never hardcode project-specific paths or checks inside `run_clang_tidy.py` itself —
   that breaks portability to other projects using this same skill.

3d. **A build failure during verification may be pre-existing and unrelated to your fixes**
   (a broken submodule, a toolchain bug, stale build-directory state). The script's
   `verify_build_or_revert` already tries to tell the difference — it only reverts a
   batch if the touched files are actually implicated in a `FAILED:`/`error:` line, not
   merely mentioned in ordinary build-progress output — but always sanity-check an
   unexpected/large revert against that distinction yourself before trusting it. If you
   find real pre-existing breakage unrelated to clang-tidy (even in a submodule, even if
   it's outside `external/`'s normal no-edit rule — corruption is not "someone else's
   legitimate code"), fix it if it's a small, obvious, mechanical fix (a missing include,
   a clearly-truncated line) and the fix is unambiguous from context; otherwise stop and
   report it plainly rather than guessing or doing invasive surgery on unfamiliar build
   config.

4. Re-run the same command once (not in a loop) to confirm the report shrank / exit code
   moved toward `0`. Do not keep re-running speculatively.

5. Report to the user: files auto-fixed by clang-tidy, issues fixed by you (per check),
   and any diagnostics you intentionally left unfixed and why.

## Notes

- Submodules are part of the project: one run from the outermost repository covers every
  submodule, recursively. Code the project does not own is skipped - anything under
  `external/`, `third_party/`, `vendor/` or `_deps/`, plus the `third_party_paths` listed in
  `<repo-root>/.agent-skills.json`.
- Portable: copy this whole folder into any C/C++ project's skills directory; nothing
  here is project-specific. The script is identical to the one in `clang-tidy-diff/`.
  Project-specific exceptions live in the target project's own
  `.clang-tidy-autofix.json` + `AGENTS.md`, never in this skill's files.
- Once this skill has been invoked, do not stop mid-run to ask the user routine
  permission/approval questions (e.g. "should I do a clean rebuild to fix this build
  issue?"). Make the judgment call and keep going, or state the action you're taking and
  proceed. Reserve actual questions for genuinely irreversible or ambiguous calls outside
  the skill's normal scope.
