"""Directory and zip package export."""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path

from claimtrace.constants import VALIDATION_REPORT_FILENAME
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
    if zip_output:
        with tempfile.TemporaryDirectory(prefix="claimtrace-export-") as tmp:
            staging = Path(tmp) / "package"
            _export_directory(source_root, staging, mode=mode, force=True)
            output.parent.mkdir(parents=True, exist_ok=True)
            zip_directory(staging, output, force=True)
            roundtrip_status = _validate_zip_roundtrip(output, mode)
            _export_directory(
                source_root,
                staging,
                mode=mode,
                force=True,
                revalidation={"performed_on_exported_package": True, "status": roundtrip_status},
            )
            zip_directory(staging, output, force=True)
            _validate_zip_roundtrip(output, mode)
            return output
    return _export_directory(source_root, output, mode=mode, force=force)


def _export_directory(
    source_root: Path,
    output: Path,
    *,
    mode: str,
    force: bool,
    revalidation: dict[str, object] | None = None,
) -> Path:
    if output.exists():
        if output.resolve() == source_root.resolve():
            raise SecurityError("Export output cannot be the source package directory.")
        if not force:
            raise SecurityError(f"Export output already exists: {output}. Pass --force to replace it.")
        if output.is_dir():
            shutil.rmtree(output)
        else:
            output.unlink()
    output.mkdir(parents=True, exist_ok=True)
    _copy_package(source_root, output)
    semantic = load_semantic_layer(output)
    (output / "schema").mkdir(parents=True, exist_ok=True)
    write_json(output / "schema" / "semantic-layer.schema.json", semantic_layer_schema())
    write_json(output / "schema" / "validation-report.schema.json", validation_report_schema())
    first_report = validate_package(output, mode=mode)
    final_report = validate_package(
        output,
        mode=mode,
        revalidation=revalidation or {"performed_on_exported_package": True, "status": first_report.overall_status},
    )
    (output / "README.md").write_text(render_readme(semantic, final_report), encoding="utf-8")
    write_json(output / VALIDATION_REPORT_FILENAME, final_report.model_dump(mode="json", exclude_none=True))
    write_sha256_txt(output)
    return output


def _reject_output_inside_source(source_root: Path, output: Path) -> None:
    source_resolved = source_root.resolve()
    output_resolved = output.resolve(strict=False)
    if output_resolved == source_resolved or output_resolved.is_relative_to(source_resolved):
        raise SecurityError("Export output cannot be inside the source package directory.")


def _reject_existing_output(output: Path, *, force: bool) -> None:
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
    if output.is_dir() and any(output.iterdir()) and not (output / "semantic_layer.json").exists():
        raise SecurityError(
            f"Refusing to replace non-ClaimTrace directory with --force: {output}. "
            "Choose a new --out path or remove the directory yourself."
        )


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
    for path in sorted(safe_walk(source_root)):
        relative = path.relative_to(source_root).as_posix()
        ensure_relative_path(relative)
        if relative.startswith("checksums/"):
            continue
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _blocking_summary(report: ValidationReport) -> str:
    blockers = [
        f"{item.rule_id}: {item.message}"
        for item in report.findings
        if item.severity == "ERROR" and item.status != "WAIVED" and report.export_mode in item.blocks_modes
    ]
    return "Export blocked by validation findings:\n" + "\n".join(blockers)
