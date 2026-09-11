#!/usr/bin/env python3
"""Portable clang-tidy runner for AI-agent skills.

Self-contained (stdlib only). Discovers the repo root, clang-tidy binary and
compile_commands.json on its own, applies clang-tidy's automatic fixes, then
re-runs and writes a compact, deduplicated report of the diagnostics that
remain (the ones an AI/human must fix by hand).

Auto-fix safety tiers:
  tier1  - checks safe to fix in independent per-conflict batches.
  tier2  - checks in whole_batch_only_checks (e.g. identifier renames): only
           ever applied as one atomic all-TUs batch with zero exclusions,
           because a partial batch can rename a declaration while leaving
           references in an excluded file stale.
  never  - checks in never_autofix_checks, and any file in clang_tidy_never_autofix_paths,
           are never auto-applied at all (left as plain diagnostics).

The default tier assignments below are generic clang-tidy-semantics judgment
calls (which checks rename symbols, which ones are commonly unsafe to
auto-apply) and apply to any C/C++ project. Project-specific exceptions
(e.g. "this header is also consumed by a non-C++ toolchain, never touch it")
do NOT belong in this script — put them in a sidecar config file so this
script stays copy-paste portable. See load_project_config() / CONFIG_FILENAME.

Build verification: after each tier's apply, this script runs `cmake --build`
on the tier's touched files. If the build fails, the touched files are
reverted with `git restore --worktree` (staged/index content is never
touched) and the diagnostics behind that tier are moved into a distinct
"needs_ai_review" section of the report instead of being silently dropped,
so a caller can hand them to an AI/subagent for a manual fix + rebuild
instead of a blind auto-fix.

Modes:
  --mode diff   analyze only translation units affected by the current git diff
                (working tree + staged; falls back to merge-base vs main/master)
  --mode all    analyze every translation unit in the compile database

Exit codes: 0 = clean, 1 = diagnostics remain, 2 = setup error.
"""

import argparse
import concurrent.futures
import glob as globmod
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

SOURCE_EXTS = {".c", ".cc", ".cpp", ".cppm", ".cxx", ".m", ".mm", ".cu"}
HEADER_EXTS = {".h", ".hh", ".hpp", ".hxx", ".inl", ".cuh"}
EXCLUDE_DIR_PARTS = {
    "external", "third_party", "thirdparty", "vendor", "_deps",
    ".git", "out", "node_modules",
}
# Submodules are part of the project and are analyzed like any other directory, recursively.
# The exceptions are code the project does not own: anything under EXCLUDE_DIR_PARTS, plus the
# paths listed as "third_party_paths" in this project-level file shared by every agent skill:
#   {"third_party_paths": ["apps/viewer/dependencies/sdl"]}
SKILLS_CONFIG_FILENAME = ".agent-skills.json"
_third_party_paths = ()  # repo-relative, set once the repo root is known


def load_third_party_paths(root):
    """Repo-relative paths the project marks as third-party in .agent-skills.json."""
    cfg_path = os.path.join(root, SKILLS_CONFIG_FILENAME)
    if not os.path.isfile(cfg_path):
        return ()
    try:
        with open(cfg_path) as f:
            paths = json.load(f).get("third_party_paths", [])
    except (OSError, ValueError) as e:
        log(f"warning: failed to parse {SKILLS_CONFIG_FILENAME}: {e}")
        return ()
    return tuple(os.path.normpath(p) for p in paths)


def is_third_party(rel):
    rel = os.path.normpath(rel)
    return any(rel == p or rel.startswith(p + os.sep) for p in _third_party_paths)


DIAG_RE = re.compile(r"^(.+?):(\d+):(\d+): (warning|error): (.*?) \[([\w.,-]+)\]$")
_CONFLICT_PATH_RE = re.compile(r"^(?:New|Existing) replacement:\s*(.+?):\s*\d+:", re.MULTILINE)

# Generic (non-project-specific) defaults. These are judgment calls about
# clang-tidy check *semantics* — which checks rename symbols, which families
# are commonly unsafe to blind-apply — and hold for any C/C++ project.
DEFAULT_WHOLE_BATCH_ONLY_CHECKS = {
    "readability-identifier-naming",
    "bugprone-reserved-identifier",
    "cert-dcl37-c",
    "cert-dcl51-cpp",
}
DEFAULT_NEVER_AUTOFIX_CHECKS = {
    "cppcoreguidelines-pro-type-member-init",
    "hicpp-member-init",
    "cppcoreguidelines-use-default-member-init",
    "modernize-use-default-member-init",
    "hicpp-explicit-conversions",
    "modernize-avoid-c-arrays",
    "cppcoreguidelines-avoid-c-arrays",
    "hicpp-avoid-c-arrays",
}

# Project-specific overrides live in a sidecar file at the repo root, never
# in this script, so the script stays copy-paste portable across projects.
CONFIG_FILENAME = ".clang-tidy-autofix.json"


