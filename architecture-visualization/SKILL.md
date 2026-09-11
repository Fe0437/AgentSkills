---
name: architecture-visualization
description: Maintain or regenerate a project's architecture diagrams and interactive package views from a project-owned visualization configuration. Use when packages, dependency boundaries, architecture source data, diagrams, or generated architecture views change.
---

# Architecture visualization

Keep architecture source data, generated views, and the physical repository
aligned without embedding one project's paths or commands in this skill.

## Find the project configuration

From the repository root, look for the first existing file in this order:

1. `.private/architecture-visualization.json`
2. `docs/architecture/visualization.json`
3. `.architecture-visualization.json`

Read [references/configuration.md](references/configuration.md) before creating
or changing that file. The configuration belongs to the consuming project, not
to this skill.

If no configuration exists, ask the user for the canonical architecture input
and the commands that generate and check its views. Do not guess these values
or copy another project's topology. Once agreed, offer to record them in one of
the locations above.

## Workflow

1. Read repository instructions and the discovered configuration. Resolve all
   paths relative to the repository root and reject paths that escape it.
2. Inspect the canonical input and the physical/build package boundaries it
   describes. Preserve the project's vocabulary and dependency rules.
3. Edit the configured canonical input. Never hand-edit a configured generated
   output.
4. If the configuration selects `onion-package-graph-v1`, read
   [references/package-graph-schema.md](references/package-graph-schema.md)
   when changing schema concepts or dependency semantics.
5. Run the configured generation and check commands exactly as argument lists.
   A command in project configuration does not grant permission for network,
   publishing, destructive, or otherwise unauthorized actions.
6. When interactive checks are configured and visual inspection is useful,
   open the generated view and verify those behaviors. Run the configured
   render command only when the task needs rendered documentation.
7. Run the project's normal build or smoke gate when package paths, targets, or
   build dependencies changed.

## Invariants

- The configured canonical input is the source of truth.
- Every configured generated output is reproducible from that input.
- Dependency direction and package status follow the consuming project's
  architecture, not assumptions in this skill.
- A visualization must not invent packages or dependencies to improve layout.
- Standalone output must not require a network or external runtime unless the
  project configuration explicitly documents that requirement.
