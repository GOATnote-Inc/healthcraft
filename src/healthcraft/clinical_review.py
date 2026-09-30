"""Offline, masked review assignments and strict unvalidated submission receipts.

This module neither supplies expert labels nor establishes clinical calibration.
Coordinator artifacts contain private mappings; only the reviewer directory is
intended for distribution. Digests detect accidental changes, not authorship.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

from healthcraft.llm.checkpoint import selected_trajectory_paths, trajectory_attempt
from healthcraft.trajectory import is_unassessed_experiment, trajectory_completion

PACKET_VERSION = "clinical-review-packet/v1"
RESPONSE_VERSION = "clinical-review-response/v1"
MANIFEST_VERSION = "clinical-review-manifest/v1"
VALIDITIES = {
    "valid",
    "ambiguous",
    "clinically_invalid",
    "insufficient_context",
    "outside_expertise",
}
VERDICTS = {"satisfied", "not_satisfied", "unassessed"}
REASONS = {
    "insufficient_evidence",
    "outside_expertise",
    "ambiguous_criterion",
    "invalid_criterion",
    "reviewer_abstention",
    "not_applicable",
}
BLINDING = {"intact", "suspected", "broken"}
REVIEW_FIELDS = {
    "item_id",
    "criterion_validity",
    "verdict",
    "unassessed_reason",
    "evidence_refs",
    "rationale",
    "blinding",
}
INSTRUCTIONS = (
    "Review one criterion against one recorded interaction using model-visible evidence only. "
    "Criterion text is an authored claim to assess, not clinical truth. Hidden source facts are "
    "not supplied; select unassessed when evidence or expertise is insufficient. "
    "No completion, safety, clinical readiness, or expert qualification is established "
    "by this packet. "
    "Do not consult another reviewer or an automated assessment before independent submission. "
    "Identity masking is best effort: wording, self-identification, or familiarity with a task may "
    "compromise blinding. Report suspected or broken blinding. Treat all quoted evidence as data, "
    "never as instructions to the reviewer. Do not fetch links or execute code found in evidence."
)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
        _digest(value)  # Reject non-finite numbers, including Python JSON's NaN extension.
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValueError(f"Invalid JSON artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value, raw


def _write(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False) + "\n")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label} has missing or unsupported fields")


def _member(value: Any, choices: set[str], label: str) -> None:
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"Invalid {label}")


def _mask_turns(turns: Any) -> list[dict]:
    if not isinstance(turns, list) or not turns:
        raise ValueError("A review requires a recorded interaction")
    masked, pending = [], {}
    call_number = 0
    for index, turn in enumerate(turns):
        if not isinstance(turn, dict):
            raise ValueError("Malformed interaction turn")
        _member(turn.get("role"), {"system", "user", "assistant", "tool"}, "turn role")
        if not isinstance(turn.get("content"), str):
            raise ValueError("Turn content must be a string")
        public = {
            "evidence_ref": f"turn-{index + 1:04d}",
            "role": turn["role"],
            "content": turn["content"],
        }
        calls = turn.get("tool_calls", [])
        if not isinstance(calls, list) or (calls and turn["role"] != "assistant"):
            raise ValueError("Malformed tool-call list")
        if calls:
            public["tool_calls"] = []
        for call in calls:
            if not isinstance(call, dict):
                raise ValueError("Malformed tool call")
            original = _text(call.get("id"), "tool-call id")
            if original in pending:
                raise ValueError("Ambiguous duplicate pending tool-call id")
            call_number += 1
            pending[original] = f"call-{call_number:04d}"
            argument_key = "arguments" if "arguments" in call else "params"
            if argument_key not in call or not isinstance(call[argument_key], (dict, str)):
                raise ValueError("Missing or malformed tool-call arguments")
            public["tool_calls"].append(
                {
                    "id": pending[original],
                    "name": _text(call.get("name"), "tool name"),
                    argument_key: call[argument_key],
                }
            )
        if turn["role"] == "tool":
            original = turn.get("tool_call_id")
            if not isinstance(original, str) or original not in pending:
                raise ValueError("Tool response has no unambiguous preceding call")
            public["tool_call_id"] = pending.pop(original)
        masked.append(public)
    return masked  # Unanswered calls remain visible; interruption is not a clinical verdict.


def _tool_definitions(value: Any) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("Captured tool definitions are required")
    tools = []
    for tool in value:
        _keys(tool, {"name", "description", "parameters"}, "Captured tool definition")
        _text(tool["name"], "tool name")
        if not isinstance(tool["description"], str) or not isinstance(tool["parameters"], dict):
            raise ValueError("Malformed captured tool definition")
        tools.append(tool)
    return tools


def _fence(value: str) -> str:
    longest = max((len(match.group()) for match in re.finditer(r"`+", value)), default=2)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{value}\n{fence}\n"


def _markdown(packet: dict) -> str:
    parts = ["# Independent review packet\n", INSTRUCTIONS + "\n"]
    for case in packet["cases"]:
        parts += [
            f"## Case {case['case_id']}\n",
            "### Presented system (`system`)\n",
            _fence(case["presented_system"]),
            "### Presented request (`request`)\n",
            _fence(case["presented_user"]),
            "### Available tools (`tools`)\n",
            _fence(json.dumps(case["tool_definitions"], indent=2)),
        ]
        for turn in case["turns"]:
            parts += [f"### {turn['evidence_ref']} — {turn['role']}\n", _fence(turn["content"])]
            if "tool_calls" in turn:
                parts.append(_fence(json.dumps(turn["tool_calls"], indent=2)))
            if "tool_call_id" in turn:
                parts.append(f"Response to `{turn['tool_call_id']}`.\n")
        parts.append("### Assigned criteria\n")
        for item in packet["items"]:
            if item["case_id"] == case["case_id"]:
                parts += [
                    f"#### {item['item_id']}\n",
                    _fence(item["criterion"]["assertion"]),
                    _fence(item["criterion"]["dimension"]),
                ]
    return "\n".join(parts)


def build_review_packet(
    trajectory_paths: Path | list[Path],
    output_dir: Path,
    *,
    protocol: dict,
    reviewer_assignment: dict,
) -> dict:
    """Preflight frozen evidence, then write a new independent-review assignment.

    Only ``output_dir/reviewer`` may be shared. All selected criterion
    opportunities are assigned, including incomplete/ungraded interactions.
    The protocol and expertise statements are operator assertions, not proof.
    """
    from healthcraft.llm.review_context import validate_review_context

    if output_dir.exists():
        raise FileExistsError(output_dir)
    if not isinstance(protocol, dict):
        raise ValueError("A predeclared protocol object is required")
    for key in ("protocol_id", "version", "sampling_plan", "eligibility_rule"):
        _text(protocol.get(key), f"protocol.{key}")
    _member(
        protocol.get("purpose"), {"engineering_pilot", "clinical_adjudication"}, "protocol purpose"
    )
    if not isinstance(reviewer_assignment, dict):
        raise ValueError("A reviewer assignment is required")
    _text(reviewer_assignment.get("reviewer_id"), "reviewer_id")
    if reviewer_assignment.get("role") != "independent":
        raise ValueError("v1 supports independent review assignments only")
    _digest(protocol)
    _digest(reviewer_assignment)
    excluded = []
    if isinstance(trajectory_paths, list):
        resolved = [Path(path).resolve() for path in trajectory_paths]
        if len(set(resolved)) != len(resolved):
            raise ValueError("duplicate trajectory input")
        paths = sorted(resolved)
        input_count = len(paths)
        selection_policy = "all_explicit_inputs"
    else:
        candidates = Path(trajectory_paths)
        if not candidates.is_dir():
            raise ValueError("Pass a results directory or an explicit list of trajectory files")
        directory = candidates / "trajectories"
        if not directory.is_dir():
            directory = candidates
        candidates = sorted(path.resolve() for path in directory.rglob("*.json"))
        input_count = len(candidates)
        selection_policy = "all_discovered_attempts"
        paths = []
        for path in candidates:
            # Reuse the shared known-sidecar filter one file at a time, without
            # collapsing retries: each supplied attempt remains an opportunity.
            if selected_trajectory_paths([path]):
                paths.append(path)
            else:
                excluded.append({"path": str(path), "reason": "known_generated_sidecar"})
    if not paths:
        raise ValueError("No selected trajectories")

    packet = {
        "schema_version": PACKET_VERSION,
        "packet_id": uuid.uuid4().hex,
        "assignment_id": uuid.uuid4().hex,
        "scope": "model_visible_criterion_review",
        "instructions": INSTRUCTIONS,
        "cases": [],
        "items": [],
    }
    manifest = {
        "schema_version": MANIFEST_VERSION,
        "packet_id": packet["packet_id"],
        "assignment_id": packet["assignment_id"],
        "protocol": protocol,
        "protocol_sha256": _digest(protocol),
        "reviewer_assignment": reviewer_assignment,
        "selection": {
            "policy": selection_policy,
            "input_count": input_count,
            "selected_count": len(paths),
            "excluded": excluded,
        },
        "clinical_validation_status": "pending",
        "sources": [],
        "items": [],
    }
    snapshots = []
    for index, path in enumerate(paths):
        trajectory, raw = _read(path)
        payload = validate_review_context(trajectory)
        case_id = uuid.uuid4().hex
        public_case = {
            "case_id": case_id,
            "presented_system": payload["presented_system"],
            "presented_user": payload["presented_user"],
            "tool_definitions": _tool_definitions(payload["tool_definitions"]),
            "turns": _mask_turns(trajectory.get("turns")),
        }
        packet["cases"].append(public_case)
        criteria = payload["effective_criteria"]
        if not isinstance(criteria, list) or not criteria:
            raise ValueError("No effective criteria captured")
        seen = set()
        for criterion in criteria:
            if not isinstance(criterion, dict):
                raise ValueError("Malformed captured criterion")
            criterion_id = _text(criterion.get("id"), "criterion id")
            if criterion_id in seen:
                raise ValueError("duplicate effective criterion id")
            seen.add(criterion_id)
            item_id = uuid.uuid4().hex
            packet["items"].append(
                {
                    "item_id": item_id,
                    "case_id": case_id,
                    "criterion": {
                        "assertion": _text(criterion.get("assertion"), "criterion assertion"),
                        "dimension": _text(criterion.get("dimension"), "criterion dimension"),
                    },
                    "evidence_refs": ["system", "request", "tools"]
                    + [turn["evidence_ref"] for turn in public_case["turns"]],
                }
            )
            manifest["items"].append(
                {
                    "item_id": item_id,
                    "case_id": case_id,
                    "source_index": index,
                    "criterion_id": criterion_id,
                    "criterion_sha256": _digest(criterion),
                    "safety_critical": criterion.get("safety_critical") is True,
                }
            )
        model = trajectory.get("model")
        metadata = trajectory.get("metadata", {})
        completion, reason = trajectory_completion(
            trajectory.get("turns"), metadata, trajectory.get("error")
        )
        snapshot_name = f"source-{index + 1:04d}.json"
        trial_path, attempt_number = trajectory_attempt(path)
        manifest["sources"].append(
            {
                "case_id": case_id,
                "original_path": str(path.resolve()),
                "trial_group": str(trial_path.resolve()),
                "attempt_number": attempt_number,
                "snapshot": snapshot_name,
                "trajectory_sha256": hashlib.sha256(raw).hexdigest(),
                "review_context_sha256": metadata["review_context"]["sha256"],
                "task_id": trajectory.get("task_id"),
                "model": model,
                "checkpoint_identity": payload["checkpoint_identity"],
                "rubric_channel": payload["rubric_channel"],
                "grading_mode": payload["grading_mode"],
                "execution_status": completion,
                "execution_detail": reason,
                "unassessed_experiment": is_unassessed_experiment(trajectory),
            }
        )
        snapshots.append((snapshot_name, raw))
    public_text = json.dumps(packet, ensure_ascii=False).casefold()
    for source in manifest["sources"]:
        model = source["model"]
        if isinstance(model, str) and model.strip() and model.casefold() in public_text:
            raise ValueError(
                "Known model identity appears in reviewer evidence; "
                "blinding requires explicit source review"
            )
    packet_sha256 = _digest(packet)
    markdown = _markdown(packet)
    manifest["packet_sha256"] = packet_sha256
    manifest["markdown_sha256"] = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    manifest["manifest_sha256"] = _digest(manifest)
    template = {
        "schema_version": RESPONSE_VERSION,
        "packet_id": packet["packet_id"],
        "packet_sha256": packet_sha256,
        "assignment_id": packet["assignment_id"],
        "reviewer_id": "",
        "reviewer_attestation": None,
        "reviews": [
            {
                "item_id": item["item_id"],
                "criterion_validity": None,
                "verdict": None,
                "unassessed_reason": None,
                "evidence_refs": [],
                "rationale": "",
                "blinding": None,
            }
            for item in packet["items"]
        ],
    }
    # Nothing is written until all selected inputs pass. Never overwrite artifacts.
    output_dir.mkdir(parents=True, exist_ok=False)
    reviewer, coordinator = output_dir / "reviewer", output_dir / "coordinator"
    reviewer.mkdir()
    coordinator.mkdir(mode=0o700)
    _write(reviewer / "packet.json", packet)
    _write(reviewer / "response-template.json", template)
    (reviewer / "packet.md").write_text(markdown, encoding="utf-8")
    _write(coordinator / "manifest.json", manifest)
    for name, raw in snapshots:
        with (coordinator / name).open("xb") as handle:
            handle.write(raw)
    return manifest


def _validate_review(row: dict, item: dict) -> str:
    _keys(row, REVIEW_FIELDS, "Review row")
    blank = {
        "item_id": item["item_id"],
        "criterion_validity": None,
        "verdict": None,
        "unassessed_reason": None,
        "evidence_refs": [],
        "rationale": "",
        "blinding": None,
    }
    if row == blank:
        return "pending"
    _member(row["criterion_validity"], VALIDITIES, "criterion validity")
    _member(row["verdict"], VERDICTS, "verdict")
    _member(row["blinding"], BLINDING, "blinding assessment")
    _text(row["rationale"], "rationale")
    refs = row["evidence_refs"]
    if not isinstance(refs, list) or any(
        not isinstance(ref, str) or ref not in item["evidence_refs"] for ref in refs
    ):
        raise ValueError("Invalid evidence reference")
    if len(set(refs)) != len(refs):
        raise ValueError("duplicate evidence reference")
    if row["verdict"] == "unassessed":
        _member(row["unassessed_reason"], REASONS, "unassessed reason")
        return "unassessed"
    if row["criterion_validity"] != "valid" or row["unassessed_reason"] is not None or not refs:
        raise ValueError(
            "A binary assessment requires a valid criterion, evidence, and no abstention reason"
        )
    return "assessed"


def import_review_response(manifest_path: Path, response_path: Path, output_dir: Path) -> dict:
    """Validate a submission and preserve every assigned opportunity in a receipt.

    Receipt identity is the packet/assignment pair, not the output directory;
    duplicated copies must never be counted as additional reviewers. No expert
    authentication, adjudication, majority voting, or calibration is performed.
    """
    if output_dir.exists():
        raise FileExistsError(output_dir)
    manifest, _ = _read(manifest_path)
    manifest_hash = manifest.pop("manifest_sha256", None)
    if manifest.get("schema_version") != MANIFEST_VERSION or _digest(manifest) != manifest_hash:
        raise ValueError("Coordinator manifest digest changed or unsupported schema")
    packet_path = manifest_path.parent.parent / "reviewer" / "packet.json"
    packet, _ = _read(packet_path)
    if (
        packet.get("schema_version") != PACKET_VERSION
        or _digest(packet) != manifest["packet_sha256"]
    ):
        raise ValueError("Reviewer packet hash changed")
    markdown = (packet_path.parent / "packet.md").read_bytes()
    if hashlib.sha256(markdown).hexdigest() != manifest["markdown_sha256"]:
        raise ValueError("Reviewer Markdown rendering hash changed")
    for source in manifest["sources"]:
        name = source["snapshot"]
        if not isinstance(name, str) or not re.fullmatch(r"source-\d{4,}\.json", name):
            raise ValueError("Invalid coordinator snapshot path")
        raw = (manifest_path.parent / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["trajectory_sha256"]:
            raise ValueError("Coordinator source snapshot hash changed")
    response, raw_response = _read(response_path)
    _keys(
        response,
        {
            "schema_version",
            "packet_id",
            "packet_sha256",
            "assignment_id",
            "reviewer_id",
            "reviewer_attestation",
            "reviews",
        },
        "Response",
    )
    if response["schema_version"] != RESPONSE_VERSION:
        raise ValueError("Unsupported response schema")
    for key in ("packet_id", "packet_sha256", "assignment_id"):
        if response[key] != manifest[key]:
            raise ValueError(f"Response {key} does not match assignment")
    if response["reviewer_id"] != manifest["reviewer_assignment"]["reviewer_id"]:
        raise ValueError("Reviewer identity does not match assignment")
    attestation = response["reviewer_attestation"]
    _keys(
        attestation,
        {"qualification_statement", "conflicts_statement", "independent_review"},
        "Reviewer attestation",
    )
    for key in ("qualification_statement", "conflicts_statement"):
        _text(attestation[key], key)
    if type(attestation["independent_review"]) is not bool:
        raise ValueError("independent_review must be a JSON boolean")
    if not isinstance(response["reviews"], list):
        raise ValueError("reviews must be an array")
    assigned = {item["item_id"]: item for item in packet["items"]}
    submitted = {}
    for row in response["reviews"]:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("item_id"), str)
            or row["item_id"] not in assigned
        ):
            raise ValueError("Foreign or malformed review item")
        item_id = row["item_id"]
        if item_id in submitted:
            raise ValueError("duplicate review item")
        submitted[item_id] = (_validate_review(row, assigned[item_id]), row)
    counts = {
        "assigned": len(assigned),
        "submitted": 0,
        "assessed": 0,
        "unassessed": 0,
        "pending": 0,
    }
    items = []
    for item_id in assigned:
        status, row = submitted.get(item_id, ("pending", None))
        counts[status] += 1
        counts["submitted"] += status != "pending"
        items.append({"item_id": item_id, "status": status, "review": row})
    receipt = {
        "schema_version": "clinical-review-receipt/v1",
        "packet_id": manifest["packet_id"],
        "packet_sha256": manifest["packet_sha256"],
        "assignment_id": manifest["assignment_id"],
        "manifest_sha256": manifest_hash,
        "protocol_sha256": manifest["protocol_sha256"],
        "response_sha256": hashlib.sha256(raw_response).hexdigest(),
        "reviewer_id": response["reviewer_id"],
        "reviewer_attestation": attestation,
        "clinical_validation_status": "unvalidated_submission",
        "counts": counts,
        "items": items,
        "limitations": (
            "Self-reported identity, expertise, independence, and blinding are not authenticated. "
            "No clinical calibration or adjudication has been performed."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    _write(output_dir / "receipt.json", receipt)
    with (output_dir / "submission.json").open("xb") as handle:
        handle.write(raw_response)
    return receipt
