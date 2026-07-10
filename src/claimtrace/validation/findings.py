"""Finding constructors."""

from __future__ import annotations

from claimtrace.models.validation import ValidationFinding


def finding(
    rule_id: str,
    gate: str,
    level: str,
    severity: str,
    finding_class: str,
    message: str,
    *,
    status: str = "FAIL",
    pointer: str = "",
    blocks: list[str] | None = None,
    claim_critical: bool = False,
    waivable: bool = False,
    fix: str = "",
) -> ValidationFinding:
    return ValidationFinding(
        rule_id=rule_id,
        gate=gate,
        validation_level=level,
        severity=severity,  # type: ignore[arg-type]
        finding_class=finding_class,
        status=status,  # type: ignore[arg-type]
        message=message,
        json_pointer=pointer,
        blocks_modes=blocks or [],
        claim_critical=claim_critical,
        waivable=waivable,
        suggested_fix=fix,
    )
