"""Immutable tutorial assignments and unvalidated human incident responses.

This is an operator workflow, not a grader or clinical-review substitute. It
preserves every assigned case and axis, including missing or invalid responses.
Content hashes establish identity, not authorship, independence or authenticity.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

from healthcraft.reconciliation.diagnostics import explain_reconciliation
from healthcraft.reconciliation.oracle import verify_reconciliation

PACKET_VERSION = "healthcraft-operator-review-packet/v1"
RESPONSE_VERSION = "healthcraft-operator-review-response/v1"
MANIFEST_VERSION = "healthcraft-operator-review-manifest/v1"
AXES = (
    "execution_completion",
    "write_acknowledgement",
    "storage",
    "readback",
    "reconciliation_correctness",
    "evidence_sufficiency",
)
_QUESTIONS = (
    (
        "Did the recorded execution complete?",
        "Completion is separate from successful actions or correct content.",
    ),
    (
        "Was a note-write request acknowledged as successful?",
        "An acknowledgement, including a retry acknowledgement, "
        "does not prove a new note was stored.",
    ),
    (
        "Does the captured final state contain any new note?",
        "A note for the wrong patient or encounter still counts as storage; "
        "target and content correctness are separate.",
    ),
    (
        "Did a later successful retrieval return the stored note text?",
        "Retrieving stored text does not establish target or reconciliation correctness; "
        "a retrieval without that text is not readback.",
    ),
    (
        "Does the recorded reconciliation satisfy the authored source and persistence contract?",
        "This is an operator interpretation of an engineering contract, not clinical correctness.",
    ),
    (
        "Is the captured evidence sufficient to support this incident assessment?",
        "Coherent captured evidence is not proof of execution authenticity.",
    ),
)
_DOCUMENTS = {"scenario", "expectations", "evidence", "oracle"}
_REASONS = {"insufficient_evidence", "conflicting_evidence", "outside_scope", "reviewer_abstention"}
_LIMITATIONS = [
    "Exposed tutorial cases only; not held-out cases or comparative value evidence.",
    "Human responses and timing are declarations, not authenticated identities or measurements.",
    "No correctness adjudication, clinical validation, score or superiority claim is produced.",
    "Repeated evidence or scenario families are not independent cases; preserve their identities.",
    "Hashes identify captured content, not execution authenticity or registration timing.",
]
_BUNDLE_FILES = {
    "inputs/scenario.json",
    "inputs/expectations.json",
    "inputs/evidence.json",
    "verification.json",
    "explanation.json",
    "report.html",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _keys(value: Any, expected: set[str], label: str) -> None:
    _require(type(value) is dict and set(value) == expected, f"Invalid {label} fields")


def _text(value: Any, label: str) -> None:
    _require(type(value) is str and bool(value.strip()), f"{label} must be nonempty text")


def _canonical(value: Any) -> bytes:
    def check(item):
        if type(item) is dict:
            for key, child in item.items():
                _require(type(key) is str, "JSON keys must be strings")
                check(child)
        elif type(item) is list:
            for child in item:
                check(child)
        elif type(item) is float:
            _require(math.isfinite(item), "Nonfinite JSON number")
        else:
            _require(type(item) in (str, int, bool, type(None)), "Unsupported JSON value")

    check(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: Any) -> str:
    return _sha(_canonical(value))


def _same(left: Any, right: Any) -> bool:
    return _canonical(left) == _canonical(right)


def _parse(raw: bytes | str) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs)
        _require(type(value) is dict, "Expected a JSON object")
        _canonical(value)
        return value
    except (TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError(f"Invalid strict JSON: {type(exc).__name__}") from exc


def _safe_id(value: Any) -> None:
    _require(
        type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value) is not None,
        "Invalid opaque case ID",
    )


def _relative(value: Any) -> None:
    _require(type(value) is str and bool(value) and "\\" not in value, "Invalid inventory path")
    path = PurePosixPath(value)
    _require(
        not path.is_absolute() and all(part not in ("", ".", "..") for part in value.split("/")),
        "Invalid inventory path",
    )


def _inventory(value: Any) -> None:
    _require(type(value) is dict and bool(value), "Missing source inventory")
    seen = set()
    for name, digest in value.items():
        _relative(name)
        _require(name.casefold() not in seen, "Ambiguous inventory path")
        seen.add(name.casefold())
        _require(
            type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
            "Invalid source inventory hash",
        )


def _tree(root: Path) -> dict[str, bytes]:
    _require(root.is_dir() and not root.is_symlink(), "Source must be a nonsymlink directory")
    result = {}
    for path in sorted(root.rglob("*")):
        _require(not path.is_symlink(), "Symlink source is not supported")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path.read_bytes()
        else:
            _require(path.is_dir(), "Unsupported source entry")
    return result


def _verify_files(
    raw: dict[str, bytes], inventory: Any, *, manifest_name: str = "manifest.json"
) -> None:
    _inventory(inventory)
    _require(
        set(raw) == set(inventory) | {manifest_name},
        "Source inventory has missing or unlisted files",
    )
    for name, expected in inventory.items():
        _require(_sha(raw[name]) == expected, f"Source file changed: {name}")


def _bundle(raw: dict[str, bytes]) -> dict:
    _require("manifest.json" in raw, "Missing bundle manifest")
    manifest = _parse(raw["manifest.json"])
    _keys(
        manifest,
        {
            "schema_version",
            "status",
            "explanation_status",
            "files",
            "source_files",
            "input_paths",
            "bindings",
            "supplied_verification_matched",
            "model_calls",
            "limitations",
            "source_context",
        },
        "bundle manifest",
    )
    _require(
        manifest["schema_version"] == "healthcraft-reconciliation-explanation-bundle/v1"
        and manifest["status"] == "complete",
        "Incomplete or unsupported source bundle",
    )
    _require(
        _same(
            manifest["source_context"],
            {"enabled": True, "schema_version": "healthcraft-reconciliation-source-context/v1"},
        ),
        "Source context is required",
    )
    _require(
        type(manifest["model_calls"]) is int and manifest["model_calls"] == 0,
        "Invalid bundle execution declaration",
    )
    _require(
        type(manifest["supplied_verification_matched"]) is bool,
        "Invalid supplied verification declaration",
    )
    _require(
        type(manifest["limitations"]) is list
        and all(type(value) is str for value in manifest["limitations"]),
        "Invalid bundle limitations",
    )
    _inventory(manifest["source_files"])
    _verify_files(raw, manifest["files"])
    expected_files = _BUNDLE_FILES | (
        {"inputs/verification.json"} if manifest["supplied_verification_matched"] else set()
    )
    _require(set(manifest["files"]) == expected_files, "Unsupported or incomplete bundle payloads")
    path_keys = {"scenario", "expectations", "evidence"} | (
        {"verification"} if manifest["supplied_verification_matched"] else set()
    )
    _keys(manifest["input_paths"], path_keys, "original input paths")
    for path in manifest["input_paths"].values():
        _text(path, "Original input path")
    documents = {
        key: _parse(raw[f"inputs/{key}.json"]) for key in ("scenario", "expectations", "evidence")
    }
    documents["oracle"] = _parse(raw["verification.json"])
    oracle = verify_reconciliation(
        documents["scenario"], documents["expectations"], documents["evidence"]
    )
    _require(
        _same(documents["oracle"], oracle), "Captured oracle differs from recomputed verification"
    )
    explanation = explain_reconciliation(
        documents["scenario"], documents["expectations"], documents["evidence"]
    )
    _require(
        _same(_parse(raw["explanation.json"]), explanation),
        "Captured explanation differs from recomputed explanation",
    )
    bindings = {name + "_sha256": _digest(value) for name, value in documents.items()}
    _require(
        _same(manifest["bindings"], bindings) and _same(explanation["bindings"], bindings),
        "Source binding mismatch",
    )
    _require(
        manifest["explanation_status"] == explanation["status"], "Explanation availability mismatch"
    )
    if manifest["supplied_verification_matched"]:
        _require(
            _same(_parse(raw["inputs/verification.json"]), oracle), "Supplied verification differs"
        )
    family = documents["scenario"].get("id")
    _text(family, "Scenario family ID")
    return {
        "documents": documents,
        "explanation": explanation,
        "source_bindings": bindings,
        "scenario_family_id": family,
    }


def _config(protocol: dict, assignment: dict) -> None:
    _canonical(protocol)
    _canonical(assignment)
    _keys(protocol, {"protocol_id", "purpose"}, "protocol")
    _text(protocol["protocol_id"], "protocol_id")
    _require(
        protocol["purpose"] == "engineering_tutorial", "Only engineering tutorials are supported"
    )
    _keys(assignment, {"assignment_id", "reviewer_id", "presentation"}, "assignment")
    for key in ("assignment_id", "reviewer_id"):
        _text(assignment[key], key)
    _require(
        type(assignment["presentation"]) is str
        and assignment["presentation"] in {"raw", "assisted"},
        "Invalid presentation",
    )


def _case(case_id: str, bundle: dict) -> dict:
    return {
        "case_id": case_id,
        **deepcopy(bundle),
        "axes": [
            {"axis_id": axis, "question": question, "scope_note": scope}
            for axis, (question, scope) in zip(AXES, _QUESTIONS, strict=True)
        ],
    }


def _packet(packet_id: str, cases: list[dict], protocol: dict, assignment: dict) -> dict:
    return {
        "schema_version": PACKET_VERSION,
        "packet_id": packet_id,
        **deepcopy(assignment),
        "protocol": deepcopy(protocol),
        "scope": "exposed_tutorial_operator_review",
        "cases": cases,
        "limitations": list(_LIMITATIONS),
    }


def _blank_axis(axis: str) -> dict:
    return {
        "axis_id": axis,
        "judgment": None,
        "unassessed_reason": None,
        "evidence_refs": [],
        "rationale": "",
    }


def _blank_timing() -> dict:
    return {"method": "not_collected", "elapsed_seconds": None, "active_seconds": None, "note": ""}


def _template(packet: dict) -> dict:
    return {
        "schema_version": RESPONSE_VERSION,
        "packet_id": packet["packet_id"],
        "packet_sha256": _digest(packet),
        "assignment_id": packet["assignment_id"],
        "reviewer_id": packet["reviewer_id"],
        "cases": [
            {
                "case_id": case["case_id"],
                "axes": [_blank_axis(axis) for axis in AXES],
                "timing": _blank_timing(),
            }
            for case in packet["cases"]
        ],
    }


def _render_packet(packet: dict, template: dict) -> str:
    from healthcraft.operator_review_report import render_operator_packet

    return render_operator_packet(packet, template)


def _new_directory(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"Destination is occupied; choose a new directory: {path}")


def _outside(output: Path, source: Path) -> None:
    _require(
        not output.resolve().is_relative_to(source.resolve()),
        "Output must not be inside a source or issued packet directory",
    )


def _implementation() -> dict[str, str]:
    root = Path(__file__).resolve().parent
    names = (
        "operator_review.py",
        "operator_review_report.py",
        "reconciliation/diagnostics.py",
        "reconciliation/oracle.py",
        "entities/base.py",
        "mcp/server.py",
    )
    return {f"src/healthcraft/{name}": _sha((root / name).read_bytes()) for name in names}


def _write_artifacts(output_dir: Path, payloads: dict[str, bytes], manifest: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=False)
    for name, raw in payloads.items():
        destination = output_dir / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(raw)
    with (output_dir / "manifest.json").open("xb") as stream:
        stream.write(_canonical(manifest) + b"\n")


def build_operator_packet(
    case_bundles: dict[str, Path], output_dir: Path, *, protocol: dict, assignment: dict
) -> dict:
    """Preflight every explicit tutorial case, then create a new bound packet.

    Source-code inventories are preserved declarations; the bundle contains
    their hashes, not a reproducible copy of that earlier execution runtime.
    Oracle/explanation outputs are independently recomputed using this runtime.
    """
    output_dir = Path(output_dir)
    _new_directory(output_dir)
    _config(protocol, assignment)
    _require(
        type(case_bundles) is dict and bool(case_bundles), "Nonempty explicit case mapping required"
    )
    implementation = _implementation()
    cases, sources, payloads = [], [], {}
    seen_ids, seen_evidence = set(), set()
    for case_id, path in case_bundles.items():
        _safe_id(case_id)
        _outside(output_dir, Path(path))
        _require(case_id.casefold() not in seen_ids, "Duplicate case ID")
        seen_ids.add(case_id.casefold())
        raw = _tree(Path(path))
        bundle = _bundle(raw)
        identity = bundle["source_bindings"]["evidence_sha256"]
        _require(identity not in seen_evidence, "Duplicate evidence identity")
        seen_evidence.add(identity)
        cases.append(_case(case_id, bundle))
        directory = f"sources/{case_id}"
        payloads.update({f"{directory}/{name}": content for name, content in raw.items()})
        sources.append(
            {
                "case_id": case_id,
                "snapshot_dir": directory,
                "bundle_manifest_sha256": _sha(raw["manifest.json"]),
                "evidence_sha256": identity,
                "scenario_family_id": bundle["scenario_family_id"],
                "source_bindings": bundle["source_bindings"],
            }
        )
    packet = _packet(uuid.uuid4().hex, cases, protocol, assignment)
    template = _template(packet)
    payloads.update(
        {
            "packet.json": _canonical(packet) + b"\n",
            "response-template.json": _canonical(template) + b"\n",
            "report.html": _render_packet(deepcopy(packet), deepcopy(template)).encode("utf-8"),
        }
    )
    manifest = {
        "schema_version": MANIFEST_VERSION,
        "packet_id": packet["packet_id"],
        "packet_sha256": _digest(packet),
        "protocol": deepcopy(protocol),
        "assignment": deepcopy(assignment),
        "sources": sources,
        "implementation_sha256": implementation,
        "files": {name: _sha(raw) for name, raw in payloads.items()},
    }
    _require(
        _same(implementation, _implementation()),
        "Implementation changed during packet derivation",
    )
    manifest["manifest_sha256"] = _digest(manifest)
    _write_artifacts(output_dir, payloads, manifest)
    return deepcopy(packet)


def _validate_packet(manifest_path: Path) -> tuple[dict, dict, bytes]:
    _require(manifest_path.name == "manifest.json", "Expected packet manifest.json")
    raw = _tree(manifest_path.parent)
    _require("manifest.json" in raw, "Missing packet manifest")
    manifest = _parse(raw["manifest.json"])
    _keys(
        manifest,
        {
            "schema_version",
            "packet_id",
            "packet_sha256",
            "protocol",
            "assignment",
            "sources",
            "implementation_sha256",
            "files",
            "manifest_sha256",
        },
        "packet manifest",
    )
    _require(manifest["schema_version"] == MANIFEST_VERSION, "Unsupported packet manifest")
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    _require(_digest(unsigned) == manifest["manifest_sha256"], "Packet manifest changed")
    _require(
        _same(manifest["implementation_sha256"], _implementation()),
        "Implementation-version mismatch; use the recorded implementation",
    )
    _verify_files(raw, manifest["files"])
    _config(manifest["protocol"], manifest["assignment"])
    _text(manifest["packet_id"], "packet_id")
    _require(
        type(manifest["sources"]) is list and bool(manifest["sources"]), "Missing assigned sources"
    )
    cases, expected_paths, ids, evidence_ids = (
        [],
        {"packet.json", "response-template.json", "report.html"},
        set(),
        set(),
    )
    for source in manifest["sources"]:
        _keys(
            source,
            {
                "case_id",
                "snapshot_dir",
                "bundle_manifest_sha256",
                "evidence_sha256",
                "scenario_family_id",
                "source_bindings",
            },
            "assigned source",
        )
        case_id = source["case_id"]
        _safe_id(case_id)
        _require(case_id.casefold() not in ids, "Duplicate case ID")
        ids.add(case_id.casefold())
        directory = f"sources/{case_id}"
        _require(source["snapshot_dir"] == directory, "Wrong source snapshot directory")
        snapshots = {
            name[len(directory) + 1 :]: value
            for name, value in raw.items()
            if name.startswith(directory + "/")
        }
        bundle = _bundle(snapshots)
        expected_paths.update(directory + "/" + name for name in snapshots)
        expected_source = {
            "case_id": case_id,
            "snapshot_dir": directory,
            "bundle_manifest_sha256": _sha(snapshots["manifest.json"]),
            "evidence_sha256": bundle["source_bindings"]["evidence_sha256"],
            "scenario_family_id": bundle["scenario_family_id"],
            "source_bindings": bundle["source_bindings"],
        }
        _require(_same(source, expected_source), "Source assignment binding changed")
        _require(source["evidence_sha256"] not in evidence_ids, "Duplicate evidence identity")
        evidence_ids.add(source["evidence_sha256"])
        cases.append(_case(case_id, bundle))
    _require(set(manifest["files"]) == expected_paths, "Unassigned packet files")
    packet = _packet(manifest["packet_id"], cases, manifest["protocol"], manifest["assignment"])
    _require(
        _same(_parse(raw["packet.json"]), packet) and _digest(packet) == manifest["packet_sha256"],
        "Packet content binding changed",
    )
    template = _template(packet)
    _require(_same(_parse(raw["response-template.json"]), template), "Response template changed")
    _require(
        raw["report.html"] == _render_packet(deepcopy(packet), deepcopy(template)).encode("utf-8"),
        "Presented report differs from controlled rendering",
    )
    _require(
        _same(manifest["implementation_sha256"], _implementation()),
        "Implementation changed during packet verification",
    )
    return packet, manifest, raw["manifest.json"]


def _resolve(value: Any, pointer: Any) -> Any:
    _require(
        type(pointer) is str and re.fullmatch(r"(?:/(?:[^~]|~[01])*)?", pointer) is not None,
        "Invalid RFC6901 reference",
    )
    if not pointer:
        return value
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if type(value) is dict:
            _require(token in value, "Source reference does not resolve")
            value = value[token]
        elif type(value) is list:
            _require(
                re.fullmatch(r"0|[1-9][0-9]*", token) is not None and int(token) < len(value),
                "Source array reference does not resolve",
            )
            value = value[int(token)]
        else:
            raise ValueError("Cannot descend into a source scalar")
    return value


def _references(refs: Any, documents: dict) -> None:
    _require(type(refs) is list, "evidence_refs must be an array")
    seen = set()
    for ref in refs:
        _require(type(ref) is dict, "Invalid source reference")
        _keys(
            ref,
            {"document", "pointer"}
            | ({"decoded_json_pointer"} if "decoded_json_pointer" in ref else set()),
            "source reference",
        )
        _require(
            type(ref["document"]) is str and ref["document"] in _DOCUMENTS,
            "Unknown source document",
        )
        value = _resolve(documents[ref["document"]], ref["pointer"])
        if "decoded_json_pointer" in ref:
            _require(type(value) is str, "Decoded reference must address captured JSON text")
            _resolve(_parse(value), ref["decoded_json_pointer"])
        identity = _digest(ref)
        _require(identity not in seen, "Duplicate source reference")
        seen.add(identity)


def _axis(row: dict, documents: dict) -> str:
    _keys(
        row,
        {"axis_id", "judgment", "unassessed_reason", "evidence_refs", "rationale"},
        "axis response",
    )
    if _same(row, _blank_axis(row["axis_id"])):
        return "pending"
    _require(
        type(row["judgment"]) is str and row["judgment"] in {"yes", "no", "unassessed"},
        "Invalid judgment; incomplete draft must retain blank fields",
    )
    _text(row["rationale"], "rationale")
    _references(row["evidence_refs"], documents)
    if row["judgment"] == "unassessed":
        _require(
            type(row["unassessed_reason"]) is str and row["unassessed_reason"] in _REASONS,
            "Invalid unassessed reason",
        )
        return "unassessed"
    _require(
        row["unassessed_reason"] is None and bool(row["evidence_refs"]),
        "Assessed judgment requires evidence and no abstention reason",
    )
    return "assessed"


def _timing(value: Any) -> None:
    _keys(value, {"method", "elapsed_seconds", "active_seconds", "note"}, "timing")
    _require(type(value["note"]) is str, "Timing note must be text")
    _require(
        type(value["method"]) is str and value["method"] in {"not_collected", "self_reported"},
        "Invalid timing provenance",
    )
    for key in ("elapsed_seconds", "active_seconds"):
        number = value[key]
        _require(
            number is None
            or (type(number) in (int, float) and math.isfinite(number) and number >= 0),
            "Timing requires finite nonnegative numbers, not booleans",
        )
    if value["method"] == "not_collected":
        _require(
            value["elapsed_seconds"] is None and value["active_seconds"] is None,
            "Uncollected timing must remain unknown",
        )
    else:
        _require(
            value["elapsed_seconds"] is not None or value["active_seconds"] is not None,
            "Self-reported timing needs a reported value",
        )
        _text(value["note"], "Self-reported timing note")
    if value["elapsed_seconds"] is not None and value["active_seconds"] is not None:
        _require(
            value["active_seconds"] <= value["elapsed_seconds"], "Active time exceeds elapsed time"
        )


def _response(value: dict, packet: dict) -> dict:
    _keys(
        value,
        {"schema_version", "packet_id", "packet_sha256", "assignment_id", "reviewer_id", "cases"},
        "response",
    )
    expected = _template(packet)
    for key in expected.keys() - {"cases"}:
        _require(_same(value[key], expected[key]), f"Response {key} does not match assignment")
    _require(type(value["cases"]) is list, "cases must be an array")
    assigned = {case["case_id"]: case for case in packet["cases"]}
    received = {}
    for case in value["cases"]:
        _keys(case, {"case_id", "axes", "timing"}, "case response")
        identifier = case["case_id"]
        _require(type(identifier) is str and identifier in assigned, "Foreign case response")
        _require(identifier not in received, "Duplicate case response")
        _require(type(case["axes"]) is list, "axes must be an array")
        _timing(case["timing"])
        rows = {}
        for row in case["axes"]:
            _require(
                type(row) is dict and type(row.get("axis_id")) is str and row["axis_id"] in AXES,
                "Unknown axis response",
            )
            _require(row["axis_id"] not in rows, "Duplicate axis response")
            rows[row["axis_id"]] = {
                "status": _axis(row, assigned[identifier]["documents"]),
                "response": row,
            }
        received[identifier] = {"axes": rows, "timing": case["timing"]}
    return received


def _account(packet: dict, received: dict) -> tuple[list[dict], dict]:
    counts = {
        "assigned_cases": len(packet["cases"]),
        "submitted_cases": 0,
        "abstained_cases": 0,
        "unassessed_cases": 0,
        "pending_cases": 0,
        "partial_cases": 0,
        "assigned_axes": len(packet["cases"]) * len(AXES),
        "assessed_axes": 0,
        "unassessed_axes": 0,
        "pending_axes": 0,
    }
    cases = []
    for case in packet["cases"]:
        incoming = received.get(case["case_id"])
        rows = incoming["axes"] if incoming else {}
        axes = [
            {"axis_id": axis, **deepcopy(rows.get(axis, {"status": "pending", "response": None}))}
            for axis in AXES
        ]
        statuses = {row["status"] for row in axes}
        if "pending" in statuses:
            status = "pending"
        elif statuses == {"unassessed"}:
            status = (
                "abstained"
                if all(
                    row["response"]["unassessed_reason"] == "reviewer_abstention" for row in axes
                )
                else "unassessed"
            )
        else:
            status = "submitted"
        counts[status + "_cases"] += 1
        counts["partial_cases"] += status == "pending" and len(statuses) > 1
        for row in axes:
            counts[row["status"] + "_axes"] += 1
        cases.append(
            {
                "case_id": case["case_id"],
                "scenario_family_id": case["scenario_family_id"],
                "evidence_sha256": case["source_bindings"]["evidence_sha256"],
                "status": status,
                "received": incoming is not None,
                "axes": axes,
                "timing": deepcopy(incoming["timing"]) if incoming else None,
            }
        )
    return cases, counts


def import_operator_response(manifest_path: Path, response_path: Path, output_dir: Path) -> dict:
    """Record raw submission bytes and all assignments without adjudicating them.

    Invalid source packets raise before writing. Invalid submissions to a valid
    packet produce a receipt with every assignment pending and no imported
    judgments. A filesystem failure can leave a new incomplete directory; it
    must be retained and a different destination used for any later attempt.
    """
    output_dir = Path(output_dir)
    _new_directory(output_dir)
    _outside(output_dir, Path(manifest_path).parent)
    packet, manifest, raw_manifest = _validate_packet(Path(manifest_path))
    raw = Path(response_path).read_bytes()
    errors, received = [], {}
    try:
        received = _response(_parse(raw), packet)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError, UnicodeError) as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    cases, counts = _account(packet, received)
    receipt = {
        "schema_version": "healthcraft-operator-review-receipt/v1",
        "status": "invalid_submission" if errors else "recorded",
        "packet_id": packet["packet_id"],
        "packet_sha256": manifest["packet_sha256"],
        "assignment_id": packet["assignment_id"],
        "reviewer_id": packet["reviewer_id"],
        "presentation": packet["presentation"],
        "protocol_sha256": _digest(packet["protocol"]),
        "manifest_sha256": manifest["manifest_sha256"],
        "response_sha256": _sha(raw),
        "errors": errors,
        "counts": counts,
        "cases": cases,
        "limitations": list(_LIMITATIONS),
    }
    payloads = {
        "submission.json": raw,
        "packet-manifest.json": raw_manifest,
        "receipt.json": _canonical(receipt) + b"\n",
    }
    output_manifest = {
        "schema_version": "healthcraft-operator-review-import/v1",
        "status": "complete",
        "files": {name: _sha(content) for name, content in payloads.items()},
        "packet_sha256": manifest["packet_sha256"],
        "response_sha256": _sha(raw),
    }
    _write_artifacts(output_dir, payloads, output_manifest)
    return deepcopy(receipt)
