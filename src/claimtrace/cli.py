"""Command-line interface."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any, Optional
from typing import List

import typer
from rich.console import Console
from rich.table import Table

from claimtrace import _simple_yaml
from claimtrace.agent_cli import agent_app
from claimtrace._finite import ensure_finite
from claimtrace.api import export_package as api_export_package
from claimtrace.api import init_package, load_package
from claimtrace.completion import (
    apply_answers,
    available_templates,
    check_answers,
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
from claimtrace.package.layout import read_completion_tasks, read_json, update_completion_tasks, write_completion_tasks, write_json
from claimtrace.package.registry import infer_role
from claimtrace.package.resources import resource_matches_artifact, resource_uri_summary
from claimtrace.path_hints import windows_path_hint
from claimtrace.schemas import semantic_layer_schema, validation_report_schema
from claimtrace.validation.engine import validate_package

APP_HELP = (
    "Prepare, review and share the evidence behind a molecular figure. "
    "Begin with a scene or image, add its scientific context, then export a review package."
)
APP_EPILOG = "Start with `claimtrace prepare` in your terminal or `claimtrace gui` in your browser."

app = typer.Typer(help=APP_HELP, epilog=APP_EPILOG)
app.add_typer(agent_app, name="agent", rich_help_panel="Agent assistance")
console = Console()

MODE_HELP = "Validation mode. Choices: draft, internal, share, archive."
TEXT_JSON_HELP = "Output format. Choices: text, json."
TEMPLATE_HELP = (
    "Completion template. Choices: auto, simple-structure-view, ligand-binding-pose. "
    "Auto selects ligand-binding-pose for pocket, binding-site, contact or distance context; "
    "other structure views use simple-structure-view."
)
SECTION_CHOICES = {"claim", "entities", "scene", "evidence", "uncertainty", "reuse"}
ARTIFACT_ROLE_CHOICES = {role.value for role in ArtifactRole}
NATIVE_SCENE_SUFFIXES = {".pml", ".cxc", ".mvsj", ".mvsx"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".webp", ".svg"}


def run() -> None:
    """Run the CLI with UTF-8 redirected streams on Windows."""
    if sys.platform == "win32" and not os.environ.get("PYTHONIOENCODING"):
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            if stream is not None and not stream.isatty() and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors=stream.errors)
    app()


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


@app.command(rich_help_panel="Open the workspace")
def skill(
    out: Optional[Path] = typer.Option(None, "--out", help="Copy the bundled skill into this new folder."),
) -> None:
    """Locate or copy the companion skill for a compatible agent client."""
    import shutil

    source = Path(__file__).parent / "resources" / "skills" / "claimtrace"
    try:
        if not (source / "SKILL.md").is_file():
            raise PackageError("Reinstall ClaimTrace to restore its companion skill.")
        if out is None:
            typer.echo(str((source / "SKILL.md").resolve()))
            return
        destination = out.expanduser().resolve()
        if destination.exists():
            raise ValueError("Choose a new folder for the companion skill.")
        shutil.copytree(source, destination)
        typer.echo(f"Skill saved: {destination / 'SKILL.md'}")
    except Exception as exc:
        _handle_error(exc)


@app.command(rich_help_panel="Open the workspace")
def gui(
    package: Optional[Path] = typer.Argument(None, help="Existing package to open in the GUI."),
    port: int = typer.Option(8765, "--port", min=0, max=65535, help="Local HTTP port; 0 selects a free port."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Print the URL without opening a browser."),
) -> None:
    """Prepare a figure, review its claims and export a package in your browser."""

    from claimtrace.gui.server import serve

    try:
        serve(package=package, port=port, open_browser=not no_browser)
    except (ClaimTraceError, OSError, ValueError) as exc:
        console.print(f"GUI startup needs attention: {exc}", markup=False)
        raise typer.Exit(1) from exc


@app.command(rich_help_panel="Open the workspace")
def prepare(
    package: Optional[Path] = typer.Argument(None, help="Existing package, or omit to choose files or an example."),
    expert: bool = typer.Option(False, "--expert", help="Show record IDs and detailed authoring actions."),
    claim: Optional[str] = typer.Option(None, "--claim", help="Select a claim by its ID or 1-based number."),
    example: Optional[str] = typer.Option(None, "--example", help="Practice example ID. See `claimtrace examples`."),
    workspace: Optional[Path] = typer.Option(None, "--workspace", help="Folder for new packages and working copies."),
) -> None:
    """Prepare a figure statement, evidence and limitations step by step."""
    from claimtrace.terminal import prepare_terminal

    try:
        if package is not None and example is not None:
            raise ValueError("Choose an existing package or a practice example with --example.")
        resolved = _resolve_package_argument(package) if package is not None else None
        prepare_terminal(resolved, expert=expert, example=example, workspace=workspace, claim_id=claim)
    except typer.Exit:
        raise
    except Exception as exc:
        _handle_error(exc)


@app.command(rich_help_panel="Open the workspace")
def examples() -> None:
    """List the practice examples shared by the terminal and browser."""
    from claimtrace.gui.examples import example_catalog

    typer.echo("Synthetic practice examples")
    typer.echo("")
    for item in example_catalog():
        typer.echo(f"{item['id']} — {item['title']}")
        typer.echo(f"  {item['description']}")
    typer.echo("")
    typer.echo("Start: claimtrace prepare --example highlight-residues")


@app.command(rich_help_panel="Open the workspace")
def quickstart() -> None:
    """Print the Prepare, Review and Export terminal workflow."""

    typer.echo(
        "\n".join(
            [
                "ClaimTrace quickstart",
                "",
                "Install:",
                "   python -m pip install claimtrace",
                "",
                "Try a practice example:",
                "   claimtrace prepare --example highlight-residues",
                "",
                "Supported native scene files: .pml, .cxc, .mvsj, .mvsx",
                "On WSL, use a /mnt/c/... path for Windows files.",
                "",
                "1. Prepare the figure and its source files:",
                '   claimtrace init --file "figure_A.pml" --file "figure_A.png" --file "model.cif" --out "scene-package"',
                "   To begin with an image:",
                '   claimtrace init --image "figure_A.png" --out "scene-package"',
                "",
                "2. Add the claim and review the imported context:",
                '   claimtrace prepare "scene-package"',
                "   Each saved step is available in the terminal and browser.",
                "",
                "3. Review the record for a collaborator:",
                '   claimtrace review "scene-package"',
                "",
                "4. Export the record and its source files:",
                '   claimtrace export "scene-package"',
                "   Review and export use the saved purpose, starting with Working draft.",
                "   Use --mode share for External review or --mode archive for an Archive.",
                "",
                "Open the same package in your browser:",
                '   claimtrace gui "scene-package"',
                "",
                "For scripted completion:",
                '   Edit "scene-package/answers.yml" in your text editor.',
                '   claimtrace complete "scene-package" --check-answers "scene-package/answers.yml"',
                '   claimtrace complete "scene-package" --answers "scene-package/answers.yml"',
                "",
                "Scene import preserves source expressions. Native-viewer replay is a separate check.",
            ]
        )
    )


@app.command(
    rich_help_panel="Prepare",
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
        help="Scene file: .pml, .cxc, .mvsj or .mvsx. Repeat for multiple files. Import reads the saved scene instructions.",
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
    files: Optional[List[Path]] = typer.Option(
        None,
        "--file",
        help="Input file; scenes, images and supporting files are identified by format. Repeat for multiple files.",
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
    """Create a draft from a scene or figure image and supporting files."""

    try:
        _validate_choice(format, {"text", "json"}, "format")
        _validate_choice(template, {"auto", *available_templates()}, "template")
        native_inputs = _validated_native_inputs(scene, native, blank=blank, image=image, artifact=artifact)
        image_inputs = list(image or [])
        artifact_inputs = list(artifact or [])
        if blank and files:
            raise ValueError("Use --blank on its own, or provide input files.")
        seen = {path.resolve() for path in native_inputs + image_inputs + artifact_inputs}
        for path in files or []:
            if path.resolve() in seen:
                continue
            seen.add(path.resolve())
            if path.suffix.lower() in NATIVE_SCENE_SUFFIXES:
                native_inputs.append(path)
            elif path.suffix.lower() in IMAGE_SUFFIXES:
                image_inputs.append(path)
            else:
                artifact_inputs.append(path)
        initial_template = "simple-structure-view" if template == "auto" else template
        pkg = init_package(
            native=native_inputs,
            image=image_inputs,
            artifacts=artifact_inputs,
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
        linked_render_ids = {
            artifact_id
            for package_scene in pkg.semantic_layer.scenes
            for artifact_id in package_scene.render_artifact_ids
        }
        unlinked_renders = [
            item
            for item in pkg.semantic_layer.artifacts
            if item.role.value == "render_image" and item.id not in linked_render_ids
        ]
        payload = {
            "package": str(pkg.root),
            "semantic_layer": str(pkg.root / "semantic_layer.json"),
            "answers": str(answers_path),
            "profile": resolved_template,
            "unlinked_render_artifacts": [item.id for item in unlinked_renders],
            "scene_ids": [item.id for item in pkg.semantic_layer.scenes],
        }
        if format == "json":
            typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            typer.echo(f"Created draft: {pkg.root}")
            _echo_materials(pkg.semantic_layer)
            if unlinked_renders:
                typer.echo(f"Figure matching: {len(unlinked_renders)} image(s) need a scene.")
            for warning in _import_warning_lines(pkg.semantic_layer, limit=2):
                typer.echo(f"Import note: {warning}")
            if blank:
                typer.echo("Empty draft: add a scene or figure image in the workspace.")
            elif not native_inputs and image_inputs:
                typer.echo("Image draft: add the figure claim and its evidence in the workspace.")
            elif not native_inputs:
                typer.echo("Files draft: record a draft claim and add its figure or scene when ready.")
            elif not linked_render_ids:
                typer.echo("Scene draft: add the rendered figure in the workspace.")
            typer.echo("")
            typer.echo(f"Next: claimtrace prepare {_quoted_path(pkg.root)}")

    except Exception as exc:
        _handle_error(exc)


@app.command(rich_help_panel="Prepare")
def inspect(
    package: Path = typer.Argument(Path("."), help="ClaimTrace package directory."),
    format: str = typer.Option("text", "--format", help=TEXT_JSON_HELP),
    details: bool = typer.Option(False, "--details", help="Show source operations, resources and the artifact inventory."),
) -> None:
    """See the imported materials and the next details to prepare."""

    try:
        _validate_choice(format, {"text", "json"}, "format")
        package = _resolve_package_argument(package)
        pkg = load_package(package)
        extraction_path = pkg.root / "semantic" / "extraction_report.json"
        extraction = read_json(extraction_path) if extraction_path.exists() else {}
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
        if not details:
            _echo_workspace_summary(pkg)
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
            typer.echo(f"  claimtrace prepare {_quoted_path(pkg.root)}")
            typer.echo("Scripted answers:")
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


@app.command(rich_help_panel="Review and export")
def review(
    package: Path = typer.Argument(Path("."), help="ClaimTrace package directory."),
    mode: Optional[str] = typer.Option(None, "--mode", help=MODE_HELP + " Defaults to the saved purpose, or draft."),
    claim: Optional[str] = typer.Option(None, "--claim", help="Review one claim by its ID or 1-based number."),
    format: str = typer.Option("text", "--format", help="Output format. Choices: text, json, md."),
    expert: bool = typer.Option(False, "--expert", help="Show record IDs and every open question."),
) -> None:
    """Trace claims to their evidence, limitations and next actions."""

    from claimtrace.workflow import review_package

    try:
        if mode is not None:
            _validate_choice(mode, {"draft", "internal", "share", "archive"}, "mode")
        _validate_choice(format, {"text", "json", "md"}, "format")
        package = _resolve_package_argument(package)
        state = review_package(package, mode=mode)
        audit = state["audit"]
        workflow = state["workflow"]
        mode = workflow["lifecycle"]["mode"]
        claim_numbers = {item["id"]: index for index, item in enumerate(audit["claims"], 1)}
        if claim:
            if claim.isdecimal() and 1 <= int(claim) <= len(audit["claims"]):
                claim = audit["claims"][int(claim) - 1]["id"]
            selected = [item for item in audit["claims"] if item["id"] == claim]
            if not selected:
                choices = ", ".join(
                    f"{index}: {item.get('figure_ref') or item['id']} ({item['id']})"
                    for index, item in enumerate(audit["claims"], 1)
                ) or "Add a claim with claimtrace prepare."
                raise ValueError(f"Unknown claim: {claim}. Available claims: {choices}")
            summary = {**audit["summary"], "claims": len(selected)}
            summary.update({status: sum(item["status"] == status for item in selected) for status in ("incomplete", "review", "recorded")})
            audit = {**audit, "claims": selected, "summary": summary}
            tasks = [item for item in workflow["tasks"] if item.get("claim_id") in {None, claim}]
            workflow = {**workflow, "tasks": tasks, "next_action": tasks[0] if tasks else None}
        payload = {"package": state["root"], "mode": mode, "audit": audit, "workflow": workflow,
                   "human_review_required": state["report"]["human_review_required"]}
        if format == "json":
            typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            typer.echo(_review_summary(payload, markdown=format == "md", expert=expert, claim_numbers=claim_numbers))
    except Exception as exc:
        _handle_error(exc)


@app.command(
    rich_help_panel="Prepare",
    epilog=(
        "Examples:\n\n"
        '  claimtrace complete "scene-package" --gui\n\n'
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
    no_input: bool = typer.Option(False, "--no-input", help="Refresh tasks or apply provided answers without prompts."),
    gui: bool = typer.Option(False, "--gui", help="Open the guided workspace for this package."),
) -> None:
    """Add scientific context in the workspace, with prompts or from an answers file."""

    try:
        _validate_choice(template, {"auto", *available_templates()}, "template")
        if section is not None:
            _validate_choice(section, SECTION_CHOICES, "section")
        action_count = sum(bool(action) for action in (gui, emit_template, check_answers_file, answers))
        if action_count > 1:
            raise ValueError(
                "Choose only one completion action: --gui, --emit-template, --check-answers, or --answers."
            )
        package = _resolve_package_argument(package)
        pkg = load_package(package)
        if not any((gui, emit_template, check_answers_file, answers, section, no_input)) and template == "auto":
            from claimtrace.terminal import prepare_terminal

            prepare_terminal(pkg.root)
            return
        if gui:
            if section is not None or no_input:
                raise ValueError("Use --gui on its own to open the guided workspace.")
            from claimtrace.gui.server import serve

            serve(package=pkg.root, port=0, open_browser=True, initial_view="prepare")
            return
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
            update_completion_tasks(pkg.root, pkg.semantic_layer, data)
            typer.echo(f"Applied answers: {pkg.root / 'semantic_layer.json'}")
            _echo_remaining_completion_questions(pkg.root)
            typer.echo(f"Next: claimtrace review {_quoted_path(pkg.root)}")
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
            typer.echo("This scene has source-linked details to review in the guided workspace.", err=True)
            typer.echo(f"Next: claimtrace complete {_quoted_path(pkg.root)} --gui", err=True)
            typer.echo(f"{verb} answers file: {_quoted_path(answers_path)}", err=True)
            typer.echo(
                f"For scripted edits: claimtrace complete {_quoted_path(pkg.root)} --answers {_quoted_path(answers_path)}",
                err=True,
            )
            raise typer.Exit(1)
        template_text = dump_package_answer_template(pkg.semantic_layer, template)
        task_sections = {task.section for task in tasks}
        if (
            len(pkg.semantic_layer.claims) > 1 and task_sections & {"claim", "evidence", "uncertainty"}
            or len(pkg.semantic_layer.scenes) > 1 and "scene" in task_sections
            or len(pkg.semantic_layer.evidence) > 1 and "evidence" in task_sections
            or len(pkg.semantic_layer.uncertainty) > 1 and "uncertainty" in task_sections
        ):
            raise ValueError(
                "Choose the record to edit in the guided workspace: "
                f"claimtrace prepare {_quoted_path(pkg.root)}"
            )
        base_answers = _interactive_answer_base(template_text, task_sections)
        answers_data = _prompt_for_answers(tasks, pkg.semantic_layer, base_answers)
        draft_path = _save_interactive_answers_draft(pkg.root, answers_data, template_text)
        typer.echo(f"Saved interactive answers draft: {draft_path}")
        problems = check_answers(answers_data, pkg.semantic_layer, root=pkg.root, answer_base=pkg.root)
        if problems:
            for problem in problems:
                typer.echo(f"Please update answers.yml: {problem}", err=True)
            typer.echo(f"Edit the saved draft {_quoted_path(draft_path)}; your responses are saved.", err=True)
            _echo_answer_fix_tip(pkg.root, draft_path, template)
            raise typer.Exit(1)
        apply_answers(pkg.root, pkg.semantic_layer, answers_data, answer_base=pkg.root)
        pkg.save()
        update_completion_tasks(pkg.root, pkg.semantic_layer, answers_data, sections=task_sections)
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


@app.command("add-artifact", rich_help_panel="Prepare")
def add_artifact(
    package: Path = typer.Argument(..., help="ClaimTrace package directory."),
    path: Path = typer.Argument(..., help="Artifact path to add."),
    role: Optional[str] = typer.Option(None, "--role", help="Artifact role, e.g. structure, render_image, contact_table, map or evidence_document."),
    detached: bool = typer.Option(False, "--detached", help="Record metadata without copying the payload into the package."),
    scene: Optional[str] = typer.Option(
        None,
        "--scene",
        help="Scene ID to link when adding a rendered panel. Recommended for multi-scene packages.",
    ),
) -> None:
    """Attach a figure image, structure, table or other supporting file."""

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
        artifact = pkg.add_artifact(path, role=role, detached=detached, scene_id=scene)
        typer.echo(f"Added {artifact.id} as {artifact.role.value}")
        if artifact.role.value == "render_image" and len(pkg.semantic_layer.scenes) > 1 and scene is None:
            scene_ids = ", ".join(item.id for item in pkg.semantic_layer.scenes)
            typer.echo(
                "Choose the scene that matches this panel. "
                f"Use --scene <id> or select it in the workspace. Scene IDs: {scene_ids}"
            )
        typer.echo(f"Next: claimtrace prepare {_quoted_path(pkg.root)}")
    except Exception as exc:
        _handle_error(exc)


@app.command(rich_help_panel="Review and export")
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


@app.command(rich_help_panel="Review and export")
def export(
    package: Path = typer.Argument(Path("."), help="ClaimTrace package directory."),
    out: Optional[Path] = typer.Option(None, "--out", help="Output directory or ZIP path. Defaults to a ZIP beside the package."),
    mode: Optional[str] = typer.Option(None, "--mode", help=MODE_HELP + " Defaults to the saved purpose, or draft."),
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
        if mode is not None:
            _validate_choice(mode, {"draft", "internal", "share", "archive"}, "mode")
        package = _resolve_package_argument(package)
        if mode is None:
            mode = load_package(package).semantic_layer.extensions.get("gui_lifecycle", "draft")
            if mode not in {"draft", "internal", "share", "archive"}:
                mode = "draft"
        out = out or _default_zip_path(package)
        zip_output = zip or out.suffix.lower() == ".zip"
        result = api_export_package(package, out, mode=mode, zip_output=zip_output, force=force)
        from claimtrace.workflow import LIFECYCLE_LABELS

        typer.echo(f"{LIFECYCLE_LABELS[mode]} checks passed.")
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
            f"Next: claimtrace review {_quoted_path(package)} --mode {mode}",
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
            typer.echo(f"Wrote schema: {out}")
        else:
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
    """Experimental: check and record compatibility with schema 0.1.0."""

    try:
        package = _resolve_package_argument(package)
        pkg = load_package(package)
        if pkg.semantic_layer.schema_version != target_schema:
            raise SchemaVersionError(
                f"This release supports schema {pkg.semantic_layer.schema_version}. Choose that target version."
            )
        pkg.semantic_layer.add_activity("migrate", "Schema version compatibility check.", target_schema=target_schema)
        pkg.save()
        typer.echo(f"The package already uses schema {target_schema}.")
    except Exception as exc:
        _handle_error(exc)


def _echo_materials(semantic: Any) -> None:
    artifacts = semantic.artifacts
    native_ids = {aid for scene in semantic.scenes for aid in scene.native_artifact_ids}
    native_count = sum(item.id in native_ids for item in artifacts)
    image_count = sum(item.role.value == "render_image" for item in artifacts)
    supporting = len(artifacts) - native_count - image_count
    typer.echo("Materials: " + ", ".join((_count_label(native_count, "scene file"), _count_label(image_count, "figure image"), _count_label(supporting, "supporting file"))))


def _echo_workspace_summary(pkg: Any) -> None:
    from claimtrace.workflow import review_package

    state = review_package(pkg.root)
    typer.echo(pkg.semantic_layer.package.title)
    _echo_materials(pkg.semantic_layer)
    typer.echo(f"Claims: {len(pkg.semantic_layer.claims)}")
    _echo_task_summary(state["workflow"], state["audit"]["claims"])
    typer.echo("")
    if state["workflow"]["tasks"]:
        typer.echo(f"Next: claimtrace prepare {_quoted_path(pkg.root)}")
    else:
        typer.echo(f"Next: claimtrace review {_quoted_path(pkg.root)}")


def _count_label(count: int, label: str) -> str:
    return f"{count} {label}{'' if count == 1 else 's'}"


def _figure_label(claim: dict[str, Any]) -> str:
    label = str(claim.get("figure_ref") or "").strip()
    return label if label.lower() not in {"", "unknown", "todo", "tbd"} else "Draft figure"


def _task_title(task: dict[str, Any], claims: list[dict[str, Any]], *, expert: bool = False) -> str:
    if len(claims) < 2:
        return task["title"]
    owner = next((item for item in claims if item["id"] == task.get("claim_id")), None)
    scope = _figure_label(owner) if owner else "Package"
    if expert and owner:
        scope += f" · {owner['id']}"
    return f"{scope}: {task['title']}"


def _echo_task_summary(workflow: dict[str, Any], claims: list[dict[str, Any]]) -> None:
    tasks = workflow["tasks"]
    if tasks:
        typer.echo("To prepare:")
        for task in tasks[:3]:
            typer.echo(f"  - {_task_title(task, claims)}")
        if len(tasks) > 3:
            typer.echo(f"  + {len(tasks) - 3} more with claimtrace review --expert")
    else:
        typer.echo("Preparation details recorded.")


def _review_summary(
    payload: dict[str, Any], *, markdown: bool = False, expert: bool = False,
    claim_numbers: dict[str, int] | None = None,
) -> str:
    audit = payload["audit"]
    workflow = payload["workflow"]
    lifecycle = workflow["lifecycle"]
    mode = lifecycle["label"]
    readiness = "Ready" if lifecycle["ready"] else f"{_count_label(lifecycle['blocking_count'], 'detail')} to resolve"
    lines = ["# ClaimTrace review" if markdown else "ClaimTrace review", "", f"{mode} package checks: {readiness}"]
    notes = payload.get("human_review_required", payload.get("report", {}).get("human_review_required", []))
    if notes:
        lines.append(_author_review_summary(notes))
    statuses = {"missing": "Add details", "incomplete": "Add details", "review": "Review needed", "recorded": "Recorded", "not_applicable": "Optional"}
    for index, claim in enumerate(audit["claims"], 1):
        number = (claim_numbers or {}).get(claim["id"], index)
        heading = f"{number}. {_figure_label(claim)}"
        if expert:
            heading += f" · {claim['id']}"
        lines.extend(["", f"## {heading}" if markdown else heading, claim["headline"]])
        for stage in claim["stages"]:
            label = stage["label"]
            summary = stage["summary"]
            if not expert:
                summary = summary.replace(f"Claim {claim['id']}", "This claim")
                summary = summary.replace(f"claim {claim['id']}", "this claim")
                summary = summary.replace(claim["id"], "this claim")
            status = statuses.get(stage["status"], stage["status"].replace("_", " ").capitalize())
            lines.append(f"- **{label}** · {status}: {summary}" if markdown else f"  {label} · {status}: {summary}")
        if expert:
            for key, label in (("scene_ids", "Scenes"), ("evidence_ids", "Evidence records"), ("uncertainty_ids", "Limitations"), ("artifact_ids", "Files")):
                if claim.get(key):
                    lines.append(f"  {label}: {', '.join(claim[key])}")
    pending = [t for t in workflow["tasks"] if t["action"] == "review-proposal"]
    if not audit["claims"] and not pending:
        lines.extend(["", "Add the statement this figure should communicate."])
    tasks = workflow["tasks"]
    if tasks:
        lines.extend(["", "Next actions:", ""])
        for index, task in enumerate(tasks if expert else tasks[:3], 1):
            lines.append(f"{index}. {_task_title(task, audit['claims'], expert=expert)}")
        if len(tasks) > 3 and not expert:
            lines.append(f"+ {len(tasks) - 3} more with --expert.")
    commands = []
    if notes:
        commands.append(("Review item details", f"claimtrace validate {_quoted_path(payload['package'])} --mode {payload['mode']} --format json"))
    if pending:
        commands.append(("Read suggestions", f"claimtrace agent proposals {_quoted_path(payload['package'])} --status pending"))
        commands.append(("Review in GUI", f"claimtrace gui {_quoted_path(payload['package'])}"))
    if tasks or not lifecycle["ready"]:
        commands.append(("Prepare", f"claimtrace prepare {_quoted_path(payload['package'])}"))
    if lifecycle["ready"]:
        commands.append(("Export", f"claimtrace export {_quoted_path(payload['package'])} --mode {payload['mode']}"))
    for label, command in commands:
        lines.extend(["", f"{label}: `{command}`" if markdown else f"{label}: {command}"])
    return "\n".join(lines)


def _prompt_for_answers(tasks, semantic: Any, base_answers: dict[str, Any]) -> dict[str, Any]:
    answers = json.loads(json.dumps(base_answers))
    for task in tasks:
        prompt = f"{task.question} ({task.examples[0] if task.examples else 'unknown'})"
        record = answers.get(task.section, {})
        if isinstance(record, list):
            record = record[0] if record else {}
        key = {
            "claim": "claim_text", "evidence": "result_summary", "scene": "notes",
            "uncertainty": "statement", "reuse": "license",
        }.get(task.section)
        current = str(record.get(key) or "unknown") if isinstance(record, dict) and key else "unknown"
        if current.lower().startswith(("todo", "tbd")):
            current = "unknown"
        answer = typer.prompt(prompt, default=current)
        if task.section == "claim":
            claim = answers.setdefault("claim", {})
            if not isinstance(claim, dict):
                claim = {}
                answers["claim"] = claim
            claim["claim_text"] = answer
            claim.setdefault("claim_type", _profile_claim_type(semantic))
            figure_ref = str(claim.get("figure_ref") or "")
            if figure_ref.lower() in {"", "unknown"} or figure_ref.lower().startswith(("todo", "tbd")):
                figure_ref = "Figure 1A"
            claim["figure_ref"] = typer.prompt("Figure or panel label", default=figure_ref)
            claim.setdefault("scope", "panel")
            claim.update(review_status="confirmed", reviewer="cli", source_type="user_asserted")
            claim.pop("reviewed_at", None)
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
            evidence_item.update(review_status="confirmed", reviewer="cli")
            evidence_item.pop("reviewed_at", None)
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
            uncertainty.update(review_status="confirmed", reviewer="cli")
            uncertainty.pop("reviewed_at", None)
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
            "Choose one scene-input form. "
            "Use `claimtrace init <scene-file>` for one scene, or repeat --native for multiple scenes."
        )
    if scene is not None:
        native_paths = [scene]
    if blank and (native_paths or image or artifact):
        raise ValueError("Use --blank for an empty package, or provide files to start from existing material.")
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


def _interactive_answer_base(template_text: str, sections: set[str]) -> dict[str, Any]:
    """Use current records and apply only the sections the prompts ask about."""
    data = _simple_yaml.loads(template_text)
    if not isinstance(data, dict):  # pragma: no cover - generated templates are mappings
        raise ValueError("Generated answers template was not a mapping.")
    if len(data.get("claims", [])) == 1:
        data["claim"] = data.pop("claims")[0]
    if len(data.get("scenes", [])) == 1:
        data["scene"] = data.pop("scenes")[0]
    if isinstance(data.get("uncertainty"), list) and len(data["uncertainty"]) == 1:
        data["uncertainty"] = data["uncertainty"][0]
    scoped = {key: value for key, value in data.items() if key in sections}
    if "claim" not in scoped:
        # Keep the answer-file envelope while leaving other scientific records
        # unchanged. New support records still need their single claim anchor.
        if sections & {"evidence", "uncertainty"} and data.get("claim", {}).get("id"):
            scoped["claim"] = {"id": data["claim"]["id"]}
        else:
            scoped["claims"] = []
    scoped.setdefault("evidence", [])
    scoped.setdefault("reuse", {})
    return scoped


def _save_interactive_answers_draft(root: Path, answers: dict[str, Any], original_template: str) -> Path:
    preferred = root / "answers.yml"
    content = "# ClaimTrace interactive answers draft\n" + _simple_yaml.dumps(answers)
    can_replace_generated = (
        preferred.exists()
        and not preferred.is_symlink()
        and preferred.read_text(encoding="utf-8") == original_template
    )
    if (not preferred.exists() and not preferred.is_symlink()) or can_replace_generated:
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
            line += f" Suggested meaning awaiting review: {candidate}"
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
            attached = "URL recorded; download pending"
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
        "dynamic_command_boundary": "dynamic command preserved; execution requires the original viewer",
        "executable_resource_boundary": "executable resource reference preserved for review",
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
            lines.append(f"Referenced file needs an attachment{location_text}: {resource.uri}")
            lines.append(
                "  Add the actual local file with: claimtrace add-artifact "
                f"{_quoted_path(package)} {_quoted_path(_example_local_path(resource.uri))} --role {role}"
            )
            lines.append(
                "  Run that command from the folder containing the file, or replace the filename with its real full path."
            )
        elif resource.uri_kind == "remote":
            lines.append(f"Remote resource URL recorded; download pending{location_text}: {resource_uri_summary(resource.uri)}")
        elif resource.uri_kind == "missing_archive_member":
            lines.append(f"Referenced file is missing from the MVSX archive{location_text}: {resource_uri_summary(resource.uri)}")
            lines.append("  Rebuild the .mvsx with that file inside the archive at its referenced path.")
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
        return ensure_finite(
            json.loads(
                value,
                parse_constant=lambda token: (_ for _ in ()).throw(
                    ValueError(f"Non-finite numeric value {token} is not valid JSON.")
                ),
            )
        )
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
            lines.append(
                f"- **{item['status']} {item['severity']} {item['rule_id']}**: {item['message']}"
            )
    else:
        lines.append("- Required checks passed.")
    waivers = report.get("waiver_list", [])
    if waivers:
        lines.extend(["", "## Waiver Records", ""])
        for waiver in waivers:
            lines.append(
                f"- `{waiver.get('rule_id', 'unknown')}` by {waiver.get('reviewer', 'unknown')}: "
                f"{waiver.get('reason', 'No reason recorded.')}"
            )
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
            "Required package checks passed. The files are ready to review.",
            _validation_summary_line(report),
            f"Create a handoff ZIP when needed: claimtrace export {_quoted_path(package)} --mode {mode} --out {_quoted_path(zip_path)}",
        ]
        lines.extend(_waiver_text_lines(report))
        return "\n".join(lines)
    if required:
        lines = [
            f"{mode} check needs attention: {len(required)} required update(s), {len(recommended)} recommended update(s).",
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
            f"{status}: ready for {mode}; {len(recommended)} recommended update(s).",
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
        lines.append("Export is ready for this purpose. Review the recommended items for a fuller handoff.")
    if _has_context_finding(findings):
        lines.extend(
            [
                "Use Prepare or an answers file to update the claim record.",
                f"For claim/context updates, edit {_quoted_path(_answers_path_for(Path(package)))}.",
                "Then: claimtrace complete "
                f"{_quoted_path(package)} --check-answers {_quoted_path(_answers_path_for(Path(package)))}",
                "Then: claimtrace complete "
                f"{_quoted_path(package)} --answers {_quoted_path(_answers_path_for(Path(package)))}",
            ]
        )
    lines.extend(_waiver_text_lines(report))
    return "\n".join(lines)


def _waiver_text_lines(report: dict[str, Any]) -> list[str]:
    waivers = report.get("waiver_list", [])
    if not waivers:
        return []
    waived_findings = sum(
        1 for item in report.get("findings", []) if item.get("status") == "WAIVED"
    )
    lines = [
        "",
        f"Waiver records: {len(waivers)}; findings waived in this check: {waived_findings}. "
        "Review the records before relying on this result.",
    ]
    for waiver in waivers[:5]:
        anchor = waiver.get("anchor_id") or waiver.get("scope", "unknown scope")
        lines.append(
            f"- {waiver.get('rule_id', 'unknown')} at {anchor}, reviewed by "
            f"{waiver.get('reviewer', 'unknown')}: {waiver.get('reason', 'No reason recorded.')}"
        )
    return lines


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
    if rule_id.startswith(("CLAIM.BASIC.EVIDENCE", "CLAIM.EVIDENCE")):
        return "Add supporting file or note"
    if rule_id.startswith("CLAIM.BASIC.SCENE"):
        return "Link claim to scene"
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
    if rule_id.startswith("CLAIM.BASIC.EVIDENCE"):
        return "answers.yml -> evidence"
    if rule_id.startswith("CLAIM.BASIC.TEXT"):
        return "answers.yml -> claim.claim_text"
    if rule_id.startswith("CLAIM.BASIC.FIGURE"):
        return "answers.yml -> claim.figure_ref"
    if rule_id == "CLAIM.BASIC.MISSING":
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
    if rule_id.startswith(("CLAIM.BASIC.TEXT", "CLAIM.BASIC.FIGURE")) or rule_id == "CLAIM.BASIC.MISSING":
        return [
            "Edit the package's answers.yml, then fill claim.claim_text and claim.figure_ref."
        ]
    if (
        rule_id.startswith("CLAIM.BASIC.EVIDENCE")
        or rule_id.startswith("CLAIM.EVIDENCE")
        or rule_id.startswith("CLAIM.SIMPLE")
        or "LIGAND" in rule_id
    ):
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
    notes = report.get("human_review_required", [])
    summary = (
        f"Summary: {len(report.get('claim_traceability_matrix', []))} claim(s), "
        f"{len(report.get('artifact_fixity', []))} artifact(s)."
    )
    if notes:
        summary += " " + _author_review_summary(notes)
        summary += " Read human_review_required with --format json."
    return summary


def _author_review_summary(notes: list[dict[str, Any]]) -> str:
    labels = {"scenes": "scene details", "selections": "selected regions",
              "native_references": "scene references", "entities": "molecular identities"}
    categories = sorted({
        labels.get(root, root.replace("_", " "))
        for item in notes if (root := item.get("json_pointer", "").strip("/").split("/")[0])
    })
    summary = f"Additional author review: {_count_label(len(notes), 'item')}"
    return summary + (f" ({', '.join(categories)})" if categories else "") + "."


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
    return package.resolve().with_suffix(".zip")


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
        typer.echo(f"Check the package path or file: {exc}", err=True)
        raise typer.Exit(2)
    if isinstance(exc, SchemaVersionError):
        typer.echo(f"This package uses an unsupported schema version: {exc}", err=True)
        raise typer.Exit(3)
    if isinstance(exc, PackageError) and str(exc).startswith(f"Missing {SEMANTIC_LAYER_FILENAME}"):
        package = str(exc).split(":", 1)[-1].strip() or "<package>"
        typer.echo(f"No ClaimTrace package found at {package}.", err=True)
        typer.echo("A ClaimTrace package directory contains semantic_layer.json.", err=True)
        package_path = Path(package)
        is_scene_file = package_path.suffix.lower() in NATIVE_SCENE_SUFFIXES and package_path.is_file()
        if is_scene_file:
            typer.echo("Import this scene to create a ClaimTrace package folder.", err=True)
        suggested_scene = package if is_scene_file else "<scene-file>"
        suggested_out = "scene-package" if package in {".", "<package>"} or is_scene_file else package
        typer.echo(
            "Next: check the package path, or create one with claimtrace init "
            f"{_quoted_path(suggested_scene)} --out {_quoted_path(suggested_out)}. "
            "Supported scenes: .pml, .cxc, .mvsj, .mvsx.",
            err=True,
        )
        raise typer.Exit(1)
    if isinstance(exc, (ValidationError, ClaimTraceError, ValueError, PackageError)):
        typer.echo(f"Action needed: {exc}", err=True)
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
