"""Static ChimeraX command-file importer."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claimtrace.importers.base import ExtractedFact, ImportResult
from claimtrace.models import (
    CompletionTask,
    ExtractionConfidence,
    NativeReference,
    ObservedSceneOperation,
    RawNativeObservation,
    ResourceReference,
    SemanticLayer,
    SourceLocation,
    VisibilityRecord,
)
from claimtrace.models.semantic_layer import (
    ClaimCriticalStatus,
    ConfidenceValue,
    MeaningStatus,
    ReviewStatus,
    SupportStatus,
    TargetResolutionStatus,
)
from claimtrace.visual_semantics import suggest_visual_encoding


SUPPORTED_COMMANDS = {
    "open",
    "show",
    "hide",
    "style",
    "cartoon",
    "surface",
    "color",
    "transparency",
    "select",
    "name",
    "set",
    "lighting",
    "turn",
    "wait",
    "label",
    "clip",
    "view",
    "zoom",
    "distance",
    "hbonds",
    "contacts",
    "volume",
    "save",
}

DYNAMIC_COMMANDS = {"runscript", "alias", "foreach", "foreachfile", "forEachFile".lower()}
VISUAL_MEANING_OPERATIONS = {"colored", "labeled", "annotated", "represented", "volume_displayed"}
COLOR_WORDS = {
    "red",
    "orange",
    "yellow",
    "green",
    "cyan",
    "blue",
    "purple",
    "magenta",
    "pink",
    "white",
    "black",
    "gray",
    "grey",
    "brown",
    "tan",
    "salmon",
    "sky",
    "royal",
    "cornflowerblue",
    "gold",
    "lime",
    "olive",
    "navy",
    "teal",
    "violet",
    "hot",
    "light",
    "dark",
    "deep",
    "pale",
    "medium",
    "bychain",
    "byhet",
    "byelement",
    "byhetero",
    "bymodel",
    "rainbow",
    "random",
}
TARGET_WORDS = {
    "all",
    "atoms",
    "cartoon",
    "ligand",
    "ligands",
    "protein",
    "proteins",
    "polymer",
    "sel",
    "selected",
    "selection",
    "solvent",
    "surface",
    "ions",
    "cartoons",
    "ribbons",
    "surfaces",
    "labels",
    "bonds",
    "pseudobonds",
    "rings",
}

COLOR_OPTION_WORDS = {"target", "halfbond", "transparency"}
COLOR_WHAT_WORDS = {"atoms", "bonds", "cartoons", "ribbons", "surfaces", "pseudobonds", "rings", "labels", "all"}
OPEN_OPTION_WORDS = {
    "alignment",
    "combine",
    "coordsets",
    "dataformat",
    "format",
    "from",
    "fromdatabase",
    "id",
    "ignorecache",
    "log",
    "loginfo",
    "maxassemblies",
    "maxmodels",
    "name",
    "resizwindow",
    "resname",
    "structuremodel",
    "verbose",
}
REMOTE_DATABASE_PREFIXES = {
    "alphafold",
    "emdb",
    "emdb_europe",
    "emdb_china",
    "emdb_japan",
    "emdb_us",
    "pdb",
    "pdbdev",
    "pdbihm",
    "pdbe",
    "pubchem",
    "redo",
    "rcsb",
    "uniprot",
}


@dataclass(frozen=True)
class SplitCommand:
    text: str
    line: int
    column: int
    end_column: int
    ordinal: int
    error: str | None = None


@dataclass(frozen=True)
class Token:
    value: str
    column: int
    native: str


class ChimeraXImporter:
    name = "chimerax"
    stability = "stable"

    def detect(self, path: Path) -> float:
        return 0.98 if path.suffix.lower() == ".cxc" else 0.0

    def import_into(self, path: Path, artifact_id: str, semantic: SemanticLayer) -> ImportResult:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"ChimeraX scene is not valid UTF-8 near byte {exc.start}: {path}. "
                "Save the file as UTF-8 and try again."
            ) from exc
        scene_id = _ensure_scene(semantic, artifact_id)
        facts: list[ExtractedFact] = []
        warnings: list[str] = []
        for split in split_commands(text):
            location = SourceLocation(artifact_id=artifact_id, line=split.line, column=split.column)
            if split.error:
                raw = _raw_observation(artifact_id, location, split.text, split.error, scene_id)
                semantic.raw_native_observations.append(raw)
                facts.append(_raw_fact(raw, len(facts) + 1))
                continue
            tokens, token_error = tokenize_command(split.text, split.column)
            if token_error or not tokens:
                raw = _raw_observation(
                    artifact_id,
                    location,
                    split.text,
                    token_error or "empty_command",
                    scene_id,
                )
                semantic.raw_native_observations.append(raw)
                facts.append(_raw_fact(raw, len(facts) + 1))
                continue
            command_token = tokens[0]
            command, support_status, support_reason = _resolve_command(command_token.value.lower())
            if support_status == SupportStatus.raw_unsupported or _is_dynamic(split.text, command):
                raw = _raw_observation(
                    artifact_id,
                    location,
                    split.text,
                    support_reason if support_status == SupportStatus.raw_unsupported else "dynamic_command_boundary",
                    scene_id,
                )
                semantic.raw_native_observations.append(raw)
                facts.append(_raw_fact(raw, len(facts) + 1))
                continue
            ast = _command_ast(command, tokens, split, support_status)
            if ast.get("parse_confidence") == "heuristic" and support_status == SupportStatus.supported_shallow:
                support_status = SupportStatus.supported_heuristic
                ast["support_status"] = support_status.value
            operation = _operation_for(command, ast)
            target = str(ast["target"]) if ast.get("target") else ""
            op = _observed_operation(
                importer=self.name,
                artifact_id=artifact_id,
                scene_id=scene_id,
                command=command,
                operation=operation,
                target=target,
                split=split,
                ast=ast,
                support_status=support_status,
            )
            semantic.observed_scene_operations.append(op)
            for resource in _resource_references(
                artifact_id,
                op.operation_id,
                command,
                tokens[1:],
                split.line,
                split.column,
            ):
                semantic.resource_references.append(resource)
                if _resource_may_execute(resource.uri):
                    raw = _raw_observation(
                        artifact_id,
                        location,
                        split.text,
                        "executable_resource_boundary",
                        scene_id,
                    )
                    semantic.raw_native_observations.append(raw)
                    facts.append(_raw_fact(raw, len(facts) + 1))
            for ref in _native_refs(artifact_id, op.operation_id, target, split.line, split.column, split.text):
                semantic.native_references.append(ref)
            _record_scene_state(semantic, scene_id, command, split, ast)
            facts.append(_operation_fact(op, ast, len(facts) + 1))
        tasks = _completion_tasks_for_operations(semantic)
        return ImportResult(importer_name=self.name, facts=facts, tasks=tasks, warnings=warnings)


def split_commands(text: str) -> list[SplitCommand]:
    result: list[SplitCommand] = []
    for line_no, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        start = 0
        quote: str | None = None
        escaped = False
        ordinal = 0
        index = 0
        while index < len(line):
            char = line[index]
            if escaped:
                escaped = False
                index += 1
                continue
            if char == "\\" and quote and index + 1 < len(line) and line[index + 1] == quote:
                escaped = True
                index += 1
                continue
            if char in {"'", '"'}:
                quote = None if quote == char else char if quote is None else quote
                index += 1
                continue
            if quote is None and char == "#":
                if _is_comment_hash(line, index):
                    break
            if quote is None and char == ";":
                _append_split(result, line, line_no, start, index, ordinal)
                ordinal += 1
                start = index + 1
            index += 1
        if quote is not None:
            text_part = line[start:].strip()
            if text_part:
                result.append(
                    SplitCommand(
                        text=text_part,
                        line=line_no,
                        column=line.find(text_part, start) + 1,
                        end_column=len(line) + 1,
                        ordinal=ordinal,
                        error="unterminated_quote",
                    )
                )
            continue
        _append_split(result, line, line_no, start, index, ordinal)
    return result


def tokenize_command(text: str, base_column: int = 1) -> tuple[list[Token], str | None]:
    tokens: list[Token] = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        token_start = index
        quote: str | None = None
        value_chars: list[str] = []
        native_chars: list[str] = []
        escaped = False
        while index < len(text):
            char = text[index]
            if escaped:
                value_chars.append(char)
                native_chars.append(char)
                escaped = False
                index += 1
                continue
            if quote and char == "\\":
                native_chars.append(char)
                next_char = text[index + 1] if index + 1 < len(text) else ""
                if next_char == quote:
                    escaped = True
                else:
                    value_chars.append(char)
                index += 1
                continue
            if char in {"'", '"'}:
                native_chars.append(char)
                if quote is None:
                    quote = char
                elif quote == char:
                    quote = None
                else:
                    value_chars.append(char)
                index += 1
                continue
            if quote is None and char.isspace():
                break
            value_chars.append(char)
            native_chars.append(char)
            index += 1
        if quote is not None:
            return tokens, "unterminated_quote"
        tokens.append(Token("".join(value_chars), base_column + token_start, "".join(native_chars)))
    return tokens, None


def _append_split(result: list[SplitCommand], line: str, line_no: int, start: int, end: int, ordinal: int) -> None:
    part = line[start:end].strip()
    if not part:
        return
    column = line.find(part, start) + 1
    result.append(SplitCommand(text=part, line=line_no, column=column, end_column=column + len(part), ordinal=ordinal))


def _is_comment_hash(line: str, index: int) -> bool:
    segment_start = line.rfind(";", 0, index) + 1
    return not line[segment_start:index].strip()


def _resolve_command(command: str) -> tuple[str, SupportStatus, str]:
    if command in DYNAMIC_COMMANDS:
        return command, SupportStatus.raw_unsupported, "dynamic_command_boundary"
    if command in SUPPORTED_COMMANDS:
        return command, SupportStatus.supported_shallow, "full_command"
    matches = [item for item in SUPPORTED_COMMANDS if item.startswith(command)]
    if len(matches) == 1:
        return matches[0], SupportStatus.supported_heuristic, "unambiguous_allowlist_abbreviation"
    if len(matches) > 1:
        return command, SupportStatus.raw_unsupported, "ambiguous_abbreviation"
    return command, SupportStatus.raw_unsupported, "unsupported_command"


def _is_dynamic(text: str, command: str) -> bool:
    return "$" in text or command in DYNAMIC_COMMANDS


def _command_ast(command: str, tokens: list[Token], split: SplitCommand, support_status: SupportStatus) -> dict[str, Any]:
    args = tokens[1:]
    ast: dict[str, Any] = {
        "command": command,
        "arguments": [
            {"role": "command", "native": tokens[0].native, "value": tokens[0].value, "span": {"line": split.line, "column": tokens[0].column}}
        ],
        "keywords": {},
        "native_text": split.text,
        "support_status": support_status.value,
    }
    if command == "color":
        if args and args[0].value.lower() in {
            "byattribute",
            "cylindrical",
            "electrostatic",
            "height",
            "image",
            "radial",
            "sample",
            "sequential",
            "zone",
        }:
            return _color_subcommand_ast(ast, args, split)
        core_tokens, option_tokens = _split_color_options(args)
        color_tokens, target_tokens, parse_order = _split_color_arguments(core_tokens)
        color = _tokens_text(color_tokens)
        target = _tokens_text(target_tokens)
        if color_tokens:
            ast["arguments"].append(
                {
                    "role": "color",
                    "native": _tokens_native(color_tokens),
                    "value": color,
                    "span": {"line": split.line, "column": color_tokens[0].column},
                }
            )
        if target_tokens:
            ast["arguments"].append(
                {
                    "role": "target",
                    "native": _tokens_native(target_tokens),
                    "value": target,
                    "span": {"line": split.line, "column": target_tokens[0].column},
                }
            )
        ast["color"] = color
        ast["target"] = target
        ast["color_parse_order"] = parse_order
        ast["options"] = _tokens_text(option_tokens)
        if parse_order.endswith("heuristic"):
            ast["parse_confidence"] = "heuristic"
        return ast
    if command == "open":
        source_tokens = _open_source_tokens(args)
        target = " ".join(token.value for token in source_tokens)
        ast["target"] = target
        ast["resources"] = [token.value for token in source_tokens]
        ast["options"] = _tokens_text(args[len(source_tokens) :])
        if source_tokens:
            ast["arguments"].append(
                {
                    "role": "resources",
                    "native": _tokens_native(source_tokens),
                    "value": [token.value for token in source_tokens],
                    "span": {"line": split.line, "column": source_tokens[0].column},
                }
            )
        return ast
    if command == "style":
        style_token = args[-1:] if args else []
        target_tokens = args[:-1] if len(args) > 1 else []
        ast["target"] = _tokens_text(target_tokens)
        ast["style"] = _tokens_text(style_token)
        return ast
    if command in {"cartoon", "surface"}:
        ast["target"] = _tokens_text(args)
        ast["style"] = command
        return ast
    if command == "transparency":
        value_index = next((index for index, token in enumerate(args) if _looks_numeric(token.value)), None)
        if value_index is None:
            ast["target"] = _tokens_text(args)
            ast["value"] = ""
            ast["parse_confidence"] = "heuristic"
        else:
            ast["target"] = _tokens_text(args[:value_index])
            ast["value"] = args[value_index].value
            ast["options"] = _tokens_text(args[value_index + 1 :])
        return ast
    if command == "label":
        text_index = next((index for index, token in enumerate(args) if token.value.lower() == "text"), -1)
        if 0 < text_index < len(args) - 1:
            target_tokens = args[:text_index]
            label_tokens = args[text_index + 1 :]
            target = " ".join(token.value for token in target_tokens)
            label = " ".join(token.value for token in label_tokens)
        else:
            target_tokens = args
            label_tokens = args
            target = " ".join(token.value for token in args)
            label = target
        ast["target"] = target
        ast["label"] = label
        if target_tokens:
            ast["arguments"].append({"role": "target", "native": target, "value": target, "span": {"line": split.line, "column": target_tokens[0].column}})
        if label_tokens and label != target:
            ast["arguments"].append({"role": "label", "native": label, "value": label, "span": {"line": split.line, "column": label_tokens[0].column}})
        return ast
    target = " ".join(token.value for token in args)
    ast["target"] = target
    if args:
        ast["arguments"].append({"role": "target", "native": target, "value": target, "span": {"line": split.line, "column": args[0].column}})
    return ast


def _split_color_options(args: list[Token]) -> tuple[list[Token], list[Token]]:
    for index, token in enumerate(args):
        lowered = token.value.lower()
        if lowered in COLOR_OPTION_WORDS:
            return args[:index], args[index:]
        if (
            lowered in COLOR_WHAT_WORDS
            and index >= 2
            and any(_looks_like_color_token(value.value) for value in args[1:index])
        ):
            return args[:index], args[index:]
    return args, []


def _color_subcommand_ast(ast: dict[str, Any], args: list[Token], split: SplitCommand) -> dict[str, Any]:
    method = args[0].value.lower()
    target_token = next((token for token in args[1:] if _looks_like_target_token(token.value)), None)
    target = target_token.value if target_token else ""
    palette_index = next((index for index, token in enumerate(args) if token.value.lower() == "palette"), None)
    palette = args[palette_index + 1].value if palette_index is not None and palette_index + 1 < len(args) else ""
    expression = args[1].value if method == "byattribute" and len(args) > 1 else ""
    ast.update(
        {
            "target": target,
            "color": f"palette {palette}" if palette else method,
            "color_method": method,
            "expression": expression,
            "palette": palette,
            "options": _tokens_text(args),
            "parse_confidence": "heuristic",
        }
    )
    if target_token:
        ast["arguments"].append(
            {
                "role": "target",
                "native": target_token.native,
                "value": target,
                "span": {"line": split.line, "column": target_token.column},
            }
        )
    return ast


def _open_source_tokens(args: list[Token]) -> list[Token]:
    for index, token in enumerate(args):
        if token.value.lower() in OPEN_OPTION_WORDS:
            return args[:index]
    return args


def _looks_numeric(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _split_color_arguments(args: list[Token]) -> tuple[list[Token], list[Token], str]:
    if not args:
        return [], [], "no_arguments"
    if len(args) == 1:
        return [args[0]], [], "color_only"
    if _looks_like_color_token(args[0].value):
        target_start = next(
            (index for index, token in enumerate(args[1:], start=1) if _looks_like_target_token(token.value)),
            None,
        )
        if target_start is not None:
            return args[:target_start], args[target_start:], "color_target"
        return [args[0]], args[1:], "color_target"
    color_start = _trailing_color_start(args)
    if color_start is not None and color_start > 0:
        return args[color_start:], args[:color_start], "target_color"
    return [args[-1]], args[:-1], "target_color_heuristic"


def _trailing_color_start(args: list[Token]) -> int | None:
    for start in range(1, len(args)):
        if all(_looks_like_color_token(token.value) for token in args[start:]):
            return start
    return None


def _looks_like_color_token(value: str) -> bool:
    text = value.strip().lower()
    if not text:
        return False
    if text.startswith("#") and len(text) in {4, 7, 9}:
        return all(char in "0123456789abcdef" for char in text[1:])
    if text.startswith(("rgb(", "rgba(")) or "," in text:
        return True
    return text in COLOR_WORDS or text.startswith("by")


def _looks_like_target_token(value: str) -> bool:
    text = value.strip().lower()
    if not text:
        return False
    return (
        text in TARGET_WORDS
        or text.startswith(("#", "/", ":", "@"))
        or "/" in text
        or ":" in text
        or "&" in text
    )


def _tokens_text(tokens: list[Token]) -> str:
    return " ".join(token.value for token in tokens)


def _tokens_native(tokens: list[Token]) -> str:
    return " ".join(token.native for token in tokens)


def _operation_for(command: str, ast: dict[str, Any]) -> str:
    return {
        "open": "resource_opened",
        "show": "displayed",
        "hide": "hidden",
        "style": "represented",
        "cartoon": "represented",
        "surface": "represented",
        "color": "colored",
        "transparency": "transparency_changed",
        "select": "selection_defined",
        "name": "selection_defined",
        "set": "configured",
        "lighting": "configured",
        "turn": "camera_changed",
        "wait": "timing_control",
        "label": "labeled",
        "clip": "clipped",
        "view": "camera_changed",
        "zoom": "camera_changed",
        "distance": "measurement_intent",
        "hbonds": "measurement_intent",
        "contacts": "measurement_intent",
        "volume": "volume_displayed",
        "save": "output_intent",
    }.get(command, f"chimerax_{command}")


def _ensure_scene(semantic: SemanticLayer, artifact_id: str) -> str:
    if semantic.scenes:
        scene = semantic.scenes[0]
        if artifact_id not in scene.native_artifact_ids:
            scene.native_artifact_ids.append(artifact_id)
        return scene.id
    from claimtrace.models import Scene

    scene = Scene(
        id="scene:native:1",
        description="Scene statically extracted from native viewer artifact.",
        native_artifact_ids=[artifact_id],
        review_status=ReviewStatus.needs_review,
    )
    semantic.scenes.append(scene)
    return scene.id


def _record_scene_state(
    semantic: SemanticLayer,
    scene_id: str,
    command: str,
    split: SplitCommand,
    ast: dict[str, Any],
) -> None:
    scene = next((item for item in semantic.scenes if item.id == scene_id), None)
    if scene is None:
        return
    target = str(ast.get("target") or "")
    if command in {"view", "zoom", "turn", "clip"}:
        commands = scene.camera.setdefault("chimerax_commands", [])
        if isinstance(commands, list):
            commands.append(
                {
                    "command": split.text,
                    "line": split.line,
                    "column": split.column,
                    "status": "statically_recorded_not_rendered",
                }
            )
    if command in {"show", "hide"}:
        state = "visible" if command == "show" else "hidden"
        scene.visibility.append(
            VisibilityRecord(
                native_target=target or "all",
                state=state,
                reason=f"Observed ChimeraX `{command}` command; intent recorded without execution.",
                review_status=ReviewStatus.auto_extracted,
            )
        )
    if command in {"style", "cartoon", "surface"}:
        scene.representations.append(
            {
                "target": target or "all",
                "style": ast.get("style") or command,
                "source_line": split.line,
                "status": "statically_recorded_not_rendered",
            }
        )


def _observed_operation(
    *,
    importer: str,
    artifact_id: str,
    scene_id: str,
    command: str,
    operation: str,
    target: str,
    split: SplitCommand,
    ast: dict[str, Any],
    support_status: SupportStatus,
) -> ObservedSceneOperation:
    op_id = _stable_id("op", importer, artifact_id, str(split.line), str(split.column), str(split.ordinal), operation, target, split.text)
    details = {"scene_id": scene_id, "command": command, "ast": ast}
    for key in ("color_method", "expression", "palette", "style", "value"):
        if ast.get(key) not in {None, ""}:
            details[key if key != "color_method" else "method"] = ast[key]
    suggestion = suggest_visual_encoding(operation, target, details, ast)
    meaning_status = suggestion.meaning_status
    return ObservedSceneOperation(
        operation_id=op_id,
        operation=operation,
        target=target,
        details=details,
        auto_annotation=suggestion.auto_annotation,
        candidate_meaning=suggestion.candidate_meaning,
        meaning_confidence=suggestion.meaning_confidence,
        meaning_basis=suggestion.meaning_basis,
        needs_author_confirmation=suggestion.needs_author_confirmation,
        source_location=SourceLocation(artifact_id=artifact_id, line=split.line, column=split.column),
        native_command=split.text,
        native_value=ast,
        support_status=support_status,
        extraction_confidence=ExtractionConfidence(
            level=ConfidenceValue.high if support_status == SupportStatus.supported_shallow else ConfidenceValue.heuristic,
            score=0.85 if support_status == SupportStatus.supported_shallow else 0.65,
            basis=["known_chimerax_command", "static_tokenizer"],
        ),
        review_status=ReviewStatus.auto_extracted,
        meaning_status=meaning_status,
        target_resolution_status=TargetResolutionStatus.expression_only if target else TargetResolutionStatus.not_checked,
    )


def _native_refs(
    artifact_id: str,
    operation_id: str,
    target: str,
    line: int,
    column: int,
    native_text: str,
) -> list[NativeReference]:
    refs = []
    for token in target.split():
        if token.startswith("#") and len(token) > 1:
            refs.append(
                NativeReference(
                    native_ref_id=_stable_id("native-ref", "chimerax", artifact_id, operation_id, token),
                    source_location=SourceLocation(artifact_id=artifact_id, line=line, column=column, path=None),
                    native_expression=token,
                    ref_type="cxc_model_spec",
                    stable_identity=None,
                    identity_status="unresolved",
                    claim_critical=ClaimCriticalStatus.unknown,
                    review_status=ReviewStatus.needs_review,
                    target_resolution_status=TargetResolutionStatus.expression_only,
                )
            )
    return refs


def _resource_references(
    artifact_id: str,
    operation_id: str,
    command: str,
    args: list[Token],
    line: int,
    column: int,
) -> list[ResourceReference]:
    if command != "open":
        return []
    sources = _open_source_tokens(args)
    return [
        ResourceReference(
            resource_ref_id=_stable_id("resource", "chimerax", artifact_id, operation_id, token.value),
            artifact_id=artifact_id,
            uri=token.value,
            uri_kind=_uri_kind(token.value),
            fetch_status="not_fetched",
            fixity_status="unknown",
            claim_critical=ClaimCriticalStatus.unknown,
            source_location=SourceLocation(artifact_id=artifact_id, line=line, column=token.column or column),
        )
        for token in sources
        if token.value and token.value.lower() != "browse"
    ]


def _uri_kind(uri: str) -> str:
    lowered = uri.lower()
    if lowered.startswith(("http://", "https://", "ftp://")):
        return "remote"
    if lowered.startswith("data:"):
        return "data"
    prefix = lowered.split(":", 1)[0] if ":" in lowered else ""
    if prefix in REMOTE_DATABASE_PREFIXES:
        return "remote"
    if re.fullmatch(r"[0-9][a-z0-9]{3}", lowered):
        return "remote"
    if lowered.startswith(("file:", "/", "~/", "\\\\", "//")) or re.match(r"^[a-z]:[\\/]", uri, re.IGNORECASE):
        return "file"
    return "relative"


def _resource_may_execute(uri: str) -> bool:
    lowered = uri.lower().split("?", 1)[0]
    return lowered.endswith((".cxc", ".py", ".pyc", ".pyo"))


def _raw_observation(
    artifact_id: str,
    location: SourceLocation,
    native_text: str,
    reason: str,
    scene_id: str,
) -> RawNativeObservation:
    return RawNativeObservation(
        raw_id=_stable_id("raw", "chimerax", artifact_id, str(location.line), str(location.column), reason, native_text),
        artifact_id=artifact_id,
        source_location=location,
        native_text=native_text,
        reason=reason,
        support_status=SupportStatus.raw_unsupported,
        extraction_confidence=ExtractionConfidence(level=ConfidenceValue.low, score=0.2, basis=["raw_boundary"]),
        may_affect_scene_id=scene_id,
        claim_critical=ClaimCriticalStatus.unknown,
        review_status=ReviewStatus.needs_review,
    )


def _operation_fact(op: ObservedSceneOperation, ast: dict[str, Any], index: int) -> ExtractedFact:
    return ExtractedFact(
        fact_id=f"fact-chimerax-{index:04d}",
        tool="chimerax",
        artifact_id=op.source_location.artifact_id or "",
        source_location=op.source_location.model_dump(mode="json", exclude_none=True),
        native_command=op.native_command or "",
        native_value=ast,
        normalized_target={"operation_id": op.operation_id, "target": op.target},
        normalized_value={
            "operation": op.operation,
            "meaning_status": op.meaning_status.value,
            "auto_annotation": op.auto_annotation,
            "candidate_meaning": op.candidate_meaning,
            "needs_author_confirmation": op.needs_author_confirmation,
        },
        support_status=op.support_status.value,
        confidence=op.extraction_confidence.model_dump(mode="json", exclude_none=True),
        review_status=op.review_status.value,
    )


def _raw_fact(raw: RawNativeObservation, index: int) -> ExtractedFact:
    return ExtractedFact(
        fact_id=f"fact-chimerax-{index:04d}",
        tool="chimerax",
        artifact_id=raw.artifact_id,
        source_location=raw.source_location.model_dump(mode="json", exclude_none=True),
        native_command=raw.native_text,
        native_value={"raw": raw.native_text, "reason": raw.reason},
        normalized_target={"raw_id": raw.raw_id},
        normalized_value={"raw": True},
        support_status=raw.support_status.value,
        confidence=raw.extraction_confidence.model_dump(mode="json", exclude_none=True),
        review_status=raw.review_status.value,
    )


def _completion_tasks_for_operations(semantic: SemanticLayer) -> list[CompletionTask]:
    tasks: list[CompletionTask] = []
    visual_ops = [
        op
        for op in semantic.observed_scene_operations
        if op.meaning_status in {MeaningStatus.requires_user_completion, MeaningStatus.tool_suggested_meaning}
        or op.auto_annotation
        or op.candidate_meaning
    ]
    if visual_ops:
        tasks.append(
            CompletionTask(
                id="task:cxc-visual-encoding-meanings",
                section="scene",
                question="Review low-confidence or claim-critical ChimeraX color/label/display suggestions; literal scene facts are already recorded.",
                target_json_pointer="/visual_encoding_semantics",
                field_use="ClaimTrace already extracted what was shown and suggested conservative meanings; author review is needed only for figure-central or uncertain meanings.",
                examples=[f"{op.operation_id}: {op.candidate_meaning or 'mark presentation only'}" for op in visual_ops[:2]],
                accepted_values=["tool_suggested_meaning", "user_confirmed_meaning", "user_declared_no_scientific_meaning"],
                blocking=False,
            )
        )
    native_refs = semantic.native_references
    if native_refs:
        tasks.append(
            CompletionTask(
                id="task:cxc-native-reference-identity",
                section="entities",
                question="Name the molecule, chain, residue or file behind any ChimeraX model references that matter to the figure.",
                target_json_pointer="/native_references",
                field_use="ChimeraX IDs such as #1 are local to the session; this adds reader-friendly names.",
                examples=[f"{ref.native_ref_id}: {ref.native_expression} -> PDB/chain/residue identity" for ref in native_refs[:2]],
                accepted_values=["resolved_against_artifact", "not_figure_central", "recorded_reason"],
                blocking=False,
            )
        )
    return tasks


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{prefix}:{digest}"
