# ClaimTrace

Turn a molecular-viewer scene into a clear, self-contained review package.

Give ClaimTrace one PyMOL `.pml`, ChimeraX `.cxc`, MolViewSpec `.mvsj`, or
MolViewSpec `.mvsx` file. It creates an ordinary folder that preserves the
original scene, lists what the scene contains and references, and gives you an
editable checklist for recording the figure's message.

One scene file is enough to start. You can add a rendered panel, structure,
map, table, or supporting result later. ClaimTrace reads scene files locally; it
does not launch the molecular viewer, run scene commands, or download remote
resources.

## Quick start: create a draft

### 1. Install ClaimTrace

ClaimTrace requires Python 3.10 or newer. Install it from PyPI:

```bash
python -m pip install claimtrace
claimtrace --version
```

This works in Bash and PowerShell. A virtual environment is optional, but
useful if you want to keep ClaimTrace separate from other Python tools.

### 2. Create a package

Open a terminal in the folder containing your scene, then run `claimtrace init`.
For example:

```bash
claimtrace init "figure_A.pml"
```

Use the same command with any supported scene format:

```bash
claimtrace init "figure_A.cxc"
claimtrace init "figure_A.mvsj"
claimtrace init "figure_A.mvsx"
```

ClaimTrace creates `scene-package/`, copies the original scene, records the
content it can recognize, and writes an `answers.yml` tailored to that scene.
The terminal prints the paths it created and the next commands to run.

| Scene format | What ClaimTrace records |
| --- | --- |
| PyMOL `.pml` | Commands, selections, visual operations, camera state, and referenced files |
| ChimeraX `.cxc` | Common commands, model and selection references, camera and visibility intent, and local or database resources |
| MolViewSpec `.mvsj` | Scene nodes, snapshots, parameters, resources, metadata, and exact JSON locations |
| MolViewSpec `.mvsx` | Scene entry, archive members, checksums, embedded resources, snapshots, and scene operations |

### 3. See what ClaimTrace found

```bash
claimtrace inspect "scene-package"
```

The report shows the files in the package, recognized scene operations,
referenced resources, and the first questions that still need your input. A
command or node that ClaimTrace cannot confidently interpret is preserved with
its source file and line number or JSON Pointer, so it can still be reviewed.

### 4. Describe the figure

Open `scene-package/answers.yml` in a text editor. Start by replacing the two
claim placeholders:

```yaml
claim:
  claim_text: Figure 1A shows the highlighted region in the molecular structure.
  figure_ref: Figure 1A
```

Keep the generated `claim_type`, operation IDs, and reference IDs unchanged.
If you only have the scene file and no supporting evidence yet, use:

```yaml
evidence: []
```

If the generated file contains review entries for colors or labels, follow the
`review_instruction` beside each one. The next section explains the available
choices.

Now check the file:

```bash
claimtrace complete "scene-package" --check-answers "scene-package/answers.yml"
```

This command does not modify the package. It tells you what this particular
scene still needs. Edit the same file and rerun the check until the required
items are resolved, then apply it:

```bash
claimtrace complete "scene-package" --answers "scene-package/answers.yml"
claimtrace validate "scene-package" --mode draft --format text
```

You now have a usable draft. It can stay in draft mode while you gather the
final render, source model, or supporting analysis. The rest of this README is
reference material for completing, replaying, or sharing the package.

## Complete `answers.yml`

`answers.yml` connects what ClaimTrace found in the scene with what you intend
the figure to communicate.

### Main fields

| Field | What to record |
| --- | --- |
| `claim.claim_text` | The main statement conveyed by the figure or panel |
| `claim.figure_ref` | The manuscript, slide, or panel label |
| `evidence[].method_name` | How a linked result, measurement, validation, or review was produced |
| `evidence[].result_summary` | What the attached result shows and how it supports the claim |
| `uncertainty[].statement` | A useful caveat, limitation, or alternative explanation |
| `reuse.license` / `reuse.citation` | Source, license, and citation information when known |

