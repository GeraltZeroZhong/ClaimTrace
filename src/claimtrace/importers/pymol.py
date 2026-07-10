"""Static shallow PyMOL PML importer."""

from __future__ import annotations

import shlex
import re
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL

from claimtrace.importers.base import ExtractedFact, ImportResult
from claimtrace.models import CompletionTask, SemanticLayer
from claimtrace.models.semantic_layer import (
    ClaimCriticalStatus,
    ConfidenceValue,
    Evidence,
    EvidenceKind,
    ExtractionConfidence,
    NativeReference,
    ObservedSceneOperation,
    ProvenancedString,
    RawNativeObservation,
    ResourceReference,
    ReviewStatus,
    Scene,
    Selection,
    SourceLocation,
    SourceType,
    SupportStatus,
    TargetResolutionStatus,
    VisibilityRecord,
)
from claimtrace.visual_semantics import suggest_visual_encoding


SUPPORTED = {
    "reinitialize",
    "load",
    "fetch",
    "select",
    "create",
    "show",
    "hide",
    "color",
    "bg_color",
    "set_color",
    "spectrum",
    "clip",
    "set",
    "set_view",
    "label",
    "distance",
    "remove",
    "delete",
    "enable",
    "disable",
    "orient",
    "center",
    "origin",
    "turn",
    "zoom",
    "ray",
    "png",
    "save",
    "quit",
}

UNSAFE_PREFIXES = ("@", "/", "run ", "cmd.", "python", "alias ", "do ", "spawn ")

RESERVED_SELECTION_NAMES = {
    "all",
    "and",
    "around",
    "bychain",
    "byobject",
    "byres",
    "center",
    "chain",
    "delete",
    "disable",
    "enable",
    "enabled",
    "extend",
    "first",
    "gap",
    "guide",
    "hetatm",
    "hide",
    "hydro",
    "id",
    "index",
    "last",
    "model",
    "name",
    "near_to",
    "none",
    "not",
    "object",
    "or",
    "polymer",
    "rank",
    "remove",
    "resi",
    "resn",
    "segi",
    "show",
    "solvent",
    "state",
    "visible",
    "within",
}

SELECTION_REMAINDER_COMMANDS = {
    "center",
    "delete",
    "disable",
    "enable",
    "orient",
    "origin",
    "remove",
    "zoom",
}


class PyMOLImporter:
    name = "pymol"
    stability = "stable"

    def detect(self, path: Path) -> float:
        return 1.0 if path.suffix.lower() == ".pml" else 0.0

    def import_into(self, path: Path, artifact_id: str, semantic: SemanticLayer) -> ImportResult:
        scene = _ensure_scene(semantic, artifact_id)
        result = ImportResult(importer_name=self.name)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line_no, raw_line in _logical_lines(lines):
            for ordinal, stripped in enumerate(_split_pml_statements(raw_line)):
                command, args = _split_command(stripped)
                lower = command.lower()
                if _is_dynamic(stripped, lower):
                    scene.parse_confidence = ConfidenceValue.low
                    _record_raw_observation(
                        semantic,
                        artifact_id,
                        line_no,
                        stripped,
                        "dynamic_or_executable_pymol_content",
                    )
                    fact = _fact(
                        line_no,
                        ordinal,
                        artifact_id,
                        stripped,
                        lower or "raw",
                        {"raw": stripped},
                        "raw_unsupported",
                        "low",
                        "Dynamic or executable PyMOL content is recorded but not interpreted.",
                    )
                    result.facts.append(fact)
                    result.tasks.append(
                        _task(
                            "scene",
                            f"Line {line_no} uses PyMOL behavior ClaimTrace kept as-is. Mark whether it matters for this figure.",
                            "/scenes/0/review_status",
                        )
                    )
                    continue
                if lower not in SUPPORTED:
                    scene.parse_confidence = ConfidenceValue.medium
                    _record_raw_observation(
                        semantic,
                        artifact_id,
                        line_no,
                        stripped,
                        f"unknown_pymol_command:{lower}",
                    )
                    result.facts.append(
                        _fact(
                            line_no,
                            ordinal,
                            artifact_id,
                            stripped,
                            lower,
                            {"args": args},
                            "raw_unsupported",
                            "medium",
                            "Unknown PyMOL command recorded as raw native observation.",
                        )
                    )
                    continue
                fact = _fact(
                    line_no,
                    ordinal,
                    artifact_id,
                    stripped,
                    lower,
                    {"args": args},
                    "supported_shallow",
                    "high",
                    "Known PyMOL command with literal command-line arguments.",
                )
                _normalize_pymol_command(
                    semantic,
                    scene,
                    artifact_id,
                    line_no,
                    ordinal,
                    lower,
                    args,
                    stripped,
                    fact,
                )
                result.facts.append(fact)
        _sync_scene(semantic, scene)
        return result


