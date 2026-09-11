#!/usr/bin/env python3
"""Read and update issues in a markdown development plan without loading the whole plan.

The plan is named by the `development_plan` entry of the nearest `.agent-skills.json`
found from the current directory upward. Issues are rows of markdown tables whose first
header cell is the issue column. A table that also has a status column is a status record;
every other such table defines issues. Optional catalog tables describe epics and sections.
Plain Python 3.9 standard library only.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys

CONFIG_FILE = ".agent-skills.json"
CONFIG_KEY = "development_plan"
DEFAULTS = {
    "section_heading_level": 2,
    "id_column": "Issue",
    "status_column": "Status",
    "evidence_column": "Evidence",
    "epic_column": "Epic",
    "epic_separator": "/",
    "section_catalog_column": "Milestone",
    "closes_epic_column": "Closes epic",
    "issue_id": "[A-Z]+-[0-9]+",
    "open_status": "Planned",
    "done_statuses": ["Complete"],
    "ignore_regions": [],
    "status_table_heading": "### {section} completion record",
    "after_update": [],
}
SEPARATOR = re.compile(r"^\|\s*:?-{3,}")
UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


class PlanError(Exception):
    """A problem the user must fix in the plan or its settings."""


@dataclass
class Table:
    """One markdown table and the section that contains it."""

    header: list[str]
    rows: list[tuple[int, list[str]]]
    section: str
    lastLine: int


@dataclass
class Issue:
    """One issue definition joined with its status record, if any."""

    identifier: str
    section: str
    fields: dict[str, str]
    status: str
    evidence: str


@dataclass
class Plan:
    """A parsed plan and the settings used to parse it."""

    path: Path
    root: Path
    settings: dict
    lines: list[str]
    sections: list[tuple[int, str]]
    tables: list[Table]


def _loadSettings() -> tuple[Path, dict]:
    for directory in [Path.cwd(), *Path.cwd().parents]:
        candidate = directory / CONFIG_FILE
        if not candidate.is_file():
            continue
        entry = json.loads(candidate.read_text(encoding="utf-8")).get(CONFIG_KEY)
        if entry is None:
            continue
        if "path" not in entry:
            raise PlanError(f"{candidate}: `{CONFIG_KEY}` needs a `path`")
        return directory, {**DEFAULTS, **entry}
    raise PlanError(f"no {CONFIG_FILE} with a `{CONFIG_KEY}` entry was found from {Path.cwd()} upward")


def _cells(line: str) -> list[str]:
    parts = UNESCAPED_PIPE.split(line.strip())
    return [part.strip() for part in parts[1:-1]]


def _row(header: list[str], cells: list[str]) -> dict[str, str]:
    """Cells keyed by their column name; a short row reads as empty cells."""
    return {name: cells[position] if position < len(cells) else "" for position, name in enumerate(header)}


def _key(text: str) -> str:
    """The first word of a heading or catalog cell, such as `M3` or `E4`."""
    return text.split(" ", 1)[0] if text else ""


def _parse() -> Plan:
    root, settings = _loadSettings()
    path = root / settings["path"]
    if not path.is_file():
        raise PlanError(f"the configured plan does not exist: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    headingPrefix = "#" * settings["section_heading_level"] + " "
    ignoreEnds = {begin: end for begin, end in settings["ignore_regions"]}
    sections: list[tuple[int, str]] = []
    tables: list[Table] = []
    section = ""
    ignoreUntil: str | None = None
    table: Table | None = None
    for index, line in enumerate(lines):
        if ignoreUntil is not None:
            if line.strip() == ignoreUntil:
                ignoreUntil = None
            continue
        if line.strip() in ignoreEnds:
            ignoreUntil = ignoreEnds[line.strip()]
            table = None
            continue
        if table is not None:
            if line.startswith("|"):
                table.rows.append((index, _cells(line)))
                table.lastLine = index
                continue
            table = None
        if line.startswith(headingPrefix):
            section = line[len(headingPrefix) :].strip()
            sections.append((index, section))
        elif line.startswith("|") and index + 1 < len(lines) and SEPARATOR.match(lines[index + 1]):
            table = Table(_cells(line), [], section, index + 1)
            tables.append(table)
    return Plan(path, root, settings, lines, sections, tables)


def _tablesStartingWith(plan: Plan, column: str) -> list[Table]:
    return [table for table in plan.tables if table.header and table.header[0] == column]


def _isStatusTable(plan: Plan, table: Table) -> bool:
    return plan.settings["status_column"] in table.header


def _issues(plan: Plan) -> list[Issue]:
    idPattern = re.compile(plan.settings["issue_id"])
    records: dict[str, dict[str, str]] = {}
    issues: list[Issue] = []
    for table in _tablesStartingWith(plan, plan.settings["id_column"]):
        for _index, cells in table.rows:
            if not cells or not idPattern.fullmatch(cells[0]):
                continue
            row = _row(table.header, cells)
            if _isStatusTable(plan, table):
                records[cells[0]] = row
            else:
                fields = {name: value for name, value in row.items() if name != plan.settings["id_column"]}
                issues.append(Issue(cells[0], table.section, fields, plan.settings["open_status"], ""))
    for issue in issues:
        record = records.get(issue.identifier)
        if record is not None:
            issue.status = record.get(plan.settings["status_column"], issue.status)
            issue.evidence = record.get(plan.settings["evidence_column"], "")
    return issues


def _catalog(plan: Plan, column: str) -> dict[str, dict[str, str]]:
    """Rows of the tables whose first header cell is `column`, keyed by their first word."""
    rows: dict[str, dict[str, str]] = {}
    for table in _tablesStartingWith(plan, column):
        for _index, cells in table.rows:
            if cells:
                rows[_key(cells[0])] = _row(table.header, cells)
    return rows


def _find(plan: Plan, issues: list[Issue], identifier: str) -> Issue:
    for issue in issues:
        if issue.identifier == identifier:
            return issue
    raise PlanError(f"issue {identifier} is not defined in {plan.path}")


def _isDone(plan: Plan, issue: Issue) -> bool:
    return issue.status in plan.settings["done_statuses"]


def _inSection(section: str, query: str | None) -> bool:
    return query is None or section == query or _key(section) == query


def _sectionBounds(plan: Plan, section: str) -> tuple[int, int]:
    for position, (start, name) in enumerate(plan.sections):
        if name == section:
            end = plan.sections[position + 1][0] if position + 1 < len(plan.sections) else len(plan.lines)
            return start, end
    raise PlanError(f"section {section!r} was not found")


def _sectionProse(plan: Plan, section: str) -> str:
    start, end = _sectionBounds(plan, section)
    kept: list[str] = []
    for line in plan.lines[start + 1 : end]:
        if line.startswith("|"):
            continue
        if not line.strip() and (not kept or not kept[-1].strip()):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def _epicsOf(plan: Plan, issue: Issue) -> list[str]:
    value = issue.fields.get(plan.settings["epic_column"], "")
    return [part.strip() for part in value.split(plan.settings["epic_separator"]) if part.strip()]


def _printDesc(plan: Plan, issue: Issue) -> None:
    print(f"{issue.identifier} | {issue.section} | {issue.status}")
    for name, value in issue.fields.items():
        print(f"\n{name}:\n{value}")
    if issue.evidence:
        print(f"\n{plan.settings['evidence_column']}:\n{issue.evidence}")


def _printEpic(plan: Plan, issues: list[Issue], issue: Issue, epic: str) -> None:
    epics = _catalog(plan, plan.settings["epic_column"])
    sections = _catalog(plan, plan.settings["section_catalog_column"])
    row = epics.get(epic)
    print(f"\n== Epic {row[plan.settings['epic_column']] if row else epic}")
    for name, value in (row or {}).items():
        if name != plan.settings["epic_column"]:
            print(f"{name}: {value}")
    closesColumn = plan.settings["closes_epic_column"]
    for section in sections.values():
        closes = section.get(closesColumn, "").split(plan.settings["epic_separator"])
        if epic in [part.strip() for part in closes]:
            print(f"Closed by: {section[plan.settings['section_catalog_column']]}")
            for name, value in section.items():
                if name not in (plan.settings["section_catalog_column"], closesColumn):
                    print(f"  {name}: {value}")
    print("Issues, in plan order (* is this issue):")
    grouped: dict[str, list[str]] = {}
    for other in issues:
        if epic in _epicsOf(plan, other):
            mark = "*" if other.identifier == issue.identifier else ""
            grouped.setdefault(_key(other.section), []).append(f"{mark}{other.identifier} {other.status}")
    for section, entries in grouped.items():
        print(f"  {section}: {', '.join(entries)}")


def _printFullDesc(plan: Plan, issues: list[Issue], issue: Issue) -> None:
    _printDesc(plan, issue)
    section = _catalog(plan, plan.settings["section_catalog_column"]).get(_key(issue.section), {})
    print(f"\n== {issue.section}")
    for name, value in section.items():
        if name not in (plan.settings["section_catalog_column"], plan.settings["closes_epic_column"]):
            print(f"{name}: {value}")
    prose = _sectionProse(plan, issue.section)
    if prose:
        print(f"\n{prose}")
    for epic in _epicsOf(plan, issue):
        _printEpic(plan, issues, issue, epic)


def describe(identifier: str, full: bool) -> None:
    """Print one issue; with `full`, also its section and every epic it belongs to."""
    plan = _parse()
    issues = _issues(plan)
    issue = _find(plan, issues, identifier)
    if full:
        _printFullDesc(plan, issues, issue)
    else:
        _printDesc(plan, issue)


def nextIssue(section: str | None, full: bool) -> None:
    """Print the current section and its next open issue.

    The current section is the first one, in plan order, with an open issue. Its tables are in
    dependency order, so the next issue is the first open one after the last done one; open
    issues before that point are listed, because work after them is already done.
    """
    plan = _parse()
    issues = _issues(plan)
    order: list[str] = []
    for issue in issues:
        if issue.section not in order:
            order.append(issue.section)
    candidates = [name for name in order if _inSection(name, section)]
    current = next(
        (name for name in candidates if any(i.section == name and not _isDone(plan, i) for i in issues)), None
    )
    if current is None:
        raise PlanError("every issue is done" if section is None else f"section {section} has no open issue")
    members = [issue for issue in issues if issue.section == current]
    lastDone = max((position for position, issue in enumerate(members) if _isDone(plan, issue)), default=-1)
    after = [issue for issue in members[lastDone + 1 :] if not _isDone(plan, issue)]
    chosen = after[0] if after else next(issue for issue in members if not _isDone(plan, issue))
    skipped = [issue.identifier for issue in members[: members.index(chosen)] if not _isDone(plan, issue)]
    done = sum(1 for issue in members if _isDone(plan, issue))
    print(f"Current section: {current} ({done} of {len(members)} issues done)")
    print(f"Next issue: {chosen.identifier}")
    if skipped:
        print(f"Still open earlier in the section: {', '.join(skipped)}")
    print()
    if full:
        _printFullDesc(plan, issues, chosen)
    else:
        _printDesc(plan, chosen)


def listIssues(section: str | None, openOnly: bool, width: int) -> None:
    """Print one line per issue, in plan order."""
    plan = _parse()
    for issue in _issues(plan):
        if not _inSection(issue.section, section) or (openOnly and _isDone(plan, issue)):
            continue
        summary = " · ".join(issue.fields.values())
        if len(summary) > width:
            summary = summary[: width - 1] + "…"
        print(f"{issue.identifier}\t{issue.status}\t{_key(issue.section)}\t{summary}")


def _cell(value: str) -> str:
    return UNESCAPED_PIPE.sub(r"\\|", " ".join(value.split()))


def _tableLine(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def setStatus(identifier: str, status: str, evidence: str | None) -> None:
    """Record `status` (and `evidence`, when given) for one issue, then run the configured hooks."""
    plan = _parse()
    settings = plan.settings
    issue = _find(plan, _issues(plan), identifier)
    statusTables = [
        table
        for table in _tablesStartingWith(plan, settings["id_column"])
        if table.section == issue.section and _isStatusTable(plan, table)
    ]
    lines = list(plan.lines)
    if statusTables:
        table = statusTables[-1]
        existing = next(((index, cells) for index, cells in table.rows if cells and cells[0] == identifier), None)
        cells = list(existing[1]) if existing else [identifier] + [""] * (len(table.header) - 1)
        cells += [""] * (len(table.header) - len(cells))
        cells[table.header.index(settings["status_column"])] = _cell(status)
        if evidence is not None and settings["evidence_column"] in table.header:
            cells[table.header.index(settings["evidence_column"])] = _cell(evidence)
        if existing:
            lines[existing[0]] = _tableLine(cells)
        else:
            lines.insert(table.lastLine + 1, _tableLine(cells))
    else:
        header = [settings["id_column"], settings["status_column"], settings["evidence_column"]]
        _start, end = _sectionBounds(plan, issue.section)
        while end > 0 and not lines[end - 1].strip():
            end -= 1
        heading = settings["status_table_heading"].format(section=_key(issue.section))
        lines[end:end] = [
            "",
            heading,
            "",
            _tableLine(header),
            "|" + "|".join("---" for _name in header) + "|",
            _tableLine([identifier, _cell(status), _cell(evidence or "")]),
        ]
    original = plan.path.read_text(encoding="utf-8")
    plan.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for command in settings["after_update"]:
        result = subprocess.run(command, shell=True, cwd=plan.root, capture_output=True, text=True)
        if result.returncode != 0:
            plan.path.write_text(original, encoding="utf-8")
            output = result.stdout + result.stderr
            raise PlanError(f"`{command}` rejected the update, so the plan was restored:\n{output}")
    print(f"{identifier}: {issue.status} -> {status}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    descParser = commands.add_parser("desc", help="one issue's own row: scope, tests, status")
    descParser.add_argument("issue")
    fullParser = commands.add_parser("full-desc", help="desc plus its section and every epic it belongs to")
    fullParser.add_argument("issue")
    nextParser = commands.add_parser("next", help="the current section and its next open issue")
    nextParser.add_argument("section", nargs="?", help="look only in this section, such as M4")
    nextParser.add_argument("--full", action="store_true", help="print full-desc instead of desc")
    listParser = commands.add_parser("list", help="one line per issue, in plan order")
    listParser.add_argument("section", nargs="?", help="section heading or its first word, such as M3")
    listParser.add_argument("--open", action="store_true", help="hide issues whose status counts as done")
    listParser.add_argument("--width", type=int, default=110, help="summary width")
    statusParser = commands.add_parser("status", help="record an issue's status")
    statusParser.add_argument("issue")
    statusParser.add_argument("status")
    statusParser.add_argument("--evidence", help="evidence text; `-` reads it from standard input")
    arguments = parser.parse_args()
    try:
        if arguments.command in ("desc", "full-desc"):
            describe(arguments.issue, arguments.command == "full-desc")
        elif arguments.command == "next":
            nextIssue(arguments.section, arguments.full)
        elif arguments.command == "list":
            listIssues(arguments.section, arguments.open, arguments.width)
        else:
            evidence = sys.stdin.read() if arguments.evidence == "-" else arguments.evidence
            setStatus(arguments.issue, arguments.status, evidence)
    except PlanError as error:
        print(f"development-plan: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
