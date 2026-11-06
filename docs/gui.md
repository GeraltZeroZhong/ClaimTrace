# ClaimTrace GUI workflow

Write a molecular figure statement, link its evidence and limitations, and
export a package for another reader. **Prepare**, **Review** and **Export**
work with the same claims, scenes and files.

For an illustrated walkthrough, open [Start here](https://github.com/GeraltZeroZhong/ClaimTrace/blob/v1.0/docs/tutorial/README.md) and follow
**Figure 1B1: Pocket visibility**. The tutorial supplies real source data, values
for every form, screenshots at each step, and a completed package to inspect.
[Choose another case](https://github.com/GeraltZeroZhong/ClaimTrace/blob/v1.0/docs/tutorial/markdown/README.md) to explore a different task.
For offline reading, open `docs/tutorial/index.html` from the extracted repository
in your browser.

## Open the workspace

For first-time setup, follow [Install and open ClaimTrace](start.md). The commands
below use the [activated environment](start.md#use-the-short-command).

```bash
claimtrace gui
claimtrace gui "scene-package"
```

The browser opens at `http://127.0.0.1:8765`. Keep the terminal open while working.
Use `--port 0` for a free port, or `--no-browser` to open the printed address
yourself. Stop the server with Ctrl+C. Packages remain available after the
server exits.

For a first visit, choose **Try an example** and **Start first example**.
The welcome screen previews the short review you will create. Each practice
case shows the next action above the figure; **Use practice values** supplies
suggested answers for each form. **How it works** explains the workflow and
the terms claim, scene, and package from any screen.

Select **Choose files** on the start screen, or **Start with files** in the header.
Begin with a saved scene, figure image, structure, or results table. Supported
native scenes are PML, CXC, MVSJ, and MVSX. Give the package a name and choose
**Create package**. Use **Open package** to continue an existing local folder.
For a received ZIP, extract it first and enter the folder containing
`semantic_layer.json`.

Opening a shared package preserves its files. The first saved edit creates
a working copy in your local workspace and keeps you on the current claim.
**Saved locally** shows the new folder. Export this copy to send the revised
record back to the recipient.

New packages are saved under `claimtrace-workspace/` in the launch directory.
The import form's **Save location** option accepts another destination.

For an agent-assisted review, [install the companion skill](agents.md#install-the-skill)
and give the agent your package path. Review its saved proposals under
**Agent suggestions** in Prepare or Review.

## Prepare the figure record

1. **Add claim**: write one statement and its figure label. Choose the scene
   that shows it. **Statement type** tailors the questions to a descriptive
   view, ligand pose, model comparison, or other interpretation. Practice
   cases start with the corresponding type selected.
2. **Add evidence**: choose the source file, record what it shows, and describe
   how it was checked. Attach analysis outputs directly in this form.
3. **Add limitation**: record the assumptions, uncertainty, or alternative
   interpretation that matters to this claim. Descriptive claims show an
   **Optional** limitation row with this action beside it.
4. Follow **Details to complete** to identify selected molecules, explain
   visual meaning, or complete the saved view and software context.

For an image, choose **Set figure type** beside the figure. **Analysis plot**
asks for axes, filters, and analysis settings; **Figure assembly** asks for
panel sources and layout settings; **Molecular view** asks for the saved
view and scene. A selection spanning multiple coordinate files can link all
of them under **Source structures**.

The evidence form follows the source you have:

| Field | What to enter |
| --- | --- |
| Evidence type | Choose a figure inspection, contact table, measurement, comparison, or other result |
| Source files | Select existing files or attach a supporting file |
| How was it checked? | Name the inspection or analysis, such as comparing a named selection with coordinate rows |
| What did you find? | Record the observation, including relevant values, residues, or states |
| Contact distance cutoff / Distance unit | For contacts, enter the threshold and unit used in the analysis |
| Measured distance / Distance unit | For a distance measurement, enter the observed atom-to-atom distance and its unit |
| Analysis settings → Selections, cutoffs and sampling | Record additional thresholds, selected residues or frames, repeat counts, and analysis options |

**Trajectory analysis** opens **Analysis settings** for frames, sampling,
selected atoms, and replicate counts. A direct distance measurement records
its observed value separately from a contact-selection cutoff.

Use **Preview** beside a source file to inspect its contents within the form.
Your entries and file selections stay in place. The selected count updates as
you choose files or attach new ones. File labels such as **Table**,
**Structure**, and **Figure image** help you identify each source.
Long file lists offer **Find source files**, **Select shown**, and **Clear
shown**. Filtering keeps previously selected files. CSV previews display
column headings and the number of rows and columns shown; **Download original**
downloads the complete source. Correcting a field clears its previous error;
saving checks the completed form again.

Choose a suggested method, use **Use a sentence template**, or open **View
example answer**. **Save draft** keeps partial claims and evidence while you
gather details. Reopen the pending question to finish the same record. A
package started from a results table can hold a draft claim while its figure
and scene are still being prepared.

Closing a changed form asks before discarding your entries; cancelling keeps
the form open. Save a draft before leaving unfinished work. Refreshing restores
the selected claim, scene and review section, or the scene-browsing view.

Browser tabs connected to the same local server share its active package. If
another tab opens a different package, saving or exporting from the older tab
is blocked. Keep an unfinished form open, reopen its package in another tab,
then retry the save.

**Save claim** and **Save evidence** confirm the entered record. **Save draft**
keeps the record open for completion.

When a required field needs attention, its message appears beside the field
and focus moves there. Press Enter in a single-line field to use the primary
save action. To keep partial work with the keyboard, Tab to **Save draft** and
press Enter.

### Add files and scenes later

Use **Add files** for structures, results, or native scenes; use **Add figure**
for a rendered panel. The **Link to scene** selector associates an image with
the appropriate scene. **Images in this package** lets you reuse a figure
already uploaded. Matching image and native-scene filenames are paired when
they identify a single scene. Adding a figure from a draft claim links the
new figure to that claim.

Structure detection includes PDB, PDBQT, CIF, mmCIF, SDF and MOL coordinate
files, including gzip-compressed versions. The original files remain in the
package.

For an image-first package, add the native scene and choose the existing
image's scene under **Link to scene**. Its figure and claim links are retained.
Choose **New scene / assign later** when adding another view, a native scene
with multiple snapshots, or a scene alongside an existing native scene. Then
use **Edit claim** to select the relevant scene or snapshots.

For a molecular view supplied as an image, describe the visible region and
orientation, link the image as evidence, and record its limits.
The saved-scene question stays visible for interactive replay. In
**Review → Reproducibility**, **Export a working draft** selects the draft
purpose and opens Export, including when another purpose was selected earlier.

For an analysis plot or assembled figure, open **Edit view details** and set
**View type** to **Analysis plot** or **Figure assembly**. Record the axes,
sample selection, thresholds, or panel layout in **Plot settings** or
**Assembly settings**, then link the analysis outputs as evidence. These
records check the saved figure, source files and settings. Molecular replay
is marked as inapplicable; package checks still follow the selected export
purpose. A saved molecular scene retains its native replay requirements.

**Scenes & files** lets you inspect materials before writing a claim. A
selection link opens its recorded command line or JSON location. **Edit view
details** records the named view, visibility choices, software, and reuse
details. Save a form to update the local package.

## Review the visual argument

Select a claim, then open **Review**. The figure and scene remain beside a
short audit:

**Claim → Visual evidence → Provenance → Uncertainty → Reproducibility**

| Audit row | Inspect |
| --- | --- |
| Claim | The statement, figure label, claim type, and linked scenes |
| Visual evidence | The figure, selected regions, molecular identities, and saved view |
| Provenance | The supporting observations, methods, parameters, and source files |
| Uncertainty | Relevant limitations and alternative explanations |
| Reproducibility | Molecular scene and saved view, or figure sources and analysis settings; software and export requirements |

Choose a row to open its details. **Edit record** returns to preparation.
When a claim links several scenes, use the scene selector to inspect each
view; questions about a particular snapshot open that snapshot's context.

**Basic** shows the figure, concise questions, and linked records. **Expert**
adds operations, exact source locations, unresolved content, evidence bindings,
validation findings, and the `answers.yml` editor. Switching modes keeps the
selected claim.

A **Recorded** audit stage has its expected information. Review the evidence
to assess how strongly it supports the statement. Check display replay in the
original molecular viewer.

## Export for the recipient

Open **Export** and choose the purpose of the copy. The workspace starts with
**Working draft** and remembers your selected purpose in the package.

| Purpose | CLI mode | Use |
| --- | --- | --- |
| Working draft | `draft` | Save a portable record while questions remain open |
| Lab handoff | `internal` | Hand work to someone in the project |
| External review | `share` | Prepare a collaborator or reviewer copy |
| Archive | `archive` | Preserve a durable, self-contained record |

Checks apply to the selected purpose. Required items lead to their relevant
form. Open authoring questions remain visible in the audit and can accompany
a passing draft or handoff check. Native-viewer replay retains its own status.

- **Download package · ZIP** includes the native scenes, figures, molecular
  data, evidence, claim records, recipient instructions, and validation
  information. ClaimTrace validates the assembled package before download.
- **Download summary · Markdown** exports the compact audit and open items.
- **Download audit JSON**, available in Expert mode, exports the complete
  audit projection for further inspection.

The summary and JSON audit contain record descriptions and source links.
The ZIP carries the package files for transfer. Shared evidence and limitation
edits apply to every linked claim; create a separate record for a different
observation or interpretation.

## Complete a practice example

Choose **Try an example** or **Examples**, then select a case. Each case
creates a fresh local package containing a coordinate diagram, a PML scene
with its camera, coordinate files, a result table, and calculation notes.
All three cases use **Synthetic practice data**.

1. In **Prepare**, choose **Add claim**. Use **Use practice values**, or enter
   the statement and figure label below, then save.
2. Choose **Add evidence**. Preview and select the listed source files, then
   enter how they were checked and what you found. Include the supplied
   cutoff and unit for ligand contacts.
3. Choose **Add limitation**, enter the example limitation, and save.
4. Open **Review** and inspect the five audit rows. In **Export**, choose
   **Archive**, then download the package and Markdown summary.

Each completed practice case has one claim, one evidence record, one
limitation, five recorded audit stages, and a passing archive check. The
practice guide provides its exact suggested answers and source downloads.

### Highlight two residues

| Field | Example answer |
| --- | --- |
| Claim | The teal markers highlight chain A residues ASP 42 and SER 85 in the synthetic structure. |
| Figure label / statement type | Practice panel A / Highlighted region |
| Evidence type | Figure or structure inspection |
| Source files | `practice.pml`, `synthetic.pdb`, `selection.csv`, `practice-notes.txt` |
| How was it checked? | Compare the named selection with the coordinate rows |
| What did you find? | The site selection contains chain A residues ASP 42 and SER 85. TYR 117 appears in gray. selection.csv records membership for all three residues. |
| Applies to | `site` |
| Limitation | The colors identify a selected residue set in synthetic coordinates. Biological roles require experimental evidence. |
| Limitation category | General limitation |

Open `selection.csv` to see two highlighted rows and one remaining row.
The `site` source link opens the matching PML selection.

### Check ligand contacts

| Field | Example answer |
| --- | --- |
| Claim | In the synthetic structure, ligand atom B/LIG1/C1 lies within 4 angstrom of A/ASP42/CA and A/SER85/CA. |
| Figure label / statement type | Practice panel B / Ligand binding pose |
| Evidence type | Contact table |
| Source files | `synthetic.pdb`, `contacts.csv`, `practice-notes.txt` |
| How was it checked? | Calculate atom-to-atom distances from synthetic.pdb using a 4 angstrom cutoff |
| What did you find? | B/LIG1/C1 is 2.000 angstrom from A/ASP42/CA and 4.000 angstrom from A/SER85/CA. Both meet the inclusive 4 angstrom cutoff; A/TYR117/CA is 6.325 angstrom away. |
| Contact distance cutoff / unit | `4` / `angstrom` |
| Applies to | `site`, `ligand` |
| Limitation | The 4 angstrom threshold describes proximity in one synthetic coordinate set. Binding affinity and pose accuracy require independent evidence. |
| Limitation category | Selection or cutoff |

The table includes all three distances. Its contact column uses an inclusive
cutoff, so the row at exactly 4.000 angstrom is included. The coordinate rows
and Euclidean distance formula are supplied for checking the calculation.

### Compare two models

| Field | Example answer |
| --- | --- |
| Claim | In the synthetic models, A/117/CA differs by 2.000 angstrom and the three-atom RMSD is 1.155 angstrom in the shared coordinate frame. |
| Figure label / statement type | Practice panel C / Model comparison |
| Evidence type | Comparison or validation report |
| Source files | `model-a.pdb`, `model-b.pdb`, `comparison.csv`, `practice-notes.txt` |
| How was it checked? | Compare matching CA coordinates in the shared coordinate frame |
| What did you find? | A/42/CA and A/85/CA differ by 0.000 angstrom; A/117/CA differs by 2.000 angstrom. RMSD over the three atoms is 1.155 angstrom. |
| Applies to | `first_model`, `second_model` |
| Limitation | RMSD depends on atom matching and the shared coordinate frame. Real model comparisons also require alignment and an uncertainty assessment. |
| Limitation category | Model confidence |

Match atoms by chain, residue number, and atom name. The comparison uses the
shared coordinate frame directly: displacements are 0, 0, and 2 angstrom;
the RMSD is `sqrt((0² + 0² + 2²) / 3) = 1.155 angstrom` after rounding.

### Continue with imported source files

Choose **Start with files** to repeat the contact exercise from its PML, PDB, CSV,
notes, and figure. Add the claim, evidence, cutoff, unit, and limitation as
above. The next actions collect the author descriptions that accompany a
raw scene:

| Action | Example entry |
| --- | --- |
| Identify regions: `ligand` | Type: Ligand; identity: Chain B, ligand LIG 1, atom C1; source: `synthetic.pdb` |
| Identify regions: `site` | Type: Residues or binding site; identity: Chain A, residues ASP 42 and SER 85; source: `synthetic.pdb` |
| Explain visual meaning: orange ligand | Orange identifies the synthetic ligand LIG in chain B residue 1. |

Saving identities links those named regions to the evidence that targets
their selections. Saving a visual meaning records the author's color key.
The Visual evidence stage shows **Review needed** while either description
is required, then **Recorded** once both are complete. Existing descriptions
can be edited from **Edit region identities** and **Explain visual meaning**.

## Continue between the GUI and CLI

The two interfaces use the same saved claims, evidence and workflow questions.
Prepare a record in the terminal:

```bash
claimtrace init --file "figure_A.pml" --file "figure_A.png" --file "model.cif" --out "scene-package"
claimtrace prepare "scene-package"
claimtrace review "scene-package"
claimtrace export "scene-package" --out "scene-package.zip"
```

Run `claimtrace gui "scene-package"` to continue in the browser. The existing
`complete "scene-package" --gui` command also opens the GUI on a free local
port. Close that server with Ctrl+C before continuing in the same terminal.
Bare `complete "scene-package"` opens the terminal preparation guide.

`inspect` prints a short preparation summary; `inspect --details` adds the
source inventory. `review --claim <id-or-number>` focuses on one claim;
`review --expert` adds record IDs and all open questions. `--format json` and
`--format md` produce reusable review output. `complete --answers` retains
scripted authoring.

Review and export use the purpose saved in the package, initially **Working
draft**. An explicit `--mode` applies to that command and preserves the saved
choice. `validate` defaults to `draft`; pass `--mode` to check another purpose.
See the [terminal walkthrough](cli.md) for exact entries and save/resume steps.

The Expert answers editor opens current claim and evidence records alongside
package-wide fields. Validation errors remain beside the editor. Applying
answers updates the corresponding records.

## Local files and previews

The server binds to `127.0.0.1` and serves registered package files. Scene
import reads source expressions locally. Remote references remain recorded
for inspection; replay and runtime results come from the molecular viewer.

Browser uploads support 45 MiB per request, with a 64 MiB encoded request
limit. Use `claimtrace add-artifact` for larger supporting files, then refresh
the GUI. For scenes with nested relative paths, create the package through
the CLI using the original paths and open it in the GUI. MVSX archives retain
their embedded resources.

TIFF files receive PNG previews; downloads preserve the originals. Text
previews show up to 512 KiB. Use **Download original** in the evidence preview
or **Download file** in a file dialog to open the complete file.

See [the workflow model](workflow-design.md) for the record relationships and
[the synthetic file examples](../examples/README.md) for a command-line exercise.
