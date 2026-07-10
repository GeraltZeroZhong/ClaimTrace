from pathlib import Path

import pytest

from claimtrace.models import SemanticLayer
from claimtrace.package.registry import register_local_artifact
from claimtrace.package.paths import ensure_relative_path
from claimtrace.errors import PackageError, SecurityError


def test_register_local_artifact_copies_and_hashes(tmp_path: Path):
    source = tmp_path / "model.cif"
    source.write_text("data_x\n", encoding="utf-8")
    root = tmp_path / "pkg"
    root.mkdir()
    semantic = SemanticLayer.new("pkg-test")

    artifact = register_local_artifact(root, semantic, source, role="structure")

    assert artifact.path == "data/structures/model.cif"
    assert artifact.sha256
    assert (root / artifact.path).exists()


def test_pymol_session_is_kept_as_native_session(tmp_path: Path):
    root = tmp_path / "pkg"
    root.mkdir()
    source = tmp_path / "scene.pse"
    source.write_bytes(b"pymol-session")
    semantic = SemanticLayer.new("pkg-test")

    artifact = register_local_artifact(root, semantic, source)

    assert artifact.role.value == "native_session"
    assert artifact.path == "native/scene.pse"


def test_relative_path_rejects_traversal():
    with pytest.raises(SecurityError):
        ensure_relative_path("../secret.txt")


def test_register_local_artifact_refuses_same_package_path_collision(tmp_path: Path):
    first_dir = tmp_path / "a"
    second_dir = tmp_path / "b"
    first_dir.mkdir()
    second_dir.mkdir()
    first = first_dir / "model.cif"
    second = second_dir / "model.cif"
    first.write_text("data_first\n", encoding="utf-8")
    second.write_text("data_second\n", encoding="utf-8")
    root = tmp_path / "pkg"
    root.mkdir()
    semantic = SemanticLayer.new("pkg-test")

    register_local_artifact(root, semantic, first, role="structure")

    with pytest.raises(PackageError, match="Artifact path already exists"):
        register_local_artifact(root, semantic, second, role="structure")


def test_identical_bytes_at_distinct_paths_receive_unique_artifact_ids(tmp_path: Path):
    first = tmp_path / "a.cif"
    second = tmp_path / "b.cif"
    first.write_text("data_same\n", encoding="utf-8")
    second.write_text("data_same\n", encoding="utf-8")
    root = tmp_path / "pkg"
    root.mkdir()
    semantic = SemanticLayer.new("pkg-test")

    first_artifact = register_local_artifact(root, semantic, first, role="structure")
    second_artifact = register_local_artifact(root, semantic, second, role="structure")

    assert first_artifact.sha256 == second_artifact.sha256
    assert first_artifact.id != second_artifact.id
    assert second_artifact.id.startswith(first_artifact.id + "-")