def _split_command(line: str) -> tuple[str, list[str]]:
    command_and_rest = line.split(None, 1)
    command = command_and_rest[0] if command_and_rest else ""
    rest = command_and_rest[1] if len(command_and_rest) > 1 else ""
    if _contains_unquoted_comma(rest):
        # Empty comma-delimited positions are meaningful for commands such as
        # ``load file, object, state`` and must not be collapsed.
        parts = _comma_words(rest)
    elif command.lower() in SELECTION_REMAINDER_COMMANDS and rest.strip():
        parts = [rest.strip()]
    else:
        parts = _shlex_words(rest)
    return command.strip(), parts


def _contains_unquoted_comma(text: str) -> bool:
    quote: str | None = None
    escaped = False
    for char in text:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == ",":
            return True
    return False


def _comma_words(text: str) -> list[str]:
    parts: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    escaped = False
    depth = 0
    for char in text:
        if quote:
            buffer.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            buffer.append(char)
        elif char in "([{":
            depth += 1
            buffer.append(char)
        elif char in ")]}":
            depth = max(0, depth - 1)
            buffer.append(char)
        elif char == "," and depth == 0:
            parts.append("".join(buffer).strip())
            buffer = []
        else:
            buffer.append(char)
    parts.append("".join(buffer).strip())
    return parts


def _logical_lines(lines: list[str]):
    buffer = ""
    start_line = 1
    paren_balance = 0
    for line_no, raw_line in enumerate(lines, start=1):
        stripped = _strip_inline_comment(raw_line).strip()
        if not stripped and not buffer:
            continue
        if not buffer:
            start_line = line_no
        continuation = _has_unquoted_trailing_backslash(stripped)
        part = stripped[:-1].strip() if continuation else stripped
        buffer = f"{buffer} {part}".strip() if buffer else part
        paren_balance += _bracket_delta(part)
        if continuation or (buffer.lower().startswith("set_view") and paren_balance > 0):
            continue
        if buffer:
            yield start_line, buffer
        buffer = ""
        paren_balance = 0
    if buffer:
        yield start_line, buffer


def _split_pml_statements(line: str) -> list[str]:
    """Split a logical PML line at top-level semicolons.

    Quotes and bracketed expressions (notably ``set_view (...)`` and label
    formatting expressions) retain literal semicolons. Inline comments have
    already been removed per physical line by :func:`_logical_lines`.
    """

    statements: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    escaped = False
    depth = 0
    for char in line:
        if quote:
            buffer.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            buffer.append(char)
        elif char in "([{":
            depth += 1
            buffer.append(char)
        elif char in ")]}":
            depth = max(0, depth - 1)
            buffer.append(char)
        elif char == ";" and depth == 0:
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
        else:
            buffer.append(char)
    statement = "".join(buffer).strip()
    if statement:
        statements.append(statement)
    return statements