You do not need to invent evidence to create a draft. Keep `evidence: []` until
you have a supporting file or a review note you can describe accurately.

### Review colors, labels, and other visual meanings

ClaimTrace adds a `scene_semantics_by_operation` entry when a color, label, or
other visual choice may carry scientific meaning. Choose the description that
matches the figure:

- Use `user_confirmed_meaning` when the visual choice communicates part of the
  panel's message.
- Use `user_declared_no_scientific_meaning` when it is only for contrast or
  readability.
- Use `claim_critical: false` when the operation is unrelated to the claim.

For example:

```yaml
scene_semantics_by_operation:
  - operation_ids: [op:...]
    meaning_status: user_confirmed_meaning
    meaning: Magenta marks the ligand discussed in this panel.
    claim_critical: true
```

Generated IDs such as `op:...` connect your answer to a specific scene
operation. Keep them unchanged. `claimtrace inspect "scene-package"` shows the
original command and source line or JSON Pointer when you need more context.

## Add files and share the package

### Include the files you already have

You can add a scene, rendered panel, structure, and supporting result in one
command. Replace the `.pml` path with any supported scene format:

```bash
claimtrace init --native "figure_A.pml" --image "figure_A.png" --artifact "model.cif" --artifact "contacts.csv" --out "scene-package"
```

Repeat `--native`, `--image`, or `--artifact` when a panel uses multiple files.
Add files that arrive later without recreating the package:

```bash
claimtrace add-artifact "scene-package" "contacts.csv" --role contact_table
```

Common roles include `structure`, `map`, `trajectory`, `topology`,
`contact_table`, `validation_report`, and `evidence_document`.

### Check whether the package is ready to share

Archive validation checks the files and context relevant to the claim: source
data, final render, camera or view state, scene resources, linked evidence, and
author-reviewed visual meanings.

```bash
claimtrace validate "scene-package" --mode archive --format text
```

Treat the output as a to-do list. Once it passes, export a directory or zip:

```bash
claimtrace export "scene-package" --mode archive --out "scene-package.zip"
```

Validation modes let the package grow with your work:

| Mode | Best used for |
| --- | --- |
| `draft` | Writing the claim while files and answers are still arriving |
| `internal` | A lab or project handoff |
| `share` | Sending the package to a collaborator or reviewer |
| `archive` | Creating a durable, self-contained directory or zip |

## Understand what ClaimTrace records

### Scene observations and replay evidence

ClaimTrace separates what is present in the scene file from what you confirm by
running the viewer or reviewing the underlying analysis.

| ClaimTrace can read from the scene | Add when available |
| --- | --- |
| A reference to `model.cif` or another resource | A successful replay, render, or viewer log |
| A native selection or selector | Confirmation that the selection is valid and non-empty |
| Representation, color, label, or camera commands | The final panel and viewer or environment details |
| A distance or measurement command | The measured value, method, cutoff, units, and interpretation |
| A render or output path | Evidence that the attached pixels came from this scene and data |

`Recognized` means that a command or node was found in the file. After replaying
a scene, attach a render, log, or environment note when that behavior matters
to the review.

Dynamic content, macros, and commands that cannot be interpreted reliably stay
visible as items for author review. MolViewSpec files are read as structured
JSON or as inventoried archives. ClaimTrace checks common required parameters
and parent relationships for recognized MolViewSpec nodes. For full schema
validation, use official MolViewSpec tooling. Uncertain content stays visible
for review.

The automatic question set follows the scene content. A displayed ligand alone
does not trigger binding-pose questions; pocket, binding-site, contact, or
measurement context is also required. Use `--template` to choose a question set
explicitly.

### Scientific details worth including

Use this table as a starting point and add details required by your method.

