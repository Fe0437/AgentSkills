#!/usr/bin/env python3
"""Produce a read-only, low-cost architecture inventory for a repository."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
import subprocess
from typing import Any


EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
    "vendor",
    "third_party",
    "external",
}

LANGUAGE_EXTENSIONS = {
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cppm": "C++ modules",
    ".cxx": "C++",
    ".h": "C/C++ headers",
    ".hpp": "C++ headers",
    ".rs": "Rust",
    ".go": "Go",
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".swift": "Swift",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".scala": "Scala",
    ".sh": "Shell",
    ".sql": "SQL",
}

BUILD_MARKERS = {
    "CMakeLists.txt": "CMake",
    "Cargo.toml": "Cargo",
    "package.json": "Node workspace/package",
    "pyproject.toml": "Python project",
    "go.mod": "Go modules",
    "go.work": "Go workspace",
    "Package.swift": "Swift Package Manager",
    "pom.xml": "Maven",
    "build.gradle": "Gradle",
    "build.gradle.kts": "Gradle Kotlin",
    "WORKSPACE": "Bazel",
    "WORKSPACE.bazel": "Bazel",
    "MODULE.bazel": "Bazel modules",
    "meson.build": "Meson",
    "Makefile": "Make",
    "Justfile": "Just",
}

PACKAGE_MARKERS = {
    "CMakeLists.txt",
    "Cargo.toml",
    "package.json",
    "pyproject.toml",
    "go.mod",
    "Package.swift",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "meson.build",
}

GUIDANCE_NAMES = {
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "CODEOWNERS",
    ".editorconfig",
    ".clang-format",
    ".clang-tidy",
    "rustfmt.toml",
    "ruff.toml",
}


def run_git(arguments: list[str], cwd: Path) -> str | None:
    result = subprocess.run(
        ["git", *arguments], cwd=cwd, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def find_root(start: Path) -> Path:
    root = run_git(["rev-parse", "--show-toplevel"], start)
    return Path(root).resolve() if root else start.resolve()


def third_party_paths(root: Path) -> set[str]:
    """Paths the project marks as code it does not own, in `.agent-skills.json`.

    Submodules are part of the project and are inventoried like any directory; these are the
    exceptions, shared by every agent skill: {"third_party_paths": ["deps/sdl"]}.
    """
    config = root / ".agent-skills.json"
    if not config.is_file():
        return set()
    try:
        return {Path(p).as_posix() for p in json.loads(config.read_text()).get("third_party_paths", [])}
    except (OSError, ValueError):
        return set()


def iter_files(root: Path, max_depth: int = 6):
    third_party = third_party_paths(root)
    for current_root, directory_names, file_names in os.walk(root):
        current = Path(current_root)
        relative = current.relative_to(root)
        depth = len(relative.parts)
        directory_names[:] = [
            name
            for name in directory_names
            if name not in EXCLUDED_DIRS
            and not name.startswith("build-")
            and (relative / name).as_posix() not in third_party
            and depth < max_depth
        ]
        for file_name in file_names:
            yield current / file_name


def relative_paths(paths: list[Path], root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in paths)


def inventory(root: Path) -> dict[str, Any]:
    files = list(iter_files(root))
    language_counts = Counter(
        LANGUAGE_EXTENSIONS[path.suffix.lower()]
        for path in files
        if path.suffix.lower() in LANGUAGE_EXTENSIONS
    )

    build_systems: dict[str, list[str]] = {}
    for marker, build_system in BUILD_MARKERS.items():
        matches = [path for path in files if path.name == marker]
        if matches:
            build_systems[build_system] = relative_paths(matches, root)

    architecture_docs = [
        path
        for path in files
        if path.name.lower()
        in {
            "architecture.md",
            "api_guidelines.md",
            "package_map.md",
            "design.md",
            "decisions.md",
        }
        or "adr" in {part.lower() for part in path.parts}
    ]
    guidance = [path for path in files if path.name in GUIDANCE_NAMES]
    package_manifests = [path for path in files if path.name in PACKAGE_MARKERS]
    ci_files = [
        path
        for path in files
        if ".github/workflows" in str(path.relative_to(root))
        or path.name in {".gitlab-ci.yml", "azure-pipelines.yml", "Jenkinsfile"}
    ]

    top_level_directories = sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and path.name not in EXCLUDED_DIRS and not path.name.startswith("build-")
    )
    status = run_git(["status", "--short"], root)

    return {
        "root": str(root),
        "git": {
            "is_repository": run_git(["rev-parse", "--is-inside-work-tree"], root) == "true",
            "changed_entries": len(status.splitlines()) if status else 0,
        },
        "top_level_directories": top_level_directories,
        "languages": dict(language_counts.most_common()),
        "build_systems": build_systems,
        "package_manifests": relative_paths(package_manifests, root),
        "architecture_docs": relative_paths(architecture_docs, root),
        "guidance_and_style": relative_paths(guidance, root),
        "ci_files": relative_paths(ci_files, root),
    }


def render_markdown(data: dict[str, Any]) -> str:
    lines = ["# Project inventory", "", f"- Root: `{data['root']}`"]
    lines.append(f"- Git repository: `{data['git']['is_repository']}`")
    lines.append(f"- Changed/untracked entries: `{data['git']['changed_entries']}`")

    for heading, key in (
        ("Languages", "languages"),
        ("Build systems", "build_systems"),
        ("Top-level directories", "top_level_directories"),
        ("Package manifests", "package_manifests"),
        ("Architecture documents", "architecture_docs"),
        ("Guidance and style", "guidance_and_style"),
        ("CI files", "ci_files"),
    ):
        lines.extend(["", f"## {heading}", ""])
        value = data[key]
        if isinstance(value, dict):
            for name, detail in value.items():
                if isinstance(detail, list):
                    lines.append(f"- **{name}**: {', '.join(f'`{item}`' for item in detail)}")
                else:
                    lines.append(f"- **{name}**: {detail}")
        elif value:
            lines.extend(f"- `{item}`" for item in value)
        else:
            lines.append("- None detected")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=".", help="project path (default: current directory)")
    parser.add_argument("--format", choices=("json", "md"), default="json")
    parser.add_argument("--output", help="optional output file; stdout when omitted")
    arguments = parser.parse_args()

    root = find_root(Path(arguments.path))
    data = inventory(root)
    text = render_markdown(data) if arguments.format == "md" else json.dumps(data, indent=2) + "\n"

    if arguments.output:
        Path(arguments.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

