"""Command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
from typing import List

import typer
from rich.console import Console
from rich.table import Table

from claimtrace import _simple_yaml
from claimtrace.api import export_package as api_export_package
from claimtrace.api import init_package, load_package
from claimtrace.completion import (
    apply_answers,
    available_templates,
    check_answers,
    completed_answer_sections,
    completion_tasks_for_template,
    dump_package_answer_template,
    load_answers,
)
from claimtrace.constants import PACKAGE_VERSION, SEMANTIC_LAYER_FILENAME, VALIDATION_REPORT_FILENAME
from claimtrace.errors import (
    ClaimTraceError,
    PackageError,
    SchemaVersionError,
    SecurityError,
    ValidationError,
)
from claimtrace.models.semantic_layer import ArtifactRole, ClaimCriticalStatus, MeaningStatus
from claimtrace.package.layout import read_completion_tasks, write_completion_tasks, write_json
from claimtrace.package.registry import infer_role
from claimtrace.package.resources import resource_matches_artifact, resource_uri_summary
from claimtrace.path_hints import windows_path_hint
from claimtrace.schemas import semantic_layer_schema, validation_report_schema
from claimtrace.validation.engine import validate_package

APP_HELP = (
    "ClaimTrace packages molecular figure context from .pml, .cxc, .mvsj and .mvsx "
    "scene files, rendered panels and supporting evidence."
)
APP_EPILOG = "Run `claimtrace quickstart` for a copy/paste workflow and supported input formats."

app = typer.Typer(help=APP_HELP, epilog=APP_EPILOG)
console = Console()

MODE_HELP = "Validation mode. Choices: draft, internal, share, archive."
TEXT_JSON_HELP = "Output format. Choices: text, json."
TEMPLATE_HELP = (
    "Completion template. Choices: auto, simple-structure-view, ligand-binding-pose. "
    "Auto uses ligand-binding-pose only when pocket, binding-site, contact or distance context is present; "
    "a scene that merely displays a ligand stays simple-structure-view."
)
SECTION_CHOICES = {"claim", "entities", "scene", "evidence", "uncertainty", "reuse"}
ARTIFACT_ROLE_CHOICES = {role.value for role in ArtifactRole}
NATIVE_SCENE_SUFFIXES = {".pml", ".cxc", ".mvsj", ".mvsx"}


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Show ClaimTrace version and exit."),
) -> None:
    if version:
        typer.echo(f"claimtrace {PACKAGE_VERSION}")
        raise typer.Exit(0)
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


@app.command(rich_help_panel="Main workflow")
def quickstart() -> None:
    """Print the shortest end-to-end workflow for a molecular scene file."""

    typer.echo(
        "\n".join(
            [
                "ClaimTrace quickstart",
                "",
                "Install:",
                "   python -m pip install claimtrace",
                "",
                "Supported native scene files: .pml, .cxc, .mvsj, .mvsx",
                "Also include the rendered panel image and any structure, map, contact table, validation report or note that supports the figure.",
                "On WSL, use a /mnt/c/... path instead of a C:\\... path.",
                "",
                "1. Create a draft package:",
                '   claimtrace init "figure_A.pml" --image "figure_A.png" --artifact "model.cif" --out "scene-package"',
                "   # The same positional command works for every native scene format:",
                '   claimtrace init "figure_A.cxc" --out "scene-package"',
                '   claimtrace init "figure_A.mvsj" --out "scene-package"',
                '   claimtrace init "figure_A.mvsx" --out "scene-package"',
                "",
                "2. See what ClaimTrace recognized automatically:",
                '   claimtrace inspect "scene-package"',
                "",
                "3. Edit the package-aware answers file created by init:",
                '   Edit "scene-package/answers.yml" in your text editor.',
                "",
                "   Fill claim.claim_text and claim.figure_ref first.",
                "   Describe evidence only when the supporting file or note is actually available.",
                "   For color/label suggestions, choose one:",
                "   - user_confirmed_meaning: this visual choice carries the figure message",
                "   - user_declared_no_scientific_meaning: it is only for contrast or readability",
                "   - claim_critical: false — it is not central to this figure or panel",
                "",
                "4. Check and apply answers:",
                '   claimtrace complete "scene-package" --check-answers "scene-package/answers.yml"',
                '   claimtrace complete "scene-package" --answers "scene-package/answers.yml"',
                "",
                "5. Validate the current draft:",
                '   claimtrace validate "scene-package" --mode draft --format text',
                "",
                "6. When the required render, data, evidence and confirmations are present, validate and export the archive:",
                '   claimtrace validate "scene-package" --mode archive --format text',
                '   claimtrace export "scene-package" --mode archive --out "scene-package.zip"',
                "",
                "Tip: ClaimTrace reads native files statically. It does not run viewer scripts or fetch remote URLs.",
            ]
        )
    )


@app.command(
    rich_help_panel="Main workflow",
    epilog=(
        "Examples:\n\n"
        '  claimtrace init "figure_A.pml" --image "figure_A.png" --artifact "model.cif" --out "scene-package"\n\n'
        '  claimtrace init "figure_A.cxc" --out "scene-package"\n\n'
        '  claimtrace init "figure_A.mvsj" --out "scene-package"\n\n'
        '  claimtrace init "figure_A.mvsx" --out "scene-package"\n\n'
        '  claimtrace init --native "figure_A.pml" --native "alternate.cxc" --out "scene-package"'
    ),
)
def init(
    scene: Optional[Path] = typer.Argument(
        None,
        help="One native viewer scene (.pml, .cxc, .mvsj or .mvsx). Use --native instead to provide multiple files.",
    ),
    native: Optional[List[Path]] = typer.Option(
        None,
        "--native",
        help="Native viewer file: .pml, .cxc, .mvsj or .mvsx. Repeat for multiple files; parsed statically, not executed.",
    ),
    image: Optional[List[Path]] = typer.Option(
        None,
        "--image",
        help="Rendered panel image to include, e.g. .png, .tif or .svg. Repeat for multiple images.",
    ),
    artifact: Optional[List[Path]] = typer.Option(
        None,
        "--artifact",
        help="Supporting file to include, e.g. structure, map, contact table, report or note. Repeat for multiple files.",
    ),
    out: Path = typer.Option(Path("scene-package"), "--out", help="Output package directory."),
    template: str = typer.Option("auto", "--template", help=TEMPLATE_HELP),
    title: str = typer.Option("Untitled ClaimTrace package", "--title", help="Package title."),
    force: bool = typer.Option(
        False,
        "--force",
        help="Replace an existing ClaimTrace output; refuses cwd, home, / and non-ClaimTrace directories.",
    ),
    blank: bool = typer.Option(False, "--blank", help="Create an empty package intentionally."),
    no_input: bool = typer.Option(
        False,
        "--no-input",
        help="Compatibility option; init is already non-interactive.",
        hidden=True,
    ),
    format: str = typer.Option("text", "--format", help=TEXT_JSON_HELP),
) -> None:
    """Create a scene package from native viewer files, rendered images and evidence artifacts."""

    try:
        _validate_choice(format, {"text", "json"}, "format")
        _validate_choice(template, {"auto", *available_templates()}, "template")
        native_inputs = _validated_native_inputs(scene, native, blank=blank, image=image, artifact=artifact)
        initial_template = "simple-structure-view" if template == "auto" else template
        pkg = init_package(
            native=native_inputs,
            image=image,
            artifacts=artifact,
            out=out,
            template=initial_template,
            title=title,
            force=force,
            blank=blank,
        )
        resolved_template = _resolve_auto_template(template, pkg.semantic_layer)
        if resolved_template != initial_template:
            pkg.semantic_layer.package.profile = resolved_template
            pkg.save()
            existing_tasks = [
                task
                for task in read_completion_tasks(pkg.root)
                if not task.id.startswith(f"task:{initial_template}:")
            ]
            write_completion_tasks(
                pkg.root,
                _merge_tasks(existing_tasks, completion_tasks_for_template(resolved_template)),
            )
        answers_path = pkg.root / "answers.yml"
        _write_answers_template_if_missing(answers_path, pkg.semantic_layer, resolved_template)
        payload = {
            "package": str(pkg.root),
            "semantic_layer": str(pkg.root / "semantic_layer.json"),
            "answers": str(answers_path),
            "profile": resolved_template,
        }
        if format == "json":
            typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            typer.echo(f"Created ClaimTrace scene package: {pkg.root}")
            typer.echo(f"Semantic layer: {pkg.root / 'semantic_layer.json'}")
            typer.echo(f"Package-aware answers template: {answers_path}")
            typer.echo(f"Completion profile: {resolved_template}")
            typer.echo("Static import only: viewer scripts were not executed; remote resources were recorded, not fetched.")
            init_tasks = read_completion_tasks(pkg.root)
            required_task_count = sum(1 for task in init_tasks if task.status == "open" and task.blocking)
            optional_task_count = sum(1 for task in init_tasks if task.status == "open" and not task.blocking)
            observed = len(pkg.semantic_layer.observed_scene_operations)
            if observed:
                typer.echo(f"Observed scene operations: {observed}")
            raw_count = len(pkg.semantic_layer.raw_native_observations)
            if raw_count:
                typer.echo(f"Items needing author review: {raw_count} (run inspect to see locations and reasons)")
            for warning in _import_warning_lines(pkg.semantic_layer):
                typer.echo(f"Import note: {warning}")
            for line in _resource_hint_lines(pkg.semantic_layer, pkg.root):
                typer.echo(line)
            if required_task_count or optional_task_count:
                typer.echo(
                    f"Completion prompts: {required_task_count} required, {optional_task_count} optional review"
                )
            typer.echo("")
            typer.echo("Next:")
            typer.echo(f"  claimtrace inspect {_quoted_path(pkg.root)}")
            typer.echo(f"  Edit {_quoted_path(answers_path)} in your text editor.")
            typer.echo("  Fill the claim first; describe only evidence and color/label meanings you can support.")
            typer.echo(
                f"  claimtrace complete {_quoted_path(pkg.root)} --check-answers {_quoted_path(answers_path)}"
            )
            typer.echo(f"  claimtrace complete {_quoted_path(pkg.root)} --answers {_quoted_path(answers_path)}")
    except Exception as exc:
        _handle_error(exc)


@app.command(rich_help_panel="Main workflow")
def inspect(
    package: Path = typer.Argument(Path("."), help="ClaimTrace package directory."),
    format: str = typer.Option("text", "--format", help=TEXT_JSON_HELP),
) -> None:
    """Show what ClaimTrace recognized, what stayed raw and what still needs input."""

    try:
        _validate_choice(format, {"text", "json"}, "format")
        package = _resolve_package_argument(package)
        pkg = load_package(package)
        extraction_path = pkg.root / "semantic" / "extraction_report.json"
        extraction = json.loads(extraction_path.read_text(encoding="utf-8")) if extraction_path.exists() else {}
        tasks = read_completion_tasks(pkg.root)
        payload = {
            "package_id": pkg.semantic_layer.package.package_id,
            "artifacts": [artifact.model_dump(mode="json") for artifact in pkg.semantic_layer.artifacts],
            "facts": extraction.get("facts", []),
            "completion_tasks": [task.model_dump(mode="json") for task in tasks],
            "observed_scene_operations": [
                operation.model_dump(mode="json") for operation in pkg.semantic_layer.observed_scene_operations
            ],
            "native_references": [
                reference.model_dump(mode="json") for reference in pkg.semantic_layer.native_references
            ],
            "resource_references": [
                reference.model_dump(mode="json") for reference in pkg.semantic_layer.resource_references
            ],
            "raw_native_observations": [
                observation.model_dump(mode="json") for observation in pkg.semantic_layer.raw_native_observations
            ],
            "visual_encoding_semantics": [
                item.model_dump(mode="json") for item in pkg.semantic_layer.visual_encoding_semantics
            ],
            "mvsx_inventories": [
                inventory.model_dump(mode="json") for inventory in pkg.semantic_layer.mvsx_inventories
            ],
        }
        if format == "json":
            typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        table = Table(title=f"ClaimTrace package {payload['package_id']}")
        table.add_column("Artifact ID")
        table.add_column("Role")
        table.add_column("Path/URL")
        table.add_column("SHA256")
        for artifact in pkg.semantic_layer.artifacts:
            table.add_row(
                artifact.id,
                artifact.role.value,
                artifact.path or artifact.url or "",
                (artifact.sha256 or "")[:16],
            )
        console.print(table)
        typer.echo(f"Facts: {len(payload['facts'])}")
        for warning in _import_warning_lines(pkg.semantic_layer):
            typer.echo(f"Import note: {warning}")
        open_tasks = sum(1 for task in tasks if task.status == "open")
        typer.echo(f"Open questions: {open_tasks}")
        if open_tasks:
            for task in [item for item in tasks if item.status == "open"][:4]:
                label = "required" if task.blocking else "optional"
                typer.echo(f"  [{label} / {task.section}] {task.question}")
            if open_tasks > 4:
                typer.echo(f"  ... {open_tasks - 4} more. Use --format json for the full list.")
        typed = pkg.semantic_layer
        if typed.observed_scene_operations:
            typer.echo(f"Observed scene operations: {len(typed.observed_scene_operations)}")
            typer.echo("Recognized scene operations:")
            for line in _operation_summary_lines(typed):
                typer.echo(f"  {line}")
        visual_review = _visual_review_lines(typed)
        if visual_review:
            typer.echo("")
            typer.echo("Visual meanings to review:")
            for line in visual_review:
                typer.echo(f"  {line}")
            typer.echo(
                "  In answers.yml choose: confirm/edit the meaning, mark presentation only, or set claim_critical: false."
            )
        if typed.native_references:
            typer.echo(f"Native references: {len(typed.native_references)}")
        if typed.resource_references:
            typer.echo("Referenced resources:")
            for line in _resource_summary_lines(typed):
                typer.echo(f"  {line}")
        if typed.raw_native_observations:
            typer.echo(f"Needs author review: {len(typed.raw_native_observations)} raw/native items")
            for line in _raw_summary_lines(typed):
                typer.echo(f"  {line}")
        if typed.mvsx_inventories:
            typer.echo("MolViewSpec archive inventory:")
            for line in _inventory_summary_lines(typed):
                typer.echo(f"  {line}")
        if open_tasks:
            typer.echo("")
            typer.echo("Next:")
            template = _profile_for_next_command(pkg.semantic_layer)
            answers_path = pkg.root / "answers.yml"
            if answers_path.exists():
                typer.echo(f"  Edit {_quoted_path(answers_path)} in your text editor.")
            else:
                answers_path = _next_available_answers_path(pkg.root / "answers.new.yml")
                typer.echo(
                    "  Create a package-aware draft without replacing an edited file: "
                    f"claimtrace complete {_quoted_path(pkg.root)} --template {template} --emit-template "
                    f"> {_quoted_path(answers_path)}"
                )
            typer.echo(
                f"  claimtrace complete {_quoted_path(pkg.root)} --check-answers {_quoted_path(answers_path)}"
            )
    except Exception as exc:
        _handle_error(exc)


@app.command(
    rich_help_panel="Main workflow",
    epilog=(
        "Examples:\n\n"
        '  claimtrace complete "scene-package" --emit-template\n\n'
        '  claimtrace complete "scene-package" --check-answers "scene-package/answers.yml"\n\n'
        '  claimtrace complete "scene-package" --answers "scene-package/answers.yml"'
    ),
)
def complete(
    package: Path = typer.Argument(Path("."), help="ClaimTrace package directory."),
    template: str = typer.Option("auto", "--template", help=TEMPLATE_HELP),
    section: Optional[str] = typer.Option(None, "--section", help="Only work on one section: claim, entities, scene, evidence, uncertainty or reuse."),
    emit_template: bool = typer.Option(False, "--emit-template", help="Print a package-aware answers.yml template."),
    answers: Optional[Path] = typer.Option(None, "--answers", help="answers.yml file to apply."),
    check_answers_file: Optional[Path] = typer.Option(None, "--check-answers", help="Validate answers.yml without applying it."),
    no_input: bool = typer.Option(False, "--no-input", help="Do not prompt; refresh tasks or apply provided answers only."),
) -> None:
    """Create, check or apply answers.yml for figure claims, caveats and visual meanings."""

    try:
        _validate_choice(template, {"auto", *available_templates()}, "template")
        if section is not None:
            _validate_choice(section, SECTION_CHOICES, "section")
        action_count = sum(bool(action) for action in (emit_template, check_answers_file, answers))
        if action_count > 1:
            raise ValueError(
                "Choose only one completion action: --emit-template, --check-answers, or --answers."
            )
        package = _resolve_package_argument(package)
        pkg = load_package(package)
        template = _resolve_auto_template(template, pkg.semantic_layer)
        if emit_template:
            typer.echo(dump_package_answer_template(pkg.semantic_layer, template))
            return
        if check_answers_file:
            if not check_answers_file.exists():
                raise ValueError(
                    f"Answer file not found: {_quoted_path(check_answers_file)}. "
                    f"Edit the package template {_quoted_path(pkg.root / 'answers.yml')} or create a new comparison file."
                )
            data = load_answers(check_answers_file)
            problems = check_answers(
                data,
                pkg.semantic_layer,
                root=pkg.root,
                answer_base=check_answers_file.parent,
            )
            if problems:
                for problem in problems:
                    typer.echo(f"Please update answers.yml: {problem}", err=True)
                _echo_answer_fix_tip(pkg.root, check_answers_file, template)
                raise typer.Exit(1)
            typer.echo("Answer file structure, paths and package anchors match this package.")
            typer.echo("Archive validation will still check required package context and author confirmations.")
            typer.echo(
                f"Next: claimtrace complete {_quoted_path(pkg.root)} --answers "
                f"{_quoted_path(check_answers_file)}"
            )
            return
        if answers:
            if not answers.exists():
                raise ValueError(
                    f"Answer file not found: {_quoted_path(answers)}. "
                    f"Edit the package template {_quoted_path(pkg.root / 'answers.yml')} first."
                )
            data = load_answers(answers)
            problems = check_answers(data, pkg.semantic_layer, root=pkg.root, answer_base=answers.parent)
            if problems:
                for problem in problems:
                    typer.echo(f"Please update answers.yml: {problem}", err=True)
                _echo_answer_fix_tip(pkg.root, answers, template)
                raise typer.Exit(1)
            apply_answers(pkg.root, pkg.semantic_layer, data, answer_base=answers.parent)
            pkg.save()
            _update_completion_task_statuses(pkg.root, completed_answer_sections(data))
            typer.echo(f"Applied answers: {pkg.root / 'semantic_layer.json'}")
            _echo_remaining_completion_questions(pkg.root)
            typer.echo(f"Next: claimtrace validate {_quoted_path(pkg.root)} --mode draft --format text")
            return
        tasks = completion_tasks_for_template(template)
        if section:
            tasks = [task for task in tasks if task.section == section]
        if no_input:
            write_completion_tasks(pkg.root, _merge_tasks(read_completion_tasks(pkg.root), tasks))
            open_count = sum(1 for task in read_completion_tasks(pkg.root) if task.status == "open")
            typer.echo(f"Completion questions refreshed; {open_count} open question(s) remain.")
            answers_path = pkg.root / "answers.yml"
            created = _write_answers_template_if_missing(answers_path, pkg.semantic_layer, template)
            verb = "Created" if created else "Preserved"
            typer.echo(f"{verb} package-aware answers file: {answers_path}")
            typer.echo(f"Next: Edit {_quoted_path(answers_path)} in your text editor.")
            return
        needs_structured_answers = _has_complex_interactive_answers(pkg.semantic_layer) or (
            template == "ligand-binding-pose"
        )
        if needs_structured_answers and (
            section is None or section in {"entities", "scene", "evidence", "uncertainty"}
        ):
            answers_path = pkg.root / "answers.yml"
            created = _write_answers_template_if_missing(answers_path, pkg.semantic_layer, template)
            verb = "Created" if created else "Preserved"
            typer.echo(
                "This scene contains operation-linked or raw native details that generic prompts cannot update safely.",
                err=True,
            )
            typer.echo(
                f"{verb} {_quoted_path(answers_path)} with its operation_ids, native_ref_ids and raw_ids intact.",
                err=True,
            )
            typer.echo(f"Edit {_quoted_path(answers_path)} in your text editor, then run:", err=True)
            typer.echo(
                f"  claimtrace complete {_quoted_path(pkg.root)} --check-answers {_quoted_path(answers_path)}",
                err=True,
            )
            raise typer.Exit(1)
        template_text = dump_package_answer_template(pkg.semantic_layer, template)
        base_answers = _interactive_answer_base(pkg.root / "answers.yml", template_text)
        answers_data = _prompt_for_answers(tasks, pkg.semantic_layer, base_answers)
        draft_path = _save_interactive_answers_draft(pkg.root, answers_data, template_text)
        typer.echo(f"Saved interactive answers draft: {draft_path}")
        problems = check_answers(answers_data, pkg.semantic_layer, root=pkg.root, answer_base=pkg.root)
        if problems:
            for problem in problems:
                typer.echo(f"Please update answers.yml: {problem}", err=True)
            typer.echo(f"Edit the saved draft {_quoted_path(draft_path)}; your responses were not discarded.", err=True)
            _echo_answer_fix_tip(pkg.root, draft_path, template)
            raise typer.Exit(1)
        apply_answers(pkg.root, pkg.semantic_layer, answers_data, answer_base=pkg.root)
        pkg.save()
        _update_completion_task_statuses(
            pkg.root,
            completed_answer_sections(answers_data),
            None if section is None else {task.id for task in tasks},
        )
        typer.echo(f"Completed {pkg.root / 'semantic_layer.json'}")
        _echo_remaining_completion_questions(pkg.root)
    except typer.Exit:
        raise
    except Exception as exc:
        _handle_error(exc)


@app.command("set", rich_help_panel="Advanced")
def set_value(
    package: Path = typer.Argument(..., help="ClaimTrace package directory."),
    json_pointer: str = typer.Argument(..., help="JSON Pointer into semantic_layer.json."),
    value: str = typer.Argument(..., help="New value. JSON scalars/objects are accepted."),
) -> None:
    """Set a value in semantic_layer.json by JSON Pointer."""

    try:
        package = _resolve_package_argument(package)
        pkg = load_package(package)
        data = pkg.semantic_layer.model_dump(mode="json", exclude_none=True)
        _set_json_pointer(data, json_pointer, _parse_value(value))
        pkg.semantic_layer = pkg.semantic_layer.model_validate(data)
        pkg.semantic_layer.add_activity("json_pointer_set", f"Set {json_pointer}.", json_pointer=json_pointer)
        pkg.save()
        typer.echo(f"Updated {json_pointer}")
    except Exception as exc:
        _handle_error(exc)


@app.command("add-artifact", rich_help_panel="Main workflow")
def add_artifact(
    package: Path = typer.Argument(..., help="ClaimTrace package directory."),
    path: Path = typer.Argument(..., help="Artifact path to add."),
    role: Optional[str] = typer.Option(None, "--role", help="Artifact role, e.g. structure, render_image, contact_table, map or evidence_document."),
    detached: bool = typer.Option(False, "--detached", help="Record metadata without copying the payload into the package."),
) -> None:
    """Add a local file to a package and compute its fixity metadata."""

    try:
        if role is not None:
            _validate_choice(role, ARTIFACT_ROLE_CHOICES, "artifact role")
        package = _resolve_package_argument(package)
        if not path.exists():
            raise ValueError(
                f"Input file not found: {path}. Run from the directory containing the file or pass an absolute path."
                f"{windows_path_hint(path)}"
            )
        pkg = load_package(package)
        artifact = pkg.add_artifact(path, role=role, detached=detached)
        typer.echo(f"Added {artifact.id} as {artifact.role.value}")
    except Exception as exc:
        _handle_error(exc)


@app.command(rich_help_panel="Main workflow")
def validate(
    package: Path = typer.Argument(Path("."), help="ClaimTrace package directory."),
    mode: str = typer.Option("draft", "--mode", help=MODE_HELP),
    format: str = typer.Option("text", "--format", help="Output format. Choices: text, json, md."),
    out: Optional[Path] = typer.Option(None, "--out", help="Write validation report JSON to this path."),
) -> None:
    """Check package health before sharing: files, paths, references, privacy and confirmations."""

    try:
        _validate_choice(mode, {"draft", "internal", "share", "archive"}, "mode")
        _validate_choice(format, {"text", "json", "md"}, "format")
        package = _resolve_package_argument(package)
        report = validate_package(package, mode=mode)
        if out:
            _validate_report_output_path(package, out)
            write_json(out, report.model_dump(mode="json", exclude_none=True))
        if format == "json":
            typer.echo(json.dumps(report.model_dump(mode="json", exclude_none=True), indent=2))
        elif format == "md":
            typer.echo(_report_markdown(report.model_dump(mode="json")))
        else:
            typer.echo(_report_text(report.model_dump(mode="json"), package))
        if report.overall_status == "fail":
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as exc:
        _handle_error(exc)


@app.command(rich_help_panel="Main workflow")
def export(
    package: Path = typer.Argument(Path("."), help="ClaimTrace package directory."),
    out: Path = typer.Option(..., "--out", help="Output directory or zip path."),
    mode: str = typer.Option("archive", "--mode", help=MODE_HELP),
    zip: bool = typer.Option(False, "--zip", help="Write a zip archive; .zip --out paths do this automatically."),
    force: bool = typer.Option(False, "--force", help="Replace an existing ClaimTrace output path; refuses unsafe targets."),
    no_input: bool = typer.Option(
        False,
        "--no-input",
        help="Compatibility option; export is already non-interactive.",
        hidden=True,
    ),
) -> None:
    """Validate and write a shareable package directory or zip archive."""

    try:
        _validate_choice(mode, {"draft", "internal", "share", "archive"}, "mode")
        package = _resolve_package_argument(package)
        zip_output = zip or out.suffix == ".zip"
        result = api_export_package(package, out, mode=mode, zip_output=zip_output, force=force)
        if zip_output:
            typer.echo(f"Exported zip package: {result}")
            typer.echo(f"Extract {_quoted_path(result)} with your file manager, then validate the extracted folder:")
            typer.echo(
                f"  claimtrace validate \"<extracted package folder>\" --mode {mode} --format text"
            )
        else:
            typer.echo(f"Exported package directory: {result}")
            typer.echo(
                f"Check it with: claimtrace validate {_quoted_path(result)} --mode {mode} --format text"
            )
    except ValidationError as exc:
        typer.echo(str(exc), err=True)
        typer.echo(
            f"Next: claimtrace validate {_quoted_path(package)} --mode {mode} --format text",
            err=True,
        )
        raise typer.Exit(1)
    except Exception as exc:
        _handle_error(exc)


@app.command(rich_help_panel="Advanced")
def schema(
    report: bool = typer.Option(False, "--report", help="Emit validation-report schema instead of CAL schema."),
    format: str = typer.Option("json", "--format", help="Output format. Choices: json."),
    out: Optional[Path] = typer.Option(None, "--out", help="Write schema to this path."),
) -> None:
    """Emit JSON Schema for semantic_layer.json or validation_report.json."""

    try:
        _validate_choice(format, {"json"}, "format")
        data = validation_report_schema() if report else semantic_layer_schema()
        if out:
            write_json(out, data)
        typer.echo(json.dumps(data, indent=2))
    except Exception as exc:
        _handle_error(exc)


@app.command(rich_help_panel="Experimental")
def redact(
    package: Path = typer.Argument(..., help="ClaimTrace package directory."),
    out: Path = typer.Option(..., "--out", help="Output redacted package directory."),
    mode: str = typer.Option("share", "--mode", help="Export mode for redacted package."),
) -> None:
    """Experimental: create a share package with a redaction summary."""

    try:
        package = _resolve_package_argument(package)
        result = api_export_package(package, out, mode=mode, zip_output=False)
        write_json(
            result / "redaction_summary.json",
            {
                "stability": "experimental",
                "summary": "Base privacy gates were applied. Full semantic redaction is experimental.",
            },
        )
        typer.echo(f"Experimental redacted package written to {result}")
    except Exception as exc:
        _handle_error(exc)


@app.command(rich_help_panel="Experimental")
def migrate(
    package: Path = typer.Argument(..., help="ClaimTrace package directory."),
    target_schema: str = typer.Option("0.1.0", "--target-schema", help="Target CAL schema version."),
) -> None:
    """Experimental: no-op migration surface for schema 0.1.0."""

    try:
        package = _resolve_package_argument(package)
        pkg = load_package(package)
        if pkg.semantic_layer.schema_version != target_schema:
            raise SchemaVersionError(
                f"Only no-op migration to {pkg.semantic_layer.schema_version} is available in v0.1.0."
            )
        pkg.semantic_layer.add_activity("migrate", "No-op schema migration check.", target_schema=target_schema)
        pkg.save()
        typer.echo(f"No migration needed for schema {target_schema}.")
    except Exception as exc:
        _handle_error(exc)


def _prompt_for_answers(tasks, semantic: Any, base_answers: dict[str, Any]) -> dict[str, Any]:
    answers = json.loads(json.dumps(base_answers))
    for task in tasks:
        prompt = f"{task.question} ({task.examples[0] if task.examples else 'unknown'})"
        answer = typer.prompt(prompt, default="unknown")
        if task.section == "claim":
            claim = answers.setdefault("claim", {})
            if not isinstance(claim, dict):
                claim = {}
                answers["claim"] = claim
            claim["claim_text"] = answer
            claim.setdefault("claim_type", _profile_claim_type(semantic))
            claim["figure_ref"] = typer.prompt("Figure or panel label", default="Figure 1A")
            claim.setdefault("scope", "panel")
        elif task.section == "entities":
            if answer.strip().lower() not in {"", "unknown", "not_applicable"}:
                entities = answers.setdefault("entities", [])
                if not isinstance(entities, list):
                    entities = []
                    answers["entities"] = entities
                entities.append(
                    {
                        "id": f"entity:interactive:{len(entities) + 1}",
                        "entity_type": "author_defined",
                        "label": answer,
                        "stable_identity": "unknown",
                        "claim_critical": True,
                        "review_status": "confirmed",
                        "extensions": {"captured_by": "claimtrace complete interactive prompt"},
                    }
                )
        elif task.section == "evidence":
            evidence = answers.setdefault("evidence", [])
            if not isinstance(evidence, list):
                evidence = []
                answers["evidence"] = evidence
            if evidence and isinstance(evidence[0], dict):
                evidence_item = evidence[0]
                evidence_item["result_summary"] = answer
            else:
                evidence_item = {"evidence_kind": "manual_rationale", "result_summary": answer}
                evidence.insert(0, evidence_item)
            roles = _source_roles_for_prompt(semantic)
            if roles:
                evidence_item["source_artifact_roles"] = roles
            method = str(evidence_item.get("method_name", "")).strip().lower()
            if not method or method in {"unknown", "todo", "tbd"} or method.startswith("todo:"):
                evidence_item["method_name"] = "Author-provided visual review"
        elif task.section == "scene":
            scene = answers.setdefault("scene", {})
            if not isinstance(scene, dict):
                scene = {}
                answers["scene"] = scene
            scene["notes"] = answer
            scene.setdefault("color_meanings", {})
            scene.setdefault("label_meanings", {})
        elif task.section == "uncertainty":
            uncertainty = answers.setdefault("uncertainty", {})
            if not isinstance(uncertainty, dict):
                uncertainty = {}
                answers["uncertainty"] = uncertainty
            uncertainty["statement"] = answer
        elif task.section == "reuse":
            reuse = answers.setdefault("reuse", {})
            if not isinstance(reuse, dict):
                reuse = {}
                answers["reuse"] = reuse
            reuse["license"] = answer
    return answers


def _profile_claim_type(semantic: Any) -> str:
    profile = getattr(semantic.package, "profile", "")
    if profile == "simple-structure-view":
        return "simple_structure_view"
    if profile == "ligand-binding-pose":
        return "ligand_binding_pose"
    return "unknown"


def _source_roles_for_prompt(semantic: Any) -> list[str]:
    return sorted(
        {
            artifact.role.value
            for artifact in getattr(semantic, "artifacts", [])
            if artifact.role.value
            in {
                "native_script",
                "chimerax_script",
                "molviewspec",
                "render_image",
                "structure",
                "map",
                "contact_table",
                "validation_report",
                "evidence_document",
            }
        }
    )


def _validated_native_inputs(
    scene: Path | None,
    native: list[Path] | None,
    *,
    blank: bool,
    image: list[Path] | None,
    artifact: list[Path] | None,
) -> list[Path]:
    native_paths = list(native or [])
    if scene is not None and native_paths:
        raise ValueError(
            "The positional scene and --native cannot be used together. "
            "Use `claimtrace init <scene-file>` for one scene, or repeat --native for multiple scenes."
        )
    if scene is not None:
        native_paths = [scene]
    if blank and (native_paths or image or artifact):
        raise ValueError("--blank cannot be combined with a scene, --native, --image or --artifact.")
    for path in native_paths:
        suffix = path.suffix.lower()
        if suffix not in NATIVE_SCENE_SUFFIXES:
            allowed = ", ".join(sorted(NATIVE_SCENE_SUFFIXES))
            raise ValueError(
                f"Unsupported native scene file {_quoted_path(path)}. "
                f"Expected one of: {allowed}. Use --image or --artifact for other file types."
            )
    return native_paths


def _resolve_auto_template(requested: str, semantic: Any) -> str:
    if requested != "auto":
        return requested
    if _looks_like_ligand_binding_package(semantic):
        return "ligand-binding-pose"
    profile = str(getattr(getattr(semantic, "package", None), "profile", ""))
    if profile in available_templates():
        return profile
    return "simple-structure-view"


def _looks_like_ligand_binding_package(semantic: Any) -> bool:
    if any(getattr(artifact.role, "value", artifact.role) == "contact_table" for artifact in semantic.artifacts):
        return True
    values: list[Any] = []
    for field in (
        "selections",
        "observed_scene_operations",
        "native_references",
        "resource_references",
    ):
        for item in getattr(semantic, field, []):
            if hasattr(item, "model_dump"):
                values.append(item.model_dump(mode="json", exclude_none=True))
            else:
                values.append(str(item))
    for artifact in getattr(semantic, "artifacts", []):
        values.append({"path": artifact.path, "role": artifact.role.value})
    searchable = json.dumps(values, ensure_ascii=False).lower()
    binding_context = any(
        clue in searchable
        for clue in ("pocket", "binding-site", "binding_site", "binding site", "contact_table", "contacts.csv")
    )
    ligand_context = any(clue in searchable for clue in ("ligand", "auth_comp_id", " resn lig"))
    measurement_context = any(
        getattr(operation, "operation", "") == "measurement_intent"
        or str(getattr(operation, "details", {}).get("command", "")).lower() in {"contacts", "hbonds", "distance"}
        for operation in getattr(semantic, "observed_scene_operations", [])
    )
    return binding_context or (ligand_context and measurement_context)


def _write_answers_template_if_missing(path: Path, semantic: Any, template: str) -> bool:
    content = dump_package_answer_template(semantic, template)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
    except FileExistsError:
        return False
    return True


def _interactive_answer_base(path: Path, template_text: str) -> dict[str, Any]:
    if path.exists() and not path.is_symlink():
        try:
            data = load_answers(path)
            return json.loads(json.dumps(data))
        except (OSError, ValueError) as exc:
            typer.echo(
                f"Could not reuse {_quoted_path(path)} ({exc}); it will be preserved and a separate draft will be written.",
                err=True,
            )
    data = _simple_yaml.loads(template_text)
    if not isinstance(data, dict):  # pragma: no cover - generated templates are mappings
        raise ValueError("Generated answers template was not a mapping.")
    return data


def _save_interactive_answers_draft(root: Path, answers: dict[str, Any], original_template: str) -> Path:
    preferred = root / "answers.yml"
    content = "# ClaimTrace interactive answers draft\n" + _simple_yaml.dumps(answers)
    can_replace_generated = (
        preferred.exists()
        and not preferred.is_symlink()
        and preferred.read_text(encoding="utf-8") == original_template
    )
    if not preferred.exists() or can_replace_generated:
        preferred.write_text(content, encoding="utf-8", newline="\n")
        return preferred
    draft = _next_available_answers_path(root / "answers.draft.yml")
    with draft.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
    return draft


def _next_available_answers_path(preferred: Path) -> Path:
    if not preferred.exists() and not preferred.is_symlink():
        return preferred
    index = 2
    while True:
        candidate = preferred.with_name(f"{preferred.stem}.{index}{preferred.suffix}")
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
        index += 1


def _update_completion_task_statuses(
    root: Path,
    completed_sections: set[str],
    task_ids: set[str] | None = None,
) -> None:
    tasks = read_completion_tasks(root)
    for task in tasks:
        if (task_ids is None or task.id in task_ids) and task.status != "waived":
            task.status = "answered" if task.section in completed_sections else "open"
    write_completion_tasks(root, tasks)


def _echo_remaining_completion_questions(root: Path) -> None:
    open_count = sum(1 for task in read_completion_tasks(root) if task.status == "open")
    if open_count:
        typer.echo(
            f"Kept {open_count} unanswered completion question(s) open. "
            f"Review them with: claimtrace inspect {_quoted_path(root)}"
        )


def _has_complex_interactive_answers(semantic: Any) -> bool:
    return any(
        (
            getattr(semantic, "observed_scene_operations", []),
            getattr(semantic, "native_references", []),
            getattr(semantic, "raw_native_observations", []),
            getattr(semantic, "resource_references", []),
        )
    )


def _quoted_path(path: Path | str) -> str:
    """Return a readable, copyable double-quoted path for command hints."""

    return '"' + str(path).replace('"', '\\"') + '"'


def _operation_summary_lines(semantic: Any, limit: int = 6) -> list[str]:
    operations = sorted(
        enumerate(getattr(semantic, "observed_scene_operations", [])),
        key=lambda item: (_operation_display_priority(item[1]), item[0]),
    )
    lines: list[str] = []
    for _, operation in operations[:limit]:
        location = _source_location_text(getattr(operation, "source_location", None), semantic)
        annotation = getattr(operation, "auto_annotation", None)
        if not annotation:
            target = f" {operation.target}" if getattr(operation, "target", "") else ""
            annotation = f"{operation.operation}{target}"
        line = f"{location}: {annotation}" if location else annotation
        candidate = getattr(operation, "candidate_meaning", None)
        if candidate:
            line += f" Tool suggestion, not confirmed: {candidate}"
        lines.append(line)
    if len(operations) > limit:
        lines.append(f"... {len(operations) - limit} more operation(s). Use --format json for full details.")
    return lines


def _operation_display_priority(operation: Any) -> int:
    """Put figure-relevant molecular observations before global viewer configuration."""

    if getattr(operation, "needs_author_confirmation", False) or getattr(operation, "candidate_meaning", None):
        return 0
    operation_name = str(getattr(operation, "operation", ""))
    if operation_name in {
        "loaded",
        "selected",
        "represented",
        "displayed",
        "shown",
        "hidden",
        "colored",
        "labeled",
        "measurement_intent",
        "transparency_changed",
        "atoms_removed",
    }:
        return 1
    target = str(getattr(operation, "target", "")).strip().lower()
    if operation_name == "configured" and target in {"", "global", "all", "*"}:
        return 9
    if operation_name == "configured":
        return 7
    return 4


def _visual_review_lines(semantic: Any, limit: int = 6) -> list[str]:
    confirmed_operation_ids = {
        operation_id
        for item in getattr(semantic, "visual_encoding_semantics", [])
        if getattr(item, "meaning_status", None)
        in {
            MeaningStatus.user_confirmed_meaning,
            MeaningStatus.user_declared_no_scientific_meaning,
        }
        for operation_id in getattr(item, "operation_ids", [])
    }
    operations = [
        operation
        for operation in getattr(semantic, "observed_scene_operations", [])
        if _operation_needs_visual_review(operation, confirmed_operation_ids)
    ]
    lines: list[str] = []
    for operation in operations[:limit]:
        location = _source_location_text(getattr(operation, "source_location", None), semantic)
        prefix = f"{location}: " if location else ""
        annotation = getattr(operation, "auto_annotation", None)
        if not annotation:
            target = f" {operation.target}" if getattr(operation, "target", "") else ""
            annotation = f"{operation.operation}{target}"
        suggestion = getattr(operation, "candidate_meaning", None) or "author meaning needed"
        lines.append(f"{prefix}{operation.operation_id}: {annotation}; suggestion: {suggestion}")
    if len(operations) > limit:
        lines.append(f"... {len(operations) - limit} more visual item(s). Use --format json for full details.")
    return lines


def _operation_needs_visual_review(operation: Any, confirmed_operation_ids: set[str]) -> bool:
    if getattr(operation, "operation_id", "") in confirmed_operation_ids:
        return False
    if getattr(operation, "claim_critical", None) == ClaimCriticalStatus.false:
        return False
    candidate = str(getattr(operation, "candidate_meaning", "") or "")
    if (
        candidate
        and "no scientific meaning is inferred" in candidate.lower()
        and not getattr(operation, "needs_author_confirmation", False)
    ):
        return False
    meaning_status = getattr(operation, "meaning_status", None)
    return bool(
        getattr(operation, "candidate_meaning", None)
        or getattr(operation, "needs_author_confirmation", False)
        or meaning_status
        in {
            MeaningStatus.requires_user_completion,
            MeaningStatus.tool_suggested_meaning,
            MeaningStatus.unresolved_claim_critical,
        }
    )


def _resource_summary_lines(semantic: Any, limit: int = 6) -> list[str]:
    resources = list(getattr(semantic, "resource_references", []))
    lines: list[str] = []
    for resource in resources[:limit]:
        location = _source_location_text(getattr(resource, "source_location", None), semantic)
        attached = (
            "attached"
            if resource_matches_artifact(semantic, resource.uri, resource_ref=resource)
            else "not attached"
        )
        if resource.uri_kind == "remote":
            attached = "remote recorded, not fetched"
        elif resource.uri_kind == "archive_member" and resource.fixity_status == "available":
            attached = "embedded in archive; checksum recorded"
        elif resource.uri_kind == "data" and resource.fixity_status == "available":
            attached = "embedded in scene"
        elif resource.uri_kind == "missing_archive_member":
            attached = "missing from archive"
        text = f"{resource_uri_summary(resource.uri)} ({resource.uri_kind}, {attached})"
        lines.append(f"{location}: {text}" if location else text)
    if len(resources) > limit:
        lines.append(f"... {len(resources) - limit} more resource reference(s). Use --format json for full details.")
    return lines


def _raw_summary_lines(semantic: Any, limit: int = 5) -> list[str]:
    raw_items = list(getattr(semantic, "raw_native_observations", []))
    lines: list[str] = []
    for item in raw_items[:limit]:
        location = _source_location_text(getattr(item, "source_location", None), semantic)
        snippet = " ".join(str(getattr(item, "native_text", "")).split())
        if len(snippet) > 110:
            snippet = snippet[:107] + "…"
        reason = _friendly_raw_reason(str(getattr(item, "reason", "needs review")))
        prefix = f"{location}: " if location else ""
        lines.append(f"{prefix}{reason} — {snippet or 'native item preserved'}")
    if len(raw_items) > limit:
        lines.append(f"... {len(raw_items) - limit} more raw/native item(s). Use --format json for full details.")
    return lines


def _import_warning_lines(semantic: Any, limit: int = 5) -> list[str]:
    warnings: list[str] = []
    provenance = getattr(semantic, "provenance", None)
    for activity in getattr(provenance, "activities", []):
        values = getattr(activity, "extensions", {}).get("warnings", [])
        for value in values if isinstance(values, list) else []:
            text = str(value)
            if text not in warnings:
                warnings.append(text)
    if len(warnings) > limit:
        return [*warnings[:limit], f"... {len(warnings) - limit} more import note(s) in semantic_layer.json"]
    return warnings


def _friendly_raw_reason(reason: str) -> str:
    labels = {
        "dynamic_command_boundary": "dynamic command preserved; not executed",
        "executable_resource_boundary": "executable resource reference preserved; not opened",
        "unsupported_command": "unsupported command preserved for review",
        "ambiguous_abbreviation": "ambiguous command abbreviation",
        "unknown_mvs_node": "unknown MolViewSpec node preserved for review",
        "invalid_mvs_child": "invalid MolViewSpec child preserved",
        "invalid_mvs_children": "MolViewSpec children has the wrong type",
        "invalid_mvs_snapshot": "invalid MolViewSpec snapshot preserved",
        "invalid_mvs_snapshot_root": "snapshot has no valid MolViewSpec root",
        "nonstandard_mvsx_scene_entry": "nonstandard MVSX scene entry; static review only",
        "unterminated_quote": "unterminated quote",
    }
    if reason in labels:
        return labels[reason]
    if reason.startswith("missing_required_mvs_params:"):
        return "MolViewSpec node is missing required parameter(s): " + reason.split(":", 1)[1]
    if reason.startswith("invalid_mvs_parent:"):
        return "invalid MolViewSpec parent/child placement: " + reason.split(":", 1)[1]
    return reason.replace("_", " ")


def _inventory_summary_lines(semantic: Any, limit: int = 5) -> list[str]:
    lines: list[str] = []
    for inventory in list(getattr(semantic, "mvsx_inventories", []))[:limit]:
        referenced = [member for member in inventory.members if member.referenced]
        lines.append(
            f"entry {inventory.scene_entry or 'unknown'}; {len(inventory.members)} members; "
            f"{len(referenced)} referenced; {inventory.format_status}"
        )
        for member in referenced[:3]:
            digest = f", sha256 {member.sha256[:12]}…" if member.sha256 else ""
            lines.append(f"  {member.normalized_name}{digest}")
    if len(getattr(semantic, "mvsx_inventories", [])) > limit:
        lines.append("More archives are recorded in semantic_layer.json.")
    return lines


def _resource_hint_lines(semantic: Any, package: Path, limit: int = 6) -> list[str]:
    lines: list[str] = []
    for resource in list(getattr(semantic, "resource_references", []))[:limit]:
        if resource_matches_artifact(semantic, resource.uri, resource_ref=resource):
            continue
        location = _source_location_text(getattr(resource, "source_location", None), semantic)
        location_text = f" ({location})" if location else ""
        if resource.uri_kind in {"relative", "local"} and _is_safe_relative_hint(resource.uri):
            role = infer_role(Path(str(resource.uri))).value
            lines.append(f"Referenced local file not attached{location_text}: {resource.uri}")
            lines.append(
                "  Add the actual local file with: claimtrace add-artifact "
                f"{_quoted_path(package)} {_quoted_path(_example_local_path(resource.uri))} --role {role}"
            )
            lines.append(
                "  Run that command from the folder containing the file, or replace the filename with its real full path."
            )
        elif resource.uri_kind == "remote":
            lines.append(f"Remote resource recorded, not fetched{location_text}: {resource_uri_summary(resource.uri)}")
        elif resource.uri_kind == "missing_archive_member":
            lines.append(f"Referenced file is missing from the MVSX archive{location_text}: {resource_uri_summary(resource.uri)}")
            lines.append("  Rebuild the .mvsx with that file at the referenced archive path; an outside sibling file will not repair the archive.")
    return lines


def _example_local_path(uri: str) -> str:
    name = Path(str(uri).replace("\\", "/")).name or "file"
    return name


def _is_safe_relative_hint(uri: str) -> bool:
    path = Path(str(uri).replace("\\", "/"))
    return bool(path.parts) and not path.is_absolute() and ".." not in path.parts and ":" not in path.parts[0]


def _source_location_text(location: Any, semantic: Any | None = None) -> str:
    if not location:
        return ""
    artifact_label = ""
    artifact_id = getattr(location, "artifact_id", None)
    if semantic is not None and artifact_id:
        artifact = next(
            (item for item in getattr(semantic, "artifacts", []) if getattr(item, "id", None) == artifact_id),
            None,
        )
        artifact_path = getattr(artifact, "path", None)
        if artifact_path:
            artifact_label = f"{Path(str(artifact_path)).name} "
    source_path = getattr(location, "path", None)
    if source_path:
        artifact_label += f"[{source_path}] "
    line = getattr(location, "line", None)
    column = getattr(location, "column", None)
    if line is not None:
        return artifact_label + f"line {line}" + (f":{column}" if column is not None else "")
    pointer = getattr(location, "json_pointer", None)
    if pointer:
        return artifact_label + f"JSON {pointer}"
    path = getattr(location, "path", None)
    if path:
        return artifact_label.rstrip()
    return ""


def _set_json_pointer(data: Any, pointer: str, value: Any) -> None:
    if not pointer.startswith("/"):
        raise ValueError("JSON Pointer must start with '/'.")
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer.split("/")[1:]]
    target = data
    try:
        for part in parts[:-1]:
            if isinstance(target, list):
                target = target[int(part)]
            else:
                target = target[part]
        last = parts[-1]
        if isinstance(target, list):
            target[int(last)] = value
        else:
            target[last] = value
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise ValueError(f"JSON Pointer does not exist in semantic_layer.json: {pointer}") from exc


def _parse_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Validation Report",
        "",
        f"Overall status: `{report['overall_status']}`",
        f"Export mode: `{report.get('export_mode', 'draft')}`",
        "",
        "## Summary",
        "",
        f"- Claims: {len(report.get('claim_traceability_matrix', []))}",
        f"- Artifacts: {len(report.get('artifact_fixity', []))}",
        f"- Unresolved notes: {len(report.get('unresolved_list', []))}",
        f"- Human review notes: {len(report.get('human_review_required', []))}",
        "",
        "## Findings",
        "",
    ]
    findings = report.get("findings", [])
    if findings:
        for item in findings:
            lines.append(f"- **{item['severity']} {item['rule_id']}**: {item['message']}")
    else:
        lines.append("- No required updates found.")
    return "\n".join(lines) + "\n"


def _report_text(report: dict[str, Any], package: Path | str = "<package>") -> str:
    status = report["overall_status"]
    mode = report.get("export_mode", "draft")
    findings = [item for item in report.get("findings", []) if item.get("status") == "FAIL"]
    required = [
        item
        for item in findings
        if item.get("severity") == "ERROR" and mode in set(item.get("blocks_modes", []))
    ]
    recommended = [item for item in findings if item not in required]
    if not findings:
        zip_path = _default_zip_path(Path(package))
        lines = [
            f"pass: {mode} check is ready.",
            "No required updates found.",
            "Package checks passed for traceability, packaging, paths and required author confirmations.",
            "Tool-suggested visual meanings remain suggestions unless the author confirms them in answers.yml.",
            _validation_summary_line(report),
            f"Next: claimtrace export {_quoted_path(package)} --mode {mode} --out {_quoted_path(zip_path)}",
        ]
        return "\n".join(lines)
    if required:
        lines = [
            f"{mode} check is not ready yet: {len(required)} required update(s), {len(recommended)} recommended update(s).",
            "This check covers package context, traceability, paths and required confirmations.",
            "",
            f"Required before {mode}:",
        ]
        for item in required[:8]:
            lines.extend(_finding_action_lines(item))
        if len(required) > 8:
            lines.append(f"- {len(required) - 8} more required update(s). Use --format json for the full report.")
    else:
        lines = [
            f"{status}: no blocking updates for {mode}; {len(recommended)} recommended update(s).",
            "This check covers package context, traceability, paths and required confirmations.",
        ]
    if recommended:
        lines.extend(["", "Recommended:"])
        for item in recommended[:6]:
            lines.extend(_finding_action_lines(item))
        if len(recommended) > 6:
            lines.append(f"- {len(recommended) - 6} more recommended update(s). Use --format json for the full report.")
    lines.append("")
    if required:
        lines.append("Start with the Required list above.")
    elif recommended:
        lines.append("No blocking updates remain; review the Recommended list if this package needs a fuller handoff.")
    if _has_context_finding(findings):
        lines.extend(
            [
                "You usually do not need to edit semantic_layer.json directly.",
                f"For claim/context updates, edit {_quoted_path(_answers_path_for(Path(package)))}.",
                "Then: claimtrace complete "
                f"{_quoted_path(package)} --check-answers {_quoted_path(_answers_path_for(Path(package)))}",
                "Then: claimtrace complete "
                f"{_quoted_path(package)} --answers {_quoted_path(_answers_path_for(Path(package)))}",
            ]
        )
    return "\n".join(lines)


def _finding_action_lines(item: dict[str, Any]) -> list[str]:
    label = _friendly_finding_label(item)
    lines = [f"- {label} ({item['rule_id']}): {item['message']}"]
    pointer = item.get("json_pointer")
    edit_hint = _friendly_edit_hint(item)
    if edit_hint:
        lines.append(f"  Edit: {edit_hint}")
    elif pointer:
        lines.append(f"  Location: {pointer}")
    suggested = item.get("suggested_fix") or item.get("fix")
    if suggested:
        lines.append(f"  Next: {suggested}")
    for example in _friendly_example_lines(item):
        lines.append(f"  Tip: {example}")
    return lines


def _friendly_finding_label(item: dict[str, Any]) -> str:
    rule_id = str(item.get("rule_id", ""))
    if rule_id.startswith("CLAIM.BASIC"):
        return "Add claim context"
    if rule_id.startswith("SECURITY"):
        return "Redact before sharing"
    if "RESOURCE" in rule_id:
        return "Attach referenced file"
    if "FIXITY" in rule_id or "PATH" in rule_id:
        return "Fix file"
    if "EVIDENCE" in rule_id or "LIGAND" in rule_id:
        return "Add supporting file or note"
    if "VISUAL_ENCODING" in rule_id or "NATIVE" in rule_id or "SCENE" in rule_id:
        return "Add author context"
    if item.get("waivable"):
        return "Add context or record a reason"
    return "Fix package"


def _friendly_edit_hint(item: dict[str, Any]) -> str:
    rule_id = str(item.get("rule_id", ""))
    if rule_id.startswith("CLAIM.BASIC"):
        return "answers.yml -> claim.claim_text and claim.figure_ref"
    if rule_id.startswith("SCENE.VISUAL_ENCODING"):
        return "answers.yml -> scene_semantics_by_operation, using the operation id shown above"
    if rule_id.startswith("SCENE.MOLECULAR_IDENTITY"):
        return "answers.yml -> native_identity_mappings"
    if rule_id.startswith("SCENE.TARGET_RESOLUTION"):
        return "answers.yml -> native_identity_mappings.target_resolution_status"
    if rule_id.startswith("IMPORT.") and "RESOURCE" in rule_id:
        return "attach the referenced file with claimtrace add-artifact, or document why it stays detached"
    return ""


def _friendly_example_lines(item: dict[str, Any]) -> list[str]:
    rule_id = str(item.get("rule_id", ""))
    if rule_id.startswith("SCENE.VISUAL_ENCODING"):
        return [
            "Choose one in answers.yml: user_confirmed_meaning, user_declared_no_scientific_meaning, or claim_critical: false.",
            "Use `claimtrace inspect <package>` to see the operation id and the literal color/label observation.",
        ]
    if rule_id.startswith("CLAIM.BASIC"):
        return [
            "Edit the package's answers.yml, then fill claim.claim_text and claim.figure_ref."
        ]
    if rule_id.startswith("CLAIM.EVIDENCE") or rule_id.startswith("CLAIM.SIMPLE") or "LIGAND" in rule_id:
        return [
            "Attach the relevant file with `claimtrace add-artifact`, or reference it from evidence.source_artifact_paths in answers.yml."
        ]
    return []


def _echo_answer_fix_tip(package: Path, answers_path: Path, template: str) -> None:
    new_answers_path = _next_available_answers_path(package / "answers.new.yml")
    typer.echo(
        "Tip: keep the current answers file and generate a fresh comparison template with: "
        f"claimtrace complete {_quoted_path(package)} --template {template} --emit-template "
        f"> {_quoted_path(new_answers_path)}",
        err=True,
    )
    typer.echo(
        f"Next: edit {_quoted_path(answers_path)}, then rerun: claimtrace complete "
        f"{_quoted_path(package)} --check-answers {_quoted_path(answers_path)}",
        err=True,
    )
    typer.echo(
        f"Then apply it with: claimtrace complete {_quoted_path(package)} --answers "
        f"{_quoted_path(answers_path)}",
        err=True,
    )
    typer.echo(
        "For visual meanings, set meaning_status to user_confirmed_meaning, user_declared_no_scientific_meaning, or keep claim_critical: false.",
        err=True,
    )


def _merge_tasks(existing: list[Any], new_tasks: list[Any]) -> list[Any]:
    by_id = {task.id: task for task in existing}
    for task in new_tasks:
        by_id[task.id] = task
    return list(by_id.values())


def _resolve_package_argument(package: Path) -> Path:
    if (package / SEMANTIC_LAYER_FILENAME).exists():
        return package
    fallback = Path("scene-package")
    if package == Path(".") and (fallback / SEMANTIC_LAYER_FILENAME).exists():
        typer.echo("Using scene-package", err=True)
        return fallback
    return package


def _profile_for_next_command(semantic: Any) -> str:
    profile = getattr(semantic.package, "profile", None)
    if profile in {None, "", "draft", "unknown"}:
        return "simple-structure-view"
    return str(profile)


def _validation_summary_line(report: dict[str, Any]) -> str:
    review_notes = len(report.get("human_review_required", []))
    return (
        f"Summary: {len(report.get('claim_traceability_matrix', []))} claim(s), "
        f"{len(report.get('artifact_fixity', []))} artifact(s), "
        f"{review_notes} non-blocking author-review note(s)."
    )


def _has_context_finding(findings: list[dict[str, Any]]) -> bool:
    return any(
        str(item.get("rule_id", "")).startswith(("CLAIM.", "SCENE.", "IMPORT.CXC", "IMPORT.MVS"))
        for item in findings
    )


def _answers_path_for(package: Path) -> Path:
    return package / "answers.yml"


def _default_zip_path(package: Path) -> Path:
    if package == Path("."):
        package = _resolve_package_argument(package)
    return package.with_suffix(".zip")


def _validate_choice(value: str, choices: set[str], label: str) -> None:
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise ValueError(f"Unknown {label}: {value}. Choose one of: {allowed}.")


def _validate_report_output_path(package: Path, out: Path) -> None:
    package_resolved = package.resolve(strict=False)
    if out.is_symlink():
        raise ValueError(f"Refusing to write a validation report through a symbolic link: {out}.")
    out_resolved = out.resolve(strict=False)
    try:
        out_resolved.relative_to(package_resolved)
    except ValueError as exc:
        raise ValueError(
            f"Validation report output must stay inside the package directory {package}; got {out}."
        ) from exc
    package_absolute = package.absolute()
    current = out.absolute().parent
    while current != package_absolute:
        if current.is_symlink():
            raise ValueError(
                f"Refusing validation report output through symbolic-link parent directory: {current}."
            )
        parent = current.parent
        if parent == current:
            break
        current = parent
    if out_resolved == (package_resolved / SEMANTIC_LAYER_FILENAME).resolve(strict=False):
        raise ValueError("Refusing to write a validation report over semantic_layer.json.")
    if (package / SEMANTIC_LAYER_FILENAME).exists():
        pkg = load_package(package)
        artifact_paths = {
            (package_resolved / str(artifact.path)).resolve(strict=False)
            for artifact in pkg.semantic_layer.artifacts
            if artifact.path
        }
        if out_resolved in artifact_paths:
            raise ValueError("Refusing to write a validation report over a package artifact.")
    if out.exists() and out.name != VALIDATION_REPORT_FILENAME:
        raise ValueError(f"Output file already exists: {out}. Choose a new path or use {VALIDATION_REPORT_FILENAME}.")


def _handle_error(exc: Exception) -> None:
    if isinstance(exc, SecurityError):
        typer.echo(f"Cannot continue safely: {exc}", err=True)
        raise typer.Exit(2)
    if isinstance(exc, SchemaVersionError):
        typer.echo(f"This package uses an unsupported schema version: {exc}", err=True)
        raise typer.Exit(3)
    if isinstance(exc, PackageError) and str(exc).startswith(f"Missing {SEMANTIC_LAYER_FILENAME}"):
        package = str(exc).split(":", 1)[-1].strip() or "<package>"
        typer.echo(f"No ClaimTrace package found at {package}.", err=True)
        typer.echo("A ClaimTrace package directory contains semantic_layer.json.", err=True)
        suggested_out = "scene-package" if package in {".", "<package>"} else package
        typer.echo(
            "Next: check the package path, or create one with claimtrace init "
            f'{_quoted_path("<scene-file>")} --out {_quoted_path(suggested_out)}. '
            "Supported scenes: .pml, .cxc, .mvsj, .mvsx.",
            err=True,
        )
        raise typer.Exit(1)
    if isinstance(exc, (ValidationError, ClaimTraceError, ValueError, PackageError)):
        typer.echo(f"Could not complete the command: {exc}", err=True)
        raise typer.Exit(1)
    if isinstance(exc, FileNotFoundError):
        typer.echo(
            f"Input file not found: {exc.filename}. Run from the directory containing the file or pass an absolute path."
            f"{windows_path_hint(exc.filename)}",
            err=True,
        )
        raise typer.Exit(1)
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)
