# Prepare a figure review in the terminal

Record one figure statement with its source files, observations, settings and
limitations. The terminal follows the same **Prepare → Review →
Export** sequence as the graphical interface. Both work with the same package
folder.

Start with [installation](start.md#install-claimtrace), then
[activate the environment](start.md#use-the-short-command) for the `claimtrace`
commands below.

## Try a built-in example

```bash
claimtrace examples
claimtrace prepare --example highlight-residues --workspace "claimtrace-practice"
```

The three practice cases match the GUI: `highlight-residues`,
`ligand-contacts` and `compare-models`. Each supplies synthetic source files
and example answers. Use **Claim**, **Evidence** and **Limitation**, then
**Review** and **Export**. The guide prints the package folder for later use.

The file-based exercise below uses a fixed folder name and gives every entry
needed for its claim audit.

## Start with the example files

From the repository root, after installing ClaimTrace:

```bash
claimtrace init --file "examples/ligand-binding-pose/figure_A.pml" --file "examples/ligand-binding-pose/figure_A.png" --file "examples/ligand-binding-pose/model.cif" --file "examples/ligand-binding-pose/contacts.csv" --out "contact-review"
claimtrace prepare "contact-review"
```

The file example contains two synthetic atoms, a supplied 2.8 angstrom distance,
a scene script and a placeholder figure card. It teaches the review record and
its file links. Use a fresh output folder when repeating the example.

`--file` assigns each file a role from its type. Use `--native`, `--image` or
`--artifact` to assign the role yourself.

## Prepare the statement

The menu uses the same tasks as the GUI:

| Action | What you can do |
| --- | --- |
| Claim | Write or edit the figure statement and its scene links. |
| Evidence | Add or edit a source-linked observation. |
| Limitation | Record an assumption, interpretation limit or alternative. |
| Figure & scene details | Record the figure type, camera or view, and visibility context. |
| Review | Read the five-part audit. |
| Export | Choose the purpose and write the package. |
| Add files | Attach more source material. |
| Choose another claim | Work on another statement in this package. |
| More details | Identify molecules and residues, explain colors, inspect sources, or record software and reuse details. |
| Finish | Leave the guide and keep saved work. |

Choose **Claim**, enter one statement and select the imported scene. These
example answers describe the supplied files:

| Field | Example entry |
| --- | --- |
| Figure statement | Synthetic ligand atom LIG:O lies 2.8 angstrom from A:ALA10:CA. |
| Figure label | Example panel B |
| Statement type | Ligand binding pose |
| Linked scene | figure_A.pml |

Choose **Save claim** after checking the claim, or **Save draft** to keep a partial
entry. **Claim saved.** confirms the save, and the menu shows the current claim.

## Add the supporting observation

Choose **Evidence** and select the structure and contact table using their
listed numbers, separated by commas. Match the evidence type to the result
you are recording.

| Field | Example entry |
| --- | --- |
| Evidence type | Contact table |
| Source files | model.cif; contacts.csv |
| How was it checked? | Inspect the supplied synthetic coordinate rows and contact table. |
| What did you find? | The table records a 2.8 angstrom distance between LIG:O and A:ALA10:CA, within the declared 4.0 angstrom cutoff. |
| Contact distance cutoff | 4.0 |
| Distance unit | angstrom |
| Analysis settings (optional) | Atom pair: LIG:O and chain A ALA10 CA; contact rule: distance within 4.0 angstrom. |

For **Regions used in this check**, select the listed ligand and pocket
selections. Choose **Save evidence**.

**How was it checked?** names the inspection or analysis. **What did you find?**
records the result that supports this statement. Attribute supplied results to
their source, and record your own measurements after performing the check.

Choose **Limitation** and enter:

```text
This two-atom synthetic example describes proximity. Alternative poses and solvent context require additional evidence.
```

Choose **Alternative poses** as the limitation type. **Limitation saved.**
confirms the entry. The example now has one claim, one evidence record and one
limitation. **Figure & scene details** keeps any questions about the source
view available for further review.

## Save and resume

Choose **Finish** to leave the guide. Run the same command to continue:

```bash
claimtrace prepare "contact-review"
```

Completed saves remain in the package. Enter keeps a shown default; `~`
clears it. Enter `:back` to leave the current form unchanged. In Claim or
Evidence, `:draft` saves the fields entered so far. Ctrl+C exits with the resume
command and retains completed saves. The guide also exits when input ends,
so piped input can complete a session.

Editing a received export creates a working copy at the first save. The menu
prints its folder and uses that copy for subsequent edits and exports.

For a package with several claims, use **Choose another claim**, or open one
by its displayed number or ID:

```bash
claimtrace prepare "contact-review" --claim 1
```

## Review the five-part audit

```bash
claimtrace review "contact-review"
```

Read the claim, visual evidence, provenance, uncertainty and reproducibility
rows. Their status distinguishes recorded details from work that still needs
attention. A saved native scene can retain **Replay pending** until it is
checked in the original viewer.

The review also reports readiness for the selected export purpose. A
**Working draft** preserves open scientific questions with the saved record.
**Additional author review** lists saved fields that still need review, grouped
by their role. The printed details command opens their full field references.

In this exercise, **Working draft package checks: Ready** confirms draft
readiness. **Visual evidence · Review needed** and **Reproducibility · Needs
details** keep the remaining identity and saved-view questions visible. Use
**Figure & scene details** for the view and **More details** for molecular
identities and color meanings.

Basic review shows up to three next actions. For detailed IDs and every
remaining question:

```bash
claimtrace review "contact-review" --expert
claimtrace inspect "contact-review" --details
```

Use a claim ID shown by Expert review to inspect one statement:

```bash
claimtrace review "contact-review" --claim "<claim ID>"
```

## Export the package

```bash
claimtrace export "contact-review" --out "contact-review.zip"
```

Review and export use the purpose saved in the package. New packages start as
**Working draft**. The export command checks the selected purpose, collects
the files and writes a verified ZIP.

| Purpose | CLI mode | Intended use |
| --- | --- | --- |
| Working draft | `draft` | Keep writing while sources or details are being gathered. |
| Lab handoff | `internal` | Pass the record to a colleague in the project. |
| External review | `share` | Share the record with a collaborator or reviewer. |
| Archive | `archive` | Preserve a complete, self-contained record. |

Choose the saved purpose in the preparation menu or the GUI. An explicit
`--mode` applies to one command and preserves that saved choice:

```bash
claimtrace review "contact-review" --mode share
claimtrace export "contact-review" --mode share --out "contact-review-share.zip"
```

If the export reports required details, return to Prepare and complete the
listed items, then review again.

## Continue in either interface

```bash
claimtrace gui "contact-review"
```

The GUI opens the same saved claim and evidence. Continue editing in either
interface, then review the package before export.

For the terminal menu through the completion command:

```bash
claimtrace complete "contact-review"
```

Add `--expert` to the terminal guide when you need its detailed records:

```bash
claimtrace prepare "contact-review" --expert
```

## Use an answers file for scripted authoring

Export the current answer template, preserve its IDs, and edit the relevant
scientific context:

```bash
claimtrace complete "contact-review" --emit-template > "contact-review/answers.new.yml"
claimtrace complete "contact-review" --check-answers "contact-review/answers.new.yml"
claimtrace complete "contact-review" --answers "contact-review/answers.new.yml"
```

Checking reports the fields to review. Applying the answers writes the saved
record. Use the [synthetic file examples](../examples/README.md) for complete
scripted inputs, or the [article tutorials](https://github.com/GeraltZeroZhong/ClaimTrace/blob/v1.0/docs/tutorial/README.md) for molecular
views and analyses using real source data.

## When a step needs attention

| What you see | Next action |
| --- | --- |
| A required entry is empty | Enter the requested value, choose Save draft where offered, or use `:back` to return to the menu. |
| A source file is missing from the list | Choose Add files, then return to Evidence and select it. |
| Replay pending | Open the saved scene in its original molecular viewer and record the replay result. |
| The selected export needs more details | Read the listed items, return to Prepare and save the requested context. |
| Piped input ends before the task is finished | Run the printed resume command, or supply the remaining responses in the next session. |
| The output folder already exists | Choose a fresh `--out` folder or resume it with `prepare`. |

Run `claimtrace prepare --help` or `claimtrace review --help` for the available
options. [GUI instructions](gui.md) explain the same record in the browser.