def _strip_inline_comment(line: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(line):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "#":
            return line[:index]
    return line


def _has_unquoted_trailing_backslash(text: str) -> bool:
    if not text.endswith("\\"):
        return False
    quote: str | None = None
    escaped = False
    for char in text[:-1]:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in {"'", '"'}:
            quote = char
    return quote is None


def _bracket_delta(text: str) -> int:
    quote: str | None = None
    escaped = False
    delta = 0
    for char in text:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char in "([{":
            delta += 1
        elif char in ")]}":
            delta -= 1
    return delta


def _shlex_words(text: str) -> list[str]:
    if not text:
        return []
    try:
        lexer = shlex.shlex(text, posix=False)
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return [text]


def _is_dynamic(line: str, command: str) -> bool:
    lowered = _unquoted_text(line).lower()
    if lowered.startswith(UNSAFE_PREFIXES) or command in {"run", "python", "alias", "do", "spawn"}:
        return True
    return any(token in lowered for token in ["${", " for ", " while ", " import ", "exec("])


def _unquoted_text(text: str) -> str:
    result: list[str] = []
    quote: str | None = None
    escaped = False
    for char in text:
        if quote:
            result.append(" ")
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            result.append(" ")
        else:
            result.append(char)
    return "".join(result)


def _ensure_scene(semantic: SemanticLayer, artifact_id: str) -> Scene:
    for scene in semantic.scenes:
        if artifact_id in scene.native_artifact_ids:
            return scene
    scene = Scene(
        id=f"scene:{uuid5(NAMESPACE_URL, artifact_id).hex[:12]}",
        native_artifact_ids=[artifact_id],
        parse_confidence=ConfidenceValue.high,
    )
    semantic.scenes.append(scene)
    return scene


def _sync_scene(semantic: SemanticLayer, scene: Scene) -> None:
    for index, existing in enumerate(semantic.scenes):
        if existing.id == scene.id:
            semantic.scenes[index] = scene
            return
    semantic.scenes.append(scene)


def _fact(
    line_no: int,
    ordinal: int,
    artifact_id: str,
    native_command: str,
    command: str,
    native_value: dict,
    support_status: str,
    confidence_level: str,
    basis: str,
) -> ExtractedFact:
    namespace = uuid5(NAMESPACE_URL, artifact_id).hex[:10]
    return ExtractedFact(
        fact_id=f"fact-pymol-{namespace}-{line_no:04d}-{ordinal:03d}",
        tool="pymol",
        artifact_id=artifact_id,
        source_location={"artifact_id": artifact_id, "line": line_no, "column": 1},
        native_command=native_command,
        native_value={"command": command, **native_value},
        normalized_target={"object_type": f"pymol.{command}", "json_pointer": ""},
        normalized_value={},
        support_status=support_status,
        confidence={
            "level": confidence_level,
            "score": _score(confidence_level),
            "basis": [basis, "runtime_unverified"],
        },
    )


def _score(level: str) -> float:
    return {"exact": 1.0, "high": 0.85, "medium": 0.55, "low": 0.25}.get(level, 0.0)


def _selection_id(artifact_id: str, name: str) -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "-" for ch in name).strip("-") or "selection"
    namespace = uuid5(NAMESPACE_URL, artifact_id).hex[:10]
    return f"selection:pymol:{namespace}:{clean[:48]}"


def _defined_selection_id(semantic: SemanticLayer, artifact_id: str, target: str) -> str | None:
    for selection in semantic.selections:
        if selection.source_artifact_id == artifact_id and selection.name == target:
            return selection.id
    return None


