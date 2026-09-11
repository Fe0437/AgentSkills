# Project configuration

The configuration is JSON owned by the consuming repository. Paths are
relative to that repository's root. Commands are arrays of arguments so an
agent can execute them without a shell.

```json
{
  "schemaVersion": 1,
  "input": "docs/architecture/packages.json",
  "inputFormat": "onion-package-graph-v1",
  "generatedOutputs": [
    "build/architecture/packages.html",
    "build/architecture/packages.puml"
  ],
  "commands": {
    "generate": [["just", "architecture-generate"]],
    "check": [["just", "architecture-check"]],
    "render": [["just", "generate-docs"]]
  },
  "interactiveChecks": [
    "The overview opens without clipping.",
    "Search isolates matching packages."
  ]
}
```

Required fields:

- `schemaVersion`: currently `1`.
- `input`: canonical architecture source data.
- `generatedOutputs`: files that must be changed only through generation.
- `commands.generate`: one or more commands that regenerate the outputs.
- `commands.check`: one or more commands that verify source and outputs agree.

Optional fields:

- `inputFormat`: a format understood by this skill or documented by the
  project. Use `onion-package-graph-v1` for the bundled package-graph reference.
- `commands.render`: documentation or diagram rendering commands.
- `interactiveChecks`: project-owned behaviors to inspect in generated views.

An empty optional command list is allowed. Do not add commands merely to fill
the configuration.
