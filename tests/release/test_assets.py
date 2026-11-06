"""Release archives keep independent downloads and public files together."""
import hashlib
import importlib.util
from pathlib import Path
import zipfile

import pytest

spec = importlib.util.spec_from_file_location(
    'release_assets', Path(__file__).parents[2] / 'scripts/build_release_assets.py')
release_assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_assets)


def test_archives_include_sources_and_licenses_without_private_payloads(tmp_path):
    root = tmp_path / 'source'
    files = {
        'pyproject.toml': 'version = "1.0"\n',
        'LICENSE': 'Synthetic software license',
        'README.md': 'Read docs/tutorial/index.html',
        'README.pypi.md': 'Installed usage',
        'CITATION.cff': 'version: "1.0"',
        'docs/start.md': (
            'Install: [Start](https://github.com/GeraltZeroZhong/ClaimTrace/blob/v1.0/'
            'docs/tutorial/index.html#start)\n'
            '![Figure](https://raw.githubusercontent.com/GeraltZeroZhong/ClaimTrace/v1.0/'
            'docs/tutorial/images/figure.png)\n'
            '[API source](https://github.com/GeraltZeroZhong/ClaimTrace/blob/v1.0/'
            'src/claimtrace/api.py)\n'
            '[Earlier guide](https://github.com/GeraltZeroZhong/ClaimTrace/blob/v0.1.0/'
            'docs/tutorial/index.html)\n'
        ),
        'docs/tutorial/index.html': '<a href="../start.md">Setup</a>',
        'docs/tutorial/images/figure.png': 'Synthetic image fixture',
        'docs/tutorial/SOURCES.md': 'Synthetic sources',
        'examples/README.md': 'Synthetic examples',
        'examples/contacts.csv': 'residue,distance\n42,3.2\n',
        '.internal/research.txt': 'Private fixture',
        'docs/.cache/temporary.json': 'Cached fixture',
    }
    for name in release_assets.SKILL_FILES:
        files[(release_assets.SKILL / name).as_posix()] = (
            f'Synthetic skill {name}\n'
            'https://github.com/GeraltZeroZhong/ClaimTrace/blob/v1.0/docs/start.md\n'
        )
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    distributions = tmp_path / 'dist'
    distributions.mkdir()
    for name in ('claimtrace-1.0-py3-none-any.whl', 'claimtrace-1.0.tar.gz'):
        (distributions / name).write_bytes(b'Built once')
    out = tmp_path / 'release'
    assets = release_assets.build(root, distributions, out)
    with zipfile.ZipFile(out / 'claimtrace-tutorials-1.0.zip') as archive:
        names = set(archive.namelist())
        assert {'index.html', 'docs/start.md', 'docs/tutorial/SOURCES.md', 'LICENSE'} <= names
        assert all('.internal' not in name and '.cache' not in name for name in names)
        guide = archive.read('docs/start.md').decode('utf-8')
        assert '[Start](tutorial/index.html#start)' in guide
        assert '![Figure](tutorial/images/figure.png)' in guide
        assert '/blob/v1.0/src/claimtrace/api.py' in guide
        assert '/blob/v0.1.0/docs/tutorial/index.html' in guide
        assert archive.read('examples/contacts.csv') == (root / 'examples/contacts.csv').read_bytes()
        for name in release_assets.SKILL_FILES:
            source = release_assets.SKILL / name
            assert archive.read(source.as_posix()) == (root / source).read_bytes()
    with zipfile.ZipFile(out / 'claimtrace-skill-1.0.zip') as archive:
        assert set(archive.namelist()) == {
            f'claimtrace/{name}' for name in (*release_assets.SKILL_FILES, 'LICENSE')}
    for asset in assets[:2]:
        assert asset.read_bytes() == (distributions / asset.name).read_bytes()
    sums = (out / 'SHA256SUMS').read_text().splitlines()
    assert sums == [f'{hashlib.sha256(a.read_bytes()).hexdigest()}  {a.name}' for a in assets]
    with pytest.raises(FileExistsError):
        release_assets.build(root, distributions, out)
