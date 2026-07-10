import builtins
from pathlib import Path

import pytest

from claimtrace import _simple_yaml
from claimtrace.package.layout import read_json


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
def test_json_and_yaml_paths_reject_non_finite_numbers(tmp_path: Path, token: str):
    payload = f'{{"threshold": {token}}}'
    path = tmp_path / "payload.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError, match="[Nn]on-finite"):
        _simple_yaml.loads(payload)
    with pytest.raises(ValueError, match="[Nn]on-finite"):
        read_json(path)


def test_yaml_dump_rejects_non_finite_values():
    with pytest.raises(ValueError, match="Non-finite"):
        _simple_yaml.dumps({"threshold": float("inf")})


def test_minimal_yaml_fallback_rejects_overflow(monkeypatch):
    real_import = builtins.__import__

    def import_without_yaml(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("simulate optional YAML dependency being unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_yaml)

    with pytest.raises(ValueError, match="Non-finite"):
        _simple_yaml.loads("threshold: 1e999\n")
