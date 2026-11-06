# Use ClaimTrace with an agent

Use the ClaimTrace skill to ask an agent about a molecular figure's evidence,
sources, settings and limitations. The agent reads the package through the
local CLI and saves proposed changes for your review in the CLI or GUI.

## Install ClaimTrace

Follow [Install ClaimTrace](start.md#install-claimtrace) to set up the local CLI.
For a first review package, work through the [illustrated tutorial](https://github.com/GeraltZeroZhong/ClaimTrace/blob/v1.0/docs/tutorial/README.md)
and keep the saved package folder path.

Run the commands below from the folder containing `.venv`. Use an agent client that
can read the package files and run the local ClaimTrace CLI. For a WSL setup,
run the agent in the same WSL environment as ClaimTrace.

## Install the skill

If **claimtrace** already appears in your Codex skill picker, continue to
[your first task](#try-a-read-only-task).

From the folder where you created `.venv`, run **one command for
your system**. It copies the bundled skill and its reference files into Codex's
user skills folder.

**Windows PowerShell**

```powershell
.\.venv\Scripts\python.exe -m claimtrace skill --out "$HOME\.agents\skills\claimtrace"
```

**Linux, macOS or WSL**

```bash
.venv/bin/python -m claimtrace skill --out "$HOME/.agents/skills/claimtrace"
```

**Check:** The command prints `Skill saved:` followed by the installed
`SKILL.md` path. The folder contains `SKILL.md`, `references/` and `agents/`.

Codex discovers user skills in `$HOME/.agents/skills`. Type `$` or use `/skills`
in Codex to select **claimtrace**. Restart Codex if the new skill has yet to
appear. See the [Codex skill guide](https://learn.chatgpt.com/docs/build-skills).

### Installation help

| What you see | Next action |
| --- | --- |
| The `.venv` Python command is unavailable | Open the folder containing `.venv` and complete [Install ClaimTrace](start.md#install-claimtrace). |
| `No module named claimtrace` | Install ClaimTrace using the same `.venv` Python shown in the command. |
| `Choose a new folder for the companion skill.` | The destination already exists. Select the installed **claimtrace** skill in Codex, or choose a fresh destination with `--out`. |
| The installed skill has yet to appear | Restart Codex and check its skill picker. For WSL, run Codex in the WSL environment where you installed the skill. |

## Try a read-only task

Open your working folder in Codex, select **claimtrace**, and send:

```text
$claimtrace Inspect the package at "<absolute package folder path>".
Keep the package unchanged. Give me the claim audit and the next useful action.
Use ClaimTrace from this folder's .venv environment.
```

Replace `<absolute package folder path>` with your package folder. The response
should connect each claim to its visual evidence, sources, limitations and
reproducibility status, then identify the next useful action.

For a focused check, add the figure statement:

> Check the statement that the ligand contacts the selected pocket residues.
> Report the source evidence, cutoff and remaining limitations.

To prepare changes, describe the record you want to add:

> Use the ClaimTrace skill to draft a limitation for this claim from the
> attached validation report. Save a proposal and show me its changes.

After reviewing the proposal, use its returned ID and your name:

> I accept proposal `<proposal ID>` as written. Record my review as
> `<your name>`, then show the updated claim audit.

To share the result:

> Export this package for its saved purpose and report any required updates.

When an input is missing, the agent identifies the file or scientific detail
needed for the next step. Contact, density, confidence and trajectory claims
each have their own evidence requirements.

## Use another compatible agent

Run `claimtrace skill` in the environment where ClaimTrace is installed to
print the bundled `SKILL.md` path. Give that path to an agent that can read
local instructions and run the CLI. For a client that discovers skills in a
designated folder, copy the full bundle there:

```bash
claimtrace skill --out "skills/claimtrace"
```

Use your client's supported skill directory as the destination. The skill
operates through the local CLI and shares the package with the GUI.

## Inspect and propose through JSON

This reference is for agents and developers. The commands run without an
interactive prompt. Use `claimtrace` from your activated environment, or replace
it with the `.venv` Python command used during installation followed by
`-m claimtrace`:

```bash
claimtrace agent inspect "PACKAGE" --summary
claimtrace agent inspect "PACKAGE" --claim "CLAIM_ID"
claimtrace agent schema
claimtrace agent check "PACKAGE" --input "proposal.json"
claimtrace agent propose "PACKAGE" --input "proposal.json"
claimtrace agent proposals "PACKAGE" --status pending
```

Replace `PACKAGE` with your package folder. Start with `--summary` for a
compact claim audit and source index. Omit it for complete semantic records,
validation findings, workflow state and saved proposals. `--claim` focuses the
audit while retaining shared source context in the full records. Use those
record IDs and the proposal schema to prepare the input.
The schema response wraps its JSON Schema in `schema`, alongside
`protocol_version` and `ok`. Read `x-record-fields` and `x-field-notes` within
that schema for the supported changes.

`check` previews the proposed changes. `propose` saves them as a pending proposal
with the agent, sources and rationale. The package's scientific records change
when you accept the proposal.

Read the bundled
[command reference](../src/claimtrace/resources/skills/claimtrace/references/commands.md)
for proposal fields, decision commands and working-copy behavior. Use
`claimtrace agent --help` for installed command options.

## Review a proposal

Inspect the proposed changes and supporting sources. To accept a proposal
through the CLI:

```bash
claimtrace agent review "PACKAGE" "PROPOSAL_ID" --decision accept --reviewer "REVIEWER" --note "REVIEW_NOTE"
```

Replace the placeholders with the proposal ID, your name and a decision note.
An agent records this action after the user authorizes the specific decision.
The review history keeps the proposing agent and human reviewer distinct.

In the GUI, open **Agent suggestions** in Prepare or Review, then **Review
suggestion**. Compare values and source files, then choose **Accept suggestion**,
**Edit suggested values** or **Reject suggestion**. Finish an edit with **Save &
accept**. Accepted suggestions retain **Revert changes** under **View decision**,
along with their review history. If a record has changed since the proposal
was created, review the current values and prepare an updated proposal.
Resolve later changes that depend on a record before reverting that record.

Inspect the updated package before exporting. Follow the package path returned
by a write operation; a received package uses a working copy for changes.

A **Working draft** can carry pending proposals to another reviewer. The
recipient can open **Agent suggestions** in the GUI or list them with
`claimtrace agent proposals "PACKAGE" --status pending`. Choose the export
purpose for the handoff; reviewing a proposal preserves the saved purpose.

## Read the outcome

The skill reports **Claim → Visual evidence → Provenance → Uncertainty →
Reproducibility** and the next useful action. Supplied results stay attributed
to their source. New measurements and viewer replay require observed outputs
from their respective tools.

Package validation checks the recorded context, links and files for the chosen
purpose. Scientific review and native viewer replay each retain their own
evidence and status. For interactive terminal preparation, see the
[terminal guide](cli.md).
