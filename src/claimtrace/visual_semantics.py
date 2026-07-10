"""Small heuristics for literal visual-encoding annotations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from claimtrace.models.semantic_layer import ConfidenceValue, MeaningStatus


@dataclass(frozen=True)
class VisualMeaningSuggestion:
    auto_annotation: str | None
    candidate_meaning: str | None
    meaning_confidence: ConfidenceValue
    meaning_basis: list[str]
    needs_author_confirmation: bool
    meaning_status: MeaningStatus


VISUAL_ENCODING_OPERATIONS = {
    "background_colored",
    "colored",
    "custom_color_defined",
    "labeled",
    "annotated",
    "represented",
    "volume_displayed",
    "opacity_changed",
    "transparency_changed",
    "primitive_overlay",
}

INTERPRETIVE_CUES = {
    "active",
    "active_site",
    "binding",
    "catalytic",
    "claim",
    "clash",
    "conserved",
    "contact",
    "confidence",
    "critical",
    "density",
    "evidence",
    "b_factor",
    "interface",
    "invalid",
    "key",
    "mechanism",
    "plddt",
    "pocket",
    "pose",
    "removed",
    "retained",
    "support",
    "uncertain",
    "uncertainty",
    "validated",
    "warning",
}


def suggest_visual_encoding(
    operation: str,
    target: str,
    details: Mapping[str, Any] | None = None,
    native_value: Mapping[str, Any] | None = None,
) -> VisualMeaningSuggestion:
    """Return a conservative literal annotation and optional author-facing guess."""

    details = details or {}
    native_value = native_value or {}
    if operation not in VISUAL_ENCODING_OPERATIONS:
        return VisualMeaningSuggestion(
            auto_annotation=None,
            candidate_meaning=None,
            meaning_confidence=ConfidenceValue.unknown,
            meaning_basis=[],
            needs_author_confirmation=False,
            meaning_status=MeaningStatus.native_observed,
        )

    if operation in {"colored", "background_colored", "custom_color_defined"}:
        color = _first_text(
            details.get("color"),
            _nested(details, "ast", "color"),
            _nested(native_value, "params", "color"),
            native_value.get("color"),
        )
        return _colored_suggestion(operation, target, color, details)

    if operation == "labeled":
        label = _first_text(
            details.get("label_expression"),
            details.get("label"),
            _nested(details, "ast", "label"),
            _nested(native_value, "params", "text"),
            _nested(native_value, "params", "label"),
            native_value.get("text"),
            native_value.get("label"),
        )
        return _labeled_suggestion(target, label)

    if operation in {"represented", "volume_displayed"}:
        representation = _first_text(
            details.get("representation"),
            _nested(details, "ast", "style"),
            _nested(details, "ast", "command"),
            _nested(native_value, "params", "type"),
            native_value.get("type"),
        )
        return _representation_suggestion(operation, target, representation)

    if operation in {"opacity_changed", "transparency_changed"}:
        opacity = _first_text(
            details.get("value"),
            _nested(native_value, "params", "opacity"),
            native_value.get("opacity"),
        )
        noun = "transparency" if operation == "transparency_changed" else "opacity"
        return _generic_suggestion(
            operation,
            target,
            f"Target `{_target_text(target)}` has {noun} `{opacity or 'unknown'}`.",
            f"{noun.capitalize()} changes the presentation of `{_target_text(target)}`; no scientific meaning is inferred.",
            ConfidenceValue.medium,
            [f"literal_{noun}_operation"],
        )

    if operation in {"annotated", "primitive_overlay"}:
        text = _first_text(
            _nested(native_value, "params", "text"),
            native_value.get("text"),
            _nested(details, "ast", "label"),
        )
        return _generic_suggestion(
            operation,
            target,
            f"Target `{_target_text(target)}` has annotation `{text or operation}`.",
            (
                f"Annotation displays or explains `{text}`; confirm its intended meaning if it carries the panel message."
                if text
                else f"Annotation or overlay is attached to `{_target_text(target)}`."
            ),
            ConfidenceValue.medium,
            ["literal_annotation_node"],
        )

    return _generic_suggestion(
        operation,
        target,
        f"Target `{_target_text(target)}` has visual operation `{operation}`.",
        f"Visual operation `{operation}` applies to `{_target_text(target)}`; no scientific meaning is inferred.",
        ConfidenceValue.low,
        ["visual_operation_literal"],
    )


def _colored_suggestion(
    operation: str,
    target: str,
    color: str | None,
    details: Mapping[str, Any],
) -> VisualMeaningSuggestion:
    target_text = _target_text(target)
    color_text = color or "unknown"
    if operation == "background_colored":
        auto = f"Scene background is colored `{color_text}`."
    elif operation == "custom_color_defined":
        auto = f"Custom color `{target_text}` is defined as `{color_text}`."
    else:
        auto = f"Target `{target_text}` is colored `{color_text}`."
    target_kind = _target_kind(target_text)
    if color is None:
        return _generic_suggestion(
            operation,
            target,
            auto,
            None,
            ConfidenceValue.low,
            ["color_command_without_color_value"],
            force_confirmation=True,
        )
    if operation == "custom_color_defined":
        return VisualMeaningSuggestion(
            auto_annotation=auto,
            candidate_meaning=(
                "A reusable color value is defined; no scientific meaning is inferred from the definition alone."
            ),
            meaning_confidence=ConfidenceValue.high,
            meaning_basis=["literal_custom_color_definition", "no_rendered_target_inferred"],
            needs_author_confirmation=False,
            meaning_status=MeaningStatus.tool_suggested_meaning,
        )
    method = _first_text(details.get("method"))
    expression = _first_text(details.get("expression"))
    palette = _first_text(details.get("palette"))
    is_spectrum = (method or "").lower() == "spectrum"
    is_attribute_color = (method or "").lower() == "byattribute"
    if is_attribute_color:
        candidate = (
            f"Color is mapped from ChimeraX attribute `{expression or 'unknown'}`"
            f" with palette `{palette or color_text}`; confirm whether it represents an experimental value, "
            "model confidence, or another attribute."
        )
        confidence = ConfidenceValue.medium
        basis = ["literal_chimerax_byattribute_command", "attribute_meaning_requires_author_confirmation"]
    elif is_spectrum:
        candidate = (
            f"Color is mapped from PyMOL expression `{expression or 'unknown'}`"
            f" with palette `{palette or color_text}`; confirm what the mapped values mean scientifically."
        )
        if (expression or "").strip().lower() in {"b", "b_factor", "bfactor"}:
            candidate = (
                "Color is mapped from the PyMOL `b` field; confirm whether that field stores an "
                "experimental B-factor, AlphaFold pLDDT, or another imported value."
            )
        confidence = ConfidenceValue.medium
        basis = ["literal_spectrum_command", "data_driven_color_mapping_requires_author_confirmation"]
    elif target_kind == "ligand":
        candidate = "Color may highlight the ligand or ligand selection; confirm if it carries the panel message."
        confidence = ConfidenceValue.medium
        basis = ["target_name_suggests_ligand", "literal_color_command"]
    elif target_kind == "protein":
        candidate = "Color visually distinguishes the protein or protein selection; no scientific meaning is inferred."
        confidence = ConfidenceValue.medium
        basis = ["target_name_suggests_protein", "literal_color_command"]
    elif target_text == "all":
        candidate = "Color applies globally to the scene; no scientific meaning is inferred."
        confidence = ConfidenceValue.medium
        basis = ["global_target", "literal_color_command"]
    else:
        candidate = f"Color visually distinguishes `{target_text}`; no scientific meaning is inferred."
        confidence = ConfidenceValue.medium
        basis = ["literal_color_command"]
    extra_text = " ".join(
        value
        for value in [color_text, expression or "", palette or "", _mapping_details_text(details)]
        if value
    )
    target_is_specific_selector = _looks_like_specific_selector(target_text)
    force_confirmation = (
        is_spectrum
        or is_attribute_color
        or _has_interpretive_cue(extra_text)
        or target_is_specific_selector
    )
    if force_confirmation and "color_mapping_requires_author_confirmation" not in basis:
        basis = [*basis, "color_mapping_requires_author_confirmation"]
    if target_is_specific_selector:
        basis = [*basis, "specific_native_selector_requires_author_confirmation"]
    return _generic_suggestion(
        operation,
        target,
        auto,
        candidate,
        confidence,
        basis,
        extra_text=extra_text,
        force_confirmation=force_confirmation,
    )


def _labeled_suggestion(target: str, label: str | None) -> VisualMeaningSuggestion:
    target_text = _target_text(target)
    label_text = _clean_label(label) if label else "unknown"
    auto = f"Target `{target_text}` is labeled with `{label_text}`."
    if not label:
        return _generic_suggestion(
            "labeled",
            target,
            auto,
            None,
            ConfidenceValue.low,
            ["label_command_without_label_text"],
            force_confirmation=True,
        )
    if label_text.lower() in {"name", "resn", "resi", "chain", "index", "id"}:
        candidate = f"Label displays native expression `{label_text}` for `{target_text}`."
        confidence = ConfidenceValue.high
        basis = ["known_viewer_label_expression", "literal_label_command"]
    else:
        candidate = f"Label displays text `{label_text}` on `{target_text}`; confirm its intended meaning if it carries the panel message."
        confidence = ConfidenceValue.high
        basis = ["literal_label_text"]
    return _generic_suggestion("labeled", target, auto, candidate, confidence, basis, extra_text=label_text)


def _representation_suggestion(operation: str, target: str, representation: str | None) -> VisualMeaningSuggestion:
    target_text = _target_text(target)
    representation_text = representation or "unknown"
    auto = f"Target `{target_text}` is displayed as `{representation_text}`."
    candidate = f"Representation displays `{target_text}` as `{representation_text}`; no scientific meaning is inferred."
    return _generic_suggestion(
        operation,
        target,
        auto,
        candidate,
        ConfidenceValue.medium,
        ["literal_representation_operation"],
    )


def _generic_suggestion(
    operation: str,
    target: str,
    auto_annotation: str,
    candidate_meaning: str | None,
    confidence: ConfidenceValue,
    basis: list[str],
    *,
    extra_text: str = "",
    force_confirmation: bool = False,
) -> VisualMeaningSuggestion:
    needs_confirmation = force_confirmation or confidence in {ConfidenceValue.low, ConfidenceValue.unknown}
    if _has_interpretive_cue(target) or _has_interpretive_cue(extra_text):
        needs_confirmation = True
        basis = [*basis, "target_or_label_contains_interpretive_cue"]
    return VisualMeaningSuggestion(
        auto_annotation=auto_annotation,
        candidate_meaning=candidate_meaning,
        meaning_confidence=confidence,
        meaning_basis=basis,
        needs_author_confirmation=needs_confirmation,
        meaning_status=MeaningStatus.requires_user_completion
        if needs_confirmation
        else MeaningStatus.tool_suggested_meaning,
    )


def _target_kind(target: str) -> str:
    lowered = target.lower()
    if any(token in lowered for token in ["ligand", " resn lig", "auth_comp_id", "hetatm"]):
        return "ligand"
    if any(token in lowered for token in ["protein", "polymer", "cartoon", "chain "]):
        return "protein"
    return "unknown"


def _looks_like_specific_selector(target: str) -> bool:
    lowered = target.strip().lower()
    return any(
        token in lowered
        for token in ("#", "/", ":", "@", "resi ", "resn ", "chain ", "name ")
    )


def _has_interpretive_cue(text: str) -> bool:
    lowered = text.lower().replace("-", "_").replace(" ", "_")
    return any(cue in lowered for cue in INTERPRETIVE_CUES)


def _mapping_details_text(details: Mapping[str, Any]) -> str:
    values: list[str] = []
    for key, value in details.items():
        values.append(str(key))
        if isinstance(value, (str, int, float)):
            values.append(str(value))
    return " ".join(values)


def _target_text(target: str) -> str:
    value = str(target or "scene").strip()
    return value or "scene"


def _clean_label(label: str | None) -> str:
    if label is None:
        return "unknown"
    text = str(label).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def _nested(mapping: Mapping[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None
