# ClaimTrace

Connect a molecular figure statement to its visual evidence, sources,
limitations and reproducibility record. ClaimTrace provides a local browser
GUI, a guided terminal workflow, a Python API and a companion agent skill.

Start with a PyMOL `.pml`, ChimeraX `.cxc`, MolViewSpec `.mvsj` or `.mvsx`
scene, a figure image, a structure, or a results table. Review the claim and
share the linked files and context as a portable package.

## Install and open

Use Python 3.10 or newer. Create an environment in a folder of your choice.

**Windows PowerShell**

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install claimtrace==1.0
.\.venv\Scripts\python.exe -m claimtrace gui
```

**Linux, macOS or WSL**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install claimtrace==1.0
.venv/bin/python -m claimtrace gui
```

Your browser opens at `http://127.0.0.1:8765`. Keep the terminal open during
your session. Choose **Try an example → Start first example** for a guided
introduction, or **Choose files** to work with your own figure.

**Prepare → Review → Export** follows the same claim in both the GUI and CLI.
Basic mode shows the essential questions; Expert adds source records and
analysis details. Packages save in `claimtrace-workspace/` in the launch folder.

## Install the agent skill

Run one command from the folder where you created `.venv`.

**Windows PowerShell**

```powershell
.\.venv\Scripts\python.exe -m claimtrace skill --out "$HOME\.agents\skills\claimtrace"
```

**Linux, macOS or WSL**

```bash
.venv/bin/python -m claimtrace skill --out "$HOME/.agents/skills/claimtrace"
```

Select **claimtrace** in Codex's skill picker. Give it your package's absolute
path and ask for a claim audit or a proposed change. Review suggestions in the
GUI under **Agent suggestions**, or through the CLI. The
[agent guide](https://github.com/GeraltZeroZhong/ClaimTrace/blob/v1.0/docs/agents.md)
covers other compatible clients and proposal review.

## Tutorials and reference

- [Start here](https://github.com/GeraltZeroZhong/ClaimTrace/blob/v1.0/docs/tutorial/README.md):
  a complete figure review with screenshots, source files and example answers.
- [Choose a case](https://github.com/GeraltZeroZhong/ClaimTrace/blob/v1.0/docs/tutorial/markdown/README.md):
  12 examples organized by scientific task.
- [Setup help](https://github.com/GeraltZeroZhong/ClaimTrace/blob/v1.0/docs/start.md),
  [GUI guide](https://github.com/GeraltZeroZhong/ClaimTrace/blob/v1.0/docs/gui.md),
  [CLI guide](https://github.com/GeraltZeroZhong/ClaimTrace/blob/v1.0/docs/cli.md)
  and [interface contracts](https://github.com/GeraltZeroZhong/ClaimTrace/blob/v1.0/docs/interfaces.md).
- [Release notes and upgrade guide](https://github.com/GeraltZeroZhong/ClaimTrace/blob/v1.0/docs/releases/1.0.md).

ClaimTrace reads scene records and checks package completeness and traceability.
Open preserved scenes in their molecular viewer to verify replay. Link measured
results, validation outputs and uncertainty to support scientific interpretation.

ClaimTrace software uses the MIT license. Tutorial datasets retain the source
and license terms recorded with each download.
