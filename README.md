# Agent skills

Reusable workflows for coding agents. Each skill discovers the target project
and its tools at runtime. Project-specific instructions and plans do not belong
in this repository.

## Included skills

- `clang-tidy-diff`, `clang-tidy-all`, and `clang-tidy-report`
- `guidelines-check-diff`, `guidelines-check-all`, and
  `guidelines-check-report`
- `guidelines-clear`
- `project-architecture-setup`
- `architecture-visualization`
- `abi-compatibility`

## Use in another project

Add this repository to the project and expose it at Codex's repository skill
discovery path:

```sh
git submodule add https://github.com/Fe0437/AgentSkills.git skills
mkdir -p .agents
ln -s ../skills .agents/skills
```

Keep the consuming project's `AGENTS.md`, plans, architecture rules, and local
skill configuration in that project. Commit the `.agents/skills` link; it is
public discovery metadata. Keep private project material somewhere else.

## Submodules and third-party code

Every skill treats the project's git submodules as part of the project, recursively: a diff
includes the files changed inside a changed submodule, and a whole-project scan walks into every
submodule. One run from the outermost repository covers them all.

Code the project does not own is skipped. Directories named `external`, `third_party`,
`vendor` or `_deps` are skipped everywhere; anything else is listed by the project in
`.agent-skills.json` at its repository root, which every skill reads:

```json
{
  "third_party_paths": ["apps/viewer/dependencies/sdl"]
}
```

## Licence and contributions

This repository uses MPL-2.0. Preserve the licence and attribution notices in
modified or redistributed files. Commit messages use the gitmoji convention.
