"""Issue a lighter, resumable view of an unchanged v2 review assignment.

The original packet and importer remain authoritative. This optional development
view neither changes the response schema nor establishes which interface a person
used, independent review, clinical validity, or comparative user benefit.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from healthcraft.operator_review import (
    _digest,
    _keys,
    _new_directory,
    _outside,
    _parse,
    _require,
    _same,
    _sha,
    _tree,
    _verify_files,
    _write_artifacts,
)

MANIFEST_VERSION = "healthcraft-operator-workbench-manifest/v1"
VIEW_VERSION = "healthcraft-operator-workbench/v1"


def _implementation():
    root = Path(__file__).resolve().parent
    names = (
        "operator_workbench.py",
        "operator_workbench_report.py",
        "operator_workbench_drafts.py",
        "operator_incidents.py",
        "operator_adjudication.py",
        "operator_incident_report.py",
        "operator_review.py",
    )
    return {"src/healthcraft/" + name: _sha((root / name).read_bytes()) for name in names}


def _render(packet, template):
    from healthcraft.operator_workbench_report import render_workbench

    return render_workbench(deepcopy(packet), deepcopy(template))


def _issuer(path, source_manifest_override=None):
    from healthcraft.operator_adjudication import validate_adjudication_packet
    from healthcraft.operator_incidents import _no_symlinks, validate_incident_packet

    path = Path(path)
    _require(path.name == "manifest.json", "Expected original issuer manifest.json")
    _no_symlinks(path)
    raw = _tree(path.parent)
    manifest = _parse(raw["manifest.json"].decode("utf-8"))
    version = manifest.get("schema_version")
    if version == "healthcraft-operator-incident-manifest/v2":
        packet, validated, raw_manifest = validate_incident_packet(
            path,
            source_manifest_override=source_manifest_override,
        )
        kind = "incident"
    elif version == "healthcraft-operator-adjudication-manifest/v2":
        _require(
            source_manifest_override is None, "A source override applies only to operator packets"
        )
        packet, validated, raw_manifest = validate_adjudication_packet(path)
        kind = "adjudication"
    else:
        raise ValueError("Unsupported original review assignment")
    _require(
        raw_manifest == raw["manifest.json"] and _same(manifest, validated),
        "Original issuer changed during validation",
    )
    _require(
        _same(packet, _parse(raw["public/packet.json"].decode("utf-8"))),
        "Original public packet changed",
    )
    template = _parse(raw["public/response-template.json"].decode("utf-8"))
    _require(_tree(path.parent) == raw, "Original issuer files changed during validation")
    return packet, template, manifest, raw, kind


def _protect_inventory_parents(output):
    # A resolver may retain prior imports by content, without their old paths.
    # Protect any existing inventory, not only dependency locations we can name.
    for parent in Path(output).resolve().parents:
        manifest = parent / "manifest.json"
        if manifest.is_file():
            try:
                value = _parse(manifest.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError) as exc:
                raise ValueError("Output is beneath an unreadable existing manifest") from exc
            _require(
                "files" not in value,
                "Output cannot be placed inside an existing manifest inventory",
            )


def _protect(output, path, manifest, raw, kind, source_manifest_override):
    _outside(output, path.parent)
    if kind == "incident":
        _outside(output, Path(manifest["source_manifest"]).parent)
        if source_manifest_override is not None:
            _outside(output, Path(source_manifest_override).parent)
    else:
        from healthcraft.operator_adjudication import _protect_sources

        _protect_sources(output, raw, manifest["source_bindings"])


def _payloads(packet, template, raw, kind):
    command = "import" if kind == "incident" else "adjudication-import"
    readme = f"""# Offline review workbench

Distribute only `public/`. Open `public/report.html` to inspect the original
source documents, complete a report, or resume a response exported from the form.
The original assignment, packet JSON and blank response template are unchanged.

