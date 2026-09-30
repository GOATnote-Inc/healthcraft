"""Separate human report-validity declarations from structural form acceptance.

This module records judgments; it does not generate a truth label, authenticate
reviewers, measure clinical performance, or establish reviewer independence.
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from pathlib import Path

from healthcraft.operator_review import (
    _canonical,
    _digest,
    _keys,
    _new_directory,
    _outside,
    _parse,
    _relative,
    _require,
    _resolve,
    _safe_id,
    _same,
    _sha,
    _text,
    _tree,
    _verify_files,
    _write_artifacts,
)

PACKET_VERSION = "healthcraft-operator-incident-adjudication-packet/v2"
RESPONSE_VERSION = "healthcraft-operator-incident-adjudication/v2"
CHECKS = (
    "target_attribution",
    "incident_accuracy_completeness",
    "evidence_support",
    "uncertainty_handling",
)
_REASONS = {"insufficient_evidence", "conflicting_evidence", "outside_scope", "reviewer_abstention"}
_SOURCE_DOCUMENTS = {"task", "scenario", "evidence", "runtime", "prior_judgments"}
_LIMITATIONS = [
    "Report-validity judgments are reviewer declarations, not software-generated truth.",
    "Qualifications and independence are declared, not authenticated by this workflow.",
    "Exposed development cases; no clinical validation, timing endpoint or superiority claim.",
]


def validity_rubric() -> dict:
    questions = (
        "Are requested and implicated record identities correctly attributed or unknown?",
        "Does the report identify material incidents without inventing or overlooking them?",
        "Do the cited source and report values support the claims?",
        "Are uncertainty, missing evidence and technical failures distinguished appropriately?",
    )
    return {
        "schema_version": "healthcraft-operator-report-validity-rubric/v2",
        "scope": "engineering_report_validity",
        "checks": [
            {"check_id": key, "question": question}
            for key, question in zip(CHECKS, questions, strict=True)
        ],
    }


def _blank_check(key: str) -> dict:
    return {
        "check_id": key,
        "judgment": None,
        "unassessed_reason": None,
        "rationale": "",
        "evidence_refs": [],
        "response_pointers": [],
    }


def adjudication_template(packet: dict) -> dict:
    """Create blank decisions without using evidence or report answers as labels."""
    return {
        "schema_version": RESPONSE_VERSION,
        **{key: packet[key] for key in ("packet_id", "assignment_id", "adjudicator_id", "role")},
        "packet_sha256": _digest(packet),
        "reviewer_declaration": {
            "independent_review": None,
            "qualifications": "",
            "conflicts": "",
        },
        "cases": [
            {
                "review_case_id": case["review_case_id"],
                "overall": None,
                "unassessed_reason": None,
                "rationale": "",
                "checks": [_blank_check(key) for key in CHECKS],
            }
            for case in packet["cases"]
        ],
    }


def _source_refs(refs, documents):
    _require(type(refs) is list, "Source references must be an array")
    seen = set()
    for ref in refs:
        _require(type(ref) is dict, "Invalid source reference")
        _keys(
            ref,
            {"document", "pointer"}
            | ({"decoded_json_pointer"} if "decoded_json_pointer" in ref else set()),
            "source reference",
        )
        document = ref["document"]
        _require(type(document) is str and document in _SOURCE_DOCUMENTS, "Unknown source document")
        _require(documents.get(document) is not None, "Source document is unavailable")
        value = _resolve(documents[document], ref["pointer"])
        if "decoded_json_pointer" in ref:
            _require(type(value) is str, "Decoded reference needs captured JSON text")
            from healthcraft.operator_incidents import _decode

            _resolve(_decode(value), ref["decoded_json_pointer"])
        identity = _digest(ref)
        _require(identity not in seen, "Duplicate source reference")
        seen.add(identity)


def _response_pointers(pointers, response):
    _require(type(pointers) is list, "Response pointers must be an array")
    seen = set()
    for pointer in pointers:
        _require(response is not None, "Operator response is unavailable")
        _resolve(response, pointer)
        _require(pointer not in seen, "Duplicate response pointer")
        seen.add(pointer)


def _check(row, documents):
    _keys(row, set(_blank_check("")), "validity check")
    _require(type(row["rationale"]) is str, "Check rationale must be text")
    _source_refs(row["evidence_refs"], documents)
    _response_pointers(row["response_pointers"], documents["response"])
    judgment, reason = row["judgment"], row["unassessed_reason"]
    _require(reason is None or (type(reason) is str and reason in _REASONS), "Invalid reason")
    if judgment is None:
        return "pending"
    _require(
        type(judgment) is str and judgment in {"supported", "unsupported", "unassessed"},
        "Invalid check judgment",
    )
    _text(row["rationale"], "Check rationale")
    if judgment == "unassessed":
        _require(reason in _REASONS, "An unassessed check requires a reason")
    else:
        _require(
            reason is None and bool(row["evidence_refs"]) and bool(row["response_pointers"]),
            "An assessed check needs source and report references, without an unassessed reason",
        )
    return judgment


def validate_adjudication_response(value: dict, packet: dict) -> dict:
    """Validate declarations and references without deciding whether claims are true.

    Null judgments can retain draft text and resolvable references. Missing
    cases/checks are pending opportunities; callers must account for the full
    packet roster independently of this received-case mapping.
    """
    _canonical(value)
    expected = adjudication_template(packet)
    _keys(value, set(expected), "adjudication response")
    for key in expected.keys() - {"cases", "reviewer_declaration"}:
        _require(_same(value[key], expected[key]), f"Adjudication {key} differs from assignment")
    declaration = value["reviewer_declaration"]
    _keys(declaration, set(expected["reviewer_declaration"]), "reviewer declaration")
    _require(
        declaration["independent_review"] is None
        or type(declaration["independent_review"]) is bool,
        "Independence declaration must be a boolean or unknown",
    )
    for key in ("qualifications", "conflicts"):
        _require(type(declaration[key]) is str, "Reviewer declarations must be text")
    _require(type(value["cases"]) is list, "Adjudications must be an array")
    assigned = {case["review_case_id"]: case for case in packet["cases"]}
    received = {}
    for row in value["cases"]:
        _keys(
            row, {"review_case_id", "overall", "unassessed_reason", "rationale", "checks"}, "case"
        )
        identifier = row["review_case_id"]
        _require(type(identifier) is str and identifier in assigned, "Foreign adjudicated case")
        _require(identifier not in received, "Duplicate adjudicated case")
        _require(type(row["checks"]) is list, "Checks must be an array")
        statuses = {}
        for check in row["checks"]:
            _require(
                type(check) is dict
                and type(check.get("check_id")) is str
                and check["check_id"] in CHECKS,
                "Unknown validity check",
            )
            key = check["check_id"]
            _require(key not in statuses, "Duplicate validity check")
            statuses[key] = _check(check, assigned[identifier]["documents"])
        checks = {key: statuses.get(key, "pending") for key in CHECKS}
        overall, reason = row["overall"], row["unassessed_reason"]
        _require(type(row["rationale"]) is str, "Overall rationale must be text")
        _require(reason is None or (type(reason) is str and reason in _REASONS), "Invalid reason")
        status = "pending"
        if overall is not None:
            _require(
                type(overall) is str and overall in {"valid", "invalid", "unassessed"},
                "Invalid overall decision",
            )
            _require("pending" not in checks.values(), "Overall decision requires all four checks")
            _text(row["rationale"], "Overall rationale")
            if overall == "valid":
                _require(
                    all(x == "supported" for x in checks.values()),
                    "Valid decision contradicts checks",
                )
                _require(
                    assigned[identifier]["operator_report_status"] != "pending",
                    "Unfinished report cannot be valid",
                )
            elif overall == "invalid":
                _require(
                    "unsupported" in checks.values(), "Invalid decision needs an unsupported check"
                )
            else:
                _require(
                    "unassessed" in checks.values() and "unsupported" not in checks.values(),
                    "Unassessed decision contradicts checks",
                )
            if overall == "unassessed":
                _require(reason in _REASONS, "Unassessed decision needs a reason")
                status = "abstained" if reason == "reviewer_abstention" else "unassessed"
            else:
                _require(reason is None, "Assessed overall decision cannot have unassessed reason")
                status = "declared"
        received[identifier] = {
            "status": status,
            "decision": overall,
            "checks": checks,
            "response": deepcopy(row),
        }
    return received


def _implementation() -> dict:
    root = Path(__file__).resolve().parent
    names = (
        "operator_adjudication.py",
        "operator_incidents.py",
        "operator_incident_report.py",
        "operator_review.py",
    )
    return {"src/healthcraft/" + name: _sha((root / name).read_bytes()) for name in names}


def _render(packet, template):
    from healthcraft.operator_incident_report import render_adjudication_packet

    return render_adjudication_packet(deepcopy(packet), deepcopy(template))


def _packet_contract(packet):
    _canonical(packet)
    _keys(
        packet,
        {
            "schema_version",
            "packet_id",
            "assignment_id",
            "adjudicator_id",
            "role",
            "protocol",
            "operator_packet_sha256",
            "operator_response_sha256",
            "validity_rubric",
            "cases",
            "limitations",
        },
        "adjudication packet",
    )
    _require(packet["schema_version"] == PACKET_VERSION, "Unknown adjudication packet version")
    for key in ("packet_id", "assignment_id", "adjudicator_id"):
        _safe_id(packet[key])
    _require(packet["role"] in ("initial", "resolver"), "Unknown review role")
    _keys(packet["protocol"], {"protocol_id", "purpose"}, "protocol")
    _text(packet["protocol"]["protocol_id"], "Protocol ID")
    _require(
        packet["protocol"]["purpose"] == "engineering_development",
        "Only development review is supported",
    )
    _require(_same(packet["validity_rubric"], validity_rubric()), "Validity rubric changed")
    for key in ("operator_packet_sha256", "operator_response_sha256"):
        value = packet[key]
        _require(
            type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value),
            "Invalid source identity",
        )
    _require(type(packet["cases"]) is list and bool(packet["cases"]), "Missing assigned reports")
    seen = set()
    for case in packet["cases"]:
        _keys(
            case,
            {"review_case_id", "scenario_family_id", "operator_report_status", "documents"},
            "report opportunity",
        )
        _safe_id(case["review_case_id"])
        _require(case["review_case_id"].casefold() not in seen, "Duplicate report opportunity")
        seen.add(case["review_case_id"].casefold())
        if case["scenario_family_id"] is not None:
            _text(case["scenario_family_id"], "Scenario family")
        _require(
            case["operator_report_status"]
            in ("pending", "submitted", "unassessed", "abstained", "invalid_submission"),
            "Invalid report status",
        )
        _keys(case["documents"], _SOURCE_DOCUMENTS | {"response"}, "review documents")
        for key, value in case["documents"].items():
            _require(
                value is None
                or type(value) is dict
                or (key == "prior_judgments" and type(value) is list),
                "Invalid document value",
            )
        if packet["role"] == "initial":
            _require(
                case["documents"]["prior_judgments"] is None,
                "Initial reviewer must not receive prior judgments",
            )
    _require(type(packet["limitations"]) is list, "Limitations must be an array")
    for item in packet["limitations"]:
        _text(item, "Limitation")


def _issue_packet(packet, output_dir, *, source_bindings=None, coordinator_files=None):
    output = Path(output_dir)
    _new_directory(output)
    _packet_contract(packet)
    implementation = _implementation()
    template = adjudication_template(packet)
    payloads = {
        "public/packet.json": _canonical(packet) + b"\n",
        "public/response-template.json": _canonical(template) + b"\n",
        "public/report.html": _render(packet, template).encode("utf-8"),
    }
    bindings = deepcopy(source_bindings or {})
    for name, raw in (coordinator_files or {}).items():
        _relative(name)
        _require(
            name.startswith("coordinator/") and type(raw) is bytes, "Invalid coordinator attachment"
        )
        payloads[name] = raw
    if coordinator_files:
        bindings["coordinator_files"] = {name: _sha(raw) for name, raw in coordinator_files.items()}
    manifest = {
        "schema_version": "healthcraft-operator-adjudication-manifest/v2",
        "packet_sha256": _digest(packet),
        "source_bindings": bindings,
        "implementation_sha256": implementation,
        "files": {name: _sha(raw) for name, raw in payloads.items()},
    }
    _coordinator_bindings(packet, payloads, bindings)
    _require(
        _same(implementation, _implementation()), "Implementation changed while issuing packet"
    )
    _write_artifacts(output, payloads, manifest)
    return deepcopy(packet)


def _packet_manifest(packet, manifest):
    _keys(
        manifest,
        {"schema_version", "packet_sha256", "source_bindings", "implementation_sha256", "files"},
        "adjudication manifest",
    )
    _require(
        manifest["schema_version"] == "healthcraft-operator-adjudication-manifest/v2",
        "Unknown adjudication manifest",
    )
    _require(manifest["packet_sha256"] == _digest(packet), "Adjudication packet identity changed")
    _require(
        _same(manifest["implementation_sha256"], _implementation()),
        "Use the issuing implementation",
    )
    _require(type(manifest["source_bindings"]) is dict, "Invalid source bindings")
    payloads = {
        "public/packet.json": _canonical(packet) + b"\n",
        "public/response-template.json": _canonical(adjudication_template(packet)) + b"\n",
        "public/report.html": _render(packet, adjudication_template(packet)).encode("utf-8"),
    }
    expected = {name: _sha(raw) for name, raw in payloads.items()}
    attachments = manifest["source_bindings"].get("coordinator_files", {})
    _require(type(attachments) is dict, "Invalid coordinator inventory")
    for name, value in attachments.items():
        _relative(name)
        _require(
            name.startswith("coordinator/"),
            "Coordinator data must be separate from public presentation",
        )
        expected[name] = value
    _require(_same(manifest["files"], expected), "Issued presentation differs from packet")


def validate_adjudication_packet(manifest_path):
    manifest_path = Path(manifest_path)
    _require(manifest_path.name == "manifest.json", "Expected manifest.json")
    raw = _tree(manifest_path.parent)
    manifest = _parse(raw["manifest.json"].decode("utf-8"))
    _verify_files(raw, manifest["files"])
    packet = _parse(raw["public/packet.json"].decode("utf-8"))
    _packet_contract(packet)
    _packet_manifest(packet, manifest)
    _coordinator_bindings(packet, raw, manifest["source_bindings"])
    return packet, manifest, raw["manifest.json"]


def _received_operator(operator, raw):
    from healthcraft.operator_incidents import validate_incident_response

    received, errors = {}, []
    try:
        received = validate_incident_response(_parse(raw.decode("utf-8")), operator)
    except (ValueError, UnicodeError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    return received, errors


def _source_cases(operator, received, errors):
    cases = []
    for case in operator["cases"]:
        incoming = received.get(case["review_case_id"])
        cases.append(
            {
                "review_case_id": case["review_case_id"],
                "scenario_family_id": case["scenario_family_id"],
                "operator_report_status": incoming["status"]
                if incoming
                else ("invalid_submission" if errors else "pending"),
                "documents": {
                    **deepcopy(case["documents"]),
                    "response": deepcopy(incoming["response"]) if incoming else None,
                    "prior_judgments": None,
                },
            }
        )
    return cases


def _coordinator_bindings(packet, raw, bindings):
    required = {
        "coordinator/operator-packet.json",
        "coordinator/operator-response.json",
        "coordinator/operator-manifest.json",
        "coordinator/operator-validation.json",
    }
    _require(required <= set(raw), "Original coordinator snapshots are required")
    _require(
        bindings.get("operator_manifest_sha256") == _sha(raw["coordinator/operator-manifest.json"]),
        "Original operator manifest changed",
    )
    _require(
        bindings.get("operator_response_sha256") == packet["operator_response_sha256"],
        "Original response binding changed",
    )
    _require(
        _sha(raw["coordinator/operator-response.json"]) == packet["operator_response_sha256"],
        "Original operator submission changed",
    )
    original = _parse(raw["coordinator/operator-packet.json"].decode("utf-8"))
    _require(
        _digest(original) == packet["operator_packet_sha256"],
        "Original operator packet changed",
    )
    _require(_same(packet["protocol"], original["protocol"]), "Original protocol changed")
    _require(
        packet["adjudicator_id"].casefold() != original["operator_id"].casefold(),
        "The declared operator cannot adjudicate their own report",
    )
    received, errors = _received_operator(original, raw["coordinator/operator-response.json"])
    expected = _source_cases(original, received, errors)
    actual = deepcopy(packet["cases"])
    if packet["role"] == "resolver":
        ids = {case["review_case_id"] for case in actual}
        expected = [case for case in expected if case["review_case_id"] in ids]
        for case in actual:
            case["documents"]["prior_judgments"] = None
    _require(
        _same(actual, expected),
        "Displayed report, source documents or roster differ from the original submission",
    )
    _require(
        _same(
            _parse(raw["coordinator/operator-validation.json"].decode("utf-8")),
            {"errors": errors},
        ),
        "Operator validation snapshot changed",
    )

    if packet["role"] == "resolver":
        _resolver_sources(packet, raw, bindings, _source_cases(original, received, errors))


def _resolver_sources(packet, raw, bindings, source_cases):
    prior = bindings.get("prior_record_sha256")
    _require(type(prior) is dict and len(prior) >= 2, "Missing bound initial judgments")
    loaded, identities = {}, {}
    for reviewer, expected in prior.items():
        _safe_id(reviewer)
        _require(
            reviewer.casefold() != packet["adjudicator_id"].casefold(),
            "Resolver cannot be an initial reviewer",
        )
        if expected is None:
            loaded[reviewer], identities[reviewer] = None, None
            continue
        prefix = f"coordinator/prior/{reviewer}/"
        snapshot = {
            name[len(prefix) :]: value for name, value in raw.items() if name.startswith(prefix)
        }
        other, receipt, identity = _record_from_raw(snapshot)
        _require(identity == expected, "Original initial import changed")
        _require(
            other["role"] == "initial" and other["adjudicator_id"] == reviewer,
            "Wrong initial reviewer snapshot",
        )
        _require(
            _same(_context(packet), _context(other)), "Initial judgments concern another report"
        )
        _require(
            [row["review_case_id"] for row in other["cases"]]
            == [row["review_case_id"] for row in source_cases],
            "Initial roster changed",
        )
        loaded[reviewer], identities[reviewer] = receipt, identity
    full = {**packet, "cases": source_cases}
    eligible = [row for row in _initial_cases(full, loaded) if _resolvable(row)]
    _require(
        [row["review_case_id"] for row in packet["cases"]]
        == [row["review_case_id"] for row in eligible],
        "Resolver roster differs from bound initial disputes",
    )
    for case, row in zip(packet["cases"], eligible, strict=True):
        expected = [
            {**item, "record_sha256": identities[item["adjudicator_id"]]}
            for item in row["initial_judgments"]
        ]
        _require(
            _same(case["documents"]["prior_judgments"], expected),
            "Displayed prior judgments differ from original initial submissions",
        )


def _protect_sources(output, raw, bindings=None):
    """Never add an output directory inside an original immutable source tree."""
    for name, content in raw.items():
        if name.endswith("operator-manifest.json"):
            source = _parse(content.decode("utf-8")).get("source_manifest")
            if source is not None:
                _outside(output, Path(source).parent)
        if name.endswith("packet-manifest.json"):
            nested = _parse(content.decode("utf-8")).get("source_bindings", {})
            for root in nested.get("protected_roots", []):
                _outside(output, Path(root))
    for root in (bindings or {}).get("protected_roots", []):
        _outside(output, Path(root))


def _operator_inputs(manifest_path, response_path, *, source_manifest_override=None):
    from healthcraft.operator_incidents import validate_incident_packet

    packet, _, raw_manifest = validate_incident_packet(
        manifest_path, source_manifest_override=source_manifest_override
    )
    raw = Path(response_path).read_bytes()
    received, errors = _received_operator(packet, raw)
    return packet, raw, received, raw_manifest, errors


def build_adjudication_packet(
    operator_manifest,
    response_path,
    output_dir,
    *,
    assignment,
    source_manifest_override=None,
    prior_records=None,
):
    """Issue a separate blank review tied to exact operator submission bytes."""
    output = Path(output_dir)
    _new_directory(output)
    _outside(output, Path(operator_manifest).parent)
    _keys(assignment, {"assignment_id", "adjudicator_id", "role"}, "review assignment")
    for key in ("assignment_id", "adjudicator_id"):
        _safe_id(assignment[key])
    _require(assignment["role"] in ("initial", "resolver"), "Unknown review role")
    if assignment["role"] == "initial":
        _require(
            prior_records is None, "Initial assignment must not include other reviewers' judgments"
        )
    else:
        _require(
            type(prior_records) is dict and len(prior_records) >= 2,
            "A resolver needs an explicit initial reviewer roster",
        )
        _require(
            assignment["adjudicator_id"].casefold()
            not in {key.casefold() for key in prior_records},
            "An initial reviewer cannot resolve their own disagreement",
        )
    operator, raw, received, raw_manifest, errors = _operator_inputs(
        operator_manifest,
        response_path,
        source_manifest_override=source_manifest_override,
    )
    _require(
        assignment["adjudicator_id"].casefold() != operator["operator_id"].casefold(),
        "The declared operator cannot independently adjudicate their own report",
    )
    cases = _source_cases(operator, received, errors)
    packet = {
        "schema_version": PACKET_VERSION,
        "packet_id": uuid.uuid4().hex,
        **deepcopy(assignment),
        "protocol": deepcopy(operator["protocol"]),
        "operator_packet_sha256": _digest(operator),
        "operator_response_sha256": _sha(raw),
        "validity_rubric": validity_rubric(),
        "cases": cases,
        "limitations": list(_LIMITATIONS),
    }
    bindings = {
        "operator_manifest_sha256": _sha(raw_manifest),
        "operator_response_sha256": _sha(raw),
        "protected_roots": [str(Path(operator_manifest).parent.resolve())],
    }
    if source_manifest_override is not None:
        bindings["protected_roots"].append(str(Path(source_manifest_override).parent.resolve()))
    attachments = {
        "coordinator/operator-packet.json": _canonical(operator) + b"\n",
        "coordinator/operator-response.json": raw,
        "coordinator/operator-manifest.json": raw_manifest,
        "coordinator/operator-validation.json": _canonical({"errors": errors}) + b"\n",
    }
    _protect_sources(output, attachments, bindings)
    if assignment["role"] == "resolver":
        loaded, identities = _assigned_records(packet, prior_records, output)
        eligible = _initial_cases(packet, loaded)
        selected = {row["review_case_id"]: row for row in eligible if _resolvable(row)}
        _require(bool(selected), "No complete disputed reports are available for resolution")
        packet["cases"] = [case for case in cases if case["review_case_id"] in selected]
        for case in packet["cases"]:
            case["documents"]["prior_judgments"] = [
                {**row, "record_sha256": identities[row["adjudicator_id"]]}
                for row in selected[case["review_case_id"]]["initial_judgments"]
            ]
        bindings["prior_record_sha256"] = identities
        for reviewer, path in prior_records.items():
            if path is not None:
                for name, content in _tree(Path(path).parent).items():
                    attachments[f"coordinator/prior/{reviewer}/{name}"] = content
    return _issue_packet(packet, output, source_bindings=bindings, coordinator_files=attachments)


def _receipt(packet, raw, manifest):
    received, errors, declaration = {}, [], None
    try:
        value = _parse(raw.decode("utf-8"))
        received = validate_adjudication_response(value, packet)
        declaration = deepcopy(value["reviewer_declaration"])
    except (ValueError, UnicodeError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    counts = {
        "assigned": len(packet["cases"]),
        "declared": 0,
        "pending": 0,
        "unassessed": 0,
        "abstained": 0,
    }
    cases = []
    for case in packet["cases"]:
        row = deepcopy(
            received.get(
                case["review_case_id"],
                {
                    "status": "pending",
                    "decision": None,
                    "checks": {key: "pending" for key in CHECKS},
                    "response": None,
                },
            )
        )
        counts[row["status"]] += 1
        cases.append({"review_case_id": case["review_case_id"], **row})
    return {
        "schema_version": "healthcraft-operator-adjudication-receipt/v2",
        "status": "invalid_submission" if errors else "recorded",
        **{
            key: packet[key]
            for key in (
                "packet_id",
                "assignment_id",
                "adjudicator_id",
                "role",
                "operator_packet_sha256",
                "operator_response_sha256",
            )
        },
        "packet_sha256": _digest(packet),
        "response_sha256": _sha(raw),
        "validity_rubric_sha256": _digest(packet["validity_rubric"]),
        "source_manifest_sha256": _sha(manifest),
        "reviewer_declaration": declaration,
        "errors": errors,
        "counts": counts,
        "cases": cases,
        "clinical_validation": "not_established",
        "limitations": list(_LIMITATIONS),
    }


def import_adjudication_response(manifest_path, response_path, output_dir):
    """Retain raw decisions and all assigned opportunities, including invalid input."""
    output = Path(output_dir)
    _new_directory(output)
    _outside(output, Path(manifest_path).parent)
    packet, issued, raw_manifest = validate_adjudication_packet(manifest_path)
    _protect_sources(output, _tree(Path(manifest_path).parent), issued["source_bindings"])
    raw = Path(response_path).read_bytes()
    receipt = _receipt(packet, raw, raw_manifest)
    payloads = {
        "submission.json": raw,
        "packet.json": _canonical(packet) + b"\n",
        "packet-manifest.json": raw_manifest,
        "receipt.json": _canonical(receipt) + b"\n",
    }
    payloads.update(
        {
            name: raw
            for name, raw in _tree(Path(manifest_path).parent).items()
            if name.startswith("coordinator/")
        }
    )
    manifest = {
        "schema_version": "healthcraft-operator-adjudication-import/v2",
        "files": {name: _sha(value) for name, value in payloads.items()},
    }
    _write_artifacts(output, payloads, manifest)
    return deepcopy(receipt)


def _load_record(manifest_path):
    path = Path(manifest_path)
    _require(path.name == "manifest.json", "Expected import manifest.json")
    return _record_from_raw(_tree(path.parent))


def _record_from_raw(raw):
    manifest = _parse(raw["manifest.json"].decode("utf-8"))
    _keys(manifest, {"schema_version", "files"}, "adjudication import manifest")
    _require(
        manifest["schema_version"] == "healthcraft-operator-adjudication-import/v2",
        "Unknown adjudication import",
    )
    _verify_files(raw, manifest["files"])
    packet = _parse(raw["packet.json"].decode("utf-8"))
    _packet_contract(packet)
    issued = _parse(raw["packet-manifest.json"].decode("utf-8"))
    _packet_manifest(packet, issued)
    attachments = issued["source_bindings"].get("coordinator_files", {})
    _require(
        set(manifest["files"])
        == {"submission.json", "packet.json", "packet-manifest.json", "receipt.json"}
        | set(attachments),
        "Unexpected adjudication import files",
    )
    _require(
        all(_sha(raw[name]) == value for name, value in attachments.items()),
        "Coordinator snapshot differs from issued packet",
    )
    _coordinator_bindings(packet, raw, issued["source_bindings"])
    receipt = _receipt(packet, raw["submission.json"], raw["packet-manifest.json"])
    _require(
        _same(receipt, _parse(raw["receipt.json"].decode("utf-8"))),
        "Recorded judgments disagree with raw submission",
    )
    return packet, receipt, _sha(raw["manifest.json"])


def _context(packet):
    return {
        key: packet[key]
        for key in (
            "protocol",
            "operator_packet_sha256",
            "operator_response_sha256",
            "validity_rubric",
        )
    }


def _agreement(rows):
    statuses = {row["status"] for row in rows}
    decisions = {row["decision"] for row in rows if row["status"] == "declared"}
    if len(decisions) > 1:
        return "disputed"
    if "pending" in statuses:
        return "pending"
    if statuses == {"abstained"}:
        return "abstained"
    if statuses != {"declared"}:
        return "unassessed"
    return "agreed_" + next(iter(decisions))


def _assigned_records(packet, records, output):
    _require(
        type(records) is dict and bool(records), "Explicit assigned reviewer roster is required"
    )
    loaded, identities, seen = {}, {}, set()
    case_ids = [row["review_case_id"] for row in packet["cases"]]
    for reviewer, path in records.items():
        _safe_id(reviewer)
        _require(reviewer.casefold() not in seen, "Ambiguous assigned reviewer")
        seen.add(reviewer.casefold())
        if path is None:
            loaded[reviewer], identities[reviewer] = None, None
            continue
        _outside(output, Path(path).parent)
        _protect_sources(output, _tree(Path(path).parent))
        other, receipt, identity = _load_record(path)
        _require(
            other["role"] == "initial" and other["adjudicator_id"] == reviewer,
            "Record does not match its assigned initial reviewer",
        )
        _require(
            _same(_context(packet), _context(other)),
            "Judgments concern different reports or rubrics",
        )
        _require(
            [row["review_case_id"] for row in other["cases"]] == case_ids,
            "Adjudication roster differs",
        )
        _require(
            identity not in {value for value in identities.values() if value},
            "Duplicate adjudication record",
        )
        loaded[reviewer], identities[reviewer] = receipt, identity
    return loaded, identities


def _initial_cases(packet, loaded):
    cases = []
    for case in packet["cases"]:
        case_id = case["review_case_id"]
        rows = []
        for reviewer, receipt in loaded.items():
            row = (
                next((row for row in receipt["cases"] if row["review_case_id"] == case_id), None)
                if receipt
                else None
            )
            rows.append(
                {
                    "adjudicator_id": reviewer,
                    **deepcopy(
                        row
                        or {
                            "review_case_id": case_id,
                            "status": "pending",
                            "decision": None,
                            "response": None,
                        }
                    ),
                }
            )
        cases.append(
            {
                "review_case_id": case_id,
                "status": _agreement(rows),
                "initial_judgments": rows,
                "resolved_decision": None,
            }
        )
    return cases


def _resolvable(case):
    return case["status"] == "disputed" and all(
        row["status"] != "pending" for row in case["initial_judgments"]
    )


def summarize_adjudications(reference_manifest, records, output_dir, *, resolver_record=None):
    """Account for explicitly assigned reviewers; disagreement is never a vote."""
    output = Path(output_dir)
    _new_directory(output)
    _outside(output, Path(reference_manifest).parent)
    packet, reference, _ = validate_adjudication_packet(reference_manifest)
    _protect_sources(output, _tree(Path(reference_manifest).parent), reference["source_bindings"])
    _require(packet["role"] == "initial", "Use an initial assignment as the reference roster")
    loaded, identities = _assigned_records(packet, records, output)
    cases = _initial_cases(packet, loaded)
    counts = {"declared": 0, "pending": 0, "unassessed": 0, "abstained": 0}
    for case in cases:
        for row in case["initial_judgments"]:
            counts[row["status"]] += 1
    resolution = None
    if resolver_record is not None:
        _outside(output, Path(resolver_record).parent)
        _protect_sources(output, _tree(Path(resolver_record).parent))
        resolver, receipt, identity = _load_record(resolver_record)
        _require(resolver["role"] == "resolver", "Resolution needs a resolver assignment")
        _require(
            resolver["adjudicator_id"].casefold() not in {key.casefold() for key in records},
            "An initial reviewer cannot resolve their disagreement",
        )
        _require(
            _same(_context(packet), _context(resolver)),
            "Resolution concerns another report or rubric",
        )
        issued = _parse((Path(resolver_record).parent / "packet-manifest.json").read_text())
        _require(
            _same(issued["source_bindings"].get("prior_record_sha256"), identities),
            "Resolution is bound to different initial submissions",
        )
        eligible = [case for case in cases if _resolvable(case)]
        _require(
            [case["review_case_id"] for case in resolver["cases"]]
            == [case["review_case_id"] for case in eligible],
            "Resolver roster differs from complete disputes",
        )
        for case, source, row in zip(eligible, resolver["cases"], receipt["cases"], strict=True):
            expected = [
                {**item, "record_sha256": identities[item["adjudicator_id"]]}
                for item in case["initial_judgments"]
            ]
            _require(
                _same(source["documents"]["prior_judgments"], expected),
                "Resolver received different initial judgments",
            )
            case["resolver_judgment"] = deepcopy(row)
            if row["status"] == "declared":
                case["status"] = "resolved_" + row["decision"]
                case["resolved_decision"] = row["decision"]
        resolution = {
            "adjudicator_id": resolver["adjudicator_id"],
            "record_sha256": identity,
            "assigned_opportunities": len(eligible),
            "counts": receipt["counts"],
            "reviewer_declaration": receipt["reviewer_declaration"],
        }
    result = {
        "schema_version": "healthcraft-operator-adjudication-summary/v2",
        **_context(packet),
        "assigned_reviewers": list(records),
        "assigned_opportunities": len(records) * len(packet["cases"]),
        "counts": counts,
        "resolution": resolution,
        "record_sha256": identities,
        "cases": cases,
        "reviewer_declarations": {
            key: value["reviewer_declaration"] if value else None for key, value in loaded.items()
        },
        "clinical_validation": "not_established",
        "limitations": list(_LIMITATIONS),
    }
    raw = _canonical(result) + b"\n"
    _write_artifacts(
        output,
        {"summary.json": raw},
        {
            "schema_version": "healthcraft-operator-adjudication-summary-manifest/v2",
            "files": {"summary.json": _sha(raw)},
        },
    )
    return deepcopy(result)