def load_project_config(root):
    """Load {root}/.clang-tidy-autofix.json if present.

    Recognized keys (all optional, all lists of strings):
      clang_tidy_never_autofix_paths        - repo-relative paths never auto-fixed for
                                    ANY check (e.g. headers shared with a
                                    non-C++ toolchain). Empty by default —
                                    this is the one setting almost every
                                    project needs to define for itself.
      clang_tidy_never_autofix_checks_add   - extra check names to add to the generic
                                    NEVER_AUTOFIX default (project add-ons).
      clang_tidy_never_autofix_checks_remove
                                  - check names to drop from the generic
                                    NEVER_AUTOFIX default, if a project has
                                    verified they're safe there.
      whole_batch_only_checks_add / _remove
                                  - same idea for WHOLE_BATCH_ONLY.

    Returns (clang_tidy_never_autofix_paths: set[str], never_autofix_checks: set[str],
             whole_batch_only_checks: set[str]).
    """
    never_paths = set()
    never_checks = set(DEFAULT_NEVER_AUTOFIX_CHECKS)
    whole_batch = set(DEFAULT_WHOLE_BATCH_ONLY_CHECKS)
    cfg_path = os.path.join(root, CONFIG_FILENAME)
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path) as f:
                cfg = json.load(f)
        except (OSError, ValueError) as e:
            log(f"warning: failed to parse {CONFIG_FILENAME}: {e}")
            cfg = {}
        never_paths |= set(cfg.get("clang_tidy_never_autofix_paths", []))
        never_checks |= set(cfg.get("clang_tidy_never_autofix_checks_add", []))
        never_checks -= set(cfg.get("clang_tidy_never_autofix_checks_remove", []))
        whole_batch |= set(cfg.get("whole_batch_only_checks_add", []))
        whole_batch -= set(cfg.get("whole_batch_only_checks_remove", []))
        log(f"loaded {CONFIG_FILENAME}: {len(never_paths)} never-autofix path(s), "
            f"{len(never_checks)} never-autofix check(s), "
            f"{len(whole_batch)} whole-batch-only check(s)")
    return never_paths, never_checks, whole_batch


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def find_repo_root():
    r = run(["git", "rev-parse", "--show-toplevel"])
    return os.path.realpath(r.stdout.strip()) if r.returncode == 0 else os.getcwd()


def find_tool(name, env_var):
    cand = os.environ.get(env_var)
    if cand and (shutil.which(cand) or os.path.isfile(cand)):
        return cand
    if shutil.which(name):
        return name
    patterns = [
        f"/opt/homebrew/opt/llvm*/bin/{name}",
        f"/usr/local/opt/llvm*/bin/{name}",
        f"/usr/lib/llvm-*/bin/{name}",
        f"/usr/bin/{name}-[0-9]*",
        f"C:/Program Files/LLVM/bin/{name}.exe",
    ]
    hits = []
    for p in patterns:
        hits.extend(globmod.glob(p))
    return sorted(hits, reverse=True)[0] if hits else None


def find_compile_db(root, build_dir):
    if build_dir:
        p = os.path.join(build_dir, "compile_commands.json")
        return p if os.path.isfile(p) else None
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        dirnames[:] = [d for d in dirnames
                       if depth < 3 and d not in EXCLUDE_DIR_PARTS and not d.startswith(".")]
        if "compile_commands.json" in filenames:
            hits.append(os.path.join(dirpath, "compile_commands.json"))
    return max(hits, key=os.path.getmtime) if hits else None


def is_excluded(path, root):
    rel = os.path.relpath(path, root)
    if rel.startswith(".."):
        return True
    return any(part in EXCLUDE_DIR_PARTS for part in rel.split(os.sep)) or is_third_party(rel)


def load_tus(db_path, root):
    with open(db_path) as f:
        db = json.load(f)
    tus = set()
    for entry in db:
        f_ = os.path.normpath(os.path.join(entry["directory"], entry["file"]))
        if os.path.splitext(f_)[1].lower() in SOURCE_EXTS and not is_excluded(f_, root):
            tus.add(os.path.realpath(f_))
    return sorted(tus)


def _changed_in(repo, prefix=""):
    """Paths changed in `repo`, and inside every first-party submodule that changed with it.

    A parent's diff shows a changed submodule as one path; the files inside it are what changed.
    Returned relative to the outermost repository.
    """
    changed = set()
    for args in (["git", "diff", "--name-only", "HEAD", "--"],
                 ["git", "ls-files", "--others", "--exclude-standard"]):
        r = run(args, cwd=repo)
        if r.returncode == 0:
            changed.update(l.strip() for l in r.stdout.splitlines() if l.strip())
    found = set()
    for rel in changed:
        full_rel = os.path.join(prefix, rel) if prefix else rel
        candidate = os.path.join(repo, rel)
        if os.path.isdir(candidate) and os.path.exists(os.path.join(candidate, ".git")):
            if not is_third_party(full_rel):
                found |= _changed_in(candidate, full_rel)
        else:
            found.add(full_rel)
    return found


