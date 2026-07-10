"""Rule identifiers used by the validation engine."""

RULES = [
    {
        "rule_id": "G0.PARSEABLE",
        "title": "semantic_layer.json can be read and uses a supported schema version",
        "gate": "G0_PARSEABLE",
        "severity": "ERROR",
        "finding_class": "INTEGRITY_ERROR",
    },
    {
        "rule_id": "G1.SCHEMA",
        "title": "semantic_layer.json matches the ClaimTrace schema",
        "gate": "G1_SCHEMA",
        "severity": "ERROR",
        "finding_class": "INTEGRITY_ERROR",
    },
    {
        "rule_id": "G2.FIXITY",
        "title": "Local files have package-safe paths and matching checksums",
        "gate": "G2_FIXITY",
        "severity": "ERROR",
        "finding_class": "INTEGRITY_ERROR",
    },
    {
        "rule_id": "G3.REFERENCE",
        "title": "Internal links point to objects in this package",
        "gate": "G3_REFERENCE",
        "severity": "ERROR",
        "finding_class": "INTEGRITY_ERROR",
    },
    {
        "rule_id": "CLAIM.BASIC.REVIEWABLE",
        "title": "Claims include figure/panel, scene and evidence links",
        "gate": "G4_CLAIM_RULES",
        "severity": "ERROR",
        "finding_class": "REVIEWABILITY_ERROR",
    },
    {
        "rule_id": "CLAIM.LIGAND.REQUIRED_CONTACTS",
        "title": "Ligand binding claim includes contact or equivalent evidence",
        "gate": "G4B_EVIDENCE_MINIMUMS",
        "severity": "ERROR",
        "finding_class": "CLAIM_EVIDENCE_ERROR",
    },
    {
        "rule_id": "SCENE.HIDDEN.CRITICAL_REASON",
        "title": "Figure-central hidden entities include a reason",
        "gate": "G5_VISIBILITY",
        "severity": "ERROR",
        "finding_class": "DISCLOSURE_WARNING",
    },
    {
        "rule_id": "SECURITY.PATH.PRIVACY",
        "title": "Package paths and free text are share-safe",
        "gate": "G7_EXPORT_READY",
        "severity": "ERROR",
        "finding_class": "SECURITY_BLOCKER",
    },
]


MODE_ORDER = {"draft": 0, "internal": 1, "share": 2, "archive": 3}


def waiver_covers(max_export_mode: str, requested_mode: str) -> bool:
    return MODE_ORDER.get(requested_mode, 3) <= MODE_ORDER.get(max_export_mode, -1)
