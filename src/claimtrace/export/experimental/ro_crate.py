"""Experimental RO-Crate sidecar generation."""

from __future__ import annotations

from claimtrace.models import SemanticLayer


def ro_crate_sidecar(semantic: SemanticLayer) -> dict:
    return {
        "@context": "https://w3id.org/ro/crate/1.1/context",
        "@graph": [
            {"@id": "ro-crate-metadata.json", "@type": "CreativeWork", "about": {"@id": "./"}},
            {
                "@id": "./",
                "@type": "Dataset",
                "name": semantic.package.title,
                "license": semantic.reuse.license,
                "hasPart": [{"@id": artifact.path or artifact.url} for artifact in semantic.artifacts],
            },
        ],
        "claimtrace_stability": "experimental",
    }
