# Architecture deliverables

Scale these artifacts to the repository. Do not create all of them when one
short document is enough.

## Source of truth

Maintain one architecture document that answers:

- system purpose and non-goals;
- architectural style actually chosen;
- layers/subsystems and dependency direction;
- key independent axes and data/control flows;
- external systems and composition roots;
- realtime/security/reliability constraints when relevant;
- external dependency policy;
- verification strategy;
- links to maintained detailed views.

## Physical package map

List every agreed package/build target with:

- canonical name and path;
- responsibility;
- permitted inward dependencies;
- status: implemented, structural or future;
- owning composition/deployment unit when relevant.

Reconcile this list with native build metadata. A machine-checkable manifest is
useful when inexpensive, but the build system should remain authoritative.

## Diagrams

Prefer separate small maintained views for different questions:

- dependency/layer view;
- runtime or event sequence;
- data/representation conversion;
- deployment/external systems;
- ownership or state lifecycle.

Use the project’s existing diagram format. Text diagrams are acceptable when no
diagram tool is established. Every diagram must agree with the package map.

## Agent/developer guidance

Add only project-specific rules that change decisions: dependency direction,
forbidden package categories, external-code policy, naming/style source, and
required verification. Do not duplicate generic agent policy or the full
architecture document.

## Completion evidence

A structure handoff should distinguish:

- what was materialized;
- what remains deliberately interface-only or placeholder-only;
- which dependencies were not introduced;
- which gates passed;
- which decisions are deferred to planning.

