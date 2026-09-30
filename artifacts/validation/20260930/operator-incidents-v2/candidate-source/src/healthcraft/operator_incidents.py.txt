"""Bound source-only operator packets and unadjudicated incident submissions.

Only ``public/`` is an operator-facing export. The root manifest is coordinator
metadata, including the pinned original source location and explicit selection.
Hashes establish consistency, not authentic execution or blinded human review.
"""

from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from healthcraft.operator_review import (
    _QUESTIONS,
    _REASONS,
    AXES,
    _blank_axis,
    _blank_timing,
    _canonical,
    _digest,
    _keys,
    _new_directory,
    _outside,
    _relative,
    _require,
    _resolve,
    _safe_id,
    _same,
    _sha,
    _text,
    _timing,
    _tree,
    _verify_files,
    _write_artifacts,
)

PACKET_VERSION = "healthcraft-operator-incident-packet/v2"
RESPONSE_VERSION = "healthcraft-operator-incident-response/v2"
MANIFEST_VERSION = "healthcraft-operator-incident-manifest/v2"
DOCUMENTS = ("task", "scenario", "evidence", "runtime")
CATEGORIES = {
    "content",
    "target",
    "persistence",
    "execution",
    "tool",
    "provider",
    "grader",
    "evidence_gap",
    "source_uncertainty",
}
_LIMITATIONS = [
    "Exposed engineering development material; independent label review is pending.",
    "Operator responses are structurally checked declarations, not adjudicated truth.",
    "Captured errors and free text remain exact and may disclose model or control identity; "
    "no blinding is claimed.",
    "Raw and assisted presentations share public documents; assistance contains claims to inspect, "
    "not answers.",
    "No clinical validation, model ranking, benchmark score or performance estimate is produced.",
    "Hashes establish content identity, not execution authenticity, registration "
    "or operator identity.",
]
_SCRIPTED_INSTRUCTION = (
    "Retrospective mechanical review contract, not a prompt issued to the original "
    "scripted actor. Review all original encounter source rows. A single "
    "healthcraft-reconciliation-note/v1 JSON note for the requested patient and encounter "
    "must preserve every current target observation exactly with source_id, patient_id, "
    "encounter_id, source_collection, source_path and raw source. Retain unknowns, dates, "
    "status qualifiers and opposing reported_status assertions for the same event_id as "
    "unresolved_conflicts. List every non-target source under scope_exclusions with its "
    "true ownership and reason other_encounter or other_patient. Do not invent treatment "
    "or resolve source contradictions. Review actual acknowledgement, new persisted "
    "notes, subsequent returned text and explicit execution completion separately from "
    "target and source correctness."
)


def _decode(raw: bytes | str) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result

    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    value = json.loads(raw, object_pairs_hook=pairs)
    _canonical(value)
    return value


def _object(raw: bytes | str) -> dict:
    value = _decode(raw)
    _require(type(value) is dict, "Expected a JSON object")
    return value


def _no_symlinks(path: Path) -> None:
    for item in (path, *path.absolute().parents):
        _require(not item.is_symlink(), "Symlink source is not supported")


def _config(protocol: dict, assignment: dict) -> None:
    _canonical(protocol)
    _canonical(assignment)
    _keys(protocol, {"protocol_id", "purpose"}, "protocol")
    _text(protocol["protocol_id"], "protocol_id")
    _require(protocol["purpose"] == "engineering_development", "Unsupported protocol purpose")
    _keys(assignment, {"assignment_id", "operator_id", "presentation"}, "assignment")
    _text(assignment["assignment_id"], "assignment_id")
    _text(assignment["operator_id"], "operator_id")
    _require(assignment["presentation"] in ("raw", "assisted"), "Invalid presentation")


