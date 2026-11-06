"""Terminal forms over the same authoring operations used by the GUI."""

from __future__ import annotations

import base64
import math
from pathlib import Path
from typing import Any, Callable

import typer

from claimtrace.errors import ClaimTraceError
from claimtrace.gui.server import IMAGE_SUFFIXES, NATIVE_SUFFIXES, Application, _deny_credential_path
from claimtrace.package.paths import resolve_package_path
from claimtrace.workflow import LIFECYCLE_LABELS, review_package

CLAIM_TYPES = {
    "simple_structure_view": "Structure view",
    "selection_highlight": "Highlighted region",
    "ligand_binding_pose": "Ligand binding pose",
    "cryo_em_map_fit": "Cryo-EM map fit",
    "xray_density_support": "X-ray density support",
    "trajectory_mechanism": "Trajectory or mechanism",
    "model_comparison": "Model comparison",
    "computed_model_claim": "Computed model",
    "unknown": "Other",
}
EVIDENCE_TYPES = {
    "manual_rationale": "Figure or structure inspection",
    "contact_table": "Contact table",
    "measurement": "Distance measurements",
    "external_validation": "Comparison or validation report",
    "density_support": "Electron-density inspection",
    "map_fit_metric": "Map-fit measurements",
    "trajectory_analysis": "Trajectory analysis",
}
LIMITATIONS = {
    "general": "General limitation",
    "alternative_pose": "Alternative poses",
    "selection_bias": "Selection or cutoff",
    "model_confidence": "Model confidence",
    "method_limit": "Method limitation",
}


class Back(Exception):
    pass


class Draft(Exception):
    pass


def _value(value: Any) -> str:
    text = str(value if value is not None else "")
    return "" if text.lower() == "unknown" or text.startswith("TODO") else text


def _text(label: str, default: Any = "", *, required: bool = False, hint: str = "") -> str:
    if hint:
        typer.echo(hint)
    while True:
        answer = typer.prompt(label, default=_value(default), show_default=bool(_value(default)))
        if answer == ":back":
            raise Back
        if answer == ":draft":
            raise Draft
        if answer == "~":
            answer = ""
        if required and not _value(answer).strip():
            typer.echo(f"Enter {label.lower()}.")
            continue
        return answer.strip()


def _choice(label: str, options: dict[str, str], default: str | None = None) -> str:
    keys = list(options)
    for index, key in enumerate(keys, 1):
        typer.echo(f"  {index}. {options[key]}")
    initial = str(keys.index(default) + 1) if default in keys else ""
    while True:
        answer = _text(label, initial)
        if answer in options:
            return answer
        if answer.isdigit() and 1 <= int(answer) <= len(keys):
            return keys[int(answer) - 1]
        typer.echo(f"Choose a number from 1 to {len(keys)}.")


def _multiple(label: str, options: dict[str, str], default: list[str] | None = None) -> list[str]:
    if not options:
        typer.echo(f"{label}: add the source files in Add files.")
        return []
    keys = list(options)
    for index, key in enumerate(keys, 1):
        typer.echo(f"  {index}. {options[key]}")
    initial = ",".join(str(keys.index(key) + 1) for key in default or [] if key in keys) or "0"
    while True:
        answer = _text(f"{label} (numbers separated by commas; 0 = leave open)", initial)
        if answer in {"", "0"}:
            return []
        numbers = [item.strip() for item in answer.split(",")]
        if all(item.isdigit() and 1 <= int(item) <= len(keys) for item in numbers):
            return list(dict.fromkeys(keys[int(item) - 1] for item in numbers))
        typer.echo("Enter the listed numbers, such as 1,2.")


def _number(label: str, default: Any = "") -> float | None:
    while True:
        answer = _text(label, default)
        if not answer:
            return None
        try:
            value = float(answer)
            if math.isfinite(value) and value > 0:
                return value
        except ValueError:
            pass
        typer.echo("Enter a number greater than zero, or leave this detail open.")


