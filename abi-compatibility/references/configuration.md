# Project configuration

The configuration is JSON owned by the consuming repository. Paths and glob
patterns are relative to that repository's root. Commands are arrays of
arguments so an agent can execute them without a shell.

```json
{
  "schemaVersion": 1,
  "boundary": "Host plugin ABI",
  "publicInputs": ["include/plugin_abi/*.h"],
  "implementationInputs": ["src/plugin_abi/**"],
  "policyDocuments": ["docs/ABI_POLICY.md"],
  "versionSources": ["include/plugin_abi/version.h"],
  "baselineArtifacts": ["abi/baseline.json"],
  "generatedArtifacts": ["bindings/generated.py"],
  "commands": {
    "check": [["just", "abi-check"]],
    "update": [["just", "abi-update"]],
    "verify": [["just", "test"]]
  }
}
```

Required fields:

- `schemaVersion`: currently `1`.
- `boundary`: short name used in reports.
- `publicInputs`: exported headers, interface definitions, symbol lists, or
  other files that define the binary contract.
- `policyDocuments`: documents that define compatibility and version rules.
- `versionSources`: files that record the advertised ABI version.
- `commands.check`: commands that compare the current contract with its
  accepted baseline.

Optional fields:

- `implementationInputs`: boundary implementations whose changes require an
  ABI review even when the public input is unchanged.
- `baselineArtifacts`: recorded layouts, signatures, symbols, or versions.
- `generatedArtifacts`: bindings or mirrors updated from the contract.
- `commands.update`: deliberate baseline/generation commands.
- `commands.verify`: builds, tests, or platform ABI checks run after updating.

Lists may contain paths or glob patterns. An empty optional list is allowed.
Do not add a placeholder command when the project has no corresponding tool.