def _source(path: Path, expected_sha256: str) -> tuple[dict, dict[str, bytes], list[dict]]:
    _require(
        type(expected_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is not None,
        "Expected a raw manifest SHA-256 pin",
    )
    _require(path.name == "manifest.json", "Expected source manifest.json")
    _no_symlinks(path)
    raw = _tree(path.parent)
    _require(_sha(raw["manifest.json"]) == expected_sha256, "Source manifest pin mismatch")
    manifest = _object(raw["manifest.json"])
    _verify_files(raw, manifest.get("files"))
    version = manifest.get("schema_version")
    if version == "healthcraft-reconciliation-casebook-run/v2":
        roster = manifest.get("roster")
    elif version == "healthcraft-reconciliation-model-cohort/v2":
        _require("plan.json" in raw, "Missing model cohort plan")
        roster = _object(raw["plan.json"]).get("roster")
    else:
        raise ValueError("Unsupported source run manifest")
    _require(type(roster) is list and bool(roster), "Missing explicit source roster")
    seen = set()
    for row in roster:
        _require(type(row) is dict, "Invalid source roster row")
        name = row.get("id")
        _relative(name)
        _require(
            len(name.split("/")) == 2 and name.casefold() not in seen,
            "Duplicate or invalid attempt ID",
        )
        _require(row.get("case_id") == name.split("/")[0], "Attempt case identity mismatch")
        seen.add(name.casefold())
    outcomes = manifest.get("outcomes")
    _require(type(outcomes) is list, "Missing source outcomes")
    ids = [r.get("id") for r in outcomes if type(r) is dict]
    _require(
        len(ids) == len(outcomes) == len(set(ids)) and set(ids) == {r["id"] for r in roster},
        "Source outcomes do not match the complete roster",
    )
    return manifest, raw, roster


def _optional(raw: dict[str, bytes], name: str) -> dict | None:
    return _object(raw[name]) if name in raw else None


def _public_documents(value: Any) -> None:
    """Reject structured private assessment data in either presentation mode.

    Captured strings remain exact: text mentioning these names is not decoded,
    removed, or represented as blinded. Only already structured data is checked.
    """
    if type(value) is dict:
        _require(
            not {"expectations", "verification", "designated_control", "original_evidence"}
            & value.keys(),
            "Incident documents contain structured private assessment data",
        )
        for child in value.values():
            _public_documents(child)
    elif type(value) is list:
        for child in value:
            _public_documents(child)


def _documents(manifest: dict, raw: dict[str, bytes], row: dict) -> tuple[dict, str]:
    attempt, case_id = row["id"], row["case_id"]
    model = manifest["schema_version"] == "healthcraft-reconciliation-model-cohort/v2"
    case = _optional(raw, f"{attempt}/case.json" if model else f"{case_id}/case.json")
    if case is None and model and "cases.json" in raw:
        all_cases = _decode(raw["cases.json"])
        _require(type(all_cases) is list, "Invalid coordinator cases")
        matches = [c for c in all_cases if type(c) is dict and c.get("case_id") == case_id]
        _require(len(matches) <= 1, "Duplicate coordinator case")
        case = matches[0] if matches else None
    scenario = deepcopy(case.get("scenario")) if case else None
    if case is not None:
        _require(case.get("case_id") == case_id, "Source case identity mismatch")
        _require(type(scenario) is dict, "Invalid source scenario")
    family = case.get("scenario_family_id") if case else None
    _require(family is None or type(family) is str, "Invalid source family")
    evidence = _optional(raw, f"{attempt}/execution.json")
    outcome = next(r for r in manifest["outcomes"] if r["id"] == attempt)
    if model:
        task = _optional(raw, f"{attempt}/public-context.json")
        receipt = _optional(raw, f"{attempt}/receipt.json")
        worker = _optional(raw, f"{attempt}/worker/worker-receipt.json")
        if worker is None:
            worker = _optional(raw, f"{attempt}/worker-receipt.json")
        journals, missing = {}, {}
        for name in ("model", "controller"):
            path = f"{attempt}/worker/{name}.jsonl"
            journals[name] = raw[path].decode("utf-8") if path in raw else None
            if path not in raw:
                missing[name] = "Not present in the pinned source inventory"
        identities = {
            name: _optional(raw, f"{attempt}/worker/identity-{name}.json")
            for name in ("before", "after")
        }
        prompt = _optional(raw, f"{attempt}/worker/initial-prompt.json")
        delivery = _optional(raw, f"{attempt}/worker/delivery-error.json")
        for name, value in {
            "receipt": receipt,
            "worker_receipt": worker,
            "identity_before": identities["before"],
            "identity_after": identities["after"],
            "initial_prompt": prompt,
        }.items():
            if value is None:
                missing[name] = "Not present in the pinned source inventory"
        runtime = {
            "kind": "model_capture",
            "receipt": receipt,
            "worker_receipt": worker,
            "journals": journals,
            "identities": identities,
            "initial_prompt": prompt,
            "delivery_error": delivery,
            "capture_errors": missing,
            "runner_error": deepcopy(outcome.get("error")),
        }
        if all(
            value is None
            for value in (
                receipt,
                worker,
                prompt,
                delivery,
                *identities.values(),
                *journals.values(),
                outcome.get("error"),
            )
        ):
            runtime = None
    else:
        task = (
            None
            if scenario is None
            else {
                "provenance": "retrospective_review_contract",
                "not_presented_to_original_agent": True,
                "target": deepcopy(scenario.get("target")),
                "instruction": _SCRIPTED_INSTRUCTION,
            }
        )
        completion = evidence.get("completion") if evidence else None
        runtime = {
            "kind": "scripted_capture",
            "runtime": deepcopy(manifest.get("runtime")),
            "execution_error": deepcopy(completion.get("error"))
            if type(completion) is dict
            else None,
            "runner_error": deepcopy(outcome.get("error")),
        }
    return {"task": task, "scenario": scenario, "evidence": evidence, "runtime": runtime}, family


def _packet(
    packet_id: str,
    manifest: dict,
    raw: dict[str, bytes],
    roster: list[dict],
    pin: str,
    selections: dict,
    protocol: dict,
    assignment: dict,
) -> dict:
    _config(protocol, assignment)
    _require(type(selections) is dict and bool(selections), "Explicit nonempty selections required")
    by_id = {row["id"]: row for row in roster}
    seen_ids, seen_attempts, cases = set(), set(), []
    for review_id, attempt in selections.items():
        _safe_id(review_id)
        _require(review_id.casefold() not in seen_ids, "Duplicate review case ID")
        _require(type(attempt) is str and attempt in by_id, "Unknown selected attempt")
        _require(attempt not in seen_attempts, "Duplicate assigned attempt")
        seen_ids.add(review_id.casefold())
        seen_attempts.add(attempt)
        documents, family = _documents(manifest, raw, by_id[attempt])
        _public_documents(documents)
        assistance = None
        if assignment["presentation"] == "assisted":
            from healthcraft.reconciliation.incident_evidence import describe_incident

            assistance = describe_incident(deepcopy(documents))
        cases.append(
            {
                "review_case_id": review_id,
                "attempt_sha256": _digest({"source_manifest_sha256": pin, "attempt_id": attempt}),
                "scenario_family_id": family,
                "documents": documents,
                "availability": {
                    name: {
                        "status": "available" if value is not None else "unavailable",
                        "reason": None
                        if value is not None
                        else "Not present in the pinned source inventory",
                        "sha256": _digest(value) if value is not None else None,
                    }
                    for name, value in documents.items()
                },
                "assistance": assistance,
            }
        )
    return {
        "schema_version": PACKET_VERSION,
        "packet_id": packet_id,
        "protocol": deepcopy(protocol),
        **deepcopy(assignment),
        "axes": [
            {"axis_id": axis, "question": question, "distinction": scope}
            for axis, (question, scope) in zip(AXES, _QUESTIONS)
        ],
        "cases": cases,
        "limitations": list(_LIMITATIONS),
    }


def _blank_target() -> dict:
    return {
        "status": None,
        "patient_id": "",
        "encounter_id": "",
        "unassessed_reason": None,
        "rationale": "",
        "evidence_refs": [],
    }


def _blank_incident() -> dict:
    return {
        "status": None,
        "summary": "",
        "findings": [],
        "unassessed_reason": None,
        "evidence_refs": [],
    }


def incident_response_template(packet: dict) -> dict:
    return {
        "schema_version": RESPONSE_VERSION,
        "packet_id": packet["packet_id"],
        "packet_sha256": _digest(packet),
        "assignment_id": packet["assignment_id"],
        "operator_id": packet["operator_id"],
        "cases": [
            {
                "review_case_id": row["review_case_id"],
                "identified_target": _blank_target(),
                "axes": [_blank_axis(axis) for axis in AXES],
                "incident_assessment": _blank_incident(),
                "timing": _blank_timing(),
            }
            for row in packet["cases"]
        ],
    }


def _render(packet: dict, template: dict) -> str:
    from healthcraft.operator_incident_report import render_incident_packet

    return render_incident_packet(packet, template)


def _implementation() -> dict:
    root = Path(__file__).resolve().parent
    names = (
        "operator_incidents.py",
        "operator_review.py",
        "operator_incident_report.py",
        "reconciliation/incident_evidence.py",
    )
    return {f"src/healthcraft/{name}": _sha((root / name).read_bytes()) for name in names}


def _payloads(packet: dict) -> dict[str, bytes]:
    template = incident_response_template(packet)
    return {
        "public/packet.json": _canonical(packet) + b"\n",
        "public/response-template.json": _canonical(template) + b"\n",
        "public/report.html": _render(deepcopy(packet), deepcopy(template)).encode("utf-8"),
    }


def build_incident_packet(
    source_manifest: Path,
    output_dir: Path,
    *,
    expected_sha256: str,
    selections: dict,
    protocol: dict,
    assignment: dict,
) -> dict:
    """Validate the entire pinned source, then issue an exclusive public packet."""
    source_manifest, output_dir = Path(source_manifest), Path(output_dir)
    _new_directory(output_dir)
    _outside(output_dir, source_manifest.parent)
    implementation = _implementation()
    manifest, raw, roster = _source(source_manifest, expected_sha256)
    packet = _packet(
        uuid.uuid4().hex, manifest, raw, roster, expected_sha256, selections, protocol, assignment
    )
    payloads = _payloads(packet)
    issued = {
        "schema_version": MANIFEST_VERSION,
        "packet_id": packet["packet_id"],
        "packet_sha256": _digest(packet),
        "protocol": deepcopy(protocol),
        "assignment": deepcopy(assignment),
        "source_manifest": str(source_manifest.resolve()),
        "source_manifest_sha256": expected_sha256,
        "selections": deepcopy(selections),
        "selection_order": list(selections),
        "implementation_sha256": implementation,
        "files": {name: _sha(value) for name, value in payloads.items()},
    }
    _require(_tree(source_manifest.parent) == raw, "Source changed during packet construction")
    _require(_same(implementation, _implementation()), "Implementation changed during construction")
    issued["manifest_sha256"] = _digest(issued)
    _write_artifacts(output_dir, payloads, issued)
    return deepcopy(packet)


def validate_incident_packet(
    manifest_path: Path, *, source_manifest_override: Path | None = None
) -> tuple[dict, dict, bytes]:
    """Recompute public presentation against its pinned coordinator source."""
    manifest_path = Path(manifest_path)
    _require(manifest_path.name == "manifest.json", "Expected packet manifest.json")
    _no_symlinks(manifest_path)
    raw = _tree(manifest_path.parent)
    manifest = _object(raw["manifest.json"])
    _keys(
        manifest,
        {
            "schema_version",
            "packet_id",
            "packet_sha256",
            "protocol",
            "assignment",
            "source_manifest",
            "source_manifest_sha256",
            "selections",
            "selection_order",
            "implementation_sha256",
            "files",
            "manifest_sha256",
        },
        "coordinator manifest",
    )
    _require(manifest["schema_version"] == MANIFEST_VERSION, "Unsupported packet version")
    _require(
        _digest({k: v for k, v in manifest.items() if k != "manifest_sha256"})
        == manifest["manifest_sha256"],
        "Packet manifest changed",
    )
    _require(
        _same(manifest["implementation_sha256"], _implementation()),
        "Issuing implementation differs",
    )
    _verify_files(raw, manifest["files"])
    source_path = (
        Path(source_manifest_override)
        if source_manifest_override is not None
        else Path(manifest["source_manifest"])
    )
    source, originals, roster = _source(source_path, manifest["source_manifest_sha256"])
    order = manifest["selection_order"]
    selections = manifest["selections"]
    _require(
        type(order) is list
        and type(selections) is dict
        and all(type(item) is str for item in order)
        and len(order) == len(set(order))
        and set(order) == set(selections),
        "Invalid ordered selection roster",
    )
    packet = _packet(
        manifest["packet_id"],
        source,
        originals,
        roster,
        manifest["source_manifest_sha256"],
        {item: selections[item] for item in order},
        manifest["protocol"],
        manifest["assignment"],
    )
    _require(_digest(packet) == manifest["packet_sha256"], "Packet identity changed")
    payloads = _payloads(packet)
    _require(set(manifest["files"]) == set(payloads), "Unassigned public packet files")
    _require(
        all(raw[name] == value for name, value in payloads.items()), "Public presentation changed"
    )
    _require(_tree(source_path.parent) == originals, "Source changed during packet validation")
    _require(
        _same(manifest["implementation_sha256"], _implementation()),
        "Implementation changed during validation",
    )
    return packet, manifest, raw["manifest.json"]


def validate_incident_references(refs: Any, documents: dict) -> None:
    """Resolve strict references in the supplied document namespace, without judging relevance."""
    _require(type(refs) is list, "evidence_refs must be an array")
    seen = set()
    for ref in refs:
        _require(type(ref) is dict, "Invalid source reference")
        _keys(
            ref,
            {"document", "pointer"}
            | ({"decoded_json_pointer"} if "decoded_json_pointer" in ref else set()),
            "reference",
        )
        name = ref["document"]
        _require(
            type(name) is str and name in documents and documents[name] is not None,
            "Unknown or unavailable source document",
        )
        value = _resolve(documents[name], ref["pointer"])
        if "decoded_json_pointer" in ref:
            _require(type(value) is str, "Decoded reference needs captured JSON text")
            _resolve(_decode(value), ref["decoded_json_pointer"])
        key = _digest(ref)
        _require(key not in seen, "Duplicate source reference")
        seen.add(key)


def _reason(value: Any) -> None:
    _require(
        value is None or (type(value) is str and value in _REASONS), "Invalid unassessed reason"
    )


def _target(value: dict, documents: dict) -> str:
    _keys(value, set(_blank_target()), "identified target")
    for key in ("patient_id", "encounter_id", "rationale"):
        _require(type(value[key]) is str, f"Target {key} must be text")
    _reason(value["unassessed_reason"])
    validate_incident_references(value["evidence_refs"], documents)
    if value["status"] is None:
        return "pending"
    _require(value["status"] in ("identified", "unassessed"), "Invalid target status")
    _text(value["rationale"], "Target rationale")
    if value["status"] == "identified":
        _text(value["patient_id"], "Identified patient")
        _text(value["encounter_id"], "Identified encounter")
        _require(
            value["unassessed_reason"] is None
            and any(r["document"] in ("task", "scenario") for r in value["evidence_refs"]),
            "Identified target requires task/source evidence",
        )
        return "assessed"
    _require(value["unassessed_reason"] is not None, "Unknown target requires a reason")
    return "unassessed"


def _axis(value: dict, documents: dict) -> str:
    _keys(value, set(_blank_axis("")), "axis")
    _require(type(value["rationale"]) is str, "Axis rationale must be text")
    _reason(value["unassessed_reason"])
    validate_incident_references(value["evidence_refs"], documents)
    if value["judgment"] is None:
        return "pending"
    _require(value["judgment"] in ("yes", "no", "unassessed"), "Invalid axis judgment")
    _text(value["rationale"], "Axis rationale")
    if value["judgment"] == "unassessed":
        _require(value["unassessed_reason"] is not None, "Unassessed axis requires reason")
        return "unassessed"
    _require(
        value["unassessed_reason"] is None and bool(value["evidence_refs"]),
        "Assessed axis needs source evidence",
    )
    return "assessed"


def _finding(value: dict, documents: dict, *, draft: bool) -> None:
    _keys(
        value,
        {"finding_id", "category", "claim", "observed_target", "source_ids", "evidence_refs"},
        "finding",
    )
    _safe_id(value["finding_id"])
    _require(
        type(value["category"]) is str and value["category"] in CATEGORIES,
        "Unknown finding category",
    )
    _require(type(value["claim"]) is str, "Finding claim must be text")
    _keys(value["observed_target"], {"patient_id", "encounter_id"}, "observed target")
    for target in value["observed_target"].values():
        if target is not None:
            _text(target, "Observed identifier")
    ids = value["source_ids"]
    _require(type(ids) is list, "source_ids must be an array")
    for identifier in ids:
        _text(identifier, "Source identifier")
    _require(len(set(ids)) == len(ids), "Duplicate source identifier")
    validate_incident_references(value["evidence_refs"], documents)
    if not draft:
        _text(value["claim"], "Finding claim")
        _require(bool(value["evidence_refs"]), "Finding requires source evidence")


def _incident(value: dict, documents: dict) -> str:
    _keys(value, set(_blank_incident()), "incident assessment")
    _require(
        type(value["summary"]) is str and type(value["findings"]) is list,
        "Invalid incident text/findings",
    )
    _reason(value["unassessed_reason"])
    validate_incident_references(value["evidence_refs"], documents)
    seen = set()
    for finding in value["findings"]:
        _finding(finding, documents, draft=value["status"] is None)
        _require(finding["finding_id"].casefold() not in seen, "Duplicate finding ID")
        seen.add(finding["finding_id"].casefold())
    if value["status"] is None:
        return "pending"
    _require(
        value["status"] in ("findings_identified", "none_identified", "unassessed"),
        "Invalid incident status",
    )
    _text(value["summary"], "Incident summary")
    if value["status"] == "unassessed":
        _require(
            value["unassessed_reason"] is not None and not value["findings"],
            "Unassessed incident requires reason and no asserted findings",
        )
        return "unassessed"
    _require(
        value["unassessed_reason"] is None and bool(value["evidence_refs"]),
        "Incident assertion requires source evidence",
    )
    _require(
        bool(value["findings"]) == (value["status"] == "findings_identified"),
        "Incident finding/status conflict",
    )
    return "assessed"


def validate_incident_response(value: dict, packet: dict) -> dict:
    """Return supplied rows and structural statuses, never target/claim truth."""
    _canonical(value)
    expected = incident_response_template(packet)
    _keys(value, set(expected), "response")
    for key in set(expected) - {"cases"}:
        _require(_same(value[key], expected[key]), f"Response {key} differs from assignment")
    _require(type(value["cases"]) is list, "Response cases must be an array")
    assigned = {row["review_case_id"]: row for row in packet["cases"]}
    received = {}
    for case in value["cases"]:
        _keys(
            case,
            {"review_case_id", "identified_target", "axes", "incident_assessment"}
            | ({"timing"} if type(case) is dict and "timing" in case else set()),
            "case response",
        )
        identifier = case["review_case_id"]
        _require(
            type(identifier) is str and identifier in assigned and identifier not in received,
            "Foreign or duplicate case response",
        )
        documents = assigned[identifier]["documents"]
        target_status = _target(case["identified_target"], documents)
        incident_status = _incident(case["incident_assessment"], documents)
        _require(type(case["axes"]) is list, "Axes must be an array")
        axes = {}
        for row in case["axes"]:
            _require(
                type(row) is dict
                and type(row.get("axis_id")) is str
                and row["axis_id"] in AXES
                and row["axis_id"] not in axes,
                "Unknown or duplicate axis",
            )
            axes[row["axis_id"]] = {"status": _axis(row, documents), "response": deepcopy(row)}
        statuses = [target_status, incident_status] + [
            axes.get(a, {"status": "pending"})["status"] for a in AXES
        ]
        status = "pending" if "pending" in statuses else "submitted"
        if set(statuses) == {"unassessed"}:
            reasons = [
                case["identified_target"]["unassessed_reason"],
                case["incident_assessment"]["unassessed_reason"],
            ] + [axes[a]["response"]["unassessed_reason"] for a in AXES]
            status = "abstained" if set(reasons) == {"reviewer_abstention"} else "unassessed"
        timing_error = None
        try:
            _timing(case["timing"])
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            timing_error = {"type": type(exc).__name__, "message": str(exc)}
        received[identifier] = {
            "response": deepcopy(case),
            "status": status,
            "target_status": target_status,
            "incident_status": incident_status,
            "axes": axes,
            "timing_error": timing_error,
            "adjudication_status": "pending",
        }
    return received


def _account(packet: dict, received: dict) -> tuple[list[dict], dict]:
    counts = {
        "assigned_cases": len(packet["cases"]),
        "assigned_axes": 6 * len(packet["cases"]),
        "submitted_cases": 0,
        "pending_cases": 0,
        "unassessed_cases": 0,
        "abstained_cases": 0,
        "assessed_axes": 0,
        "unassessed_axes": 0,
        "pending_axes": 0,
        "timing_errors": 0,
    }
    cases = []
    for row in packet["cases"]:
        result = deepcopy(
            received.get(
                row["review_case_id"],
                {
                    "response": None,
                    "status": "pending",
                    "target_status": "pending",
                    "incident_status": "pending",
                    "axes": {},
                    "timing_error": None,
                    "adjudication_status": "pending",
                },
            )
        )
        counts[result["status"] + "_cases"] += 1
        counts["timing_errors"] += result["timing_error"] is not None
        for axis in AXES:
            counts[result["axes"].get(axis, {"status": "pending"})["status"] + "_axes"] += 1
        cases.append(
            {
                "review_case_id": row["review_case_id"],
                "attempt_sha256": row["attempt_sha256"],
                "scenario_family_id": row["scenario_family_id"],
                **result,
            }
        )
    return cases, counts


def import_incident_response(
    manifest_path: Path,
    response_path: Path,
    output_dir: Path,
    *,
    source_manifest_override: Path | None = None,
) -> dict:
    """Preserve invalid bytes/all opportunities; timing errors do not erase reports."""
    output_dir, manifest_path = Path(output_dir), Path(manifest_path)
    _new_directory(output_dir)
    _outside(output_dir, manifest_path.parent)
    packet, manifest, raw_manifest = validate_incident_packet(
        manifest_path, source_manifest_override=source_manifest_override
    )
    source_path = (
        Path(source_manifest_override)
        if source_manifest_override is not None
        else Path(manifest["source_manifest"])
    )
    _outside(output_dir, source_path.parent)
    raw_response = Path(response_path).read_bytes()
    errors, received = [], {}
    try:
        received = validate_incident_response(_object(raw_response), packet)
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError) as exc:
        errors.append({"type": type(exc).__name__, "message": str(exc)})
    cases, counts = _account(packet, received)
    receipt = {
        "schema_version": "healthcraft-operator-incident-receipt/v2",
        "status": "invalid_submission" if errors else "recorded",
        "packet_id": packet["packet_id"],
        "packet_sha256": manifest["packet_sha256"],
        "assignment_id": packet["assignment_id"],
        "operator_id": packet["operator_id"],
        "presentation": packet["presentation"],
        "manifest_sha256": manifest["manifest_sha256"],
        "response_sha256": _sha(raw_response),
        "protocol_sha256": _digest(packet["protocol"]),
        "errors": errors,
        "cases": cases,
        "counts": counts,
        "adjudication_status": "pending",
        "limitations": list(_LIMITATIONS),
    }
    payloads = {
        "submission.json": raw_response,
        "packet-manifest.json": raw_manifest,
        "receipt.json": _canonical(receipt) + b"\n",
    }
    _write_artifacts(
        output_dir,
        payloads,
        {
            "schema_version": "healthcraft-operator-incident-import/v2",
            "packet_sha256": manifest["packet_sha256"],
            "response_sha256": _sha(raw_response),
            "files": {name: _sha(raw) for name, raw in payloads.items()},
        },
    )
    return deepcopy(receipt)
