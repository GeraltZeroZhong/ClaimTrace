"""Directory and zip package export."""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path

from claimtrace.constants import EXPORT_MARKER_FILENAME, VALIDATION_REPORT_FILENAME
from claimtrace.errors import SecurityError, ValidationError
from claimtrace.export.readme import render_readme
from claimtrace.export.zip import zip_directory
from claimtrace.models.validation import ValidationReport
from claimtrace.package.checksums import write_sha256_txt
from claimtrace.package.layout import load_semantic_layer, write_json
from claimtrace.package.paths import ensure_relative_path, safe_walk
from claimtrace.schemas import semantic_layer_schema, validation_report_schema
from claimtrace.validation.engine import validate_package


def export_package(
    source_root: Path,
    output: Path,
    *,
    mode: str = "archive",
    zip_output: bool = False,
    force: bool = False,
) -> Path:
    source_root = Path(source_root)
    output = Path(output)
    _reject_output_inside_source(source_root, output)
    _reject_existing_output(output, force=force)
    source_report = validate_package(source_root, mode=mode)
    if source_report.overall_status == "fail":
        raise ValidationError(_blocking_summary(source_report))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}.claimtrace-export-",
        dir=output.parent,
    ) as tmp:
        container = Path(tmp)
        staging = container / "package"
        _build_export_directory(source_root, staging, mode=mode)
        staged_output = staging
        if zip_output:
            staged_output = container / "package.zip"
            zip_directory(staging, staged_output)
            _validate_zip_roundtrip(staged_output, mode)
        else:
            final_report = validate_package(
                staging,
                mode=mode,
                revalidation={"performed_on_exported_package": True, "status": source_report.overall_status},
            )
            if final_report.overall_status == "fail":
                raise ValidationError(_blocking_summary(final_report))
        # Re-check immediately before installation so an output that appeared or
        # changed while the export was being built is not silently overwritten.
        _reject_existing_output(output, force=force)
        _replace_output_atomically(staged_output, output, container, force=force)
    return output


def _build_export_directory(source_root: Path, output: Path, *, mode: str) -> None:
    output.mkdir(parents=True)
    _copy_package(source_root, output)
    semantic = load_semantic_layer(output)
    (output / "schema").mkdir(parents=True, exist_ok=True)
    write_json(output / "schema" / "semantic-layer.schema.json", semantic_layer_schema())
    write_json(output / "schema" / "validation-report.schema.json", validation_report_schema())
    report = validate_package(
        output,
        mode=mode,
        revalidation={"performed_on_exported_package": True, "status": "pending_final_check"},
    )
    if report.overall_status == "fail":
        raise ValidationError(_blocking_summary(report))
    report.revalidation = {
        "performed_on_exported_package": True,
        "status": report.overall_status,
    }
    (output / "README.md").write_text(render_readme(semantic, report), encoding="utf-8")
    write_json(output / VALIDATION_REPORT_FILENAME, report.model_dump(mode="json", exclude_none=True))
    write_json(
        output / EXPORT_MARKER_FILENAME,
        {
            "format": "claimtrace-export.v1",
            "checksum_manifest": "checksums/sha256.txt",
            "validation_report": VALIDATION_REPORT_FILENAME,
        },
    )
    write_sha256_txt(output)


def _replace_output_atomically(
    staged: Path,
    output: Path,
    container: Path,
    *,
    force: bool,
) -> None:
    backup = container / "previous-output"
    had_output = output.exists() or output.is_symlink()
    if had_output and not force:
        raise SecurityError(f"Export output already exists: {output}. Pass --force to replace it.")
    if had_output:
        output.rename(backup)
    try:
        staged.rename(output)
    except Exception:
        if had_output and backup.exists():
            backup.rename(output)
        raise
    if had_output:
        if backup.is_dir() and not backup.is_symlink():
            shutil.rmtree(backup)
        else:
            backup.unlink()


def _reject_output_inside_source(source_root: Path, output: Path) -> None:
    source_resolved = source_root.resolve()
    output_resolved = output.resolve(strict=False)
    if (
        output_resolved == source_resolved
        or output_resolved.is_relative_to(source_resolved)
        or source_resolved.is_relative_to(output_resolved)
    ):
        raise SecurityError("Export output and source package cannot contain one another.")


def _reject_existing_output(output: Path, *, force: bool) -> None:
    if output.is_symlink():
        raise SecurityError(f"Export output cannot be a symbolic link: {output}")
    if output.exists() and not force:
        raise SecurityError(f"Export output already exists: {output}. Pass --force to replace it.")
    if output.exists() and force:
        _validate_force_replace_output(output)


def _validate_force_replace_output(output: Path) -> None:
    resolved = output.resolve()
    cwd = Path.cwd().resolve()
    home = Path.home().resolve()
    if resolved in {Path("/").resolve(), home, cwd} or cwd.is_relative_to(resolved):
        raise SecurityError(f"Refusing to replace this path with --force: {output}")
    if output.is_file():
        try:
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
        except (OSError, zipfile.BadZipFile) as exc:
            raise SecurityError(
                f"Refusing to replace a non-ClaimTrace file with --force: {output}. "
                "Choose a new --out path or remove the file yourself."
            ) from exc
        required = {"semantic_layer.json", EXPORT_MARKER_FILENAME}
        if not required.issubset(names):
            raise SecurityError(
                f"Refusing to replace a ZIP that is not a completed ClaimTrace export: {output}. "
                "Choose a new --out path or remove the file yourself."
            )
        return
    if output.is_dir() and any(output.iterdir()):
        semantic_path = output / "semantic_layer.json"
        if not semantic_path.is_file() or semantic_path.is_symlink():
            raise SecurityError(
                f"Refusing to replace non-ClaimTrace directory with --force: {output}. "
                "Choose a new --out path or remove the directory yourself."
            )
        try:
            load_semantic_layer(output)
        except Exception as exc:
            raise SecurityError(
                f"Refusing to replace a directory with an invalid ClaimTrace manifest: {output}."
            ) from exc


def _validate_zip_roundtrip(output: Path, mode: str) -> str:
    with tempfile.TemporaryDirectory(prefix="claimtrace-zip-roundtrip-") as tmp:
        target = Path(tmp) / "unzipped"
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output) as archive:
            archive.extractall(target)
        report = validate_package(
            target,
            mode=mode,
            revalidation={"performed_on_exported_package": True, "status": "roundtrip"},
        )
        if report.overall_status == "fail":
            raise ValidationError(_blocking_summary(report))
        return report.overall_status


def _copy_package(source_root: Path, output: Path) -> None:
    source_root = source_root.resolve()
    output = output.resolve()
    for path in sorted(safe_walk(source_root, include_directories=True)):
        relative = path.relative_to(source_root).as_posix()
        ensure_relative_path(relative)
        if relative.startswith("checksums/") or relative in {
            "README.md",
            VALIDATION_REPORT_FILENAME,
            EXPORT_MARKER_FILENAME,
            "schema/semantic-layer.schema.json",
            "schema/validation-report.schema.json",
        }:
            continue
        target = output / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _blocking_summary(report: ValidationReport) -> str:
    blockers = [
        f"{item.rule_id}: {item.message}"
        for item in report.findings
        if item.severity == "ERROR" and item.status != "WAIVED" and report.export_mode in item.blocks_modes
    ]
    return "Export blocked by validation findings:\n" + "\n".join(blockers)