class TerminalWorkspace:
    def __init__(
        self, application: Application, *, expert: bool = False, claim_id: str | None = None
    ):
        self.application = application
        self.expert = expert
        self.reviewed = False
        self.exported: Path | None = None
        claims = self.layer.claims
        if claim_id and claim_id.isdigit() and 1 <= int(claim_id) <= len(claims):
            claim_id = claims[int(claim_id) - 1].id
        if claim_id and claim_id not in {item.id for item in claims}:
            raise ValueError(
                "Choose a claim number from claimtrace review or an existing claim ID."
            )
        self.claim_id = claim_id or (claims[0].id if claims else None)

    @property
    def package(self):
        return self.application.require_package()

    @property
    def layer(self):
        return self.package.semantic_layer

    @property
    def claim(self):
        return next((item for item in self.layer.claims if item.id == self.claim_id), None)

    def practice(self, section: str) -> dict[str, Any]:
        return self.layer.extensions.get("gui_example", {}).get(section, {})

    def save(self, method: Callable, data: dict[str, Any], message: str) -> None:
        with self.application.edit_package() as original:
            method(data)
        if original:
            typer.echo(f"Working copy: {self.package.root}")
        self.reviewed = False
        self.exported = None
        typer.echo(message)

    def files(self, *, role: str | None = None) -> dict[str, str]:
        return {
            item.id: f"{item.path or item.url or item.id}"
            + (f" · {item.id}" if self.expert else "")
            for item in self.layer.artifacts
            if role is None or item.role.value == role
        }

    def scenes(self) -> dict[str, str]:
        files = self.files()
        return {
            scene.id: ", ".join(
                files.get(aid, aid)
                for aid in (scene.native_artifact_ids or scene.render_artifact_ids)
            )
            or scene.description
            for scene in self.layer.scenes
        }

    def require_claim(self) -> bool:
        if self.claim:
            return True
        typer.echo("Add the figure statement in Claim first.")
        return False

    def record(self, items: list[Any], label: str, field: str) -> Any:
        if not items:
            return None
        options = {item.id: f"Edit: {_value(getattr(item, field))}" for item in items}
        options["new"] = f"Add {label.lower()}"
        selected = _choice(label, options, items[0].id)
        return next((item for item in items if item.id == selected), None)

    def claim_form(self, *, new: bool = False) -> None:
        current = None if new else self.claim
        sample = self.practice("claim") if current is None else {}
        data = (
            {
                "id": current.id,
                "claim_text": current.claim_text.value,
                "figure_ref": current.figure_ref,
                "claim_type": current.claim_type.value,
                "scene_ids": list(current.scene_ids),
            }
            if current
            else {}
        )
        typer.echo("\nClaim · What does the figure show?")
        try:
            data["claim_text"] = _text(
                "Figure statement",
                current.claim_text.value if current else sample.get("claim_text", ""),
                hint="Example: The teal markers highlight chain A residues ASP 42 and SER 85.",
            )
            data["figure_ref"] = _text(
                "Figure label",
                current.figure_ref if current else sample.get("figure_ref", ""),
                hint="Example: Figure 2A",
            )
            data["claim_type"] = _choice(
                "Statement type",
                CLAIM_TYPES,
                current.claim_type.value
                if current
                else sample.get("claim_type", "simple_structure_view"),
            )
            scenes = self.scenes()
            if len(scenes) == 1:
                data["scene_ids"] = list(scenes)
                typer.echo(f"Linked scene: {next(iter(scenes.values()))}")
            else:
                data["scene_ids"] = _multiple(
                    "Linked scenes", scenes, current.scene_ids if current else []
                )
            complete = all(
                _value(data.get(k)).strip() for k in ("claim_text", "figure_ref")
            ) and bool(data["scene_ids"])
            options = (
                {"save": "Save claim", "draft": "Save draft"}
                if complete
                else {"draft": "Save draft"}
            )
            if not complete:
                typer.echo("Add a statement, figure label, and linked scene to confirm this claim.")
            data["save_draft"] = _choice("Save", options, next(iter(options))) == "draft"
        except Draft:
            data["save_draft"] = True
        self.save(
            self.application.save_claim,
            data,
            "Claim draft saved." if data["save_draft"] else "Claim saved.",
        )
        if current is None:
            self.claim_id = self.layer.claims[-1].id

    def evidence_form(self) -> None:
        if not self.require_claim():
            return
        claim = self.claim
        items = [
            e for e in self.layer.evidence if e.id in claim.evidence_ids or claim.id in e.claim_ids
        ]
        existing = self.record(items, "Evidence", "result_summary")
        sample = self.practice("evidence") if existing is None else {}
        initial = existing.model_dump(mode="json") if existing else sample
        data: dict[str, Any] = {
            "claim_id": claim.id,
            "source_artifact_ids": initial.get("source_artifact_ids", []),
            "parameters": dict(initial.get("parameters", {})),
            "thresholds": dict(initial.get("thresholds", {})),
            "units": dict(initial.get("units", {})),
        }
        if existing:
            data["id"] = existing.id
            for key in (
                "evidence_kind",
                "method_name",
                "result_summary",
                "target_selection_ids",
                "target_entity_ids",
            ):
                data[key] = initial[key]
        kinds = dict(EVIDENCE_TYPES)
        if self.expert:
            kinds.update(
                native_observation="Scene observation",
                waiver="Recorded exception",
                negative_control="Negative control",
            )
        current_kind = initial.get("evidence_kind", "manual_rationale")
        if current_kind not in kinds:
            kinds[current_kind] = current_kind.replace("_", " ").title()
        typer.echo("\nEvidence · Link a check and its finding to source files.")
        try:
            data["evidence_kind"] = _choice("Evidence type", kinds, current_kind)
            data["source_artifact_ids"] = _multiple(
                "Source files", self.files(), data["source_artifact_ids"]
            )
            hints = {
                "manual_rationale": (
                    "Compare the highlighted region with the structure selection.",
                    "The selected region contains chain A residues 42 and 85.",
                ),
                "contact_table": (
                    "Measure atom-to-atom distances using a 4 angstrom cutoff.",
                    "Two contacts meet the inclusive 4 angstrom cutoff.",
                ),
                "measurement": (
                    "Measure the distance between A/ASP42/OD1 and B/LIG1/C1.",
                    "The selected atoms are 3.2 angstrom apart.",
                ),
                "external_validation": (
                    "Align matching CA atoms and calculate RMSD.",
                    "The aligned residues have an RMSD of 1.2 angstrom.",
                ),
                "density_support": (
                    "Inspect the ligand against the electron-density map at the recorded contour.",
                    "Continuous density covers the ligand core at this contour.",
                ),
                "map_fit_metric": (
                    "Calculate the local map-model correlation in the selected region.",
                    "The selected region has a correlation of 0.82.",
                ),
                "trajectory_analysis": (
                    "Evaluate the defined event at each sampled time point.",
                    "The event is present in 35% of the sampled frames.",
                ),
            }.get(
                data["evidence_kind"],
                ("Record the check and its settings.", "Record the observation and its scope."),
            )
            data["method_name"] = _text(
                "How was it checked?",
                initial.get("method_name", ""),
                hint=f"Example: {hints[0]}",
            )
            data["result_summary"] = _text(
                "What did you find?",
                initial.get("result_summary", ""),
                hint=f"Example: {hints[1]}",
            )
            distance = data["evidence_kind"] in {"contact_table", "measurement"}
            if distance:
                if data["evidence_kind"] == "measurement":
                    measured = _number(
                        "Measured distance", data["parameters"].get("measured_distance", "")
                    )
                    if measured is not None:
                        data["parameters"]["measured_distance"] = measured
                    else:
                        data["parameters"].pop("measured_distance", None)
                cutoff = _number("Contact distance cutoff", data["thresholds"].get("distance", ""))
                if cutoff is not None:
                    data["thresholds"]["distance"] = cutoff
                else:
                    data["thresholds"].pop("distance", None)
                data["units"]["distance"] = _text(
                    "Distance unit",
                    data["units"].get("distance", ""),
                    hint="Examples: angstrom, nm",
                )
            settings = _text(
                "Analysis settings (optional)",
                data["parameters"].get("analysis_settings", ""),
                hint="Include the atom selection, alignment, or calculation settings used for this result.",
            )
            if settings:
                data["parameters"]["analysis_settings"] = settings
            else:
                data["parameters"].pop("analysis_settings", None)
            scenes = [s for s in self.layer.scenes if s.id in claim.scene_ids]
            selections = {
                s.id: s.native_selector.value
                for s in self.layer.selections
                if any(s.id in sc.selection_ids for sc in scenes)
                or s.id in initial.get("target_selection_ids", [])
            }
            data["target_selection_ids"] = (
                _multiple(
                    "Regions used in this check",
                    selections,
                    initial.get("target_selection_ids", []),
                )
                if selections
                else []
            )
            selected = set(data["target_selection_ids"])
            previous_regions = set(initial.get("target_selection_ids", []))
            previous_entities = {
                eid
                for s in self.layer.selections
                if s.id in previous_regions
                for eid in s.entity_ids
            }
            entity_ids = [
                eid for eid in initial.get("target_entity_ids", []) if eid not in previous_entities
            ]
            data["target_entity_ids"] = list(
                dict.fromkeys(
                    entity_ids
                    + [
                        eid
                        for s in self.layer.selections
                        if s.id in selected
                        for eid in s.entity_ids
                    ]
                )
            )
            complete = bool(data["source_artifact_ids"]) and all(
                _value(data.get(k)).strip() for k in ("method_name", "result_summary")
            )
            if distance:
                complete = (
                    complete
                    and bool(_value(data["units"].get("distance")))
                    and bool(
                        data["parameters"].get("measured_distance")
                        if data["evidence_kind"] == "measurement"
                        else data["thresholds"].get("distance")
                    )
                )
            if not complete:
                if (
                    data["evidence_kind"] == "measurement"
                    and not data["parameters"].get("measured_distance")
                ):
                    typer.echo("Enter the measured distance to confirm this measurement; a contact cutoff is optional.")
                typer.echo(
                    "Add the source, check, finding, and applicable distance details to confirm this evidence."
                )
            options = (
                {"save": "Save evidence", "draft": "Save draft"}
                if complete
                else {"draft": "Save draft"}
            )
            data["save_draft"] = _choice("Save", options, next(iter(options))) == "draft"
        except Draft:
            data["save_draft"] = True
        self.save(
            self.application.save_evidence,
            data,
            "Evidence draft saved." if data["save_draft"] else "Evidence saved.",
        )

    def limitation_form(self) -> None:
        if not self.require_claim():
            return
        claim = self.claim
        items = [
            u
            for u in self.layer.uncertainty
            if u.id in claim.uncertainty_ids or claim.id in u.claim_ids
        ]
        existing = self.record(items, "Limitation", "statement")
        initial = existing.model_dump() if existing else self.practice("uncertainty")
        data = {"claim_id": claim.id}
        if existing:
            data["id"] = existing.id
        data["statement"] = _text(
            "What limits this conclusion?",
            initial.get("statement", ""),
            required=True,
            hint="Example: " + (
                self.practice("uncertainty").get("statement")
                or {
                    "ligand_binding_pose": "The contact list depends on the selected atoms and distance cutoff.",
                    "trajectory_mechanism": "Events are resolved at the recorded sampling interval.",
                    "model_comparison": "The comparison depends on the aligned residues and reference model.",
                    "xray_density_support": "The visible map features depend on the contour level.",
                    "cryo_em_map_fit": "The visible map features depend on the contour level.",
                }.get(claim.claim_type.value, "This view shows one selected region and conformation.")
            ),
        )
        categories = dict(LIMITATIONS)
        category = initial.get("category", "general")
        categories.setdefault(category, category.replace("_", " ").title())
        data["category"] = _choice("Limitation type", categories, category)
        self.save(self.application.save_uncertainty, data, "Limitation saved.")

    def scene_form(self) -> None:
        scenes = self.scenes()
        if not scenes:
            typer.echo("Add a figure image or scene in Add files.")
            return
        scene_id = next(iter(scenes)) if len(scenes) == 1 else _choice("Scene", scenes)
        scene = next(s for s in self.layer.scenes if s.id == scene_id)
        typer.echo(f"\nFigure & scene details · {scenes[scene_id]}")
        kinds = {
            "molecular": "Molecular view",
            "plot": "Analysis plot",
            "figure_assembly": "Figure assembly",
        }
        kind = (
            "molecular"
            if scene.native_artifact_ids
            else _choice("Figure type", kinds, scene.extensions.get("view_kind", "molecular"))
        )
        label = "View, camera, and state" if kind == "molecular" else "Plot or figure settings"
        context = _text(
            label,
            scene.camera.get("author_context", ""),
            hint="Record the displayed orientation and state."
            if kind == "molecular"
            else "Record the axes, scale, data selection, and panel layout.",
        )
        data: dict[str, Any] = {"id": scene_id, "view_kind": kind, "camera_context": context}
        data["visibility"] = []
        for index, record in enumerate(scene.visibility):
            if record.state in {"hidden", "excluded", "simplified"}:
                target = (
                    record.native_target or record.selection_id or record.entity_id or "this region"
                )
                reason = _text(f"Why is {target} {record.state}?", record.reason)
                data["visibility"].append({"index": index, "reason": reason})
        self.save(self.application.save_context, {"scene": data}, "Figure details saved.")

    def add_files(self) -> None:
        filename = _text(
            "File path",
            required=True,
            hint="Add a figure, native scene, structure, or result file. Repeat Add files for another file.",
        )
        path = Path(filename.strip('"')).expanduser().resolve()
        _deny_credential_path(str(path))
        if not path.is_file():
            typer.echo(f"Choose an existing file: {path}")
            return
        scenes = self.scenes()
        scene_id = next(iter(scenes)) if len(scenes) == 1 else None
        image = path.suffix.lower() in IMAGE_SUFFIXES
        new_scene = False
        if len(scenes) > 1 or scenes and (image or path.suffix.lower() in NATIVE_SUFFIXES):
            options = {**scenes, "new": "New scene / package source"}
            # Native scenes can complete an image-only view or start another view.
            # Existing native views keep their source and receive a separate scene.
            if path.suffix.lower() in NATIVE_SUFFIXES:
                options = {
                    key: value for key, value in options.items()
                    if key == "new" or any(
                        scene.id == key and not scene.native_artifact_ids
                        for scene in self.layer.scenes
                    )
                }
            default = scene_id if scene_id in options else "new"
            scene_id = _choice("Attach to scene", options, default)
            if scene_id == "new":
                scene_id = None
                new_scene = image
        data = {
            "files": [
                {"name": path.name, "content": base64.b64encode(path.read_bytes()).decode("ascii")}
            ],
            "scene_id": scene_id,
        }
        if new_scene:
            data.update(role="render_image", new_scene=True)
        self.save(self.application.attach, data, f"File added: {path.name}")

    def choose_claim(self) -> None:
        claims = self.layer.claims
        options = {
            c.id: f"{_value(c.figure_ref) or 'Draft figure'} · {_value(c.claim_text.value) or 'Add a statement'}"
            for c in claims
        }
        options["new"] = "Add another claim"
        selected = _choice("Claim", options, self.claim_id)
        if selected == "new":
            self.claim_form(new=True)
        else:
            self.claim_id = selected

    def review(self) -> None:
        from claimtrace.cli import _review_summary

        payload = review_package(self.package.root)
        payload["package"] = payload["root"]
        payload["mode"] = payload["workflow"]["lifecycle"]["mode"]
        typer.echo("\n" + _review_summary(payload, expert=self.expert))
        self.reviewed = True

    def export(self) -> None:
        current = self.layer.extensions.get("gui_lifecycle", "draft")
        mode = _choice("Export purpose", LIFECYCLE_LABELS, current)
        if mode != current:
            self.save(
                self.application.set_lifecycle,
                {"mode": mode},
                f"Purpose saved: {LIFECYCLE_LABELS[mode]}.",
            )
        payload = review_package(self.package.root, mode=mode)
        if not payload["workflow"]["lifecycle"]["ready"]:
            self.review()
            return
        destination = Path(
            _text(
                "Save ZIP to",
                self.package.root.parent / f"{self.package.root.name}-{mode}.zip",
                required=True,
            )
        ).expanduser()
        # The exporter enforces output boundaries and refuses overwriting a file.
        output = self.package.export(destination, mode=mode, zip_output=True)
        self.exported = output
        typer.echo(f"Audit exported: {output}")
        typer.echo(f"{LIFECYCLE_LABELS[mode]} checks passed.")

    def identities(self) -> None:
        if not self.require_claim():
            return
        claim = self.claim
        ids = {sid for s in self.layer.scenes if s.id in claim.scene_ids for sid in s.selection_ids}
        selections = {s.id: s.native_selector.value for s in self.layer.selections if s.id in ids}
        if not selections:
            typer.echo("Add a native scene with named selections in Add files.")
            return
        if not self.files(role="structure"):
            typer.echo("Add the structure file in Add files to identify its molecules or residues.")
            return
        selection_id = _choice("Region", selections)
        entity = next(
            (
                e
                for e in self.layer.entities
                if e.extensions.get("gui_identity")
                == {"claim_id": claim.id, "selection_id": selection_id}
            ),
            None,
        )
        kind = _choice(
            "Region type",
            {"ligand": "Ligand", "residue": "Residue", "model": "Model", "other": "Other"},
            entity.entity_type if entity else "residue",
        )
        label = _text(
            "Molecule or residue identity",
            entity.label if entity else "",
            required=True,
            hint="Example: Chain A, ASP 42 and SER 85",
        )
        sources = _multiple(
            "Structure files",
            self.files(role="structure"),
            entity.source_artifact_ids if entity else [],
        )
        if not sources:
            typer.echo("Choose a structure file to save the identity.")
            return
        self.save(
            self.application.save_identities,
            {
                "claim_id": claim.id,
                "identities": [
                    {
                        "selection_id": selection_id,
                        "entity_type": kind,
                        "label": label,
                        "source_artifact_ids": sources,
                    }
                ],
            },
            "Region identity saved.",
        )

    def visual_meanings(self) -> None:
        if not self.require_claim():
            return
        state = self.application.state()
        audit = next(c for c in state["audit"]["claims"] if c["id"] == self.claim_id)
        operations = [
            o
            for o in self.layer.observed_scene_operations
            if o.operation_id in audit["operation_ids"]
            and o.operation in {"colored", "labeled", "represented", "displayed"}
        ]
        if not operations:
            typer.echo("Add a native scene to describe its colors, labels, and representations.")
            return
        selected = _choice(
            "Visual cue",
            {o.operation_id: f"{o.operation} · {o.target} · {o.details}" for o in operations},
        )
        purpose = _choice(
            "Purpose", {"meaning": "Scientific meaning", "style": "Display styling"}, "meaning"
        )
        meaning = _text("Meaning" if purpose == "meaning" else "Styling reason", required=True)
        self.save(
            self.application.save_identities,
            {
                "claim_id": self.claim_id,
                "visual_meanings": [
                    {
                        "operation_id": selected,
                        "meaning": meaning,
                        "presentation_only": purpose == "style",
                    }
                ],
            },
            "Visual meaning saved.",
        )

    def source(self) -> None:
        files = self.files()
        if not files:
            typer.echo("Add a source in Add files.")
            return
        selected = _choice("Source file", files)
        artifact = next(a for a in self.layer.artifacts if a.id == selected)
        if artifact.path:
            path = resolve_package_path(self.package.root, artifact.path)
            typer.echo(f"Source: {path}")
            if path.is_file():
                with path.open("rb") as stream:
                    data = stream.read(4001)
                try:
                    text = data[:4000].decode("utf-8")
                    if "\x00" in text:
                        raise UnicodeError
                    typer.echo(text)
                    if len(data) > 4000:
                        typer.echo(
                            "Preview: first 4,000 bytes. Open the source path for the complete file."
                        )
                except UnicodeError:
                    typer.echo("Open this file in its viewer to inspect it.")
        else:
            typer.echo(f"Source: {artifact.url}")

    def more(self) -> None:
        action = _choice(
            "More details",
            {
                "source": "Inspect source files",
                "identity": "Identify molecules and residues",
                "visual": "Explain colors and labels",
                "software": "Software and version",
                "reuse": "Reuse and citation",
                "raw": "Review preserved source content",
                "purpose": "Review purpose",
                "expert": "Toggle Expert mode",
            },
        )
        if action == "source":
            self.source()
        elif action == "identity":
            self.identities()
        elif action == "visual":
            self.visual_meanings()
        elif action == "software":
            existing = self.record(self.layer.software_environment, "Software", "name")
            software = {
                "name": _text("Software name", existing.name if existing else "", required=True),
                "version": _text("Version", existing.version if existing else ""),
                "command": _text(
                    "Command or script (optional)", existing.command if existing else ""
                ),
            }
            if existing:
                software["id"] = existing.id
            self.save(
                self.application.save_context, {"software": software}, "Software details saved."
            )
        elif action == "reuse":
            current = self.layer.reuse
            reuse = {
                "license": _text("License", current.license),
                "citation": _text("Citation", current.citation),
                "restrictions": [
                    s.strip()
                    for s in _text(
                        "Reuse restrictions (separate with semicolons)",
                        "; ".join(current.restrictions),
                    ).split(";")
                    if s.strip()
                ],
            }
            self.save(self.application.save_context, {"reuse": reuse}, "Reuse details saved.")
        elif action == "raw":
            items = self.layer.raw_native_observations
            if not items:
                typer.echo("Preserved source content: all content has a structured record.")
                return
            item_id = _choice(
                "Preserved source",
                {item.raw_id: f"{item.native_text} · {item.reason}" for item in items},
            )
            resolution = _choice(
                "Review decision",
                {
                    "reviewed_no_claim_impact": "Reviewed: claim remains unchanged",
                    "no_scene_effect": "Scene remains unchanged",
                    "not_applicable": "Outside this claim's scope",
                },
            )
            reason = _text("Review reason", required=True)
            self.save(
                self.application.save_context,
                {"raw_reviews": [{"raw_id": item_id, "resolution": resolution, "reason": reason}]},
                "Source review saved.",
            )
        elif action == "purpose":
            mode = _choice(
                "Review purpose",
                LIFECYCLE_LABELS,
                self.layer.extensions.get("gui_lifecycle", "draft"),
            )
            self.save(self.application.set_lifecycle, {"mode": mode}, "Review purpose saved.")
        else:
            self.expert = not self.expert
            typer.echo(f"Mode: {'Expert' if self.expert else 'Basic'}")

    def run(self) -> None:
        typer.echo("ClaimTrace · Prepare → Review → Export")
        typer.echo("Connect a figure statement to its evidence, sources, and limitations.")
        typer.echo(
            "Choose a number. Enter keeps the shown value; ~ clears it; :back returns to the menu."
        )
        typer.echo(
            "In Claim and Evidence, :draft saves the fields entered so far. Ctrl+C finishes."
        )
        if self.application.is_exported(self.package):
            typer.echo("Editing this received package creates a working copy when you first save.")
        if self.layer.extensions.get("gui_example"):
            typer.echo("Synthetic practice data · Supplied answers appear as editable defaults.")
        actions = {
            "1": self.claim_form,
            "2": self.evidence_form,
            "3": self.limitation_form,
            "4": self.scene_form,
            "5": self.review,
            "6": self.export,
            "7": self.add_files,
            "8": self.choose_claim,
            "9": self.more,
        }
        try:
            while True:
                state = self.application.state()
                typer.echo(
                    f"\n{self.layer.package.title} · {state['workflow']['lifecycle']['label']} · {'Expert' if self.expert else 'Basic'}"
                )
                typer.echo(f"Folder: {self.package.root}")
                claim = self.claim
                if claim:
                    label = _value(claim.figure_ref) or "Draft figure"
                    statement = _value(claim.claim_text.value) or "Add a statement"
                    typer.echo(f"Current claim: {label} · {statement}")
                    if self.expert:
                        typer.echo(f"Claim ID: {claim.id}")
                tasks = [
                    t
                    for t in state["workflow"]["tasks"]
                    if t.get("claim_id") in {None, self.claim_id}
                ]
                if tasks:
                    route = {
                        "new-claim": "1 Claim",
                        "edit-claim": "1 Claim",
                        "new-evidence": "2 Evidence",
                        "edit-evidence": "2 Evidence",
                        "cutoff": "2 Evidence",
                        "new-uncertainty": "3 Limitation",
                        "edit-uncertainty": "3 Limitation",
                        "context": "4 Figure & scene details",
                        "add-figure": "7 Add files",
                        "attach": "7 Add files",
                        "add-structure": "7 Add files",
                        "review-proposal": "5 Review",
                    }.get(tasks[0]["action"], "9 More details")
                    typer.echo(f"Next: {tasks[0]['title']} → {route}")
                elif (
                    claim and self.practice("uncertainty")
                    and not any(u.id in claim.uncertainty_ids or claim.id in u.claim_ids for u in self.layer.uncertainty)
                ):
                    typer.echo("Next: Record the practice limitation → 3 Limitation")
                elif self.exported:
                    typer.echo("Export saved. Choose 0 Finish or continue editing.")
                elif self.reviewed:
                    typer.echo("Next: Save the audit → 6 Export")
                else:
                    typer.echo("Next: Review the audit → 5 Review")
                typer.echo("1 Claim    2 Evidence    3 Limitation    4 Figure & scene details")
                typer.echo("5 Review   6 Export      7 Add files    8 Choose another claim")
                typer.echo("9 More details          0 Finish")
                try:
                    action = _text("Choose an action", "0")
                    if action == "0":
                        break
                    if action not in actions:
                        typer.echo("Choose an action from 0 to 9.")
                        continue
                    actions[action]()
                except Back:
                    typer.echo("Returned to the menu.")
                except Draft:
                    typer.echo("Use :draft in Claim or Evidence; use :back to return to the menu.")
                except (ClaimTraceError, ValueError, OSError) as exc:
                    typer.echo(f"Action needs attention: {exc}")
        except (typer.Abort, EOFError, KeyboardInterrupt):
            typer.echo("\nSession finished. Completed saves are available in the package.")
        typer.echo(f'Continue: claimtrace prepare "{self.package.root}"')


