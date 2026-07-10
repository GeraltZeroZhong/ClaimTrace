import os
from pathlib import Path

import pytest

from claimtrace import init_package
from claimtrace.errors import SecurityError
from claimtrace.export.directory import export_package
from claimtrace.importers.experimental.molviewspec import _read_mvs
from claimtrace.models import SemanticLayer
from claimtrace.package.paths import ensure_relative_path
from claimtrace.package.registry import register_local_artifact
from claimtrace.validation.engine import validate_package


def test_absolute_path_rejected():
    with pytest.raises(SecurityError):
        ensure_relative_path("/tmp/secret")


def test_mvsx_zip_slip_rejected(tmp_path: Path):
    import zipfile

    archive = tmp_path / "bad.mvsx"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../evil.txt", "bad")
        zf.writestr("index.mvsj", "{}")
    with pytest.raises(SecurityError):
        _read_mvs(archive)


def test_export_rejects_output_inside_source_package(tmp_path: Path):
    source = Path("examples/simple-pymol-structure")
    package = init_package(
        native=source / "figure_A.pml",
        image=source / "figure_A.png",
        out=tmp_path / "pkg",
    )

    with pytest.raises(SecurityError):
        export_package(package.root, package.root / "nested-export", mode="draft")


def test_validate_rejects_semantic_layer_symlink_escape(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    try:
        (package / "semantic_layer.json").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available on this filesystem")

    report = validate_package(package, mode="archive")

    assert report.overall_status == "fail"
    assert any(item.rule_id == "SECURITY.PATH.TRAVERSAL" for item in report.findings)


def test_register_rejects_symlink_file(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    target = source / "model.cif"
    target.write_text("data_model\n", encoding="utf-8")
    link = tmp_path / "linked-model.cif"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are not available on this filesystem")

    package = tmp_path / "pkg"
    package.mkdir()
    semantic = SemanticLayer.new("pkg-test")

    with pytest.raises(SecurityError, match="linked-model\\.cif"):
        register_local_artifact(package, semantic, link, role="structure")


def test_register_rejects_directory_containing_external_symlink(tmp_path: Path):
    source = tmp_path / "source-tree"
    source.mkdir()
    link = source / "linked-hosts"
    try:
        link.symlink_to("/etc/hosts")
    except OSError:
        pytest.skip("symlinks are not available on this filesystem")

    package = tmp_path / "pkg"
    package.mkdir()
    semantic = SemanticLayer.new("pkg-test")

    with pytest.raises(SecurityError, match="linked-hosts"):
        register_local_artifact(package, semantic, source, role="directory")

    assert not (package / "data" / source.name).exists()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are not available")
def test_register_rejects_special_file_inside_directory(tmp_path: Path):
    source = tmp_path / "source-tree"
    source.mkdir()
    fifo = source / "stream.pipe"
    os.mkfifo(fifo)
    package = tmp_path / "pkg"
    package.mkdir()
    semantic = SemanticLayer.new("pkg-test")

    with pytest.raises(SecurityError, match="FIFO.*stream\\.pipe"):
        register_local_artifact(package, semantic, source, role="directory")


def test_register_rejects_recursive_directory_copy(tmp_path: Path):
    source = tmp_path / "source-tree"
    source.mkdir()
    (source / "input.txt").write_text("content\n", encoding="utf-8")
    package = source / "pkg"
    package.mkdir()
    semantic = SemanticLayer.new("pkg-test")

    with pytest.raises(SecurityError, match="inside source directory"):
        register_local_artifact(package, semantic, source, role="directory")

    assert not (package / "data").exists()
    assert semantic.artifacts == []


def test_archive_privacy_scan_checks_text_attachments(tmp_path: Path):
    note = tmp_path / "review-note.txt"
    note.write_text("api_key = abcdefghijklmnopqrstuvwxyz123456\n", encoding="utf-8")
    package = init_package(artifacts=[note], out=tmp_path / "pkg")

    report = validate_package(package.root, mode="archive")

    assert report.overall_status == "fail"
    assert any(
        item.rule_id == "SECURITY.PATH.PRIVACY" and "review-note.txt" in item.message
        for item in report.findings
    )


def test_archive_privacy_scan_checks_unregistered_package_text(tmp_path: Path):
    package = init_package(blank=True, out=tmp_path / "pkg")
    (package.root / "answers.yml").write_text(
        "token: abcdefghijklmnopqrstuvwxyz123456\n",
        encoding="utf-8",
    )

    report = validate_package(package.root, mode="archive")

    assert report.overall_status == "fail"
    assert any(
        item.rule_id == "SECURITY.PATH.PRIVACY" and "answers.yml" in item.message
        for item in report.findings
    )
