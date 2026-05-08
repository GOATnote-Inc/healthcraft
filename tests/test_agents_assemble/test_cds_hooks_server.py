"""HTTP integration tests for the live CDS Hooks service.

Boots the in-process ThreadingHTTPServer on an ephemeral port and exercises
the two endpoints CDS Hooks defines:

- ``GET /cds-services`` returns the discovery doc with our service id.
- ``POST /cds-services/healthcraft-ed-triage`` runs the agent over a
  prefetch payload and returns a CDS Hooks card.

Network is loopback-only (no internet); test exits in <1s.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from typing import Any

import pytest

from healthcraft.agents_assemble.cds_hooks_server import SERVICE_ID, serve
from healthcraft.agents_assemble.demo.bundles import load_scenario


def _bundle_to_prefetch(bundle: dict[str, Any]) -> dict[str, Any]:
    """Mirror what an EHR sends as ``prefetch`` — keyed by resource role."""
    by_type: dict[str, list[dict[str, Any]]] = {}
    for entry in bundle.get("entry", []):
        resource = entry.get("resource") or {}
        by_type.setdefault(resource.get("resourceType", ""), []).append(resource)
    return {
        "patient": (by_type.get("Patient") or [{}])[0],
        "encounter": (by_type.get("Encounter") or [{}])[0],
        "conditions": {
            "resourceType": "Bundle",
            "type": "searchset",
            "entry": [{"resource": r} for r in by_type.get("Condition", [])],
        },
        "observations": {
            "resourceType": "Bundle",
            "type": "searchset",
            "entry": [{"resource": r} for r in by_type.get("Observation", [])],
        },
        "documentreference": (by_type.get("DocumentReference") or [{}])[0],
    }


@pytest.fixture
def server_url():
    server = serve(port=0, host="127.0.0.1")
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _get_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(url: str, payload: dict[str, Any]) -> Any:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_discovery_lists_our_service(server_url: str) -> None:
    payload = _get_json(f"{server_url}/cds-services")
    assert "services" in payload
    assert any(s["id"] == SERVICE_ID for s in payload["services"])
    service = next(s for s in payload["services"] if s["id"] == SERVICE_ID)
    assert service["hook"] == "encounter-start"
    assert "prefetch" in service


def test_invocation_returns_critical_card_for_high_risk(server_url: str) -> None:
    bundle = load_scenario("sepsis").bundle
    payload = {
        "hookInstance": "test-hook-instance-1",
        "hook": "encounter-start",
        "context": {
            "patientId": "PAT-SEPSIS",
            "encounterId": "ENC-SEPSIS",
        },
        "prefetch": _bundle_to_prefetch(bundle),
    }
    response = _post_json(f"{server_url}/cds-services/{SERVICE_ID}", payload)
    assert "cards" in response
    assert response["cards"], "expected at least one card"
    card = response["cards"][0]
    assert card["indicator"] == "critical"
    assert "qSOFA" in card["summary"]


def test_invocation_with_empty_prefetch_returns_info_card(server_url: str) -> None:
    response = _post_json(
        f"{server_url}/cds-services/{SERVICE_ID}",
        {"hookInstance": "i", "hook": "encounter-start", "context": {}, "prefetch": {}},
    )
    assert response["cards"][0]["indicator"] == "info"


def test_unknown_service_returns_404(server_url: str) -> None:
    req = urllib.request.Request(
        f"{server_url}/cds-services/does-not-exist",
        data=b"{}",
        method="POST",
        headers={"content-type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=5)
    assert exc.value.code == 404
