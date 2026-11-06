"""Small, complete source packages for learning ClaimTrace with synthetic data.

The examples leave claim, evidence and limitation records to the learner. Their
coordinates, calculations, images and scene context are supplied together so
the suggested answers can be checked against local files.
"""

from __future__ import annotations

import csv
import math
import platform
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageDraw, __version__ as pillow_version

from claimtrace.api import ClaimTracePackage, init_package
from claimtrace.constants import PACKAGE_VERSION
from claimtrace.models.semantic_layer import (
    Entity,
    MeaningStatus,
    ReviewStatus,
    SoftwareEnvironment,
    VisualEncodingSemantics,
    utc_now,
)


_CATALOG = (
    {
        "id": "highlight-residues",
        "title": "Highlight two residues",
        "description": "Connect a figure statement to its source files, then export your first review.",
    },
    {
        "id": "ligand-contacts",
        "title": "Check ligand contacts",
        "description": "Link two measured contacts to the structure, distance cutoff, and limitations.",
    },
    {
        "id": "compare-models",
        "title": "Compare two models",
        "description": "Record how two models differ using their coordinates and a comparison table.",
    },
)

_VIEW = "set_view (1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, -30, 3, 3, 0, 20, 40, -20)\n"


def example_catalog() -> list[dict[str, Any]]:
    return [{**item, "synthetic": True} for item in _CATALOG]


def _pdb(path: Path, atoms: list[tuple[str, str, int, str, float, float, float]]) -> None:
    lines = ["HEADER    SYNTHETIC PRACTICE DATA - GEOMETRY EXERCISE"]
    for serial, (resname, chain, residue, atom, x, y, z) in enumerate(atoms, 1):
        record = "HETATM" if resname == "LIG" else "ATOM"
        lines.append(
            f"{record:<6}{serial:5d} {atom:^4} {resname:>3} {chain}{residue:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}{20.0:6.2f}          {'C':>2}"
        )
    path.write_text("\n".join(lines) + "\nEND\n", encoding="utf-8")


