# Agent CLI

Use `claimtrace agent --help` to confirm that the installed CLI provides this
interface. Commands in this group return JSON. Read the returned package path
after a write; received packages may be opened as a working copy.

Use the executable in the active environment. In a source checkout, check
`.venv/bin/claimtrace` on Linux/macOS or `.venv/Scripts/claimtrace.exe` on Windows
when `claimtrace` is absent from PATH. Use that executable throughout the task.

## Inspect a package

```bash
claimtrace agent inspect "PACKAGE" --summary
claimtrace agent inspect "PACKAGE" --claim "CLAIM_ID"
claimtrace agent schema
```

Replace `PACKAGE` with the actual package folder and `CLAIM_ID` with an ID from
the first response. `--summary` returns a compact audit, artifact index,
validation findings and proposal summaries. Omit it to read full records.
Full inspection returns `protocol_version`, `package`, `mode`,
`semantic`, `audit`, `validation`, `workflow` and `proposals`. The semantic data
provides the actual record and artifact IDs. An optional `--mode` selects
`draft`, `internal`, `share` or `archive` for the check.

Read each finding's `blocking` flag in summary output against the selected
purpose. A draft can pass while retaining findings that block an archive.
Use `workflow.next_action` to locate the next open review task.

For an authorized new package, import actual source files:

```bash
claimtrace init --file "figure.pml" --file "figure.png" --file "model.cif" --out "figure-review" --format json
```

Use existing files, adapting their paths and types. Repeated `--file` options
select import roles by file type. Native scene, image and supporting data
remain separate artifacts.

## Check and save a proposal

Read `agent schema` before constructing a proposal. Its response contains
`protocol_version`, `ok` and `schema`. The schema's `x-record-fields` lists the
editable fields for each record type; `x-field-notes` explains special handling.
The `Change` alternatives define each field's type and accepted enum values.
Save the proposal JSON in an authorized working location. Its fields include:

| Field | Meaning |
| --- | --- |
| `schema_version` | Proposal format version, currently `"1"`. |
| `id` | Stable proposal ID for this change and its retries. |
| `actor` | Agent `id` and `name`; actual `version`, `provider` and `model` when available. |
| `title`, `rationale` | The concrete change and its evidence-based reason. |
| `claim_id` | Existing claim receiving this proposal, when applicable. |
| `source_artifact_ids` | Actual package artifacts supporting the change; an empty list keeps unavailable sources explicit. |
| `changes` | Record type, explicit record ID and changed fields. Evidence and uncertainty changes can identify their linked claim. |
| `tool_calls` | Actual executed tools, parameters, input/output artifact IDs and observed results, when relevant. |

Supported record types are `claim`, `evidence`, `uncertainty`, `scene`,
`selection` and `entity`. A new claim needs
`scene_ids`, `figure_ref` and `claim_text`. Use existing scene IDs and the user's
actual statement and figure reference.

For `evidence_kind: "measurement"`, record the supplied or calculated distance
in `parameters.measured_distance` and its unit in `units.distance`. For
`contact_table`, use `thresholds.distance` for the contact cutoff and
`units.distance` for its unit. A measured distance and a classification cutoff
have different meanings. Preserve the source's value and unit.

```bash
claimtrace agent check "PACKAGE" --input "proposal.json"
claimtrace agent propose "PACKAGE" --input "proposal.json"
claimtrace agent proposals "PACKAGE" --status pending
```

`check` examines the projected record without changing the package. Read `ok`,
`preview` and `errors`; resolve invalid input before saving. `propose` stores
the pending proposal while preserving accepted record values. It accepts
`--workspace DIR` for working copies of received packages.

This example adds an observation and a limitation to an existing claim. Replace
the capitalized IDs and authoring text with values from the inspected package
and its sources, then check the proposal:

```json
{
  "id": "proposal:source-review",
  "actor": {"id": "AGENT_ID", "name": "AGENT_NAME"},
  "title": "Link the figure statement to its source",
  "rationale": "Explain which source supports this update.",
  "claim_id": "CLAIM_ID",
  "source_artifact_ids": ["ARTIFACT_ID"],
  "changes": [
    {
      "record_type": "evidence",
      "record_id": "evidence:source-review",
      "claim_id": "CLAIM_ID",
      "fields": {
        "evidence_kind": "manual_rationale",
        "method_name": "Describe the source inspection performed.",
        "result_summary": "State the observation supported by that source.",
        "source_artifact_ids": ["ARTIFACT_ID"]
      }
    },
    {
      "record_type": "uncertainty",
      "record_id": "uncertainty:source-scope",
      "claim_id": "CLAIM_ID",
      "fields": {
        "category": "scope",
        "statement": "State the relevant interpretation limit."
      }
    }
  ]
}
```

For an update, reuse the existing evidence or uncertainty ID. Choose the
evidence kind that matches the task; the schema lists the available fields.

## Record a real review decision

Run a review action when the user has actually authorized that decision for the
specific proposal. Use the real reviewer name and proposal ID.

```bash
claimtrace agent review "PACKAGE" "PROPOSAL_ID" --decision accept --reviewer "REVIEWER" --note "REVIEW_NOTE"
```

`--decision reject` records rejection. `--decision revert` reverses an accepted
proposal when its current state permits reversal. Restore later dependent
changes first when they still reference records created by that proposal.
`--edits edited-changes.json`
supplies an edited changes array using the same target IDs and field keys.
`--workspace DIR` selects the working-copy location when needed.

Inspect the returned state and package path, then run `agent inspect` again.
Conflicts require reviewing the current record before another change. The
reviewer argument records a supplied decision; access to the command conveys
no human approval by itself.

## Review and export

```bash
claimtrace review "PACKAGE" --format json
claimtrace export "PACKAGE" --out "figure-review.zip"
```

Review and export use the saved purpose, initially `draft`. An explicit `--mode`
is a temporary override. Report the actual export result and any required
updates. Package checks, scientific assessment and native viewer replay retain
their separate meanings.

A Working draft can carry pending proposals to a reviewer. Its README lists
the suggested statement, observations and limitations under **Suggestions
awaiting review**; the complete proposed changes remain in the package.
