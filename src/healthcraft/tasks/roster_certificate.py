"""Mechanical source transport checks for experimental roster projections.

Expected observations come from authored task data, independently of the profile
builder and captured tool outputs. This is not a clinical oracle or benchmark
grader. Captures and the final world are trusted in-process evidence; matching
audit metadata and content hashes do not authenticate third-party transcripts.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from healthcraft.tasks.loader import Task
from healthcraft.tasks.roster_profile import PROFILE_VERSION, roster_contract
from healthcraft.world.state import WorldState


def _digest(value: Any) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Certificate source and evidence must be finite JSON values") from exc
    return hashlib.sha256(encoded.encode()).hexdigest()


def _same(actual: Any, expected: Any) -> bool:
    """Keep JSON types distinct: a numeric source identity is not a string/bool."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            _same(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _same(a, b) for a, b in zip(actual, expected, strict=True)
        )
    return actual == expected


def _expected(task: Task, context: dict) -> list[dict]:
    if not isinstance(context, dict) or context.get("profile_version") != PROFILE_VERSION:
        raise ValueError("Unsupported roster profile context")
    if context.get("task_id") != task.id:
        raise ValueError("Roster context must reference the supplied task")
    contract = roster_contract(task.id)
    source = task.source_data
    if not isinstance(source, dict) or source.get("id") != task.id:
        raise ValueError("Matching authored task source is required")
    if context.get("source_sha256") != _digest(source):
        raise ValueError("Context source hash does not match the authored task")
    if context.get("contract_sha256") != _digest([PROFILE_VERSION, contract]):
        raise ValueError("Context contract hash does not match the registered field selector")

    expected = []
    labels = set()
    for collection, count, identity, required, allowed, excluded, source_context in contract:
        rows = source.get(collection)
        if not isinstance(rows, list) or len(rows) != count:
            raise ValueError(f"Authored source {collection} must contain exactly {count} rows")
        for index, raw in enumerate(rows):
            path = f"{collection}/{index}"
            if not isinstance(raw, dict) or set(raw) - set(allowed) - set(excluded):
                raise ValueError(f"Unreviewed or malformed source row: {path}")
            identity_value = raw.get(identity)
            if type(identity_value) not in (str, int) or not str(identity_value).strip():
                raise ValueError(f"Missing authored source identity: {path}")
            if not isinstance(raw.get(required), str) or not raw[required].strip():
                raise ValueError(f"Missing required authored observation: {path}/{required}")
            observations = {field: raw[field] for field in allowed if field in raw}
            if any(
                type(value) not in (str, int, float)
                or (isinstance(value, float) and not math.isfinite(value))
                for value in observations.values()
            ):
                raise ValueError(f"Source observations must be finite authored scalars: {path}")
            label = f"Bed {identity_value}" if identity == "bed" else str(identity_value)
            if label in labels:
                raise ValueError("Duplicate authored roster identity")
            labels.add(label)
            suffix = _digest([PROFILE_VERSION, task.id, collection, identity_value])[:12].upper()
            expected.append(
                {
                    "label": label,
                    "patient_id": f"PAT-{suffix}",
                    "encounter_id": f"ENC-{suffix}",
                    "source_path": path,
                    "source_context": source_context,
                    "source_identity": {"field": identity, "value": identity_value},
                    "authored_observations": observations,
                }
            )
    roster = context.get("roster")
    if not isinstance(roster, list) or len(roster) != len(expected):
        raise ValueError("Context must contain every authored roster member")
    if any(not isinstance(row, dict) for row in roster):
        raise ValueError("Context roster members must be objects")
    paths = [row.get("source_path") for row in roster]
    if any(not isinstance(path, str) for path in paths) or len(set(paths)) != len(paths):
        raise ValueError("Context source paths must be unique")
    actual = {row["source_path"]: row for row in roster}
    keys = ("label", "patient_id", "encounter_id", "source_path", "source_context")
    if set(actual) != {row["source_path"] for row in expected} or any(
        any(not _same(actual[row["source_path"]].get(key), row[key]) for key in keys)
        for row in expected
    ):
        raise ValueError("Context roster does not match the registered source membership")
    return expected