def _table(path: Path, fields: list[str], rows: list[list[Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(fields)
        writer.writerows(rows)


def _panel(source: Path, example_id: str, title: str, rows: list[list[Any]]) -> None:
    """Draw a labeled coordinate diagram; its scope is explicit in the image."""
    canvas = Image.new("RGB", (960, 560), "#f8f7f3")
    draw = ImageDraw.Draw(canvas)
    draw.text((36, 28), "SYNTHETIC PRACTICE DATA", fill="#53685d", font_size=18)
    draw.text((36, 66), title, fill="#273e34", font_size=26)
    draw.text((36, 108), "Coordinate diagram | distances in angstroms", fill="#65736b", font_size=15)
    if example_id == "compare-models":
        draw.text((50, 175), "Matched atom", fill="#53685d", font_size=18)
        draw.text((340, 175), "Model A", fill="#32766e", font_size=18)
        draw.text((555, 175), "Model B", fill="#b78639", font_size=18)
        draw.text((770, 175), "Change", fill="#53685d", font_size=18)
        for index, row in enumerate(rows):
            y = 230 + index * 70
            draw.text((50, y), row[0], fill="#273e34", font_size=18)
            draw.ellipse((365, y, 387, y + 22), fill="#32766e")
            shift = float(row[1]) * 25
            draw.line((376, y + 11, 587 + shift, y + 11), fill="#ccd5ce", width=2)
            draw.ellipse((576 + shift, y, 598 + shift, y + 22), fill="#b78639")
            draw.text((770, y), f"{row[1]} A", fill="#273e34", font_size=18)
        draw.text(
            (50, 475),
            "Shared coordinate frame | 3 matched CA atoms | RMSD 1.155 A",
            fill="#53685d",
            font_size=17,
        )
    else:
        # x/y projection is derived from the same coordinates as the PDB.
        positions = [(0, 0, "A / ASP 42"), (6, 0, "A / SER 85"), (0, 6, "A / TYR 117")]
        for index, (x, y, label) in enumerate(positions):
            px, py = 190 + x * 78, 425 - y * 36
            color = "#32766e" if index < 2 else "#bbc2bc"
            draw.ellipse((px - 14, py - 14, px + 14, py + 14), fill=color)
            draw.text((px - 52, py + 24), label, fill="#273e34", font_size=16)
        if example_id == "ligand-contacts":
            px, py = 190 + 2 * 78, 425
            for x, text in [(190, "2.000 A"), (658, "4.000 A")]:
                draw.line((px, py, x, py), fill="#b78639", width=3)
                draw.text(((px + x) / 2 - 32, py - 30), text, fill="#805e30", font_size=15)
            draw.ellipse((px - 14, py - 14, px + 14, py + 14), fill="#b78639")
            draw.text((px - 52, py + 24), "B / LIG 1", fill="#805e30", font_size=16)
            draw.text((440, 240), "Contact: distance <= 4.000 A", fill="#53685d", font_size=18)
            draw.text((440, 272), "A / TYR 117: 6.325 A", fill="#65736b", font_size=17)
        else:
            draw.text((440, 240), "Teal: selected residues 42 and 85", fill="#32766e", font_size=18)
            draw.text((440, 272), "Gray: residue 117", fill="#65736b", font_size=17)
        draw.text(
            (36, 515), "Synthetic coordinates for a GUI exercise", fill="#65736b", font_size=15
        )
    canvas.save(source / "practice-panel.png")


def _sources(
    source: Path, example_id: str
) -> tuple[dict[str, Any], dict[str, tuple[str, str, str]]]:
    atoms = [
        ("ASP", "A", 42, "CA", 0.0, 0.0, 0.0),
        ("SER", "A", 85, "CA", 6.0, 0.0, 0.0),
        ("TYR", "A", 117, "CA", 0.0, 6.0, 0.0),
    ]
    selection_entities: dict[str, tuple[str, str, str]]
    evidence: dict[str, Any] = {"thresholds": {}, "units": {}, "parameters": {}}
    if example_id == "compare-models":
        first = [
            ("ASP", "A", 42, "CA", 0.0, 0.0, 0.0),
            ("SER", "A", 85, "CA", 3.0, 0.0, 0.0),
            ("TYR", "A", 117, "CA", 3.0, 4.0, 0.0),
        ]
        second = [*first[:2], ("TYR", "A", 117, "CA", 3.0, 4.0, 2.0)]
        _pdb(source / "model-a.pdb", first)
        _pdb(source / "model-b.pdb", second)
        differences = [math.dist(a[4:], b[4:]) for a, b in zip(first, second)]
        rows = [[f"A/{a[2]}/CA", f"{distance:.3f}"] for a, distance in zip(first, differences)]
        _table(source / "comparison.csv", ["atom", "displacement_angstrom"], rows)
        rmsd = math.sqrt(sum(value * value for value in differences) / len(differences))
        script = "load model-a.pdb, model_a\nload model-b.pdb, model_b\nselect first_model, model_a and name CA\nselect second_model, model_b and name CA\nshow spheres, first_model or second_model\ncolor teal, first_model\ncolor orange, second_model\n"
        selection_entities = {
            "first_model": ("model", "Model A: chain A residues 42, 85 and 117", "model-a.pdb"),
            "second_model": ("model", "Model B: chain A residues 42, 85 and 117", "model-b.pdb"),
        }
        claim = {
            "claim_text": f"In the synthetic models, A/117/CA differs by 2.000 angstrom and the three-atom RMSD is {rmsd:.3f} angstrom in the shared coordinate frame.",
            "figure_ref": "Practice panel C",
            "claim_type": "model_comparison",
        }
        evidence.update(
            evidence_kind="external_validation",
            method_name="Compare matching CA coordinates in the shared coordinate frame",
            result_summary=f"A/42/CA and A/85/CA differ by 0.000 angstrom; A/117/CA differs by 2.000 angstrom. RMSD over the three atoms is {rmsd:.3f} angstrom.",
            source_filenames=["model-a.pdb", "model-b.pdb", "comparison.csv", "practice-notes.txt"],
            parameters={
                "atom_matching": "chain, residue number and atom name",
                "alignment": "shared coordinate frame",
                "atom_count": 3,
            },
            units={"displacement": "angstrom", "RMSD": "angstrom"},
        )
        uncertainty = {
            "statement": "RMSD depends on atom matching and the shared coordinate frame. Real model comparisons also require alignment and an uncertainty assessment.",
            "category": "model_confidence",
        }
        notes = "Match CA atoms by chain, residue number and atom name.\nDisplacement = sqrt((xB-xA)^2 + (yB-yA)^2 + (zB-zA)^2).\nRMSD = sqrt(mean(displacement^2)) over all three matched atoms.\nBoth synthetic models use a shared coordinate frame; coordinates are compared directly.\nThe panel is a diagram of matched atom displacements.\n"
    else:
        if example_id == "ligand-contacts":
            atoms.append(("LIG", "B", 1, "C1", 2.0, 0.0, 0.0))
        _pdb(source / "synthetic.pdb", atoms)
        script = "load synthetic.pdb, practice\nselect site, chain A and resi 42+85\nshow spheres, all\ncolor gray70, all\ncolor teal, site\n"
        selection_entities = {
            "site": ("residue", "Synthetic chain A: ASP 42 / CA and SER 85 / CA", "synthetic.pdb")
        }
        if example_id == "ligand-contacts":
            script += "select ligand, chain B and resn LIG and resi 1\ncolor orange, ligand\n"
            selection_entities["ligand"] = (
                "ligand",
                "Synthetic chain B: LIG 1 / C1",
                "synthetic.pdb",
            )
            rows = [
                [
                    f"A/{atom[2]}/CA",
                    "B/1/C1",
                    f"{math.dist(atom[4:], atoms[-1][4:]):.3f}",
                    str(math.dist(atom[4:], atoms[-1][4:]) <= 4.0).lower(),
                ]
                for atom in atoms[:3]
            ]
            _table(
                source / "contacts.csv",
                ["site_atom", "ligand_atom", "distance_angstrom", "within_4_angstrom"],
                rows,
            )
            claim = {
                "claim_text": "In the synthetic structure, ligand atom B/LIG1/C1 lies within 4 angstrom of A/ASP42/CA and A/SER85/CA.",
                "figure_ref": "Practice panel B",
                "claim_type": "ligand_binding_pose",
            }
            evidence.update(
                evidence_kind="contact_table",
                method_name="Calculate atom-to-atom distances from synthetic.pdb using a 4 angstrom cutoff",
                result_summary="B/LIG1/C1 is 2.000 angstrom from A/ASP42/CA and 4.000 angstrom from A/SER85/CA. Both meet the inclusive 4 angstrom cutoff; A/TYR117/CA is 6.325 angstrom away.",
                source_filenames=["synthetic.pdb", "contacts.csv", "practice-notes.txt"],
                thresholds={"distance": 4.0},
                units={"distance": "angstrom"},
                parameters={
                    "distance_definition": "Euclidean atom-to-atom distance",
                    "comparison": "less than or equal",
                },
            )
            uncertainty = {
                "statement": "The 4 angstrom threshold describes proximity in one synthetic coordinate set. Binding affinity and pose accuracy require independent evidence.",
                "category": "selection_bias",
            }
            notes = "Distance = sqrt((x2-x1)^2 + (y2-y1)^2 + (z2-z1)^2).\nA contact is an atom pair with distance <= 4.000 angstrom.\nCompare the three chain A CA atoms against chain B residue 1 atom C1.\nCSV distances are rounded to three decimals after applying the cutoff.\nThe panel projects the coordinates onto the x/y plane.\n"
        else:
            rows = [
                ["A", atom[2], atom[0], "CA", str(atom[2] in {42, 85}).lower()] for atom in atoms
            ]
            _table(
                source / "selection.csv",
                ["chain", "residue", "residue_name", "atom", "highlighted"],
                rows,
            )
            claim = {
                "claim_text": "The teal markers highlight chain A residues ASP 42 and SER 85 in the synthetic structure.",
                "figure_ref": "Practice panel A",
                "claim_type": "selection_highlight",
            }
            evidence.update(
                evidence_kind="manual_rationale",
                method_name="Compare the named selection with the coordinate rows",
                result_summary="The site selection contains chain A residues ASP 42 and SER 85. TYR 117 appears in gray. selection.csv records membership for all three residues.",
                source_filenames=[
                    "practice.pml",
                    "synthetic.pdb",
                    "selection.csv",
                    "practice-notes.txt",
                ],
            )
            uncertainty = {
                "statement": "The colors identify a selected residue set in synthetic coordinates. Biological roles require experimental evidence.",
                "category": "general",
            }
            notes = "The site selection is chain A and residue number 42 or 85.\nMatch selection membership to the chain and residue columns in synthetic.pdb.\nTeal identifies the selected residues; gray identifies the remaining residue.\nThe panel projects the coordinates onto the x/y plane.\n"
    (source / "practice.pml").write_text(
        "# Synthetic practice data\n" + script + _VIEW, encoding="utf-8"
    )
    (source / "practice-notes.txt").write_text(
        "SYNTHETIC PRACTICE DATA\n\n"
        + notes
        + "\nCoordinate sets are authored for this teaching exercise.\nThe diagram was generated with Pillow; the PML includes a fixed camera for viewer inspection.\nOpen the PML in PyMOL to check the saved view.\n",
        encoding="utf-8",
    )
    specification = {"claim": claim, "evidence": evidence, "uncertainty": uncertainty}
    title = next(item["title"] for item in _CATALOG if item["id"] == example_id)
    _panel(source, example_id, title, rows)
    return specification, selection_entities


def create_example(example_id: str, workspace: Path) -> ClaimTracePackage:
    entry = next((item for item in _CATALOG if item["id"] == example_id), None)
    if entry is None:
        raise ValueError("Choose a practice example from the list.")
    root = workspace / f"practice-{example_id}-{uuid4().hex[:8]}"
    with tempfile.TemporaryDirectory(prefix="claimtrace-practice-") as directory:
        source = Path(directory)
        specification, entity_specs = _sources(source, example_id)
        package = init_package(
            native=source / "practice.pml",
            image=source / "practice-panel.png",
            artifacts=sorted(source.glob("*.pdb")),
            out=root,
            title=entry["title"],
        )
        for path in sorted(source.glob("*.csv")):
            package.add_artifact(
                path, role="contact_table" if path.name == "contacts.csv" else "evidence_document"
            )
        package.add_artifact(source / "practice-notes.txt", role="evidence_document")
    semantic = package.semantic_layer
    semantic.package.creator = "ClaimTrace practice example generator"
    semantic.package.license = "MIT"
    semantic.package.description = (
        "Synthetic practice data with local source files and suggested answers."
    )
    semantic.reuse.license = "MIT"
    semantic.reuse.citation = "ClaimTrace synthetic GUI practice examples"
    artifacts = {Path(item.path).name: item for item in semantic.artifacts if item.path}
    for selection in semantic.selections:
        entity_type, label, filename = entity_specs[selection.name]
        entity = Entity(
            id=f"entity:practice:{selection.name}",
            entity_type=entity_type,
            label=label,
            stable_identity=f"{filename}: {label}",
            source_artifact_ids=[artifacts[filename].id],
            review_status=ReviewStatus.confirmed,
        )
        semantic.entities.append(entity)
        selection.entity_ids = [entity.id]
        selection.review_status = ReviewStatus.confirmed
    for scene in semantic.scenes:
        scene.description = f"Synthetic practice scene: {entry['title']}"
        scene.entity_ids = [item.id for item in semantic.entities]
        scene.review_status = ReviewStatus.confirmed
    for operation in semantic.observed_scene_operations:
        if operation.operation == "colored":
            semantic.visual_encoding_semantics.append(
                VisualEncodingSemantics(
                    operation_ids=[operation.operation_id],
                    encoding_type="color",
                    meaning_status=MeaningStatus.user_confirmed_meaning,
                    meaning="Color identifies the named synthetic object or selection described in practice-notes.txt.",
                    reviewer="ClaimTrace practice example generator",
                    reviewed_at=utc_now(),
                )
            )
    semantic.software_environment.extend(
        [
            SoftwareEnvironment(
                id="software:practice:claimtrace",
                name="ClaimTrace",
                version=PACKAGE_VERSION,
                role="package generator",
            ),
            SoftwareEnvironment(
                id="software:practice:python",
                name="Python",
                version=platform.python_version(),
                role="coordinate calculations",
            ),
            SoftwareEnvironment(
                id="software:practice:pillow",
                name="Pillow",
                version=pillow_version,
                role="coordinate diagram rendering",
            ),
        ]
    )
    evidence = specification["evidence"]
    evidence["source_artifact_ids"] = [artifacts[name].id for name in evidence["source_filenames"]]
    evidence["target_selection_ids"] = [item.id for item in semantic.selections]
    evidence["target_entity_ids"] = [item.id for item in semantic.entities]
    semantic.extensions["gui_example"] = {
        **entry,
        "notice": "Synthetic practice data",
        "instructions": [
            "Add the suggested claim.",
            "Add evidence using the supplied files and example answers.",
            "Record the suggested limitation.",
            "Review the five audit stages and download the audit.",
        ],
        **specification,
    }
    semantic.add_activity(
        "generate_practice_example",
        "Generated synthetic coordinate sources, computed tables and a labeled diagram for a practice exercise.",
        generated_ids=[item.id for item in semantic.artifacts],
    )
    package.save()
    return package
