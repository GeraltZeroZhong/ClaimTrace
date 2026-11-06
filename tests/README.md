# Test fixtures

The public test suite uses small, independently authored inputs to exercise file
parsing, claim records, validation, local HTTP interactions, and package export.

- `golden/simple-pymol-structure/input/model.cif` contains one carbon atom at the
  origin. The accompanying scene commands, image, answers, and expected records
  form a synthetic package contract.
- Inline PDB, mmCIF, SDF, MOL, PDBQT, scene, JSON, and CSV inputs are constructed
  directly in the tests. Format-recognition fixtures use a single atom or a small
  schema fragment; measured-distance tests use a toy value of 3.0 angstrom.
- The GUI practice generator in `claimtrace.gui.examples` authors its coordinates
  explicitly. Distance and RMSD tests derive their expected values from those
  coordinates. Pillow generates the associated coordinate diagrams.
- Image-preview tests create solid-color images with Pillow. Archive tests assemble
  their members locally. Security tests use invented credential-like strings and
  reserved example domains to exercise detection and path boundaries.
- Unicode path tests encode non-Latin filenames with Unicode escapes to verify
  file handling. Their source comments and descriptions use English.

Install development dependencies with `python -m pip install -e '.[dev]'`, then
run `python -m pytest` from the repository root. Tests use temporary directories
and local HTTP servers. The fixtures check software behavior with known inputs
and expected results.