def _validate_calls(calls: Any, world: WorldState) -> None:
    if not isinstance(calls, list):
        raise ValueError("Calls must be an ordered list of captured invocations")
    audit, seen, previous_index = world.audit_log, set(), -1
    for call in calls:
        if not isinstance(call, dict):
            raise ValueError("Captured invocation must be an object")
        call_id = call.get("id")
        if not isinstance(call_id, str) or not call_id or call_id in seen:
            raise ValueError("Captured invocation IDs must be nonempty and unique")
        seen.add(call_id)
        name, params, response = call.get("name"), call.get("params"), call.get("response")
        if not isinstance(name, str) or not name or not isinstance(params, dict):
            raise ValueError("Captured invocation requires tool name and parameters")
        if not isinstance(response, dict) or response.get("status") not in ("ok", "error"):
            raise ValueError("Captured invocation requires an explicit completed response")
        if response["status"] == "ok" and "data" not in response:
            raise ValueError("Successful captured response requires data")
        index = call.get("audit_index")
        if type(index) is not int or not previous_index < index < len(audit):
            raise ValueError("Audit indices must be in range, unique, and strictly increasing")
        entry = audit[index]
        if (
            entry.tool_name != name
            or not _same(entry.params, params)
            or entry.result_summary != response["status"]
        ):
            raise ValueError("Captured invocation does not match its world audit entry")
        if response["status"] == "error" and entry.error_code != response.get("code", ""):
            raise ValueError("Captured error code does not match its world audit entry")
        previous_index = index


def _linked(data: Any, member: dict, task_id: str, kind: str) -> bool:
    if not isinstance(data, dict):
        return False
    expected = {
        "id": member[f"{kind}_id"],
        "entity_type": kind,
        "task_id": task_id,
        "profile_version": PROFILE_VERSION,
        **{key: member[key] for key in ("source_path", "source_context", "source_identity")},
    }
    if kind == "encounter":
        expected.update(patient_id=member["patient_id"], arrival_time=None)
    return all(key in data and _same(data[key], value) for key, value in expected.items())


def _facts(data: dict, member: dict) -> bool:
    return _same(data.get("authored_observations"), member["authored_observations"])


def verify_roster_retrieval(
    task: Task, context: dict, calls: list[dict], world: WorldState
) -> dict:
    """Verify exact authored observation retrieval, independently of task grading.

    Malformed context/captures or audit mismatches raise ValueError. Validly
    captured but incomplete, wrong-patient, or source-discordant retrieval
    returns mechanical_passed=False. Successful retries may supply evidence;
    failed calls and repeated retrieval of one member do not fill other rows.
    """
    expected = _expected(task, context)
    _validate_calls(calls, world)
    members = []
    for member in expected:
        retrieved, witnesses = [], []
        for call in calls:
            if (
                call["name"] != "getEncounterDetails"
                or call["params"].get("encounter_id") != member["encounter_id"]
                or call["response"]["status"] != "ok"
            ):
                continue
            data = call["response"]["data"]
            if _linked(data, member, task.id, "encounter"):
                retrieved.append(call["id"])
                if _facts(data, member):
                    witnesses.append(call["id"])
        final_matches = True
        for kind in ("patient", "encounter"):
            data = world.get_entity(kind, member[f"{kind}_id"])
            final_matches &= _linked(data, member, task.id, kind) and _facts(data, member)
        members.append(
            {
                **{
                    key: member[key]
                    for key in ("label", "patient_id", "encounter_id", "source_path")
                },
                "retrieved": bool(retrieved),
                "source_concordant": bool(witnesses),
                "final_world_source_concordant": final_matches,
                "retrieval_call_ids": retrieved,
                "witness_call_ids": witnesses,
            }
        )
    checks = {
        "source_context_validated": True,
        "audit_bound_calls": True,
        "all_members_retrieved": all(row["retrieved"] for row in members),
        "source_facts_concordant": all(row["source_concordant"] for row in members),
        "final_world_source_concordant": all(
            row["final_world_source_concordant"] for row in members
        ),
    }
    return {
        "certificate_version": "roster-retrieval-mechanical/v1",
        "profile_version": PROFILE_VERSION,
        "task_id": task.id,
        "source_sha256": context["source_sha256"],
        "contract_sha256": context["contract_sha256"],
        "mechanical_passed": all(checks.values()),
        "checks": checks,
        "members": members,
        "benchmark_score": None,
        "coverage": {
            "expected_members": len(expected),
            "retrieved_members": sum(row["retrieved"] for row in members),
            "source_concordant_members": sum(row["source_concordant"] for row in members),
            "measured_clinical_criteria": 0,
            "measured_safety_criteria": 0,
            "unassessed_criteria": [criterion["id"] for criterion in task.criteria],
        },
        "execution_evidence": (
            "Trusted synchronous captures linked to world audit indices; no provider-ID claim. "
            "The world audit binds call metadata/status, not the full response payload."
        ),
        "limitations": (
            "Exact source-observation transport and final record concordance only. No clinical "
            "judgment, prioritization, treatment, safety validation, task reward, or full-task "
            "solvability is assessed. Source assessments are not clinical ground truth. "
            "Content hashes are not attestations of third-party evidence."
        ),
    }
