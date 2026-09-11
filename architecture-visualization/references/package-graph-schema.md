# Package graph schema

The source document has four top-level concepts:

- `rings`: dependency distance from the core. `order` increases outward.
- `families`: role-based groupings placed in one ring, with color, base path,
  summary, optional defaults, and packages.
- `packages`: stable package IDs with path/target/status and dependency IDs.
- `slices`: optional named cross-layer views exposed as viewer filters.
- `slices`: optional family/package membership in any number of declared slices.
- `schemaVersion`: increment only when the generator input shape changes.

Each family provides:

```json
{
  "id": "scene_usd",
  "label": "Scene · OpenUSD",
  "ring": "outer",
  "color": "#22c55e",
  "basePath": "src/infrastructure/scene/usd",
  "status": "structural",
  "summary": "Shared scene and interchange infrastructure.",
  "defaultDependsOn": ["core.geometry.discrete"],
  "packages": []
}
```

Each package provides:

```json
{
  "id": "scene.usd.stage_sync",
  "label": "stage_sync",
  "path": "stage_sync",
  "target": "FlexibleDrawing::SceneUsdStageSync",
  "status": "structural",
  "summary": "Incremental model to UsdStage synchronization.",
  "dependsOn": ["use_cases.export"]
}
```

`path` is relative to the family `basePath`. Use `plannedPath` instead for a
future package or external registry identity that does not exist physically.
Valid status values are `implemented`, `structural`, and `future`.

Family `defaultDependsOn` values are added to every package in that family.
Package `dependsOn` adds package-specific edges. Dependencies point toward the
package being used.

A family or package may set `"slices": ["graph", "geometry-authoring"]` when
those IDs are declared in the top-level `slices` list. Family memberships are
inherited and combined with package memberships. Slices never reserve diagram
area or alter package placement. They appear as a separate,
inactive-by-default filter row; selecting one highlights its packages across
the existing rings. A package can participate in multiple end-to-end flows
while retaining the dependency rules of its physical `core`, `application`, or
`outer` layer.

The generator validates unique IDs, statuses, known rings/families/dependencies,
filesystem paths, dependency direction, cycles, and the visual capacity of each
Onion ring before writing any output.
The generator also computes the exact package-card positions and performs an
oriented-rectangle collision test. The generated viewer consumes those
validated positions rather than calculating an unchecked browser-only layout.
