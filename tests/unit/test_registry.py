from pathlib import Path

import pytest

from claimtrace.models import SemanticLayer
from claimtrace.models.semantic_layer import ArtifactKind
from claimtrace.package.registry import register_local_artifact, register_remote_artifact
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


def test_bcif_is_not_assumed_to_be_coordinate_structure(tmp_path: Path):
    source = tmp_path / "annotation.bcif"
    source.write_bytes(b"binary annotation payload")
    root = tmp_path / "pkg"
    root.mkdir()
    semantic = SemanticLayer.new("pkg-test")

    artifact = register_local_artifact(root, semantic, source)

    assert artifact.role.value == "generic"


def test_fractional_coordinate_cif_is_inferred_as_structure(tmp_path: Path):
    source = tmp_path / "small-molecule.cif"
    source.write_text(
        "data_small\nloop_\n_atom_site_label\n_atom_site_fract_x\n"
        "_atom_site_fract_y\n_atom_site_fract_z\nC1 0.1 0.2 0.3\n",
        encoding="utf-8",
    )
    root = tmp_path / "pkg"
    root.mkdir()
    semantic = SemanticLayer.new("pkg-test")

    artifact = register_local_artifact(root, semantic, source)

    assert artifact.role.value == "structure"


def test_unregistered_destination_file_is_not_overwritten(tmp_path: Path):
    incoming_dir = tmp_path / "incoming"
    incoming_dir.mkdir()
    source = incoming_dir / "model.cif"
    source.write_text("incoming\n", encoding="utf-8")
    root = tmp_path / "pkg"
    destination = root / "data" / "structures" / "model.cif"
    destination.parent.mkdir(parents=True)
    destination.write_text("existing\n", encoding="utf-8")
    semantic = SemanticLayer.new("pkg-test")

    with pytest.raises(PackageError, match="unregistered different artifact"):
        register_local_artifact(root, semantic, source, role="structure")

    assert destination.read_text(encoding="utf-8") == "existing\n"
    assert semantic.artifacts == []


def test_unregistered_destination_directory_is_not_overwritten(tmp_path: Path):
    incoming_parent = tmp_path / "incoming"
    source = incoming_parent / "dataset"
    source.mkdir(parents=True)
    (source / "new.txt").write_text("incoming\n", encoding="utf-8")
    root = tmp_path / "pkg"
    destination = root / "data" / "dataset"
    destination.mkdir(parents=True)
    (destination / "keep.txt").write_text("existing\n", encoding="utf-8")
    semantic = SemanticLayer.new("pkg-test")

    with pytest.raises(PackageError, match="unregistered different artifact"):
        register_local_artifact(root, semantic, source, role="directory")

    assert (destination / "keep.txt").read_text(encoding="utf-8") == "existing\n"
    assert not (destination / "new.txt").exists()


def test_remote_reregistration_adds_role_checksum_and_fixity():
    semantic = SemanticLayer.new("pkg-test")
    url = "https://example.org/model.cif"
    digest = "A" * 64

    first = register_remote_artifact(semantic, url)
    updated = register_remote_artifact(
        semantic,
        url,
        role="structure",
        expected_sha256=digest,
    )

    assert updated is first
    assert len(semantic.artifacts) == 1
    assert updated.role.value == "structure"
    assert updated.sha256 == digest.lower()
    assert updated.fixity_status == "available"


def test_remote_reregistration_rejects_conflicting_checksum():
    semantic = SemanticLayer.new("pkg-test")
    url = "https://example.org/model.cif"
    register_remote_artifact(semantic, url, expected_sha256="a" * 64)

    with pytest.raises(PackageError, match="conflicting SHA-256 checksum"):
        register_remote_artifact(semantic, url, expected_sha256="b" * 64)

    assert semantic.artifacts[0].sha256 == "a" * 64


def test_malformed_remote_url_has_friendly_error():
    semantic = SemanticLayer.new("pkg-test")

    with pytest.raises(PackageError, match="URL is malformed"):
        register_remote_artifact(
            semantic,
            "https://reader:private-password@[invalid/model.cif",
        )

    assert semantic.artifacts == []


def test_detached_artifact_is_copied_when_reregistered_as_attached(tmp_path: Path):
    source = tmp_path / "incoming" / "model.cif"
    source.parent.mkdir()
    source.write_text("data_model\n", encoding="utf-8")
    root = tmp_path / "pkg"
    root.mkdir()
    semantic = SemanticLayer.new("pkg-test")

    detached = register_local_artifact(
        root,
        semantic,
        source,
        role="structure",
        detached=True,
    )
    destination = root / str(detached.path)
    assert not destination.exists()

    attached = register_local_artifact(root, semantic, source, role="structure")

    assert attached is detached
    assert attached.kind == ArtifactKind.local_attached
    assert attached.included is True
    assert destination.read_text(encoding="utf-8") == "data_model\n"


def test_missing_attached_payload_is_restored_on_reregistration(tmp_path: Path):
    source = tmp_path / "incoming" / "model.cif"
    source.parent.mkdir()
    source.write_text("data_model\n", encoding="utf-8")
    root = tmp_path / "pkg"
    root.mkdir()
    semantic = SemanticLayer.new("pkg-test")
    artifact = register_local_artifact(root, semantic, source, role="structure")
    destination = root / str(artifact.path)
    destination.unlink()

    restored = register_local_artifact(root, semantic, source, role="structure")

    assert restored is artifact
    assert restored.kind == ArtifactKind.local_attached
    assert destination.read_text(encoding="utf-8") == "data_model\n"


def test_attached_artifact_cannot_be_implicitly_changed_to_detached(tmp_path: Path):
    source = tmp_path / "incoming" / "model.cif"
    source.parent.mkdir()
    source.write_text("data_model\n", encoding="utf-8")
    root = tmp_path / "pkg"
    root.mkdir()
    semantic = SemanticLayer.new("pkg-test")
    artifact = register_local_artifact(root, semantic, source, role="structure")
    destination = root / str(artifact.path)

    with pytest.raises(PackageError, match="already attached.*cannot be changed to detached"):
        register_local_artifact(root, semantic, source, role="structure", detached=True)

    assert artifact.kind == ArtifactKind.local_attached
    assert artifact.included is True
    assert destination.read_text(encoding="utf-8") == "data_model\n"