| Figure content | Context to include |
| --- | --- |
| Ligand or binding pose | Ligand and model identity; chain, residue, atom, or selection definition; pose source; contact or distance method, cutoff, and units; relevant protonation, alternate-location, density, docking, or validation caveats |
| Trajectory or MD-derived view | Topology and trajectory identity; software and version; force field; sampling length and replicas; equilibration and frame-selection rule; analysis definition and uncertainty |
| Density or potential map | Map identity and type; reconstruction or calculation source; resolution where relevant; contour level and units; fitted model; map-model or method-specific validation |
| Computed model | Method and version; input, source, or model identifier; confidence and uncertainty measures; relevant validation; wording that distinguishes prediction from experiment |
| Model comparison | Both source models; alignment or comparison method; selection definition; metric and units; linked result supporting the comparison |

Measurement operations are recorded as intent until you supply the measured
value, method, cutoff, units, and interpretation. A color ramp over a generic
numeric field also needs context, such as whether an atom `b` field represents
crystallographic B-factors, AlphaFold pLDDT, or another imported quantity.

Passing archive validation confirms package completeness, traceability, and
required author review. Readers can then evaluate the linked scientific
evidence directly.

## Replay and review

### Replay an original scene

Exported packages keep the original scene under `native/`. Start the viewer in
that directory when the scene uses relative paths.

| Format | Replay guidance |
| --- | --- |
| `.pml` | Start PyMOL in `scene-package/native/` so relative `load` paths resolve |
| `.cxc` | Start ChimeraX in the same directory so relative `open` paths resolve |
| `.mvsj` | Open it in a Mol* viewer with MolViewSpec support; a browser may not expose adjacent local files |
| `.mvsx` | Open the archive directly; embedded relative resources remain inside it |

For example:

```bash
cd "scene-package/native"
pymol "figure_A.pml"
```

Or, from the same directory:

```bash
chimerax "figure_A.cxc"
```

A local `.mvsj` opened in a browser cannot always access adjacent files. Serve
the files from URLs or build a standard `.mvsx` when those resources need to
travel together.

A standard `.mvsx` contains a top-level `index.mvsj`. If an archive contains
exactly one differently named or nested `.mvsj`, ClaimTrace can still read it
for static review, but reports that it must be rebuilt before standard MVSX
replay. A referenced file that is missing from the archive must be added at the
path used by `index.mvsj`; placing a sibling file outside the archive does not
make it self-contained.

An MVSX file is already a viewer archive. A ClaimTrace package adds the figure
claim, author explanations, supporting files, validation report, and package
checksums around that viewer archive.

PyMOL `.pse` sessions can be attached as additional evidence, but they are not
one of the four scene formats accepted by `claimtrace init <scene-file>`.

### Review a package you received

1. Extract the zip and open its generated `README.md`.
2. Read the claim, evidence, caveats, visual meanings, and open items.
3. Open the panel in `renders/` and replay the scene when a viewer is available.
4. Use `checksums/sha256.txt` or `claimtrace validate` to check file integrity.

`semantic_layer.json` is the complete machine-readable record for deeper
inspection or downstream tooling.

## Windows, PowerShell, and WSL

Native Windows PowerShell and WSL use different path syntax and usually
different Python environments. Install and run ClaimTrace in the environment
whose paths you are using.

### Native Windows PowerShell

```powershell
Set-Location "C:\Users\YourName\Documents\review-visualization"
claimtrace init ".\figure_A.mvsj"
```

### WSL Bash

```bash
cd "/mnt/c/Users/YourName/Documents/review-visualization"
claimtrace init "./figure_A.mvsj"
```

Replace `.mvsj` with `.pml`, `.cxc`, or `.mvsx` in either example. Inside WSL,
translate `C:\Users\...` to `/mnt/c/Users/...`. Paths stored in a package are
package-relative, so the exported package remains portable between platforms.

To extract and validate a zip in PowerShell:

```powershell
Expand-Archive -Path ".\scene-package.zip" -DestinationPath ".\scene-package-roundtrip"
claimtrace validate ".\scene-package-roundtrip" --mode archive --format text
```

On Linux or WSL, Python can perform the same extraction:

