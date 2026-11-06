# ClaimTrace workflow model

ClaimTrace connects a molecular figure's claim to its saved view, supporting
observations, source files and interpretation limits. These records travel
together in a review package. The original molecular viewer renders the scene
and provides the replay check.

## Records and relationships

A package contains scenes, figures, and claims. A claim can link to several
scenes, and several claims can use the same scene. Evidence and limitations
retain explicit claim links. Selecting a claim restores its scene context;
browsing another scene changes the inspection target while preserving those
links.

| Record | Contents | Related records |
| --- | --- | --- |
| Claim | Statement, figure label, interpretation type | Scenes, evidence, limitations |
| Scene | Native file, figure, selections, saved view | Structures, operations, visual meanings |
| Evidence | Observation, method, parameters, source files | Claims, selections, entities |
| Limitation | Assumption, uncertainty, alternative interpretation | Claims or evidence |
| Package | File inventory, software and reuse details | All records and export checks |

## Workspaces

| Workspace | Task | Result |
| --- | --- | --- |
| Prepare | Write the claim, connect supporting observations and limitations, and answer the remaining questions | Saved draft or confirmed records |
| Review | Follow claim → visual evidence → provenance → uncertainty → reproducibility and open linked sources | A claim audit with traceable sources |
| Export | Choose a purpose, complete its required checks, and download the package or summary | A portable record for the recipient |

The workspaces can be revisited in any order. A package can begin with a
scene, image, structure, or results table and receive additional files later.
**Save draft** preserves partial claims and evidence for continued authoring.

**Basic** presents the figure, concise questions, and linked records.
**Expert** adds native operations, source locations, unresolved observations,
validation findings, and structured editing in the same selected context.

## Status meanings

| Status | Meaning |
| --- | --- |
| Saved locally | The current edits have been written to the local package |
| Author confirmed | The author has confirmed the entered interpretation |
| Recorded | The audit stage has the expected linked information |
| Checks passed | The package satisfies the selected validation purpose |
| Replay pending | Runtime verification in the molecular viewer remains open |

Open authoring questions remain visible alongside a passing package check.
Scientific interpretation follows review of the linked evidence. Runtime
replay is recorded separately from the presence of a saved scene or camera.

## GUI and CLI

Both interfaces use the same package and workflow questions. `init` creates
the package; `prepare` opens guided terminal editing; `gui` opens the same
record in the browser. Bare `complete` also opens the terminal guide, while
`complete --gui` opens the browser. `inspect` summarizes the materials and
remaining questions; `review` presents the five-part audit; `export` builds
the deliverable.

Review and export use the saved package purpose, initially Working draft.
An explicit `--mode` overrides the purpose for that command. `validate`
defaults to `draft` and accepts `--mode` for another purpose. Expert review,
`inspect --details` and YAML completion support detailed inspection and
automation.

See the [GUI workflow](gui.md) and [terminal walkthrough](cli.md) for guided
examples, and the [command reference](../README.md#command-and-file-reference)
for entry points and the package layout.
