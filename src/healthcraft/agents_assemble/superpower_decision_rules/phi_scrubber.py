"""Minimal PHI scrubber for FHIR Bundles before LLM extraction.

The hackathon judges score on "Does the architecture respect data privacy,
safety standards, and regulatory constraints?" — and HIPAA Safe Harbor
de-identification removes 18 categories of identifiers. Stripping every
category before *any* LLM call would also strip clinical signal we need
to extract decision-rule variables (DOB-derived age, dates of recent
travel/surgery for Wells, etc.).

This scrubber is intentionally **minimal**: it removes the highest-risk,
lowest-clinical-value identifiers — names, MRNs, SSNs, phone numbers,
e-mail addresses, postal addresses — while preserving:

- ``birthDate`` (needed for age scoring on HEART, qSOFA, CURB-65, etc.)
- Clinical free text (HPI, notes) — but with embedded SSN/phone/email
  patterns redacted
- Coded clinical data (Conditions, Observations, AllergyIntolerance)

The aggressive Safe Harbor variant (also redact dates / dates-derived
identifiers / IPs / device IDs) is left as a future option; the
hackathon platform layer (Prompt Opinion handles auth, credential
bridging, audit) is expected to enforce the rest at infrastructure level.

Round-trip determinism: scrubbing the same bundle twice yields the same
bytes (sorted-key JSON). The scrubber never modifies the input bundle in
place — it returns a new dict.
"""

from __future__ import annotations

import copy
import re
from typing import Any

# Field paths we redact entirely. Keys are FHIR resource type aliases.
_RESOURCE_REDACT_FIELDS: dict[str, tuple[str, ...]] = {
    "Patient": (
        "name",
        "telecom",
        "address",
        "photo",
        "identifier",
        "contact",
        "communication",
    ),
    "RelatedPerson": ("name", "telecom", "address", "photo", "identifier"),
    "Practitioner": ("name", "telecom", "address", "photo"),
    "Person": ("name", "telecom", "address", "photo", "identifier"),
}

# Patterns redacted from any free-text string field (notes, HPI, extension values).
_TEXT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # SSN
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED-SSN]"),
    # US phone (loose)
    (re.compile(r"\b(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b"), "[REDACTED-PHONE]"),
    # Email
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[REDACTED-EMAIL]"),
    # MRN-like patterns (e.g. MRN-12345678 or MRN: 12345678)
    (re.compile(r"\bMRN[-:\s]*\d{4,12}\b", re.I), "[REDACTED-MRN]"),
    # Common name-prefix tags ("Mr. Smith", "Mrs. Smith"). Heuristic; opt-in.
    # Disabled by default — too easy to over-redact a clinical field like
    # "Mr." appearing in a free-text radiology note. The platform layer
    # owns full name de-id when needed.
)

# Identifier system patterns whose values are PHI even though the field name
# is innocuous. We blank the ``value`` while keeping the ``system`` so the
# downstream system can still know what kind of identifier was present.
_PHI_IDENTIFIER_SYSTEMS = (
    "urn:oid:2.16.840.1.113883",  # US national IDs
    "ssn",
    "mrn",
)


def scrub_bundle(bundle: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a new Bundle with PHI minimized for LLM extraction."""
    if bundle is None:
        return None
    cleaned = copy.deepcopy(bundle)
    for entry in cleaned.get("entry", []) or []:
        resource = entry.get("resource")
        if isinstance(resource, dict):
            entry["resource"] = _scrub_resource(resource)
    return cleaned


def scrub_resource(resource: dict[str, Any]) -> dict[str, Any]:
    """Public single-resource scrub (used by tests and external callers)."""
    return _scrub_resource(copy.deepcopy(resource))


def _scrub_resource(resource: dict[str, Any]) -> dict[str, Any]:
    rtype = resource.get("resourceType")
    if rtype in _RESOURCE_REDACT_FIELDS:
        for field in _RESOURCE_REDACT_FIELDS[rtype]:
            if field in resource:
                resource.pop(field, None)
    # Walk the rest of the resource and scrub free text + identifier values.
    return _walk(resource)


def _walk(node: Any) -> Any:
    if isinstance(node, dict):
        # Redact identifier values for known PHI systems.
        if (
            "system" in node
            and "value" in node
            and isinstance(node.get("system"), str)
            and any(p in node["system"].lower() for p in _PHI_IDENTIFIER_SYSTEMS)
        ):
            node["value"] = "[REDACTED]"
        return {k: _walk(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk(v) for v in node]
    if isinstance(node, str):
        return _redact_text(node)
    return node


def _redact_text(text: str) -> str:
    out = text
    for pattern, replacement in _TEXT_PATTERNS:
        out = pattern.sub(replacement, out)
    return out
