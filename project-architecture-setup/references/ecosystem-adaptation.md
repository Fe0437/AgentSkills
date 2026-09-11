# Ecosystem adaptation

Read only the section matching the repository under work. Preserve mixed or
custom systems when inventory shows they are intentional.

## CMake / C / C++

Express packages as targets and dependency direction with
`target_link_libraries`; avoid directory-global include/link state. Module or
header files belong to the target that owns the contract. An interface target
can represent an agreed structure-only boundary. Use configure-time target
checks when a maintained package manifest must be enforced.

Do not add a dependency through `FetchContent`, submodule or package manager
until requested. Preserve the selected compiler/language standard and existing
warning/sanitizer policy.

## Rust / Cargo

Use workspace crates only for independent contracts/lifecycles. Keep feature
flags local to the crate owning optional behavior. Avoid a universal `common`
crate; dependency inversion can use small traits in the stable consuming crate.
Verify with workspace metadata, `cargo check` and existing tests/lints.

## JavaScript / TypeScript

Respect the existing npm/pnpm/yarn/bun workspace. Packages should expose narrow
entry points and avoid deep imports across boundaries. Use project references,
workspace dependency declarations or lint rules already present rather than a
second bespoke dependency graph.

## Python

Follow the current `pyproject.toml`/workspace convention. A package boundary is
valuable when it separates ownership, deployment, optional dependencies or a
stable protocol—not just to shorten modules. Keep optional framework imports at
their integration edge. Verify importability, type checks and tests already
configured by the project.

## Go

Prefer packages organized around cohesive capabilities. Use `internal/` for
implementation boundaries and introduce another module only for a real release
or ownership boundary. Avoid generic `util` packages. Verify with the existing
module/workspace tooling and tests.

## Swift / SwiftPM

Use targets for dependency direction and products only for public distribution
boundaries. Keep Apple-framework code in platform integration targets when the
domain is intended to remain portable.

## JVM / Gradle / Maven

Use modules/subprojects for ownership, deployment or dependency isolation.
Keep framework plugins and generated code in the module that owns them. Enforce
direction through native project dependencies and existing architecture-test
facilities when present.

## Other or mixed repositories

Map the project’s native unit of composition first: Bazel target, Meson target,
package, service, plugin, firmware image, notebook environment or deployment
unit. If no build metadata exists, document the matrix before introducing a
tool; do not select a build system merely because this skill needs enforcement.

