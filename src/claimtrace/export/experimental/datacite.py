"""Experimental DataCite sidecar generation."""

from __future__ import annotations

from claimtrace.models import SemanticLayer


def datacite_sidecar(semantic: SemanticLayer) -> dict:
    return {
        "schemaVersion": "http://datacite.org/schema/kernel-4",
        "identifier": {"identifier": semantic.package.package_id, "identifierType": "ClaimTracePackageID"},
        "creators": [{"name": semantic.package.creator}],
        "titles": [{"title": semantic.package.title}],
        "publisher": "ClaimTrace",
        "publicationYear": semantic.package.created_at[:4],
        "resourceType": {"resourceTypeGeneral": "Dataset", "resourceType": "Molecular visualization claim package"},
        "rightsList": [{"rights": semantic.reuse.license}],
        "claimtrace_stability": "experimental",
    }
