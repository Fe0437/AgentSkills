# Boundary design

Use this reference when converting requirements into packages and dependency
directions.

## Boundary questions

A useful boundary has a reason to change independently. Ask:

- Can its responsibility be stated without joining unrelated jobs with “and”?
- Do its data, behavior and lifecycle change under the same invariant?
- Does separation remove a volatile dependency or create an independently
  useful/testable contract?
- Is the dependency direction from policy/composition toward stable concepts?
- Does a generic option bag, backend-only field, mode flag or nullable argument
  reveal that implementation policy leaked inward?
- Is the abstraction supported by a real replaceable boundary, multiple
  participants, or a concrete testing/lifecycle need?

Keep cohesive implementation helpers private. Moving lines or creating one
folder per noun is not modularity.

## Separate independent axes

Do not collapse concepts that vary independently. Common examples:

- representation vs construction history vs authority/provenance;
- authored graph vs compiled plan vs execution runtime;
- domain identity vs persistence key vs external-system handle;
- input capture vs tool behavior vs rendering backend;
- authoritative storage vs metadata catalog vs derived cache;
- foreground intent vs background optimization.

Name each axis in the project’s vocabulary.

## Dependency rules

- Domain/stable packages own contracts that describe their needs.
- Application workflows orchestrate stable contracts.
- Infrastructure implements contracts and depends inward.
- A composition root selects concrete implementations.
- External framework/runtime inspection stays at a documented interop edge.
- Reusable subprojects do not depend on application-specific policy.

These are heuristics, not a mandatory layering scheme. A plugin, compiler,
embedded system, data pipeline or monolith may need a different topology; keep
the same focus on volatility, ownership and dependency direction.

## Structural placeholders

Use a placeholder only for an agreed package needed to make the architecture
visible before implementation. Prefer, in order:

1. native workspace/build metadata with no sources;
2. a concise package-level description;
3. a tracked placeholder file when the VCS cannot retain an empty directory.

Do not create empty public classes, fake service methods, speculative schemas or
third-party bindings solely to demonstrate a future boundary.

