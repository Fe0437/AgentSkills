---
name: abi-compatibility
description: Check a project's native binary interface for backward compatibility using its project-owned ABI configuration, policy, baselines, and verification commands. Use when exported native contracts or their implementations change, before committing an ABI change, or when the configured ABI gate fails.
---

# ABI compatibility

Drive the consuming project's ABI policy and tooling without embedding its
headers, symbols, version scheme, or release rules in this skill.

## Find the project configuration

From the repository root, look for the first existing file in this order:

1. `.private/abi-compatibility.json`
2. `docs/abi/compatibility.json`
3. `.abi-compatibility.json`

Read [references/configuration.md](references/configuration.md) before creating
or changing that file. The configuration and every referenced policy document
belong to the consuming project.

If no configuration exists, ask the user for the exported inputs, ABI policy,
version source, baseline artifacts, and check/update commands. Do not infer a
versioning policy or record a new baseline until those choices are explicit.

## Workflow

1. Read repository instructions and the discovered configuration. Resolve
   paths and glob matches inside the repository root; reject paths that escape
   it.
2. Read the configured policy documents before judging compatibility. Inspect
   the diff for every configured public and implementation input.
3. Run each configured check command exactly as an argument list. Prefer the
   checker verdict and measured layouts/signatures over manual inspection.
4. Reconcile the tool result with changes tools commonly miss: semantic
   meaning, ownership and lifetime, concurrency, call frequency, error
   behavior, allocation bounds, calling convention, and platform differences.
5. Classify the change and choose the version action using only the configured
   policy. When the policy does not cover the change, stop and ask for a
   release decision rather than inventing one.
6. Report a breaking classification and its consumers before changing a major
   version. A check or update command in configuration does not itself
   authorize a release-level decision.
7. After an approved version change, run the configured update commands. Review
   every baseline and generated-artifact diff; never hand-edit generated ABI
   artifacts. Run the check commands again, followed by the configured build or
   test commands.

## Invariants

- The project-owned ABI policy is authoritative.
- A passing structural checker does not prove semantic compatibility.
- Never update a baseline merely to silence an unexplained difference.
- Preserve old entry points or layouts when the project's extension mechanism
  can express the change additively.
- Do not assume semantic versioning, a C ABI, or a particular major/minor rule
  unless the configuration and policy select it.
