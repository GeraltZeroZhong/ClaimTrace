"""CSV previews retain table semantics and clearly bound large scientific tables."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_browser_csv_preview_handles_scientific_tables_and_quoted_cells():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the browser CSV parser")
    app = Path(__file__).parents[2] / "src/claimtrace/gui/static/app.js"
    source = app.read_text(encoding="utf-8")
    parser = source[source.index("function csvPreviewData("):source.index("function renderFilePreview(")]
    checks = r'''
const assert = require("node:assert/strict");
const quoted = csvPreviewData('\uFEFFrank,note,rmsd\r\n1,"pocket, A",1.25\r\n2,"line one\nline ""two""",2.50\r\n');
assert.deepEqual(quoted.headers, ["rank", "note", "rmsd"]);
assert.deepEqual(quoted.rows, [["1", "pocket, A", "1.25"], ["2", 'line one\nline "two"', "2.50"]]);
assert.equal(quoted.rowCount, 2);
assert.equal(csvPreviewData('a,b\n1,"unfinished'), null);
assert.equal(csvPreviewData("plain text\nsecond line"), null);
assert.deepEqual(csvPreviewData('a,b,c\n1,,\n').rows, [["1", "", ""]]);
const wide = Array.from({length: 501}, (_, i) => "frame" + i).join(",");
const matrix = csvPreviewData(Array.from({length: 51}, () => wide).join("\n"));
assert.equal(matrix.columnCount, 501);
assert.equal(matrix.shownColumns, 30);
assert.equal(matrix.rowCount, 50);
assert.equal(matrix.rows.length, 40);
assert.equal(matrix.rows[0].length, 30);
assert.equal(csvPreviewData('a,b\n"<script>alert(1)</script>",2').rows[0][0], "<script>alert(1)</script>");
const partial = csvPreviewData('atom,value\nA,3.0\nB,"truncated', 40, 30, true);
assert.equal(partial.rowCount, null);
assert.equal(partial.partial, true);
assert.deepEqual(partial.rows, [["A", "3.0"]]);
const partialLong = csvPreviewData('a,b\n' + '1,2\n'.repeat(5000) + '3,', 40, 30, true);
assert.equal(partialLong.rows.length, 40);
assert.equal(partialLong.rowCount, null);
'''
    result = subprocess.run([node, "-e", parser + checks], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