Import exported responses using `scripts/operator_incidents.py {command}` with
the ORIGINAL issuer manifest, not this workbench manifest. Use a fresh destination.
The original importer remains authoritative; structural acceptance is not validity.

This is a separately versioned development view. Retain its manifest if reporting
which view was issued. The response schema alone cannot prove which interface was
used. Comparative studies must prospectively bind the view and assignment; this
view is not evidence of measured time savings or clinical benefit.

There is no network service, participant authentication or activity timer.
Browser visual QA and intended-user feasibility remain unverified. Preserve
original artifacts and use new directories for revisions.
"""
    return {
        "public/packet.json": raw["public/packet.json"],
        "public/response-template.json": raw["public/response-template.json"],
        "public/report.html": _render(packet, template).encode("utf-8"),
        "README.md": readme.encode("utf-8"),
    }


def build_workbench(issuer_manifest, output_dir, *, source_manifest_override=None):
    """Create a new view while preserving the exact original assignment bytes."""
    path, output = Path(issuer_manifest), Path(output_dir)
    _new_directory(output)
    _protect_inventory_parents(output)
    _outside(output, path.parent)
    implementation = _implementation()
    packet, template, issuer, raw, kind = _issuer(path, source_manifest_override)
    _protect(output, path, issuer, raw, kind, source_manifest_override)
    payloads = _payloads(packet, template, raw, kind)
    manifest = {
        "schema_version": MANIFEST_VERSION,
        "view_version": VIEW_VERSION,
        "issuer_manifest": str(path.resolve()),
        "issuer_manifest_sha256": _sha(raw["manifest.json"]),
        "issuer_kind": kind,
        "packet_sha256": _digest(packet),
        "implementation_sha256": implementation,
        "files": {name: _sha(value) for name, value in payloads.items()},
    }
    _require(_tree(path.parent) == raw, "Original issuer changed while building view")
    _require(_same(implementation, _implementation()), "View implementation changed during build")
    _write_artifacts(output, payloads, manifest)
    return deepcopy(manifest)


def validate_workbench(
    manifest_path, *, issuer_manifest_override=None, source_manifest_override=None
):
    """Reconstruct the complete view from the pinned, still-valid original issuer."""
    path = Path(manifest_path)
    _require(path.name == "manifest.json", "Expected workbench manifest.json")
    raw = _tree(path.parent)
    manifest = _parse(raw["manifest.json"].decode("utf-8"))
    _keys(
        manifest,
        {
            "schema_version",
            "view_version",
            "issuer_manifest",
            "issuer_manifest_sha256",
            "issuer_kind",
            "packet_sha256",
            "implementation_sha256",
            "files",
        },
        "workbench manifest",
    )
    _require(
        manifest["schema_version"] == MANIFEST_VERSION and manifest["view_version"] == VIEW_VERSION,
        "Unknown workbench version",
    )
    _require(
        _same(manifest["implementation_sha256"], _implementation()),
        "Use the issuing workbench implementation",
    )
    _verify_files(raw, manifest["files"])
    source = (
        Path(issuer_manifest_override)
        if issuer_manifest_override is not None
        else Path(manifest["issuer_manifest"])
    )
    _require(
        _sha(source.read_bytes()) == manifest["issuer_manifest_sha256"],
        "Original issuer manifest pin mismatch",
    )
    packet, template, _, originals, kind = _issuer(source, source_manifest_override)
    _require(
        kind == manifest["issuer_kind"] and _digest(packet) == manifest["packet_sha256"],
        "Original assignment differs",
    )
    expected = _payloads(packet, template, originals, kind)
    _require(set(expected) == set(manifest["files"]), "Unexpected workbench files")
    _require(
        all(raw[name] == content for name, content in expected.items()),
        "Displayed view differs from original assignment",
    )
    _require(
        _same(manifest["implementation_sha256"], _implementation()),
        "View implementation changed during validation",
    )
    return deepcopy(packet), deepcopy(manifest)
