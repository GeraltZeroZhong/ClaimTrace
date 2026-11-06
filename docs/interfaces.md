# Interface contracts

ClaimTrace 1.0 uses CAL schema `0.1.0`, validation-report schema `0.1.0` and
agent protocol `"1"`. These versions describe separate contracts. Package
updates can improve extraction and validation while retaining the data format.

## Python

The public entry points are exported from `claimtrace`:
`init_package`, `load_package`, `validate_package`, `export_package`,
`ClaimTracePackage`, and the documented error classes. Use
`ClaimTracePackage.add_claim`, `add_artifact`, `complete_from_answers`,
`check_proposal`, `propose`, `review_proposal`, `validate`, `save` and `export` for programmatic work. The
[Python example](../README.md#python-api-and-development) shows a complete package flow.

Within the 1.x series, documented parameters and return types remain compatible.
New optional parameters and fields may be added. Internal modules and methods
whose names begin with `_` may change between releases.

Domain-specific failures raise `ClaimTraceError` or its subclasses
`ValidationError`, `SecurityError` and `SchemaVersionError`. Invalid input can
also raise `ValueError`; filesystem operations can raise `OSError`. Catch the
relevant category and show its message to the user. Exact message wording may
improve in later releases.

## Command line

`claimtrace` and `python -m claimtrace` provide the same commands. Public command
names and options remain compatible within 1.x. Use `--help` for the installed
version. Human-readable tables and menu text can evolve.

| Exit | Meaning |
| --- | --- |
| `0` | The requested operation completed. For `inspect` and `review`, read the findings to determine readiness. |
| `1` | An operation failed, or `validate` found an overall failure. |
| `2` | A usage error or a security/path-boundary error in the general CLI. |
| `3` | An unsupported schema version in the general CLI. |

General commands with `--format json` produce JSON on successful inspection;
operation errors use human-readable stderr. `review` uses the saved package
purpose by default; `validate` defaults to `draft`. Specify `--mode` in scripts
that require a particular readiness level.

## Agent protocol

Use `claimtrace agent` for machine-readable inspection and proposals. Command
handlers return an envelope with `protocol_version: "1"` and `ok`. Handler
errors have `ok: false`, `errors` entries with `code`, `pointer` and `message`,
and exit `1`. Argument parsing, `--help` and usage errors follow the CLI parser's
text interface and exit codes.

Redirected Windows CLI streams use UTF-8 by default, including agent JSON.
An explicit `PYTHONIOENCODING` setting takes precedence. Terminal console
streams keep their native Python encoding.

`agent schema` places its JSON Schema in the `schema` field. `agent inspect
--summary` provides a compact audit; full inspection retains semantic records.
`--claim` focuses the audit and tasks while validation covers the whole package.
Clients should accept additional response fields and use record IDs for links.
Incompatible envelope changes require a new protocol version.

`check` leaves the package unchanged. `propose` saves a pending proposal.
`review` records an explicit decision and reviewer. Follow the returned
`package` path after writes: editing a received export through the GUI, guided
terminal or agent commands creates a working copy and reports
`working_copy_from`. See the [agent guide](agents.md) for examples.

## Answers and stored records

Explicit IDs in `answers.yml` update the corresponding records. Unspecified
fields retain their current values; supplied lists replace that field's list.
Use generated IDs for selections, operations and source files. Run
`complete --check-answers` before applying a hand-edited file.

Unchanged content retains its extraction provenance and review metadata.
Changing reviewed scientific content clears the previous acceptance, reviewer
and timestamp until a new review is recorded. The Expert **current answers**
document reflects the live package; the saved-answer view shows the earlier
file separately.

Low-level `set`, `complete --answers`, `add-artifact` and Python API writes
modify the supplied package directly. Use a separate copy when keeping an
original export as a reference. Keep one writer active per package.

Supported `0.1.0` semantic packages load directly in 1.0. `load_package` raises
`SchemaVersionError` for an unsupported schema version; `validate_package`
reports that problem in its validation findings. Extension fields carry additional context;
preserve them when copying or editing a record. Validation findings can become
more precise as checks improve, even while the schema stays compatible.

## GUI and experimental features

The GUI serves a local browser on loopback and uses `/api/*` internally. External
automation uses the versioned agent CLI or public Python API. Browser preferences
control presentation; the package files carry the scientific records.

`redact` and `migrate` remain experimental. Their help text describes their
current behavior; the 1.x compatibility commitment covers the stable interfaces
listed above.
