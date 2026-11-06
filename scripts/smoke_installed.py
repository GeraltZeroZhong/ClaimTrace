"""Exercise an installed wheel from a temporary working directory."""
from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile

import claimtrace
from PIL import Image
from claimtrace.gui.server import create_server


def main() -> None:
    origin = Path(claimtrace.__file__).resolve()
    assert origin.is_relative_to(Path(sys.prefix).resolve()), origin
    assert importlib.metadata.version('claimtrace') == claimtrace.PACKAGE_VERSION
    with tempfile.TemporaryDirectory(prefix='claimtrace-wheel-') as temporary:
        work = Path(temporary)
        image = work / 'figure.png'
        Image.new('RGB', (20, 20), '#315f4b').save(image)
        entry = Path(sys.executable).parent / ('claimtrace.exe' if os.name == 'nt' else 'claimtrace')
        installed_cli = subprocess.run([str(entry), '--version'], cwd=work, capture_output=True,
                                       text=True, encoding='utf-8')
        assert installed_cli.returncode == 0, installed_cli.stderr
        assert claimtrace.PACKAGE_VERSION in installed_cli.stdout
        pkg = claimtrace.init_package(image=image, out=work / 'package')
        scene = pkg.semantic_layer.scenes[0].id

        def command(*arguments: str) -> str:
            result = subprocess.run([sys.executable, '-m', 'claimtrace', *arguments],
                                    cwd=work, capture_output=True, text=True, encoding='utf-8')
            assert result.returncode == 0, (arguments, result.stdout, result.stderr)
            return result.stdout

        command('--version')
        command('--help')
        json.loads(command('schema'))
        assert json.loads(command('agent', 'schema'))['ok']
        source = work / 'proposal.json'
        source.write_text(json.dumps({
            'id': 'proposal:smoke',
            'actor': {'id': 'agent:smoke', 'name': 'Installation check'},
            'title': 'Describe the synthetic panel',
            'rationale': 'The fixture contains a solid-color panel.',
            'changes': [{'record_type': 'claim', 'record_id': 'claim:smoke', 'fields': {
                'claim_text': 'The panel shows a synthetic color patch.',
                'claim_type': 'simple_structure_view', 'figure_ref': 'A', 'scene_ids': [scene],
            }}],
        }), encoding='utf-8')
        before = (pkg.root / 'semantic_layer.json').read_bytes()
        assert json.loads(command('agent', 'check', str(pkg.root), '--input', str(source)))['ok']
        assert before == (pkg.root / 'semantic_layer.json').read_bytes()
        assert json.loads(command('agent', 'propose', str(pkg.root), '--input', str(source)))['ok']
        assert json.loads(command('agent', 'review', str(pkg.root), 'proposal:smoke',
                                  '--decision', 'accept', '--reviewer', 'Installation reviewer'))['ok']
        summary = json.loads(command('agent', 'inspect', str(pkg.root), '--summary'))
        assert summary['audit']['claims'][0]['id'] == 'claim:smoke'
        command('review', str(pkg.root))
        command('export', str(pkg.root), '--out', str(work / 'review.ZIP'), '--mode', 'draft')
        with zipfile.ZipFile(work / 'review.ZIP') as archive:
            assert {'semantic_layer.json', 'README.md', 'claimtrace-export.json'} <= set(archive.namelist())
        command('skill', '--out', str(work / 'skill'))
        assert (work / 'skill/SKILL.md').is_file()
        assert (work / 'skill/agents/openai.yaml').is_file()
        assert len(list((work / 'skill/references').glob('*.md'))) == 3
        server = create_server(package=pkg.root, port=0, workspace=work / 'workspace')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for path in ('/', '/app.js', '/style.css', '/api/state'):
                with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}{path}') as response:
                    payload = response.read()
                    assert response.status == 200 and payload
                    if path == '/api/state':
                        assert json.loads(payload)['semantic']['claims'][0]['id'] == 'claim:smoke'
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
    print(f'Installed package checks passed: {origin}')


if __name__ == '__main__':
    main()
