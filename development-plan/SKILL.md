---
name: development-plan
description: Find the next open issue, or fetch one issue (scope, required tests, status, milestone and epic context) from the project's markdown development plan, list open issues, or record an issue's status and evidence - without reading the plan file. Use whenever work starts on, looks up, or finishes a planned issue such as "continue with ABC-123" or "what is next in M3".
---

# Development plan: read and update issues cheaply

**Token economy - follow strictly:** never open the plan file itself. The script prints only
what you ask for, and it writes status records for you.

`plan.py` sits next to this file. From the repository root it is
`.agents/skills/development-plan/plan.py`. Run it with `python3` (3.9 or newer, standard library only).

## Commands

```sh
P=.agents/skills/development-plan/plan.py
python3 $P next                  # current section and its next open issue, as desc
python3 $P next --full           # the same, as full-desc: start here when picking up work
python3 $P next M4               # the next open issue of one section
python3 $P desc ABC-123          # the issue's own row: scope, tests, status, evidence
python3 $P full-desc ABC-123     # desc + its section's goal, exit signal and text + each epic
python3 $P list M3 --open        # one line per open issue of a section, in plan order
python3 $P status ABC-123 "In progress"
python3 $P status ABC-123 Complete --evidence - <<'EOF'
What now works and the tests that prove it.
EOF
```

- **Starting work:** run `next --full` once. It says which section is current and which issue
  is next, and gives the issue, its section, and every epic it belongs to: the epic's goal, the
  section that closes it, and all the epic's issues with their status, so you can see where the
  issue fits. Later lookups need only `desc`.
- **How `next` chooses:** the current section is the first one, in plan order, with an open
  issue. Its table is in dependency order, so the next issue is the first open one after the
  last done one. Open issues before that point are listed as "still open earlier": later work
  is already done, so they are usually owned elsewhere or blocked. Say so if one looks next.
- `list` without a section lists every issue. The summary is cut to `--width` characters.
- `status` replaces the row in the issue's section's status table, or adds one. If the section
  has no status table yet, it creates one. Pass `--evidence -` with a heredoc so backticks and
  quotes survive the shell. Without `--evidence`, existing evidence is kept.
- After a write, `status` runs the configured `after_update` commands. If one fails, the plan is
  restored and the command output is printed. Fix the text and run it again.

## Settings

The script uses the nearest `.agent-skills.json` from the working directory upward that has a
`development_plan` entry. Only `path` is required. Paths are relative to that file.

```json
{
  "development_plan": {
    "path": "docs/DEVELOPMENT_PLAN.md",
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
    "ignore_regions": [["<!-- BEGIN GENERATED -->", "<!-- END GENERATED -->"]],
    "status_table_heading": "### {section} completion record",
    "after_update": ["just plan-check"]
  }
}
```

The plan format this expects:

- A section is a heading at `section_heading_level`. Its first word, such as `M3`, is its short name.
- An issue is a row whose first cell matches `issue_id`, in a table whose first header cell is
  `id_column`. The other columns become the issue's fields.
- A table that also has `status_column` is a status record. An issue with no record has
  `open_status`.
- Optional: the issue's `epic_column` names its epics, split by `epic_separator`. A table whose
  first header cell is `epic_column` describes each epic. A table whose first header cell is
  `section_catalog_column` describes each section; its `closes_epic_column` names the epics that
  section closes. Rows are matched by the first word of their first cell, such as `E4` or `M3`.
- Lines inside `ignore_regions` are skipped, for example a generated view that repeats the issues.

If there are no settings, or the plan does not follow this format, tell the user what is
missing. Do not fall back to reading the plan.
