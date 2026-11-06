import hashlib
import os
from pathlib import Path

import pytest

from claimtrace import init_package
from claimtrace.errors import SecurityError
from claimtrace.package.paths import safe_walk
from claimtrace.validation import engine


def test_fixity_observation_is_shared_with_report_and_refreshed_next_call(tmp_path, monkeypatch):
    source = tmp_path / "evidence.csv"
    source.write_bytes(b"value\n1\n")
    package = init_package(artifacts=[source], out=tmp_path / "package")
    artifact = package.semantic_layer.artifacts[0]
    attached = package.root / artifact.path
    original_stat = attached.stat()
    original_hash = engine.sha256_file
    reads = []

    def count_reads(path):
        if Path(path) == attached:
            reads.append(path)
        return original_hash(path)

    monkeypatch.setattr(engine, "sha256_file", count_reads)
    initial = package.validate()
    assert len(reads) == 1
    assert initial.artifact_fixity[0]["status"] == "pass"

    # Identical size and mtime must still receive a fresh content check.
    changed = b"value\n2\n"
    attached.write_bytes(changed)
    os.utime(attached, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    updated = package.validate()
    assert len(reads) == 2
    assert updated.artifact_fixity[0]["actual_sha256"] == hashlib.sha256(changed).hexdigest()
    assert updated.artifact_fixity[0]["status"] == "fail"
    assert any(f.rule_id == "G2.FIXITY.HASH_MISMATCH" for f in updated.findings)

    attached.unlink()
    removed = package.validate()
    assert len(reads) == 2
    assert removed.artifact_fixity[0]["exists"] is False
    assert removed.artifact_fixity[0]["actual_sha256"] is None


def test_safe_walk_rechecks_links_between_traversals(tmp_path):
    root = tmp_path / "package"
    directory = root / "data"
    directory.mkdir(parents=True)
    target = directory / "source.txt"
    target.write_text("source")
    assert list(safe_walk(root)) == [target]

    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    target.unlink()
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(SecurityError, match="Symbolic links"):
        list(safe_walk(root))