def _normalize_pymol_command(
    semantic: SemanticLayer,
    scene: Scene,
    artifact_id: str,
    line_no: int,
    ordinal: int,
    command: str,
    args: list[str],
    native_command: str,
    fact: ExtractedFact,
) -> None:
    def observe(operation: str, target: str, details: dict[str, object] | None = None) -> None:
        _record_scene_operation(
            semantic,
            scene,
            artifact_id,
            operation,
            target=target,
            line_no=line_no,
            ordinal=ordinal,
            native_command=native_command,
            details=details,
        )

    if command == "select" and args:
        name = _argument(args, 0, "selection")
        selector = args[1].strip() if len(args) > 1 and args[1].strip() else "unknown"
        name_issue = _selection_name_issue(name)
        if name_issue:
            scene.parse_confidence = ConfidenceValue.medium
            _record_raw_observation(
                semantic,
                artifact_id,
                line_no,
                native_command,
                f"{name_issue}_pymol_selection_name:{name}",
            )
        selection = Selection(
            id=_selection_id(artifact_id, name),
            name=name,
            native_selector=ProvenancedString(
                value=selector,
                source_type=SourceType.native_file,
                source_location=SourceLocation(artifact_id=artifact_id, line=line_no, column=1),
                confidence=ConfidenceValue.high,
                review_status=ReviewStatus.needs_review,
            ),
            source_artifact_id=artifact_id,
            review_status=ReviewStatus.needs_review,
            extensions={
                "runtime_verification": "unverified",
                "name_validation": name_issue or "valid_literal",
                "arguments": [_strip_outer_quotes(value) for value in args[2:] if value.strip()],
            },
        )
        _upsert_selection(semantic, selection)
        if selection.id not in scene.selection_ids:
            scene.selection_ids.append(selection.id)
        fact.normalized_target = {
            "object_type": "selection.native_selector",
            "json_pointer": f"/selections/{_selection_index(semantic, selection.id)}/native_selector",
        }
        fact.normalized_value = {
            "selection_id": selection.id,
            "native_selector": selector,
            "name_validation": name_issue or "valid_literal",
        }
    elif command in {"load", "fetch"} and args:
        uri = _option(args, 0, "filename" if command == "load" else "code", "unknown")
        explicit_object_name = _option(args, 1, "object" if command == "load" else "name", "")
        object_name = explicit_object_name or _default_object_name(uri)
        state = _option(args, 2, "state", "")
        details: dict[str, object] = {"command": command, "resource": uri}
        if state:
            details["state"] = state
        if command == "load":
            option_names = (
                ("format", 3),
                ("finish", 4),
                ("discrete", 5),
                ("quiet", 6),
                ("multiplex", 7),
                ("zoom", 8),
            )
        else:
            option_names = (
                ("finish", 3),
                ("discrete", 4),
                ("multiplex", 5),
                ("zoom", 6),
                ("type", 7),
                ("async", 8),
            )
        for option_name, index in option_names:
            option_value = _option(args, index, option_name, "")
            if option_value:
                details[option_name] = option_value
        _record_resource_reference(semantic, artifact_id, line_no, uri, object_name, command)
        observe("loaded" if command == "load" else "fetched", object_name, details)
        fact.normalized_target = {"object_type": "native.resource_reference", "json_pointer": ""}
        fact.normalized_value = {"uri": uri, "object": object_name, **details}
    elif command == "create" and args:
        object_name = _argument(args, 0, "unknown")
        source_selector = _argument(args, 1, "unknown")
        observe("created", object_name, {"command": command, "source_selector": source_selector})
        fact.normalized_target = {"object_type": "scene.observed_operation", "json_pointer": ""}
        fact.normalized_value = {
            "operation": "created",
            "target": object_name,
            "source_selector": source_selector,
        }
    elif command in {"show", "hide"} and args:
        representation = _argument(args, 0, "unknown")
        target = _argument(args, 1, "all")
        state = "visible" if command == "show" else "hidden"
        selection_id = _defined_selection_id(semantic, artifact_id, target)
        scene.visibility.append(
            VisibilityRecord(
                selection_id=selection_id,
                native_target=target,
                state=state,
                source_type=SourceType.native_file,
                review_status=ReviewStatus.needs_review,
            )
        )
        scene.representations.append(
            {"command": command, "representation": representation, "target": target, "line": line_no}
        )
        observe(
            "displayed" if command == "show" else "hidden",
            target,
            {"command": command, "representation": representation},
        )
        if command == "show" and _is_simplified_representation(representation):
            observe("simplified", target, {"command": command, "representation": representation})
        fact.normalized_target = {"object_type": "scene.visibility", "json_pointer": ""}
        fact.normalized_value = {"state": state, "representation": representation, "target": target}
    elif command == "color" and args:
        color = _argument(args, 0, "unknown")
        target = _argument(args, 1, "all")
        details = {"command": command, "color": color}
        suggestion = suggest_visual_encoding("colored", target, details)
        scene.representations.append({"command": "color", "color": color, "target": target, "line": line_no})
        observe("colored", target, details)
        fact.normalized_target = {"object_type": "scene.color", "json_pointer": ""}
        fact.normalized_value = {
            "color": color,
            "selection_id": _defined_selection_id(semantic, artifact_id, target),
            "native_target": target,
            "meaning_status": suggestion.meaning_status.value,
            "auto_annotation": suggestion.auto_annotation,
            "candidate_meaning": suggestion.candidate_meaning,
            "needs_author_confirmation": suggestion.needs_author_confirmation,
        }
    elif command == "label" and args:
        target = _argument(args, 0, "all")
        label_expression = args[1] if len(args) > 1 else "unknown"
        suggestion = suggest_visual_encoding("labeled", target, {"label_expression": label_expression})
        scene.representations.append(
            {
                "command": "label",
                "target": target,
                "label_expression": label_expression,
                "line": line_no,
            }
        )
        observe("labeled", target, {"command": command, "label_expression": label_expression})
        fact.normalized_target = {"object_type": "scene.label", "json_pointer": ""}
        fact.normalized_value = {
            "target": target,
            "label_expression": label_expression,
            "meaning_status": suggestion.meaning_status.value,
            "auto_annotation": suggestion.auto_annotation,
            "candidate_meaning": suggestion.candidate_meaning,
            "needs_author_confirmation": suggestion.needs_author_confirmation,
        }
    elif command == "clip" and args:
        clip_mode = _argument(args, 0, "unknown")
        distance = _argument(args, 1, "unknown")
        target = _argument(args, 2, "scene")
        observe(
            "clipped",
            target,
            {"command": command, "clip_mode": clip_mode, "distance": distance},
        )
        fact.normalized_target = {"object_type": "scene.clip", "json_pointer": ""}
        fact.normalized_value = {"target": target, "clip_mode": clip_mode, "distance": distance}
    elif command == "set" and args:
        setting = _argument(args, 0, "unknown")
        value = _argument(args, 1, "unknown")
        target = _argument(args, 2, "global")
        details = {"command": command, "setting": setting, "value": value}
        observe("configured", target, details)
        if "transparency" in setting.lower():
            observe("transparency_changed", target, details)
        fact.normalized_target = {"object_type": "scene.setting", "json_pointer": ""}
        fact.normalized_value = {
            "target": target,
            "setting": setting,
            "value": value,
            "operation": "transparency_changed" if "transparency" in setting.lower() else "configured",
        }
    elif command == "set_view":
        scene.camera["pymol_set_view"] = native_command
        observe(
            "camera_set",
            "scene",
            {"command": command, "camera_native_expression": native_command},
        )
        fact.normalized_target = {"object_type": "scene.camera", "json_pointer": ""}
        fact.normalized_value = {"camera_native_expression": native_command}
    elif command == "distance":
        measurement_name = _option(args, 0, "name", "dist")
        selection_1 = _option(args, 1, "selection1", "unknown")
        selection_2 = _option(args, 2, "selection2", "unknown")
        details: dict[str, object] = {
            "command": command,
            "measurement_name": measurement_name,
            "selection_1": selection_1,
            "selection_2": selection_2,
        }
        for parameter_name, index in (
            ("cutoff", 3),
            ("mode", 4),
            ("label", 5),
            ("quiet", 6),
            ("reset", 7),
            ("state", 8),
            ("zoom", 9),
        ):
            value = _option(args, index, parameter_name, "")
            if value:
                details[parameter_name] = value
        namespace = uuid5(NAMESPACE_URL, artifact_id).hex[:10]
        evidence = Evidence(
            id=f"evidence:pymol:{namespace}:distance:{line_no}:{ordinal}",
            evidence_kind=EvidenceKind.measurement,
            source_artifact_ids=[artifact_id],
            generated_by="PyMOL distance command (native observation only)",
            method_name="PyMOL distance command",
            parameters={"native_command": native_command, **details},
            result_summary="Distance/measurement intent observed in PyMOL script; not classified as a hydrogen bond or contact.",
            limitations=[
                "runtime_unverified: the script was parsed statically and no distance value was observed."
            ],
            review_status=ReviewStatus.needs_review,
            fixity_status="available",
            extensions={"runtime_verification": "unverified"},
        )
        _upsert_evidence(semantic, evidence)
        observe("measurement_intent", measurement_name, details)
        fact.normalized_target = {"object_type": "evidence.measurement_intent", "json_pointer": ""}
        fact.normalized_value = {
            "evidence_id": evidence.id,
            "classification": "measurement_intent",
            **details,
        }
    elif command == "reinitialize":
        mode = _argument(args, 0, "everything")
        target = _argument(args, 1, "scene")
        details = {"command": command, "mode": mode}
        observe("reinitialized", target, details)
        fact.normalized_target = {"object_type": "scene.lifecycle", "json_pointer": ""}
        fact.normalized_value = {"operation": "reinitialized", "target": target, **details}
    elif command == "bg_color":
        color = _argument(args, 0, "unknown")
        details = {"command": command, "color": color, "surface": "background"}
        observe("background_colored", "scene", details)
        fact.normalized_target = {"object_type": "scene.background", "json_pointer": ""}
        fact.normalized_value = {"operation": "background_colored", **details}
    elif command == "set_color":
        color_name = _argument(args, 0, "unknown")
        rgb = _argument(args, 1, "unknown")
        details = {"command": command, "color": rgb, "color_name": color_name}
        observe("custom_color_defined", color_name, details)
        fact.normalized_target = {"object_type": "scene.color_definition", "json_pointer": ""}
        fact.normalized_value = {"operation": "custom_color_defined", **details}
    elif command == "spectrum":
        expression = _option(args, 0, "expression", "count")
        palette = _option(args, 1, "palette", "rainbow")
        target = _option(args, 2, "selection", "all")
        details: dict[str, object] = {
            "command": command,
            "method": "spectrum",
            "expression": expression,
            "palette": palette,
            "color": f"spectrum:{palette}",
        }
        for parameter_name, index in (
            ("minimum", 3),
            ("maximum", 4),
            ("byres", 5),
            ("quiet", 6),
        ):
            value = _option(args, index, parameter_name, "")
            if value:
                details[parameter_name] = value
        suggestion = suggest_visual_encoding("colored", target, details)
        observe("colored", target, details)
        scene.representations.append(
            {
                "command": command,
                "expression": expression,
                "palette": palette,
                "target": target,
                "line": line_no,
            }
        )
        fact.normalized_target = {"object_type": "scene.color", "json_pointer": ""}
        fact.normalized_value = {
            "operation": "colored",
            "target": target,
            **details,
            "meaning_status": suggestion.meaning_status.value,
            "candidate_meaning": suggestion.candidate_meaning,
            "needs_author_confirmation": suggestion.needs_author_confirmation,
        }
    elif command in {"remove", "delete"}:
        target = _argument(args, 0, "all")
        operation = "atoms_removed" if command == "remove" else "object_deleted"
        details = {"command": command, "destructive": True}
        if command == "remove":
            scene.visibility.append(
                VisibilityRecord(
                    selection_id=_defined_selection_id(semantic, artifact_id, target),
                    native_target=target,
                    state="excluded",
                    reason="Atoms removed by a statically observed PyMOL command; runtime effect unverified.",
                    source_type=SourceType.native_file,
                    review_status=ReviewStatus.needs_review,
                )
            )
        observe(operation, target, details)
        fact.normalized_target = {"object_type": "scene.content", "json_pointer": ""}
        fact.normalized_value = {"operation": operation, "target": target, **details}
    elif command in {"enable", "disable"}:
        target = _argument(args, 0, "all")
        state = "visible" if command == "enable" else "hidden"
        selection_id = _defined_selection_id(semantic, artifact_id, target)
        scene.visibility.append(
            VisibilityRecord(
                selection_id=selection_id,
                native_target=target,
                state=state,
                source_type=SourceType.native_file,
                review_status=ReviewStatus.needs_review,
            )
        )
        observe(command + "d", target, {"command": command, "state": state})
        fact.normalized_target = {"object_type": "scene.visibility", "json_pointer": ""}
        fact.normalized_value = {"operation": command + "d", "target": target, "state": state}
    elif command in {"orient", "center"}:
        target = _option(args, 0, "selection", "all")
        operation = "camera_oriented" if command == "orient" else "camera_centered"
        details: dict[str, object] = {"command": command}
        state = _option(args, 1, "state", "")
        if state:
            details["state"] = state
        if command == "center":
            move_origin = _option(args, 2, "origin", "")
            animate = _option(args, 3, "animate", "")
            if move_origin:
                details["move_origin"] = move_origin
            if animate:
                details["animate"] = animate
        observe(operation, target, details)
        fact.normalized_target = {"object_type": "scene.camera", "json_pointer": ""}
        fact.normalized_value = {"operation": operation, "target": target, **details}
    elif command == "origin":
        target = _option(args, 0, "selection", "all")
        details: dict[str, object] = {"command": command}
        for parameter_name, index in (("object", 1), ("position", 2), ("state", 3)):
            value = _option(args, index, parameter_name, "")
            if value:
                details[parameter_name] = value
        observe("origin_set", target, details)
        fact.normalized_target = {"object_type": "scene.camera", "json_pointer": ""}
        fact.normalized_value = {"operation": "origin_set", "target": target, **details}
    elif command == "turn":
        axis = _option(args, 0, "axis", "unknown")
        angle = _option(args, 1, "angle", "unknown")
        details = {"command": command, "axis": axis, "angle_degrees": angle}
        observe("camera_turned", "scene", details)
        fact.normalized_target = {"object_type": "scene.camera", "json_pointer": ""}
        fact.normalized_value = {"operation": "camera_turned", **details}
    elif command == "zoom":
        target = _option(args, 0, "selection", "all")
        details: dict[str, object] = {"command": command}
        for parameter_name, index in (("buffer", 1), ("state", 2), ("complete", 3), ("animate", 4)):
            value = _option(args, index, parameter_name, "")
            if value:
                details[parameter_name] = value
        observe("camera_zoomed", target, details)
        fact.normalized_target = {"object_type": "scene.camera", "json_pointer": ""}
        fact.normalized_value = {"operation": "camera_zoomed", "target": target, **details}
    elif command == "ray":
        details: dict[str, object] = {"command": command, "runtime_output": "unverified"}
        for parameter_name, index in (
            ("width", 0),
            ("height", 1),
            ("antialias", 2),
            ("angle", 3),
            ("shift", 4),
            ("renderer", 5),
            ("quiet", 6),
            ("async", 7),
        ):
            value = _option(args, index, parameter_name, "")
            if value:
                details[parameter_name] = value
        observe("ray_traced", "scene", details)
        fact.normalized_target = {"object_type": "scene.render", "json_pointer": ""}
        fact.normalized_value = {"operation": "ray_traced", **details}
    elif command in {"png", "save"}:
        output_path = _option(args, 0, "filename", "unknown")
        details: dict[str, object] = {
            "command": command,
            "output_path": output_path,
            "output_kind": "image" if command == "png" else "session_or_structure",
            "runtime_output": "unverified",
        }
        if command == "png":
            option_names = (
                ("width", 1),
                ("height", 2),
                ("dpi", 3),
                ("ray", 4),
                ("quiet", 5),
                ("prior", 6),
            )
        else:
            option_names = (("selection", 1), ("state", 2), ("format", 3), ("partial", 4))
        for option_name, index in option_names:
            option_value = _option(args, index, option_name, "")
            if option_value:
                details[option_name] = option_value
        observe("output_intent", output_path, details)
        fact.normalized_target = {"object_type": "native.output", "json_pointer": ""}
        fact.normalized_value = {"operation": "output_intent", **details}
    elif command == "quit":
        code = _argument(args, 0, "")
        details: dict[str, object] = {"command": command}
        if code:
            details["code"] = code
        observe("session_terminated", "session", details)
        fact.normalized_target = {"object_type": "scene.lifecycle", "json_pointer": ""}
        fact.normalized_value = {"operation": "session_terminated", **details}


