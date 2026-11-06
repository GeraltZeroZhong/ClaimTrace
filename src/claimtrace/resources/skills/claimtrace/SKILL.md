---
name: claimtrace
description: Prepare and review claim-linked molecular visualization evidence with ClaimTrace. Use for auditing a figure statement, tracing it to structures and scene settings, recording source-backed evidence or limitations, proposing reviewed changes, and exporting a ClaimTrace package. General figure layout and workflow illustrations use their own authoring tools.
---

# ClaimTrace

Help the user trace one molecular figure statement through its visual evidence,
provenance, uncertainty and reproducibility status. Work with the user's package,
files and stated scientific question.

Use a ClaimTrace installation with the `agent` command group and local file
access. Viewer replay and scientific analysis use their corresponding tools
and inputs.

## Start with the task

Identify the package or source files, the statement to examine, and the requested
outcome: read-only assessment, draft changes, a review decision or export. Use
context already supplied by the user. Ask only for information that changes the
next useful action.

Read [commands.md](references/commands.md) when using the CLI. Read
[tasks.md](references/tasks.md) for contact, density, model-confidence or
trajectory questions, and [record-semantics.md](references/record-semantics.md)
when attributing results or interpreting review and replay status.

For a read-only request, inspect and report. Keep packages, proposal files and
exports unchanged. Follow existing user authorization and host permissions for
other actions. Creating a draft proposal requires ordinary write authorization;
recording a human decision requires that person's actual decision on the
specific proposal.

## Inspect before proposing

1. Start with `claimtrace agent inspect PACKAGE --summary` and select the relevant
   claim. Open full records with `agent inspect PACKAGE --claim CLAIM_ID` when
   needed. Use returned IDs and source locations to locate scenes, selections
   and artifacts; filter large JSON responses to the fields needed for the task.
2. Inspect the actual supporting files needed for that claim. Limit questions
   and analysis to its material gaps. A visible ligand alone leaves the claim
   type open.
3. Keep native expressions, supplied results, new tool outputs and human
   interpretations distinguishable. A scene command records an intended
   operation; an executed result needs its own evidence.

Record missing inputs plainly. Derive measurements, thresholds, identifiers and
software details from available sources or actual execution. Keep unavailable
information explicitly open.

## Save agent work as a proposal

For authorized drafting, obtain `claimtrace agent schema`, construct the
smallest relevant proposal, then run `agent check`. Use the supported proposal
interface for changes; preserve the package manifest through that interface.

- Reuse observed record IDs. Assign explicit new IDs to new records and keep
  the proposal ID stable when retrying the same input.
- Include source artifact IDs and the rationale. Attribute the proposing agent
  using identity details actually available from the host.
- Keep result summaries focused on the observation. Put settings in structured
  parameters and interpretation limits in uncertainty records.
- Describe supplied analyses as supplied. Record tool calls and their actual
  outputs when this task performs a new analysis.
- Resolve reported input or reference errors before `agent propose`. A conflict
  calls for fresh inspection and a revised proposal based on the current state.

`agent propose` stores a pending proposal. Present its ID, relevant changes and
evidence to the user. Accepted scientific records retain their current values
until the proposal is reviewed.

When the user has specifically accepted, rejected or requested reversal of a
proposal, record that decision with `agent review` and the actual reviewer.
Use an already supplied decision directly. Preserve pending status while a
decision is still open. Re-inspect after a review action to verify the result.

## Review and finish

Report a compact audit, adapting detail to the user's question:

| Item | Include |
| --- | --- |
| Claim | Exact statement and claim ID. |
| Visual evidence | Relevant figure, scene, selection and observation. |
| Provenance | Source files, recorded settings and who supplied or produced the result. |
| Uncertainty | Material limitations, alternatives and open inputs. |
| Reproducibility | Package check result and the separate state of native viewer replay. |

End with the most useful next action or the completed output path. Distinguish
saved proposals from accepted records. Validation reports package readiness for
its purpose; scientific support and viewer replay depend on their evidence.

Export when requested, using the saved purpose unless the user specifies another
one. Report blocking findings as concrete actions. Preserve the chosen purpose
and scientific record when a check requires more evidence.
