"""Build skill and tutorial downloads from explicit public file groups."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import posixpath
import re
import shutil
from urllib.parse import unquote, urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKILL = Path('src/claimtrace/resources/skills/claimtrace')
SKILL_FILES = ('SKILL.md', 'agents/openai.yaml', 'references/commands.md',
               'references/record-semantics.md', 'references/tasks.md')
PUBLIC_SUFFIXES = {'.md', '.txt', '.html', '.css', '.js', '.json', '.png', '.zip',
                   '.yml', '.yaml', '.pml', '.cif', '.csv'}


def public_files(root: Path, folder: Path) -> list[Path]:
    paths = []
    for path in sorted((root / folder).rglob('*')):
        relative = path.relative_to(root)
        if any(part.startswith('.') or part == '__pycache__' for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f'Use regular source files: {relative}')
        if path.is_file() and path.suffix in PUBLIC_SUFFIXES:
            paths.append(relative)
    return paths


def localize_repository_links(text: str, source: Path, version: str, included: set[str]) -> str:
    """Keep versioned documentation links usable in the offline tutorial ZIP."""
    pattern = re.compile(
        r'https://(?:github\.com/GeraltZeroZhong/ClaimTrace/blob/'
        r'|raw\.githubusercontent\.com/GeraltZeroZhong/ClaimTrace/)v'
        + re.escape(version) + r'/[^\s<>"\')]+')

    def local_link(match: re.Match) -> str:
        original = match.group(0)
        parts = urlsplit(original)
        target = unquote(parts.path.split(f'/v{version}/', 1)[1])
        if target not in included:
            return original
        relative = posixpath.relpath(target, source.parent.as_posix())
        return relative + (f'?{parts.query}' if parts.query else '') + (
            f'#{parts.fragment}' if parts.fragment else '')

    return pattern.sub(local_link, text)


def add_file(archive: zipfile.ZipFile, root: Path, source: Path, name: str,
             *, version: str = '', included: set[str] | None = None) -> None:
    path = root / source
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError(f'Use a regular source file: {source}')
    if included is not None and source.suffix in {'.md', '.html'}:
        text = path.read_bytes().decode('utf-8')
        archive.writestr(name, localize_repository_links(text, source, version, included))
    else:
        archive.write(path, name)


def build(root: Path, distributions: Path, output: Path) -> list[Path]:
    version = re.search(r'^version = "([^"]+)"',
                        (root / 'pyproject.toml').read_text(), re.MULTILINE).group(1)
    # Require a fresh destination so stale distributions cannot enter a release.
    output.mkdir(parents=True, exist_ok=False)
    assets = []
    for name in (f'claimtrace-{version}-py3-none-any.whl', f'claimtrace-{version}.tar.gz'):
        target = output / name
        shutil.copyfile(distributions / name, target)
        assets.append(target)
    skill = output / f'claimtrace-skill-{version}.zip'
    with zipfile.ZipFile(skill, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in SKILL_FILES:
            add_file(archive, root, SKILL / name, f'claimtrace/{name}')
        add_file(archive, root, Path('LICENSE'), 'claimtrace/LICENSE')
    assets.append(skill)
    tutorial = output / f'claimtrace-tutorials-{version}.zip'
    tutorial_files = public_files(root, Path('docs')) + public_files(root, Path('examples'))
    root_files = [Path(name) for name in ('README.md', 'README.pypi.md', 'LICENSE', 'CITATION.cff')]
    included = {source.as_posix() for source in tutorial_files + root_files}
    included.update((SKILL / name).as_posix() for name in SKILL_FILES)
    with zipfile.ZipFile(tutorial, 'w', zipfile.ZIP_DEFLATED) as archive:
        for source in tutorial_files:
            add_file(archive, root, source, source.as_posix(), version=version, included=included)
        for name in SKILL_FILES:
            add_file(archive, root, SKILL / name, (SKILL / name).as_posix())
        for source in root_files:
            add_file(archive, root, source, source.as_posix(), version=version, included=included)
        archive.writestr('index.html', '<!doctype html><html lang="en"><meta charset="utf-8">'
                        '<meta http-equiv="refresh" content="0;url=docs/tutorial/index.html">'
                        '<title>ClaimTrace tutorials</title>'
                        '<a href="docs/tutorial/index.html">Start here</a></html>')
        archive.writestr('OPEN.txt',
                        'ClaimTrace tutorials\n\nExtract this archive and open index.html.\n'
                        'Keep the folders together for screenshots and downloads.\n'
                        'Install ClaimTrace with the setup guide linked from Start here.\n'
                        'Source installation uses a separate repository checkout.\n'
                        'Data attribution and terms: docs/tutorial/SOURCES.md\n')
    assets.append(tutorial)
    lines = []
    for asset in assets:
        digest = hashlib.sha256()
        with asset.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        lines.append(f'{digest.hexdigest()}  {asset.name}\n')
    (output / 'SHA256SUMS').write_text(''.join(lines), encoding='utf-8')
    return assets


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, default=ROOT / 'dist')
    parser.add_argument('--out', type=Path, required=True, help='New output folder')
    args = parser.parse_args()
    for asset in build(ROOT, args.dist, args.out):
        print(asset)