```bash
python -m zipfile -e "scene-package.zip" "scene-package-roundtrip"
claimtrace validate "scene-package-roundtrip" --mode archive --format text
```

## Command and file reference

### Main commands

| Command | Purpose |
| --- | --- |
| `claimtrace init <scene-file>` | Create a draft from `.pml`, `.cxc`, `.mvsj`, or `.mvsx` and write a tailored `answers.yml` |
| `claimtrace inspect <package>` | Show files, scene observations, references, and open questions |
| `claimtrace complete ... --check-answers ...` | Check an edited answers file without changing the package |
| `claimtrace complete ... --answers ...` | Apply author context to the semantic layer |
| `claimtrace add-artifact ...` | Add a supporting file later |
| `claimtrace validate ...` | Check a draft, handoff, share package, or archive |
| `claimtrace export ...` | Validate and write a directory or zip |
| `claimtrace quickstart` | Print the shortest copy-and-paste workflow |

Run `claimtrace <command> --help` for command-specific options.

### Package layout

```text
scene-package/
  answers.yml
  semantic_layer.json
  native/
  renders/
  data/
  evidence/
  semantic/
  checksums/                 # added during export
  schema/                    # added during export
  README.md                  # generated for the recipient
  validation_report.json     # added during export
```

`semantic_layer.json` is the canonical machine-readable manifest. Exported
packages add a reader-oriented README, schemas, validation report, and checksum
inventory.

## Troubleshooting

| What you see | What to try |
| --- | --- |
| `No matching distribution found for claimtrace` | Check the package name, network connection, Python version, and configured package index. From a source checkout, use `python -m pip install .` |
| `claimtrace: command not found` | Check the active environment with `python -m pip show claimtrace`, reopen the shell, or run `python -m claimtrace --help` |
| `Input file not found` | Check the current folder, quote paths containing spaces, and use the path syntax for your current shell |
| `Output directory already exists` | Choose another `--out` path. Use `--force` only when the target is an existing ClaimTrace package you intend to replace |
| A referenced local file is unresolved | Add the file with `claimtrace add-artifact`, or rerun `init` with `--artifact` |
| `Invalid MolViewSpec JSON` | Use the reported line and column, save the file as UTF-8 JSON, and rerun `init` |
| An item needs author review | Run `claimtrace inspect "scene-package"`, then record whether the item affects the figure in `answers.yml` |
| Answer checking lists remaining fields | Keep editing the same file and rerun `--check-answers`; the package changes only after you use `--answers` |
| An MVSX member is missing | Rebuild the `.mvsx` with the file at the path used by `index.mvsj`; an outside sibling cannot satisfy an archive member |
| ClaimTrace reports a nonstandard MVSX entry | Move or rename the intended scene to top-level `index.mvsj` before viewer replay |
| Archive validation is not ready | Start with the required items in the report; draft mode remains available while you complete them |
| An operation ID is unknown | Keep the edited file. Generate `answers.new.yml` for comparison with `claimtrace complete "scene-package" --emit-template > "scene-package/answers.new.yml"` |

Useful help commands:

```bash
claimtrace --help
claimtrace quickstart
claimtrace init --help
claimtrace complete --help
```

## Python API and development

### Python API

```python
from claimtrace import init_package, load_package, validate_package

pkg = init_package(
    native="figure_A.pml",
    image="figure_A.png",
    out="scene-package",
)
report = validate_package(pkg, mode="draft")
loaded = load_package("scene-package")
```

The `native` argument accepts `.pml`, `.cxc`, `.mvsj`, or `.mvsx`. The CLI is
the most guided route because it creates and explains `answers.yml`; the
top-level Python functions and `claimtrace.api` expose the same package
operations for scripts and integrations.

### Development

```bash
python -m pip install -e '.[dev]'
python -m pytest
python -m build
python -m twine check dist/*
```

## License

ClaimTrace is released under the MIT License. See `LICENSE` for the full text.