def git_changed_files(root):
    changed = _changed_in(root)
    if not changed:  # clean tree: compare against merge-base with the main branch
        for ref in ("origin/main", "origin/master", "main", "master"):
            mb = run(["git", "merge-base", "HEAD", ref], cwd=root)
            if mb.returncode == 0:
                r = run(["git", "diff", "--name-only", mb.stdout.strip(), "HEAD", "--"],
                        cwd=root)
                changed.update(l.strip() for l in r.stdout.splitlines() if l.strip())
                break
    return {os.path.realpath(os.path.join(root, c)) for c in changed}


def restore_worktree(paths, root):
    """`git restore --worktree` each path in the repository that owns it (worktree only).

    A file inside a submodule belongs to that submodule's repository; restoring it from the
    parent would do nothing.
    """
    by_repo = {}
    for p in paths:
        full = p if os.path.isabs(p) else os.path.join(root, p)
        top = run(["git", "rev-parse", "--show-toplevel"], cwd=os.path.dirname(full))
        repo = top.stdout.strip() if top.returncode == 0 else root
        by_repo.setdefault(repo, []).append(os.path.relpath(full, repo))
    for repo, rels in by_repo.items():
        run(["git", "restore", "--worktree", "--"] + rels, cwd=repo)


def select_diff_tus(tus, changed):
    exts = SOURCE_EXTS | HEADER_EXTS
    changed_code = {c for c in changed if os.path.splitext(c)[1].lower() in exts}
    header_stems = {os.path.splitext(os.path.basename(c))[0]
                    for c in changed_code
                    if os.path.splitext(c)[1].lower() in HEADER_EXTS}
    selected = []
    for tu in tus:
        stem = os.path.splitext(os.path.basename(tu))[0]
        if tu in changed_code or stem in header_stems:
            selected.append(tu)
    return selected, changed_code


def run_tidy_pass(tidy, db_dir, tus, jobs, timeout, export_dir=None, fix_inplace=False,
                   checks=None, heartbeat=30):
    """Run clang-tidy over tus. Returns {tu: combined output}."""
    outputs = {}
    done = [0]

    def one(tu):
        t0 = time.monotonic()
        cmd = [tidy, "-p", db_dir, "--quiet"]
        if checks:
            cmd.append(f"--checks={checks}")
        if export_dir:
            yaml = os.path.join(export_dir, re.sub(r"[^\w]", "_", tu) + ".yaml")
            cmd.append(f"--export-fixes={yaml}")
        if fix_inplace:
            cmd.append("--fix")
        cmd.append(tu)
        try:
            r = run(cmd, timeout=timeout)
            out = r.stdout + "\n" + r.stderr
        except subprocess.TimeoutExpired:
            out = (f"{tu}:1:1: error: clang-tidy timed out after {timeout}s "
                   f"(re-run with a larger --timeout) [runner-timeout]")
        dt = time.monotonic() - t0
        done[0] += 1
        tag = " SLOW" if dt >= 60 else ""
        log(f"  [{done[0]}/{len(tus)}]{tag} {os.path.basename(tu)} ({dt:.1f}s)")
        return tu, out

    if fix_inplace:  # serial: parallel --fix runs corrupt shared headers
        for tu in tus:
            k, v = one(tu)
            outputs[k] = v
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
            futs = {ex.submit(one, tu): tu for tu in tus}
            last_beat = time.monotonic()
            pending = set(futs)
            while pending:
                done_now, pending = concurrent.futures.wait(
                    pending, timeout=heartbeat,
                    return_when=concurrent.futures.FIRST_COMPLETED)
                for fut in done_now:
                    k, v = fut.result()
                    outputs[k] = v
                if pending and time.monotonic() - last_beat >= heartbeat:
                    names = [os.path.basename(futs[f]) for f in list(pending)[:3]]
                    log(f"  ...{len(outputs)}/{len(tus)} done, {len(pending)} in flight "
                        f"(longest: {', '.join(names)})")
                    last_beat = time.monotonic()
    return outputs


