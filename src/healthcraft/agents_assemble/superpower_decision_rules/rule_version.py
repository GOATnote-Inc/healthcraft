"""Content-hash versioning for decision rules.

Production CDS deployment requires reproducibility: a hospital's audit
team must be able to point at a chart from last Tuesday and prove which
exact rule definition scored it. We do that with a SHA-256 of the rule's
canonical content (variables + score_ranges + recommendation strings).

The hash is short (12 hex chars displayed; full hash retained for audit).
Embedding it in:

- the SHARP envelope's ``trace`` (already present via the Superpower)
- the CDS Hooks card's ``detail`` field (so the EHR shows which rule
  version it rendered)
- the persistent audit log (one line per invocation)

is what enables a clinician to say "the rule applied to this chart was
version ``a3f1...e2`` of HEART Score" with cryptographic certainty.

The ``rule_version`` function is pure: same rule data -> same hash, every
time. It tolerates dataclass and dict inputs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from typing import Any


def _normalize(rule: Any) -> dict[str, Any]:
    """Normalize a rule (dataclass or dict) to the fields that affect scoring."""
    if is_dataclass(rule):
        d = asdict(rule)
    elif isinstance(rule, dict):
        d = dict(rule)
    else:
        raise TypeError(f"unsupported rule type: {type(rule).__name__}")

    # Only the fields that actually affect the rule's clinical behavior
    # contribute to the version. ``id``, ``created_at``, ``updated_at``,
    # ``description`` (free text), and ``url`` are deliberately excluded so
    # that doc edits don't bump the version.
    return {
        "name": d.get("name", ""),
        "variables": list(d.get("variables") or []),
        "score_ranges": list(d.get("score_ranges") or []),
        "category": d.get("category", ""),
    }


def rule_version(rule: Any) -> str:
    """Return a deterministic SHA-256 hex digest of the rule's content."""
    payload = json.dumps(_normalize(rule), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def short_version(rule: Any) -> str:
    """Short (12-char) display form of the rule version."""
    return rule_version(rule)[:12]
