"""Stable Python API for ClaimTrace."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from claimtrace.completion import (
    apply_answers,
    check_answers,
    completed_answer_sections,
    completion_tasks_for_template,
    ensure_scene_for_images,
    load_answers,
)
from claimtrace.constants import SEMANTIC_LAYER_FILENAME
from claimtrace.errors import PackageError
from claimtrace.importers.base import default_importers, detect_importer
from claimtrace.models import Claim, ProvenancedString, SemanticLayer
from claimtrace.models.semantic_layer import ClaimType, ConfidenceValue, ReviewStatus, SourceType, utc_now
from claimtrace.models.validation import ValidationReport
from claimtrace.package.layout import (
    append_extraction_report,
    create_package_root,
    load_semantic_layer,
    read_completion_tasks,
    write_completion_tasks,
    write_semantic_layer,
)
from claimtrace.package.registry import register_local_artifact, replay_destination_for
from claimtrace.path_hints import windows_path_hint
from claimtrace.package.resources import synchronize_resource_bindings


class ClaimTracePackage:
    """A package directory loaded with its CAL semantic layer."""

    def __init__(self, root: Path, semantic_layer: SemanticLayer):
        self.root = Path(root)
        self.semantic_layer = semantic_layer

    def save(self) -> None:
        """Write `semantic_layer.json` to disk."""

        synchronize_resource_bindings(self.semantic_layer)
        write_semantic_layer(self.root, self.semantic_layer)

    def add_claim(
        self,
        text: str,
        claim_type: str = "unknown",
        figure_ref: str = "unknown",
        *,
        scope: str = "panel",
    ) -> Claim:
        """Add or replace a claim in the CAL."""

        claim = Claim(
            id=f"claim:{len(self.semantic_layer.claims) + 1:03d}",
            claim_text=ProvenancedString(
                value=text,
                source_type=SourceType.user_asserted,
                confidence=ConfidenceValue.unknown,
                review_status=ReviewStatus.confirmed,
                reviewer="api",
                reviewed_at=utc_now(),
            ),
            claim_type=ClaimType(claim_type),
            figure_ref=figure_ref,
            scope=scope,
            scene_ids=[scene.id for scene in self.semantic_layer.scenes],
            claim_status="reviewable",
            review_status=ReviewStatus.confirmed,
        )
        self.semantic_layer.claims.append(claim)
        self.semantic_layer.add_activity("api_add_claim", f"Added claim {claim.id}.")
        self.save()
        return claim

    def add_artifact(
        self,
        path: str | Path,
        role: str | None = None,
        *,
        detached: bool = False,
    ):
        """Register a local artifact and copy it into the package by default."""

        source = Path(path)
        artifact = register_local_artifact(
            self.root,
            self.semantic_layer,
            source,
            role=role,
            copy=True,
            detached=detached,
            relative_destination=replay_destination_for(self.semantic_layer, source),
        )
        self.semantic_layer.add_activity("api_add_artifact", f"Added artifact {artifact.id}.")
        self.save()
        return artifact

    def complete_from_answers(self, answers_path: str | Path) -> "ClaimTracePackage":
        """Apply a user-friendly answer file to the package."""

        answers_path = Path(answers_path)
        answers = load_answers(answers_path)
        problems = check_answers(
            answers,
            self.semantic_layer,
            root=self.root,
            answer_base=answers_path.parent,
        )
        if problems:
            raise ValueError("Answer file needs updates:\n" + "\n".join(f"- {problem}" for problem in problems))
        apply_answers(self.root, self.semantic_layer, answers, answer_base=answers_path.parent)
        self.save()
        completed_sections = completed_answer_sections(answers)
        tasks = read_completion_tasks(self.root)
        for task in tasks:
            if task.status != "waived":
                task.status = "answered" if task.section in completed_sections else "open"
        write_completion_tasks(self.root, tasks)
        return self

    def validate(self, mode: str = "draft") -> ValidationReport:
        """Run validation and return a validation report."""

        from claimtrace.validation.engine import validate_package

        return validate_package(self.root, mode=mode)

    def export(
        self,
        output: str | Path,
        mode: str = "archive",
        zip_output: bool | None = None,
        *,
        force: bool = False,
    ) -> Path:
        """Export this package as a directory or zip archive."""

        from claimtrace.export.directory import export_package

        return export_package(self.root, Path(output), mode=mode, zip_output=zip_output, force=force)


def init_package(
    native: str | Path | list[str | Path] | None = None,
    image: str | Path | list[str | Path] | None = None,
    out: str | Path | None = None,
    template: str = "simple-structure-view",
    artifacts: list[str | Path] | None = None,
    title: str = "Untitled ClaimTrace package",
    force: bool = False,
    blank: bool = False,
) -> ClaimTracePackage:
    """Initialize a ClaimTrace package from native, image and optional evidence artifacts."""

    root = Path(out) if out is not None else Path("scene-package")
    native_paths = _coerce_paths(native)
    image_paths = _coerce_paths(image)
    artifact_paths = _coerce_paths(artifacts)
    input_paths = native_paths + image_paths + artifact_paths
    if not input_paths and not blank:
        raise PackageError("No input files were provided. Add --native, --image or --artifact, or pass --blank.")
    _ensure_inputs_exist(input_paths)
    _ensure_supported_inputs(native_paths, {".pml", ".cxc", ".mvsj", ".mvsx"}, "native scene")
    _ensure_supported_inputs(
        image_paths,
        {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".webp", ".svg"},
        "rendered image",
    )
    tasks = completion_tasks_for_template(template)
    root_was_absent = not root.exists()
    root_was_empty = root.exists() and root.is_dir() and not any(root.iterdir())
    try:
        semantic = create_package_root(root, title=title, force=force)
        semantic.package.profile = template
        importers = default_importers(include_experimental=False)
        for path in native_paths:
            _register_and_import(root, semantic, Path(path), importers)
        for path in image_paths:
            _register_and_import(root, semantic, Path(path), importers)
        for path in artifact_paths:
            source = Path(path)
            artifact = register_local_artifact(
                root,
                semantic,
                source,
                copy=True,
                relative_destination=replay_destination_for(semantic, source),
            )
            semantic.add_activity("artifact_registration", f"Registered artifact {artifact.id}.")
        ensure_scene_for_images(semantic)
        synchronize_resource_bindings(semantic)
        write_semantic_layer(root, semantic)
        write_completion_tasks(root, tasks + read_completion_tasks(root))
        return ClaimTracePackage(root=root, semantic_layer=semantic)
    except Exception:
        if (root_was_absent or root_was_empty) and root.exists():
            shutil.rmtree(root)
            if root_was_empty:
                root.mkdir(parents=True, exist_ok=True)
        raise


def load_package(package: str | Path) -> ClaimTracePackage:
    """Load an existing ClaimTrace package directory."""

    root = Path(package)
    if not (root / SEMANTIC_LAYER_FILENAME).exists():
        raise PackageError(f"Missing {SEMANTIC_LAYER_FILENAME}: {root}")
    return ClaimTracePackage(root=root, semantic_layer=load_semantic_layer(root))


def validate_package(package: str | Path | ClaimTracePackage, mode: str = "draft") -> ValidationReport:
    """Validate a package directory."""

    from claimtrace.validation.engine import validate_package as _validate

    root = package.root if isinstance(package, ClaimTracePackage) else Path(package)
    return _validate(root, mode=mode)


def export_package(
    package: str | Path | ClaimTracePackage,
    output: str | Path,
    mode: str = "archive",
    zip_output: bool | None = None,
    *,
    force: bool = False,
) -> Path:
    """Export a package as a directory or zip archive."""

    from claimtrace.export.directory import export_package as _export

    root = package.root if isinstance(package, ClaimTracePackage) else Path(package)
    output_path = Path(output)
    if zip_output is None:
        zip_output = output_path.suffix == ".zip"
    return _export(root, output_path, mode=mode, zip_output=zip_output, force=force)


def _register_and_import(root: Path, semantic: SemanticLayer, source: Path, importers: list[Any]) -> None:
    artifact = register_local_artifact(root, semantic, source, copy=True)
    package_path = root / str(artifact.path)
    plugin = detect_importer(package_path, importers)
    result = plugin.import_into(package_path, artifact.id, semantic)
    append_extraction_report(root, result.importer_name, result.fact_dicts())
    existing_tasks = read_completion_tasks(root)
    write_completion_tasks(root, existing_tasks + result.tasks)
    semantic.add_activity(
        "static_import",
        f"Imported {artifact.path} with {result.importer_name}.",
        importer=result.importer_name,
        warnings=result.warnings,
    )


def _coerce_paths(value: Any) -> list[Path]:
    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return [Path(value)]
    return [Path(item) for item in value]


def _ensure_inputs_exist(paths: list[Path]) -> None:
    for path in paths:
        if not path.exists():
            raise PackageError(
                f"Input file not found: {path}. "
                "Run from the directory containing the file or pass an absolute path."
                f"{windows_path_hint(path)}"
            )


def _ensure_supported_inputs(paths: list[Path], suffixes: set[str], label: str) -> None:
    allowed = ", ".join(sorted(suffixes))
    for path in paths:
        if not path.is_file():
            raise PackageError(f"{label.capitalize()} input must be a regular file: {path}")
        if path.suffix.lower() not in suffixes:
            raise PackageError(
                f"Unsupported {label} format for {path}. Supported extensions: {allowed}. "
                "Use --artifact for other supporting files."
            )


def semantic_to_json(semantic: SemanticLayer) -> str:
    """Serialize a CAL object as stable pretty JSON."""

    return json.dumps(semantic.model_dump(mode="json", exclude_none=True), indent=2) + "\n"
