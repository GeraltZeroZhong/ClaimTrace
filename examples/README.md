# Synthetic file examples

Use these small synthetic examples to learn import, authoring, validation and
export. The coordinates define simple geometry, the contact table gives the
resulting distances, and the PNGs are labeled placeholder cards. The example
statements describe these inputs.

For guided molecular diagrams with source tables and suggested answers, use
the same practice cases in the terminal or GUI:

```bash
claimtrace examples
claimtrace prepare --example highlight-residues
```

In the GUI, run `claimtrace gui` and choose **Try an example**. The file
examples below support terminal and package-format exercises.

For molecular views and analyses using real research data, follow the
[12 worked article cases](https://github.com/GeraltZeroZhong/ClaimTrace/blob/v1.0/docs/tutorial/README.md). Each walkthrough
provides its source files, form entries, screenshots, and a completed package.
Source attribution and reuse details accompany the tutorial.

## Example contents and provenance

| Folder | Construction | Use |
| --- | --- | --- |
| `simple-pymol-structure` | Three atoms of a toy ALA residue lie on the x-axis at 0.0, 1.5, and −1.2 angstrom. The PML requests a cyan cartoon and includes a fixed example camera. The PNG is a labeled outline card. | Native-scene import, author context, and archive export |
| `ligand-binding-pose` | One ALA CA atom is at the origin and one invented LIG O atom is at x = 2.8 angstrom. Their Euclidean distance is 2.8 angstrom, as recorded in `contacts.csv`; the answer file uses a 4.0 angstrom threshold. The PNG is a labeled outline card. | Ligand selections, a contact result, and its cutoff |
| `static-figure-only` | A labeled outline card supplies an image-only input. The answer file records the missing scene context. | Starting and sharing an image-first draft |

The YAML files provide sample entries for each example's claim and supporting
records. The PNG cards exercise image attachment and transfer. Use the
real-data tutorials above to practice reviewing a molecular view.

## Command-line quick start

From the repository root, after installing ClaimTrace:

```bash
claimtrace init --file "examples/ligand-binding-pose/figure_A.pml" --file "examples/ligand-binding-pose/figure_A.png" --file "examples/ligand-binding-pose/model.cif" --file "examples/ligand-binding-pose/contacts.csv" --out "contact-review"
claimtrace prepare "contact-review"
```

Choose **Claim**, **Evidence** and **Limitation**. The
[terminal walkthrough](../docs/cli.md) supplies every example entry. Finish
with **Review** and **Export**, or run:

```bash
claimtrace review "contact-review"
claimtrace export "contact-review" --out "contact-review.zip"
```

Both commands use the package's saved purpose, initially **Working draft**.
Run `claimtrace prepare "contact-review"` again to continue editing.

## Scripted completion

For a complete fixture-based record, apply the supplied answers:

```bash
claimtrace init "examples/simple-pymol-structure/figure_A.pml" --image "examples/simple-pymol-structure/figure_A.png" --artifact "examples/simple-pymol-structure/model.cif" --out "example-package" --template simple-structure-view --no-input
claimtrace complete "example-package" --answers "examples/simple-pymol-structure/answers.yml" --no-input
claimtrace review "example-package" --mode archive
claimtrace export "example-package" --mode archive --out "example-package.zip" --no-input
```

Use a fresh output name for each run. The explicit `--artifact` argument adds
`model.cif` alongside the scene and image. The answers file supplies the example
claim, evidence, limitation, and color explanation. Review displays the five
audit stages for Archive; export validates and writes the ZIP. The placeholder image
remains available as the original file.

To inspect the same record in the browser:

```bash
claimtrace gui "example-package"
```

## Image-first draft

```bash
claimtrace init --image "examples/static-figure-only/figure_A.png" --out "image-example" --no-input
claimtrace complete "image-example" --answers "examples/static-figure-only/answers.yml" --no-input
claimtrace review "image-example" --mode draft
claimtrace export "image-example" --mode draft --out "image-example.zip" --no-input
```

The draft includes its image and author context. The saved-scene question
remains available for later completion. See the [GUI workflow](../docs/gui.md)
for adding a native scene to an existing image scene.
