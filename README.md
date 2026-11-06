# ClaimTrace

Connect a molecular figure statement to its scene, evidence, sources and
limitations. Review the links, record the settings needed to reproduce the
view, and share a package that another reader can inspect.

Start with the files you have: a PyMOL `.pml`, ChimeraX `.cxc`, MolViewSpec
`.mvsj` or `.mvsx` scene, a figure image, a structure, or a results table.
Add the remaining files and scientific context as your work develops.
ClaimTrace preserves scene files and their commands. Open them in the original
molecular viewer to check that they reproduce the view.

## Start here

| I want to… | Open this |
| --- | --- |
| Follow a tutorial | [Start here](https://github.com/GeraltZeroZhong/ClaimTrace/blob/v1.0/docs/tutorial/README.md) for a guided review with screenshots, input files and example answers. |
| Use the GUI | [Install and open ClaimTrace](docs/start.md), then try the first built-in example. |
| Use an agent | [Install the ClaimTrace skill](#install-the-agent-skill) with one command, then give the agent your package path and question. |

## Read the tutorials

Open [Start here](https://github.com/GeraltZeroZhong/ClaimTrace/blob/v1.0/docs/tutorial/README.md) to follow **Figure 1B1: Pocket
visibility** from source files to an exported draft. The tutorial and screenshots
display directly on GitHub. [Choose another case](https://github.com/GeraltZeroZhong/ClaimTrace/blob/v1.0/docs/tutorial/markdown/README.md)
to explore the 12 examples by task.

For offline reading, download this repository with **Code → Download ZIP**,
extract it, and open `docs/tutorial/index.html` in your browser. Keep the tutorial
folder together so its screenshots and downloads remain available. Reading the
tutorials requires only a browser.

## Install and open the GUI

ClaimTrace requires Python 3.10 or newer. Create an environment in a folder
of your choice and install the release from PyPI:

**Windows · PowerShell**

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install claimtrace==1.0
.\.venv\Scripts\python.exe -m claimtrace gui
```

**Linux, macOS or WSL · Bash**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install claimtrace==1.0
.venv/bin/python -m claimtrace gui
```

For a source checkout, run the commands from the folder containing
`pyproject.toml` and replace `pip install claimtrace==1.0` with `pip install .`.

A browser opens at `http://127.0.0.1:8765`. Keep the terminal open while using
ClaimTrace. If the browser stays closed, open the address printed in the terminal.
Choose **Try an example → Start first example** for a guided introduction, or
**Choose files** to begin with your own figure.

**Prepare → Review → Export** takes one figure statement through its evidence,
limitations and reproducibility record. **Basic** shows the essential questions;
**Expert** adds source records and analysis details. Packages save locally under
`claimtrace-workspace/` in the launch folder. Stop the server with Ctrl+C and
return later using **Open package**.

The [setup guide](docs/start.md) covers reopening the GUI, free ports, Windows/WSL
paths and installation help. The [GUI guide](docs/gui.md) explains the forms and
review workflow.

## Install the agent skill

After [installing ClaimTrace](docs/start.md#install-claimtrace), open a terminal
in the folder where you created `.venv`. Run **one command for your
system** to install the bundled skill for Codex:

If **claimtrace** already appears in Codex's skill picker, continue to the
example below.

**Windows · PowerShell**

```powershell
.\.venv\Scripts\python.exe -m claimtrace skill --out "$HOME\.agents\skills\claimtrace"
```

**Linux, macOS or WSL · Bash**

```bash
.venv/bin/python -m claimtrace skill --out "$HOME/.agents/skills/claimtrace"
```

**Check:** The command prints `Skill saved:` followed by the installed
`SKILL.md` path. It copies the complete skill and its reference files into
your user skills folder. With WSL, run ClaimTrace and Codex in the same WSL
environment.

Open Codex's skill picker and select **claimtrace**. In the CLI or IDE extension,
type `$` or run `/skills` to find it. Restart Codex if it has yet to appear.

Open your working folder in Codex and try:

```text
$claimtrace Inspect the package at "<absolute package folder path>".
Keep the package unchanged. Summarize the claim, visual evidence, provenance,
uncertainty and reproducibility status. Use ClaimTrace from this folder's
.venv environment.
```

Replace the placeholder with your package folder. For changes, ask the agent to
save a proposal. In the GUI, **Agent suggestions** lets you inspect its sources
and accept, edit, reject or revert a suggestion.

The [agent guide](docs/agents.md) covers installation help, other compatible
clients and reviewing proposals.

## Use the terminal

After [activating your environment](docs/start.md#use-the-short-command), these
commands prepare, review and export the same package used by the GUI:

```bash
claimtrace init --file "figure_A.pml" --file "figure_A.png" --file "model.cif" --out "scene-package"
claimtrace prepare "scene-package"
claimtrace review "scene-package"
claimtrace export "scene-package" --out "scene-package.zip"
```

Repeat `--file` for each scene, image, structure or result. PML, CXC, MVSJ and MVSX
scenes are supported. Start with an image or table and add more context later.
Use [the terminal walkthrough](docs/cli.md) for example answers, or
[the synthetic examples](examples/README.md) for a small file-based exercise.

The commands below use the short `claimtrace` form. You can also append the same
arguments to `.venv/bin/python -m claimtrace` (Linux/macOS/WSL) or
`.\.venv\Scripts\python.exe -m claimtrace` (Windows), from the folder containing `.venv`.

## Scripted completion with `answers.yml`

The generated `answers.yml` connects imported scene records to author context.
Edit it in your text editor, preserving the generated operation and reference
IDs, then check and apply it:

```bash
claimtrace complete "scene-package" --check-answers "scene-package/answers.yml"
claimtrace complete "scene-package" --answers "scene-package/answers.yml"
claimtrace review "scene-package" --mode draft
```

Checking leaves the package unchanged. Applying saves the corresponding
records. Keep `evidence: []` while gathering evidence, and add observations as
their sources become available.

### Main fields

| Field | What to record |
| --- | --- |
| `claim.claim_text` | The main statement conveyed by the figure or panel |
| `claim.figure_ref` | The manuscript, slide, or panel label |
| `evidence[].method_name` | How a linked result, measurement, validation, or review was produced |
| `evidence[].result_summary` | What the attached result shows and how it supports the claim |
| `uncertainty[].statement` | A useful caveat, limitation, or alternative explanation |
| `reuse.license` / `reuse.citation` | Source, license, and citation information when known |

Use a draft while the supporting files and review notes are being assembled.

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
operation. Keep them unchanged. Use
`claimtrace inspect "scene-package" --details` to see the original command
and source line or JSON Pointer when you need more context.

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
| A distance or measurement command | The measured value, method, units and interpretation; the cutoff when one was used |
| A render or output path | Evidence that the attached pixels came from this scene and data |

`Recognized` means that a command or node was found in the file. After replaying
a scene, attach a render, log, or environment note when that behavior matters
to the review.

Dynamic content, macros, and commands requiring runtime context stay
visible for author review. MolViewSpec files are read as structured
JSON or as inventoried archives. ClaimTrace checks common required parameters
and parent relationships for recognized MolViewSpec nodes. For full schema
validation, use official MolViewSpec tooling.

The automatic question set follows the scene content. Ligands shown with
pocket, binding-site, contact or measurement context prompt binding-pose
questions. Use `--template` to choose a question set explicitly.

### Scientific details worth including

Use this table as a starting point and add details required by your method.

| Figure content | Context to include |
| --- | --- |
| Ligand or binding pose | Ligand and model identity; chain, residue, atom, or selection definition; pose source; contact or distance method, cutoff, and units; relevant protonation, alternate-location, density, docking, or validation caveats |
| Trajectory or MD-derived view | Topology and trajectory identity; software and version; force field; sampling length and replicas; equilibration and frame-selection rule; analysis definition and uncertainty |
| Density or potential map | Map identity and type; reconstruction or calculation source; resolution where relevant; contour level and units; fitted model; map-model or method-specific validation |
| Computed model | Method and version; input, source, or model identifier; confidence and uncertainty measures; relevant validation; wording that distinguishes prediction from experiment |
| Model comparison | Both source models; alignment or comparison method; selection definition; metric and units; linked result supporting the comparison |

Measurement commands record the intended operation. Add the measured value,
method, units and interpretation, including any cutoff used. A color ramp over a generic
numeric field also needs context, such as whether an atom `b` field represents
crystallographic B-factors, AlphaFold pLDDT, or another imported quantity.

Archive validation checks package completeness and traceability. Review its
warnings, waivers and linked evidence when assessing the scientific claim.

## Replay and review

### Replay an original scene

Exported packages keep the original scene under `native/`. Start the viewer in
that directory when the scene uses relative paths.

| Format | Replay guidance |
| --- | --- |
| `.pml` | Start PyMOL in `scene-package/native/` so relative `load` paths resolve |
| `.cxc` | Start ChimeraX in the same directory so relative `open` paths resolve |
| `.mvsj` | Open it in a Mol* viewer with MolViewSpec support and make its referenced resources accessible to that viewer |
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

For browser-based `.mvsj` replay, serve referenced files from accessible URLs
or bundle them in a standard `.mvsx` archive.

A standard `.mvsx` contains a top-level `index.mvsj`. If an archive contains
exactly one differently named or nested `.mvsj`, ClaimTrace can still read it
for static review, but reports that it must be rebuilt before standard MVSX
replay. A referenced file that is missing from the archive must be added at the
path used by `index.mvsj` inside the archive.

An MVSX file is already a viewer archive. A ClaimTrace package adds the figure
claim, author explanations, supporting files, validation report, and package
checksums around that viewer archive.

Attach PyMOL `.pse` sessions with `--artifact` alongside a PML scene or figure
image. Use `.pml`, `.cxc`, `.mvsj` or `.mvsx` for the native scene input.

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
Set-Location "C:\work\figure-project"
claimtrace init ".\figure_A.mvsj"
```

### WSL Bash

```bash
cd "/mnt/c/work/figure-project"
claimtrace init "./figure_A.mvsj"
```

Replace `.mvsj` with `.pml`, `.cxc`, or `.mvsx` in either example. Inside WSL,
translate `C:\work\...` to `/mnt/c/work/...`. Paths stored in a package are
package-relative, avoiding machine-specific absolute paths in the exported package.

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
| `claimtrace init --file <file> --out <package>` | Create a draft from scenes, images and supporting files; repeat `--file` for multiple inputs |
| `claimtrace gui [package]` | Open the local Prepare, Review, and Export workspace |
| `claimtrace inspect <package>` | Summarize materials and pending preparation questions |
| `claimtrace inspect <package> --details` | Inspect source operations, resources, and file inventory |
| `claimtrace prepare <package>` | Prepare a claim, evidence, limitations and scene details in the terminal |
| `claimtrace prepare <package> --expert` | Show detailed records while preparing the package |
| `claimtrace complete <package>` | Open the same terminal guide |
| `claimtrace review <package>` | Read the five-part audit for the saved purpose |
| `claimtrace review <package> --expert` | Show record IDs and all remaining questions |
| `claimtrace examples` | List the shared synthetic practice cases |
| `claimtrace prepare --example <id>` | Start a guided practice package |
| `claimtrace complete ... --check-answers ...` | Check an edited answers file without changing the package |
| `claimtrace complete ... --answers ...` | Apply author context to the semantic layer |
| `claimtrace add-artifact ...` | Add a supporting file later |
| `claimtrace validate ...` | Check a draft, handoff, share package, or archive |
| `claimtrace export ...` | Validate and write a directory or zip |
| `claimtrace agent ...` | Inspect JSON records, check and save proposals, or record a human review decision |
| `claimtrace skill [--out <folder>]` | Locate the bundled agent skill or copy it into a new folder |
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
  claimtrace-export.json     # identifies a completed ClaimTrace export
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
| A PyMOL or ChimeraX scene has a text-encoding error | Re-save the script as UTF-8 (a UTF-8 BOM is accepted) and rerun `init` |
| An item needs author review | Run `claimtrace prepare "scene-package"` and choose the matching detail, or update the corresponding `answers.yml` entry |
| Answer checking lists remaining fields | Keep editing the same file and rerun `--check-answers`; the package changes only after you use `--answers` |
| An MVSX member is missing | Rebuild the `.mvsx` with the file inside the archive at the path used by `index.mvsj` |
| ClaimTrace reports a nonstandard MVSX entry | Move or rename the intended scene to top-level `index.mvsj` before viewer replay |
| Archive validation reports required items | Complete the listed items, or export in draft mode while gathering the remaining context |
| An operation ID is unknown | Keep the edited file. Generate `answers.new.yml` for comparison with `claimtrace complete "scene-package" --emit-template > "scene-package/answers.new.yml"` |

Useful help commands:

```bash
claimtrace --help
claimtrace quickstart
claimtrace init --help
claimtrace prepare --help
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

The `native` argument accepts `.pml`, `.cxc`, `.mvsj` or `.mvsx`. The Python
functions and `claimtrace.api` expose the package operations used by the GUI
and terminal guide.

### Development

```bash
python -m pip install -e '.[dev]'
python -m pytest
python -m build
python -m twine check dist/*
```

## License

ClaimTrace software is released under the MIT License. See `LICENSE` for the
full text. Tutorial data and figures retain their source-specific attribution
and reuse terms; see the [tutorial sources](https://github.com/GeraltZeroZhong/ClaimTrace/blob/v1.0/docs/tutorial/SOURCES.md).

## Version and citation

Read the [1.0 release notes](docs/releases/1.0.md) for downloads and upgrade
steps, and [Interface contracts](docs/interfaces.md) for stable API, CLI and
agent behavior. [Development](docs/development.md) covers testing and local builds.
Use [CITATION.cff](CITATION.cff) to cite the software.