def _argument(args: list[str], index: int, default: str) -> str:
    if index >= len(args):
        return default
    value = args[index].strip()
    return _strip_outer_quotes(value) if value else default


def _option(args: list[str], index: int, name: str, default: str) -> str:
    for value in args:
        keyword, keyword_value = _keyword_argument(value)
        if keyword == name.lower():
            return _strip_outer_quotes(keyword_value) if keyword_value else default
    if index >= len(args) or _keyword_argument(args[index])[0] is not None:
        return default
    return _argument(args, index, default)


def _keyword_argument(value: str) -> tuple[str | None, str]:
    text = value.strip()
    if "=" not in text:
        return None, ""
    key, raw_value = text.split("=", 1)
    normalized_key = key.strip().lower()
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", normalized_key):
        return None, ""
    return normalized_key, raw_value.strip()


def _strip_outer_quotes(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        try:
            parsed = shlex.split(text)
        except ValueError:
            return text[1:-1]
        if len(parsed) == 1:
            return parsed[0]
        return text[1:-1]
    return text


def _default_object_name(uri: str) -> str:
    # ``Path`` on Linux does not split a Windows PML path at backslashes.
    # Normalize only for basename inference; the resource URI remains exact.
    basename = uri.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1]
    return Path(basename).stem or basename or uri