def prepare_terminal(
    package: Path | None,
    *,
    expert: bool = False,
    example: str | None = None,
    workspace: Path | None = None,
    claim_id: str | None = None,
) -> None:
    application = Application(package, workspace, interface="cli")
    if example:
        if package:
            raise ValueError("Choose a package or a practice example for this session.")
        application.example({"id": example})
    if application.package is None:
        typer.echo("ClaimTrace · Review a figure statement and the evidence behind it.")
        typer.echo("Start with your files or a practice example.")
        try:
            start = _choice(
                "Start",
                {"open": "Open a package", "files": "Choose files", "example": "Try an example"},
                "files",
            )
            if start == "open":
                application.open(Path(_text("Package folder", required=True)).expanduser())
            elif start == "example":
                from claimtrace.gui.examples import example_catalog

                chosen = _choice(
                    "Practice example", {e["id"]: e["title"] for e in example_catalog()}
                )
                application.example({"id": chosen})
            else:
                from claimtrace.api import init_package
                from claimtrace.gui.server import IMAGE_SUFFIXES, NATIVE_SUFFIXES

                paths = []
                while True:
                    filename = _text(
                        "File path" if not paths else "Next file path (Enter to continue)",
                        required=not paths,
                    )
                    if not filename:
                        break
                    path = Path(filename.strip('"')).expanduser().resolve()
                    _deny_credential_path(str(path))
                    if path.is_file():
                        paths.append(path)
                    else:
                        typer.echo(f"Choose an existing file: {path}")
                title = _text("Figure title", paths[0].stem, required=True)
                output = Path(
                    _text("Package folder", application.workspace / paths[0].stem, required=True)
                ).expanduser()
                natives = [p for p in paths if p.suffix.lower() in NATIVE_SUFFIXES]
                images = [p for p in paths if p.suffix.lower() in IMAGE_SUFFIXES]
                application.package = init_package(
                    native=natives,
                    image=images,
                    artifacts=[p for p in paths if p not in natives + images],
                    out=output,
                    title=title,
                )
                typer.echo(f"Package created: {application.package.root}")
        except (typer.Abort, EOFError, KeyboardInterrupt, Back, Draft):
            typer.echo("Start again: claimtrace prepare")
            return
    TerminalWorkspace(application, expert=expert, claim_id=claim_id).run()
