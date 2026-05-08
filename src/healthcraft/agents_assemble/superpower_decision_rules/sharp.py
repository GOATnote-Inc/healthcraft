"""SHARP context propagation helpers.

Prompt Opinion's SHARP extension specs propagate FHIR data context through
multi-agent call chains. This module provides a minimal, dependency-free
shape for that envelope so HEALTHCRAFT tools can produce and consume it
without coupling to any specific transport. Three concerns:

1. Round-trip integrity: a Superpower MUST echo back the inbound
   ``contextId`` (and the ``correlationId`` if present) so the caller can
   stitch the response into its trace.
2. Bundle reference: the FHIR Bundle is conveyed by reference (``bundleUri``
   + ``bundleHash``) when small enough, or inline (``bundle``). Tools must
   not silently drop either field.
3. Provenance: every Superpower appends a ``sharp.trace`` entry naming the
   tool, the rule (if any), and the SHA-256 of the input bundle so the
   downstream judge can verify which inputs the tool actually saw.

The helpers are intentionally schema-loose: the Prompt Opinion platform
owns the canonical SHARP schema, and we want to avoid drifting from a
moving target. Where the platform spec is ambiguous, we emit fields under
a conservative ``sharp`` key so they don't collide with the host envelope.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


def bundle_hash(bundle: dict[str, Any] | None) -> str:
    """Stable SHA-256 of a FHIR Bundle (or ``""`` when bundle is None)."""
    if not bundle:
        return ""
    payload = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass
class SharpEnvelope:
    """Inbound SHARP envelope: identifies the call and carries the FHIR Bundle.

    Field names mirror the language used in the hackathon brief
    ("contextId", "correlationId", FHIR Bundle propagation). Production
    Prompt Opinion deployments may rename fields; ``from_dict`` accepts
    common aliases.
    """

    context_id: str = ""
    correlation_id: str = ""
    bundle: dict[str, Any] | None = None
    bundle_uri: str = ""
    extensions: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> SharpEnvelope:
        """Best-effort decode of a SHARP envelope from a host transport.

        Tolerates camelCase, snake_case, and a top-level ``sharp`` key.
        """
        raw = dict(raw or {})
        sharp = raw.get("sharp") or {}
        merged = {**sharp, **raw}
        return cls(
            context_id=str(merged.get("contextId") or merged.get("context_id") or ""),
            correlation_id=str(merged.get("correlationId") or merged.get("correlation_id") or ""),
            bundle=merged.get("bundle"),
            bundle_uri=str(merged.get("bundleUri") or merged.get("bundle_uri") or ""),
            extensions={
                k: v
                for k, v in merged.items()
                if k
                not in {
                    "sharp",
                    "contextId",
                    "context_id",
                    "correlationId",
                    "correlation_id",
                    "bundle",
                    "bundleUri",
                    "bundle_uri",
                }
            },
        )

    def trace_entry(self, tool_name: str, **detail: Any) -> dict[str, Any]:
        """Provenance record echoed back to the caller."""
        return {
            "tool": tool_name,
            "contextId": self.context_id,
            "correlationId": self.correlation_id,
            "bundleSha256": bundle_hash(self.bundle),
            "ts": time.time(),
            "detail": detail,
        }


def reply_envelope(
    inbound: SharpEnvelope,
    payload: dict[str, Any],
    *,
    tool_name: str,
    trace_detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Wrap a Superpower payload in a SHARP-compatible response envelope.

    Always echoes ``contextId`` / ``correlationId`` and appends a single
    ``sharp.trace`` entry naming the tool. The host transport can re-flow
    these fields into whatever shape Prompt Opinion ultimately publishes
    without us having to rename anything internally.
    """
    return {
        "sharp": {
            "contextId": inbound.context_id or _new_id(),
            "correlationId": inbound.correlation_id or _new_id(),
            "trace": [inbound.trace_entry(tool_name, **(trace_detail or {}))],
        },
        "data": payload,
    }


def _new_id() -> str:
    """UUIDv4 as a string; isolated for monkeypatching in tests."""
    return str(uuid.uuid4())