def _selection_name_issue(name: str) -> str | None:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
        return "invalid"
    if name.lower() in RESERVED_SELECTION_NAMES:
        return "reserved"
    return None


def _record_scene_operation(
    semantic: SemanticLayer,
    scene: Scene,
    artifact_id: str,
    operation: str,
    *,
    target: str,
    line_no: int,
    ordinal: int,
    native_command: str,
    details: dict[str, object] | None = None,
) -> None:
    details = details or {}
    suggestion = suggest_visual_encoding(operation, target, details)
    meaning_status = suggestion.meaning_status
    operation_identity = f"{artifact_id}:{line_no}:{operation}:{target}:{native_command}"
    if ordinal:
        operation_identity = f"{operation_identity}:{ordinal}"
    operation_id = f"op:pymol:{uuid5(NAMESPACE_URL, operation_identity).hex[:12]}"
    typed_operation = ObservedSceneOperation(
        operation_id=operation_id,
        operation=operation,
        target=target,
        details=details,
        auto_annotation=suggestion.auto_annotation,
        candidate_meaning=suggestion.candidate_meaning,
        meaning_confidence=suggestion.meaning_confidence,
        meaning_basis=suggestion.meaning_basis,
        needs_author_confirmation=suggestion.needs_author_confirmation,
        source_location=SourceLocation(artifact_id=artifact_id, line=line_no, column=1),
        native_command=native_command,
        native_value={"tool": "pymol", "operation": operation, "target": target, "details": details},
        support_status=SupportStatus.supported_shallow,
        extraction_confidence=ExtractionConfidence(
            level=ConfidenceValue.high,
            score=0.85,
            basis=["pymol_static_command", "runtime_unverified"],
        ),
        review_status=ReviewStatus.auto_extracted,
        meaning_status=meaning_status,
        target_resolution_status=TargetResolutionStatus.expression_only,
        claim_critical=ClaimCriticalStatus.unknown,
    )
    _upsert_observed_operation(semantic, typed_operation)
    operations = scene.extensions.get("observed_scene_operations", [])
    if not isinstance(operations, list):
        operations = []
    operations.append(
        {
            "operation_id": operation_id,
            "operation": operation,
            "target": target,
            "details": details,
            "source_location": {"line": line_no, "column": 1},
            "native_command": native_command,
            "source_type": "native_file",
            "review_status": "auto_extracted",
            "meaning_status": meaning_status.value,
            "auto_annotation": suggestion.auto_annotation,
            "candidate_meaning": suggestion.candidate_meaning,
            "meaning_confidence": suggestion.meaning_confidence.value,
            "meaning_basis": suggestion.meaning_basis,
            "needs_author_confirmation": suggestion.needs_author_confirmation,
            "runtime_verification": "unverified",
        }
    )
    scene.extensions["observed_scene_operations"] = operations