def apply_exported_fixes(export_dir, apply_tool, fmt_tool, root,
                          preexcluded_paths=(), whole_batch_only=False):
    """Apply fixes collected in export_dir.

    Returns (fixed_files, excluded_files): fixed_files is the sorted list of
    repo-relative paths that were actually rewritten; excluded_files is the
    set of repo-relative paths whose fixes were skipped (never-autofix path,
    or dropped due to an unmergeable conflict during exclude-and-retry).

    If whole_batch_only is True, no exclude-and-retry happens: a conflict
    aborts the whole batch (returns no fixed_files) rather than dropping the
    conflicting file, since these checks are only safe applied atomically.
    """
    fp_re = re.compile(r"FilePath:\s*'?([^'\n]+)'?")
    yaml_by_path = {}
    all_paths = set()
    for y in globmod.glob(os.path.join(export_dir, "*.yaml")):
        try:
            with open(y, errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        paths = set()
        for m in fp_re.finditer(text):
            p = os.path.realpath(m.group(1).strip())
            if not is_excluded(p, root):
                paths.add(p)
        all_paths |= paths
        for p in paths:
            yaml_by_path.setdefault(p, []).append(y)

    excluded = {os.path.realpath(os.path.join(root, p)) for p in preexcluded_paths}
    excluded &= all_paths
    for p in list(excluded):
        for y in yaml_by_path.get(p, []):
            try:
                os.remove(y)
            except OSError:
                pass

    active = {p for p in all_paths if p not in excluded}
    if not active:
        return [], sorted(os.path.relpath(p, root) for p in excluded)

    for _ in range(50):  # bounded exclude-and-retry
        r = run([apply_tool, export_dir])
        if r.returncode == 0:
            if fmt_tool and os.path.isfile(os.path.join(root, ".clang-format")):
                run([fmt_tool, "-i", "--style=file"] + sorted(active))
            return (sorted(os.path.relpath(f, root) for f in active),
                    sorted(os.path.relpath(f, root) for f in excluded))
        m = _CONFLICT_PATH_RE.search(r.stderr)
        if whole_batch_only or not m:
            log(f"warning: clang-apply-replacements failed"
                f"{' (whole-batch-only, no retry)' if whole_batch_only else ''}: "
                f"{r.stderr.strip()[:500]}")
            return [], sorted(os.path.relpath(f, root) for f in excluded | active)
        bad = os.path.realpath(m.group(1).strip())
        if bad not in active:
            log(f"warning: clang-apply-replacements failed, "
                f"unrecognized conflict path: {r.stderr.strip()[:300]}")
            return [], sorted(os.path.relpath(f, root) for f in excluded | active)
        active.discard(bad)
        excluded.add(bad)
        for y in yaml_by_path.get(bad, []):
            try:
                os.remove(y)
            except OSError:
                pass
        if not active:
            return [], sorted(os.path.relpath(f, root) for f in excluded)
    log("warning: exclude-and-retry exceeded 50 iterations, giving up on this batch")
    return [], sorted(os.path.relpath(f, root) for f in excluded | active)


def verify_build_or_revert(root, build_dir, touched_files, build_timeout=1800):
    """Build the project; on failure, revert touched_files (worktree only,
    never the index/staged content) and return (ok, build_log_tail)."""
    if not touched_files:
        return True, ""
    if not build_dir:
        return True, ""  # can't verify without a build dir; caller decides
    log(f"verifying build after applying {len(touched_files)} file(s)...")
    keep_going = ["-k", "100000"]  # ninja syntax
    cache = os.path.join(build_dir, "CMakeCache.txt")
    if os.path.isfile(cache):
        try:
            with open(cache, errors="replace") as f:
                if "CMAKE_GENERATOR:INTERNAL=Unix Makefiles" in f.read():
                    keep_going = ["-k"]  # make syntax: no numeric arg
        except OSError:
            pass
    try:
        r = run(["cmake", "--build", build_dir, "--parallel", "--", *keep_going],
                cwd=root, timeout=build_timeout)
        combined = r.stdout + "\n" + r.stderr
        tail = "\n".join(combined.splitlines()[-80:])
        if r.returncode == 0:
            ok = True
        else:
            # Only lines that are themselves failure signals — a compiler
            # "error:" diagnostic or a ninja "FAILED:" build-edge line — are
            # evidence a touched file broke the build. Ordinary progress
            # lines ("Building CXX object X.cpp.o") mention every touched
            # file regardless of outcome and must NOT count as "implicated."
            # CMake's own C++20-modules dyndep bookkeeping errors ("provides
            # the module but it is not found in a FILE_SET", "Disagreement
            # of the location") are excluded even though they say "error" —
            # they're a build-graph tooling issue, not a compile error in
            # that file's content.
            failure_lines = "\n".join(
                line for line in combined.splitlines()
                if ("error:" in line or line.startswith("FAILED:"))
                and "Disagreement of the location" not in line
                and "is not found in a `FILE_SET`" not in line
            )
            basenames = {os.path.basename(f) for f in touched_files}
            ok = not any(b in failure_lines for b in basenames)
            if not ok:
                implicated = sorted(b for b in basenames if b in failure_lines)
                log(f"build failure implicates touched file(s): {implicated}")
            else:
                log("build has failures, but none are attributable to the "
                    "files just touched (pre-existing/unrelated breakage or "
                    "known module-scan bookkeeping noise) — not reverting")
    except subprocess.TimeoutExpired:
        ok, tail = False, f"build timed out after {build_timeout}s"
    if not ok:
        log(f"build FAILED after applying fixes; reverting {len(touched_files)} "
            f"file(s) via 'git restore --worktree' (staged content untouched)")
        restore_worktree(touched_files, root)
    else:
        log("build OK")
    return ok, tail


def collect_diagnostics(outputs, root):
    diags = set()
    for out in outputs.values():
        for line in out.splitlines():
            m = DIAG_RE.match(line.strip())
            if not m:
                continue
            path = os.path.realpath(m.group(1))
            if is_excluded(path, root):
                continue
            diags.add((os.path.relpath(path, root), int(m.group(2)), int(m.group(3)),
                       m.group(4), m.group(5), m.group(6)))
    return sorted(diags)


def write_report(report_path, mode, tus, fixed_files, diags, needs_ai_review=()):
    by_check = {}
    for d in diags:
        by_check[d[5]] = by_check.get(d[5], 0) + 1
    lines = [f"clang-tidy report  (mode={mode}, {len(tus)} TUs analyzed)",
             f"auto-fixed files: {len(fixed_files)}",
             *(f"  fixed: {f}" for f in fixed_files)]
    if needs_ai_review:
        lines.append(f"needs_ai_review: {len(needs_ai_review)} diagnostic(s) "
                      f"(auto-fix was attempted, broke the build, and was reverted — "
                      f"fix these by hand/AI edit, then rebuild before moving on)")
        for path, ln, col, sev, msg, chk, reason in needs_ai_review:
            lines.append(f"  {path}:{ln}:{col}: {sev}: {msg} [{chk}]  -- {reason}")
    lines.append(f"remaining diagnostics: {len(diags)}")
    if diags:
        lines.append("by check:")
        for chk, n in sorted(by_check.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {n:5d}  {chk}")
        lines.append("-" * 60)
        for path, ln, col, sev, msg, chk in diags:
            lines.append(f"{path}:{ln}:{col}: {sev}: {msg} [{chk}]")
    text = "\n".join(lines) + "\n"
    with open(report_path, "w") as f:
        f.write(text)
    return text


def _md_anchor(chk):
    """GitHub-style heading-to-anchor slug: lowercase, spaces/invalid chars -> '-'."""
    return re.sub(r"[^a-z0-9_-]", "-", chk.lower())


def write_report_markdown(report_path, mode, tus, fixed_files, diags, needs_ai_review=(),
                           report_only=False):
    """Same data as write_report(), rendered as a standalone Markdown report:
    a summary table (linked to per-check sections) plus every diagnostic
    grouped under its check, each formatted as a clickable `path:line:col`
    code span. Meant to be read/committed/opened by a human, not consumed by
    an agent mid-fix-loop (that's what write_report()'s plain-text form is
    for) — this is the "regenerate the report" end product."""
    by_check = {}
    for d in diags:
        by_check[d[5]] = by_check.get(d[5], 0) + 1

    generated = time.strftime("%Y-%m-%d %H:%M:%S %z")
    lines = [
        "# clang-tidy report",
        "",
        f"_mode={mode} &middot; {len(tus)} TU(s) analyzed &middot; generated {generated}"
        f"{' &middot; report-only, no auto-fix applied' if report_only else ''}_",
        "",
    ]

    if not report_only or fixed_files:
        lines += [f"**Auto-fixed files:** {len(fixed_files)}", ""]
        if fixed_files:
            lines += [f"- `{f}`" for f in fixed_files]
            lines.append("")

    if needs_ai_review:
        lines += [
            f"## needs_ai_review ({len(needs_ai_review)})",
            "",
            "Auto-fix was attempted, broke the build, and was reverted — fix these by "
            "hand/AI edit, then rebuild before moving on.",
            "",
        ]
        for path, ln, col, sev, msg, chk, reason in needs_ai_review:
            lines.append(f"- `{path}:{ln}:{col}` — {sev}: {msg} `[{chk}]` — *{reason}*")
        lines.append("")

    lines += [f"## Summary ({len(diags)} remaining diagnostic(s))", ""]
    if diags:
        lines += ["| Check | Count |", "|---|---:|"]
        for chk, n in sorted(by_check.items(), key=lambda kv: -kv[1]):
            lines.append(f"| [{chk}](#{_md_anchor(chk)}) | {n} |")
        lines.append("")

        lines.append("## Diagnostics by check")
        lines.append("")
        by_check_diags = {}
        for path, ln, col, sev, msg, chk in diags:
            by_check_diags.setdefault(chk, []).append((path, ln, col, sev, msg))
        for chk, n in sorted(by_check.items(), key=lambda kv: -kv[1]):
            lines.append(f"### {chk}")
            lines.append("")
            for path, ln, col, sev, msg in by_check_diags[chk]:
                lines.append(f"- `{path}:{ln}:{col}` — {sev}: {msg}")
            lines.append("")
    else:
        lines.append("Clean — no remaining diagnostics.")
        lines.append("")

    text = "\n".join(lines) + "\n"
    with open(report_path, "w") as f:
        f.write(text)
    return text


def _md_anchor(chk):
    """GitHub-style heading-to-anchor slug: lowercase, spaces/invalid chars -> '-'."""
    return re.sub(r"[^a-z0-9_-]", "-", chk.lower())


def write_report_markdown(report_path, mode, tus, fixed_files, diags, needs_ai_review=(),
                           report_only=False):
    """Same data as write_report(), rendered as a standalone Markdown report:
    a summary table (linked to per-check sections) plus every diagnostic
    grouped under its check, each formatted as a clickable `path:line:col`
    code span. Meant to be read/committed/opened by a human, not consumed by
    an agent mid-fix-loop (that's what write_report()'s plain-text form is
    for) — this is the "regenerate the report" end product."""
    by_check = {}
    for d in diags:
        by_check[d[5]] = by_check.get(d[5], 0) + 1

    generated = time.strftime("%Y-%m-%d %H:%M:%S %z")
    lines = [
        "# clang-tidy report",
        "",
        f"_mode={mode} &middot; {len(tus)} TU(s) analyzed &middot; generated {generated}"
        f"{' &middot; report-only, no auto-fix applied' if report_only else ''}_",
        "",
    ]

    if not report_only or fixed_files:
        lines += [f"**Auto-fixed files:** {len(fixed_files)}", ""]
        if fixed_files:
            lines += [f"- `{f}`" for f in fixed_files]
            lines.append("")

    if needs_ai_review:
        lines += [
            f"## needs_ai_review ({len(needs_ai_review)})",
            "",
            "Auto-fix was attempted, broke the build, and was reverted — fix these by "
            "hand/AI edit, then rebuild before moving on.",
            "",
        ]
        for path, ln, col, sev, msg, chk, reason in needs_ai_review:
            lines.append(f"- `{path}:{ln}:{col}` — {sev}: {msg} `[{chk}]` — *{reason}*")
        lines.append("")

    lines += [f"## Summary ({len(diags)} remaining diagnostic(s))", ""]
    if diags:
        lines += ["| Check | Count |", "|---|---:|"]
        for chk, n in sorted(by_check.items(), key=lambda kv: -kv[1]):
            lines.append(f"| [{chk}](#{_md_anchor(chk)}) | {n} |")
        lines.append("")

        lines.append("## Diagnostics by check")
        lines.append("")
        by_check_diags = {}
        for path, ln, col, sev, msg, chk in diags:
            by_check_diags.setdefault(chk, []).append((path, ln, col, sev, msg))
        for chk, n in sorted(by_check.items(), key=lambda kv: -kv[1]):
            lines.append(f"### {chk}")
            lines.append("")
            for path, ln, col, sev, msg in by_check_diags[chk]:
                lines.append(f"- `{path}:{ln}:{col}` — {sev}: {msg}")
            lines.append("")
    else:
        lines.append("Clean — no remaining diagnostics.")
        lines.append("")

    text = "\n".join(lines) + "\n"
    with open(report_path, "w") as f:
        f.write(text)
    return text


def _xml_escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def write_report_xml(report_path, mode, tus, fixed_files, diags, needs_ai_review=(),
                      report_only=False):
    """Same data as write_report()/write_report_markdown(), rendered as a compact,
    custom-schema XML document meant for a *different* AI/agent session (or any XML
    tooling) to parse reliably later — attribute-based, one element per diagnostic, no
    prose to re-derive structure from. Schema (informal, no external XSD):

      <clang-tidy-report mode="all|diff" tus="N" generated="ISO8601"
                          autofixed="N" reportOnly="true|false" remaining="N">
        <fixedFiles>                                 (omitted if empty)
          <file path="..."/>
        </fixedFiles>
        <needsAiReview count="N">                    (omitted if empty)
          <diag file="..." line="N" col="N" severity="warning|error"
                check="..." reason="...">message</diag>
        </needsAiReview>
        <checks>                                     (per-check counts, omitted if 0 diags)
          <check name="..." count="N"/>
        </checks>
        <diagnostics>                                 (omitted if 0 diags)
          <check name="...">
            <diag file="..." line="N" col="N" severity="warning|error">message</diag>
          </check>
        </diagnostics>
      </clang-tidy-report>
    """
    by_check = {}
    for d in diags:
        by_check[d[5]] = by_check.get(d[5], 0) + 1
    by_check_diags = {}
    for path, ln, col, sev, msg, chk in diags:
        by_check_diags.setdefault(chk, []).append((path, ln, col, sev, msg))

    generated = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             f'<clang-tidy-report '
             f'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
             f'xsi:noNamespaceSchemaLocation="clang_tidy_report.xsd" '
             f'mode="{_xml_escape(mode)}" tus="{len(tus)}" '
             f'generated="{generated}" autofixed="{len(fixed_files)}" '
             f'reportOnly="{"true" if report_only else "false"}" '
             f'remaining="{len(diags)}">']

    if fixed_files:
        lines.append("  <fixedFiles>")
        for f in fixed_files:
            lines.append(f'    <file path="{_xml_escape(f)}"/>')
        lines.append("  </fixedFiles>")

    if needs_ai_review:
        lines.append(f'  <needsAiReview count="{len(needs_ai_review)}">')
        for path, ln, col, sev, msg, chk, reason in needs_ai_review:
            lines.append(
                f'    <diag file="{_xml_escape(path)}" line="{ln}" col="{col}" '
                f'severity="{_xml_escape(sev)}" check="{_xml_escape(chk)}" '
                f'reason="{_xml_escape(reason)}">{_xml_escape(msg)}</diag>')
        lines.append("  </needsAiReview>")

    if diags:
        lines.append("  <checks>")
        for chk, n in sorted(by_check.items(), key=lambda kv: -kv[1]):
            lines.append(f'    <check name="{_xml_escape(chk)}" count="{n}"/>')
        lines.append("  </checks>")

        lines.append("  <diagnostics>")
        for chk, n in sorted(by_check.items(), key=lambda kv: -kv[1]):
            lines.append(f'    <check name="{_xml_escape(chk)}">')
            for path, ln, col, sev, msg in by_check_diags[chk]:
                lines.append(
                    f'      <diag file="{_xml_escape(path)}" line="{ln}" col="{col}" '
                    f'severity="{_xml_escape(sev)}">{_xml_escape(msg)}</diag>')
            lines.append("    </check>")
        lines.append("  </diagnostics>")

    lines.append("</clang-tidy-report>")
    text = "\n".join(lines) + "\n"
    with open(report_path, "w") as f:
        f.write(text)
    return text


def diags_for_files(outputs, root, files_rel):
    """Diagnostics (from a pre-fix pass) whose file is in files_rel, keyed
    for the needs_ai_review section."""
    files_abs = {os.path.realpath(os.path.join(root, f)) for f in files_rel}
    out = []
    for out_text in outputs.values():
        for line in out_text.splitlines():
            m = DIAG_RE.match(line.strip())
            if not m:
                continue
            path = os.path.realpath(m.group(1))
            if path in files_abs:
                out.append((os.path.relpath(path, root), int(m.group(2)), int(m.group(3)),
                            m.group(4), m.group(5), m.group(6)))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["diff", "all"], required=True)
    ap.add_argument("--build-dir", help="directory containing compile_commands.json")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--no-fix", action="store_true", help="report only, apply no fixes")
    ap.add_argument("--report", help="report output path")
    ap.add_argument("--format", choices=["txt", "md", "xml"], default="txt",
                    help="report format: plain-text diagnostic list (default, for an "
                         "agent to fix from in the same session), a standalone Markdown "
                         "report with a per-check summary table and clickable "
                         "path:line:col entries (for a human to read/commit), or a "
                         "compact custom-schema XML report (for a *different* AI/agent "
                         "session to parse reliably later, without re-deriving structure "
                         "from prose)")
    ap.add_argument("--timeout", type=int, default=300,
                    help="per-TU clang-tidy timeout in seconds (default 300); "
                         "TUs that time out are skipped, not fatal")
    ap.add_argument("--heartbeat", type=int, default=30,
                    help="seconds between progress heartbeats while a batch runs")
    ap.add_argument("--log-file", help="also append the live log to this file")
    ap.add_argument("--build-timeout", type=int, default=1800,
                    help="timeout in seconds for the post-fix build verification")
    args = ap.parse_args()

    if args.log_file:
        global log
        lf = open(args.log_file, "a")
        _orig_log = log

        def log(msg):  # noqa: F811
            _orig_log(msg)
            print(msg, file=lf, flush=True)

    root = find_repo_root()
    global _third_party_paths
    _third_party_paths = load_third_party_paths(root)
    if _third_party_paths:
        log(f"third-party paths from {SKILLS_CONFIG_FILENAME}: {', '.join(_third_party_paths)}")
    tidy = find_tool("clang-tidy", "CLANG_TIDY")
    if not tidy:
        log("error: clang-tidy not found (set CLANG_TIDY or install LLVM)")
        return 2
    db = find_compile_db(root, args.build_dir)
    if not db:
        log("error: compile_commands.json not found; configure the build with "
            "CMAKE_EXPORT_COMPILE_COMMANDS=ON or pass --build-dir")
        return 2
    build_dir = args.build_dir or os.path.dirname(db)
    if not os.path.isfile(os.path.join(root, ".clang-tidy")):
        log("warning: no .clang-tidy at repo root; clang-tidy default checks will be used")

    tus = load_tus(db, root)
    if args.mode == "diff":
        tus, _changed = select_diff_tus(tus, git_changed_files(root))
        if not tus:
            print("clang-tidy: no C/C++ changes detected in git diff — nothing to do")
            return 0
    if not tus:
        log("error: no translation units found in compile database under repo root")
        return 2

    log(f"clang-tidy={tidy}\ncompile_db={db}\nanalyzing {len(tus)} TUs "
        f"(mode={args.mode}, jobs={args.jobs})")

    clang_tidy_never_autofix_paths, never_autofix_checks, whole_batch_only_checks = \
        load_project_config(root)

    fixed_files = []
    needs_ai_review = []

    if not args.no_fix:
        apply_tool = find_tool("clang-apply-replacements", "CLANG_APPLY_REPLACEMENTS")
        fmt_tool = find_tool("clang-format", "CLANG_FORMAT")
        never_disable = ",".join(
            "-" + c for c in (never_autofix_checks | whole_batch_only_checks))

        if apply_tool:
            # Tier 1: everything except whole-batch-only and never-autofix checks.
            log("pass 1/3: collecting tier1 auto-fixes (parallel)...")
            with tempfile.TemporaryDirectory(prefix="tidy-fixes-t1-") as export_dir:
                pre_outputs = run_tidy_pass(tidy, os.path.dirname(db), tus, args.jobs,
                                             args.timeout, export_dir=export_dir,
                                             checks=never_disable, heartbeat=args.heartbeat)
                t1_fixed, t1_excluded = apply_exported_fixes(
                    export_dir, apply_tool, fmt_tool, root,
                    preexcluded_paths=clang_tidy_never_autofix_paths)
            if t1_fixed:
                ok, tail = verify_build_or_revert(root, build_dir, t1_fixed, args.build_timeout)
                if ok:
                    fixed_files += t1_fixed
                else:
                    log(f"tier1 build failure tail:\n{tail}")
                    for d in diags_for_files(pre_outputs, root, t1_fixed):
                        needs_ai_review.append(d + ("tier1 auto-fix broke the build",))

            # Tier 2: whole-batch-only checks, --mode all only, atomic (no retry).
            if args.mode == "all" and whole_batch_only_checks:
                log("pass 2/3: collecting tier2 (whole-batch-only) auto-fixes...")
                t2_checks = ",".join(sorted(whole_batch_only_checks))
                with tempfile.TemporaryDirectory(prefix="tidy-fixes-t2-") as export_dir:
                    pre_outputs2 = run_tidy_pass(tidy, os.path.dirname(db), tus, args.jobs,
                                                  args.timeout, export_dir=export_dir,
                                                  checks="-*," + t2_checks,
                                                  heartbeat=args.heartbeat)
                    t2_fixed, t2_excluded = apply_exported_fixes(
                        export_dir, apply_tool, fmt_tool, root,
                        preexcluded_paths=clang_tidy_never_autofix_paths, whole_batch_only=True)
                if t2_fixed:
                    ok, tail = verify_build_or_revert(root, build_dir, t2_fixed,
                                                       args.build_timeout)
                    if ok:
                        fixed_files += t2_fixed
                    else:
                        log(f"tier2 build failure tail:\n{tail}")
                        for d in diags_for_files(pre_outputs2, root, t2_fixed):
                            needs_ai_review.append(
                                d + ("tier2 (rename) auto-fix broke the build",))
            else:
                log("pass 2/3: skipped (tier2 only runs in --mode all)")
        else:
            log("pass 1/3: clang-apply-replacements not found; applying tier1 fixes "
                "serially (never-autofix checks disabled)...")
            pre_outputs = run_tidy_pass(tidy, os.path.dirname(db), tus, args.jobs, args.timeout,
                                         fix_inplace=True, checks=never_disable,
                                         heartbeat=args.heartbeat)
            touched = sorted(_changed_in(root))
            candidate = [l for l in touched if l not in clang_tidy_never_autofix_paths]
            # revert anything touched under clang_tidy_never_autofix_paths just in case
            never_touched = [l for l in touched if l in clang_tidy_never_autofix_paths]
            if never_touched:
                restore_worktree(never_touched, root)
            if candidate:
                ok, tail = verify_build_or_revert(root, build_dir, candidate, args.build_timeout)
                if ok:
                    fixed_files += candidate
                else:
                    log(f"tier1(serial) build failure tail:\n{tail}")
                    for d in diags_for_files(pre_outputs, root, candidate):
                        needs_ai_review.append(d + ("tier1 auto-fix broke the build",))

    log("pass 3/3: verifying...")
    outputs = run_tidy_pass(tidy, os.path.dirname(db), tus, args.jobs, args.timeout,
                             heartbeat=args.heartbeat)
    diags = collect_diagnostics(outputs, root)

    report_path = args.report or os.path.join(
        tempfile.gettempdir(), f"clang_tidy_report_{args.mode}.{args.format}")
    if args.format == "md":
        text = write_report_markdown(report_path, args.mode, tus, fixed_files, diags,
                                      needs_ai_review, report_only=args.no_fix)
    elif args.format == "xml":
        text = write_report_xml(report_path, args.mode, tus, fixed_files, diags,
                                 needs_ai_review, report_only=args.no_fix)
    else:
        text = write_report(report_path, args.mode, tus, fixed_files, diags, needs_ai_review)

    head = text.splitlines()
    print("\n".join(head[:60]))
    if len(head) > 60:
        print(f"... ({len(head) - 60} more lines)")
    print(f"\nfull report: {report_path}")
    return 1 if (diags or needs_ai_review) else 0


if __name__ == "__main__":
    sys.exit(main())