def _record_raw_observation(
    semantic: SemanticLayer,
    artifact_id: str,
    line_no: int,
    native_text: str,
    reason: str,
) -> None:
    raw = RawNativeObservation(
        raw_id=f"raw:pymol:{uuid5(NAMESPACE_URL, f'{artifact_id}:{line_no}:{native_text}').hex[:12]}",
        artifact_id=artifact_id,
        source_location=SourceLocation(artifact_id=artifact_id, line=line_no, column=1),
        native_text=native_text,
        reason=reason,
        support_status=SupportStatus.raw_unsupported,
        extraction_confidence=ExtractionConfidence(
            level=ConfidenceValue.low,
            score=0.25,
            basis=["pymol_raw_preserved", "runtime_unverified"],
        ),
        claim_critical=ClaimCriticalStatus.unknown,
        review_status=ReviewStatus.needs_review,
    )
    if not any(existing.raw_id == raw.raw_id for existing in semantic.raw_native_observations):
        semantic.raw_native_observations.append(raw)


def _record_resource_reference(
    semantic: SemanticLayer,
    artifact_id: str,
    line_no: int,
    uri: str,
    object_name: str,
    command: str,
) -> None:
    resource_id = f"resource:pymol:{uuid5(NAMESPACE_URL, f'{artifact_id}:{line_no}:{uri}').hex[:12]}"
    native_ref_id = f"native-ref:pymol:{uuid5(NAMESPACE_URL, f'{artifact_id}:{line_no}:{object_name}').hex[:12]}"
    resource = ResourceReference(
        resource_ref_id=resource_id,
        artifact_id=artifact_id,
        uri=uri,
        uri_kind=_uri_kind(uri, command),
        fetch_status="not_fetched",
        fixity_status="unknown",
        claim_critical=ClaimCriticalStatus.unknown,
        source_location=SourceLocation(artifact_id=artifact_id, line=line_no, column=1),
    )
    if not any(existing.resource_ref_id == resource_id for existing in semantic.resource_references):
        semantic.resource_references.append(resource)
    native_ref = NativeReference(
        native_ref_id=native_ref_id,
        source_location=SourceLocation(artifact_id=artifact_id, line=line_no, column=1),
        native_expression=object_name,
        ref_type="pymol_object",
        stable_identity=uri if command == "load" else None,
        identity_status="resolved" if command == "load" else "unresolved",
        claim_critical=ClaimCriticalStatus.unknown,
        review_status=ReviewStatus.needs_review,
        target_resolution_status=TargetResolutionStatus.expression_only,
    )
    if not any(existing.native_ref_id == native_ref_id for existing in semantic.native_references):
        semantic.native_references.append(native_ref)


def _uri_kind(uri: str, command: str) -> str:
    lowered = uri.lower()
    if lowered.startswith(("http://", "https://")):
        return "remote"
    if lowered.startswith(("file:", "/", "\\\\")) or re.match(r"^[a-z]:[\\/]", lowered):
        return "file"
    if command == "fetch":
        return "remote"
    return "relative"


def _upsert_observed_operation(semantic: SemanticLayer, operation: ObservedSceneOperation) -> None:
    for index, existing in enumerate(semantic.observed_scene_operations):
        if existing.operation_id == operation.operation_id:
            semantic.observed_scene_operations[index] = operation
            return
    semantic.observed_scene_operations.append(operation)


def _is_simplified_representation(representation: str) -> bool:
    return representation.lower() in {"cartoon", "ribbon", "surface", "mesh"}


def _upsert_selection(semantic: SemanticLayer, selection: Selection) -> None:
    for index, existing in enumerate(semantic.selections):
        if existing.id == selection.id:
            semantic.selections[index] = selection
            return
    semantic.selections.append(selection)


def _upsert_evidence(semantic: SemanticLayer, evidence: Evidence) -> None:
    for index, existing in enumerate(semantic.evidence):
        if existing.id == evidence.id:
            semantic.evidence[index] = evidence
            return
    semantic.evidence.append(evidence)


def _selection_index(semantic: SemanticLayer, selection_id: str) -> int:
    for index, selection in enumerate(semantic.selections):
        if selection.id == selection_id:
            return index
    return -1


def _task(section: str, question: str, pointer: str) -> CompletionTask:
    return CompletionTask(
        id=f"task:{uuid5(NAMESPACE_URL, section + question).hex[:12]}",
        section=section,
        question=question,
        target_json_pointer=pointer,
        field_use="Adds author context that native viewer commands do not contain.",
        examples=["unknown", "not_applicable: because ...", "short author note"],
        accepted_values=["unknown", "not_applicable", "short author-provided value"],
    )
