"""Fixed, source-bound development cohorts using installed local model weights.

Controller completion, observed storage/retrieval, and mechanical verification
remain distinct. These exposed attempts carry no clinical or benchmark score.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from healthcraft.reconciliation.casebook import (
    DEFAULT_CASEBOOK_PATH,
    _hash,
    _read,
    canonical_bytes,
    digest,
    load_cases,
)
from healthcraft.reconciliation.fixture import _keys
from healthcraft.reconciliation.model_case import run_model_case, validate_model_config
from healthcraft.reconciliation.oracle_v2 import verify_case
from healthcraft.reconciliation.public_case import public_case_context

ROOT = Path(__file__).resolve().parents[3]
_BINDINGS = (
    "case_id",
    "scenario_family_id",
    "casebook_sha256",
    "scenario_sha256",
    "expectations_sha256",
)


def _write(path: Path, value: object) -> None:
    with path.open("xb") as stream:
        stream.write(canonical_bytes(value) + b"\n")


def _source_hashes() -> dict[str, str]:
    paths = set((ROOT / "src").rglob("*.py"))
    paths.update({ROOT / "configs/mcp-tools.json", ROOT / "scripts/reconciliation_local_cohort.py"})
    return {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(paths)
    }


def load_plan(plan_path: Path, *, expected_sha256: str, casebook_path: Path | None = None):
    """Authenticate and validate the complete roster before model/output access."""
    _hash(expected_sha256)
    raw, plan = _read(Path(plan_path))
    if digest(plan) != expected_sha256:
        raise ValueError("Cohort plan digest mismatch")
    _keys(plan, {"schema_version", "exposure", "casebook_sha256", "models", "cases", "roster"})
    if (
        plan["schema_version"] != "healthcraft-reconciliation-model-cohort-plan/v2"
        or plan["exposure"] != "development"
    ):
        raise ValueError("Only the exposed development cohort is supported")
    cases = {
        case["case_id"]: case
        for case in load_cases(casebook_path, expected_sha256=plan["casebook_sha256"])
    }
    if type(plan["models"]) is not list or not 1 <= len(plan["models"]) <= 8:
        raise ValueError("One to eight distinct local models are required")
    models, aliases, weights = {}, set(), set()
    common = None
    for entry in plan["models"]:
        _keys(entry, {"id", "config"})
        identifier = entry["id"]
        if (
            type(identifier) is not str
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", identifier)
            or identifier in models
        ):
            raise ValueError("Invalid or duplicate model identifier")
        config = validate_model_config(entry["config"])
        if config["model"] in aliases or config["expected_digest"] in weights:
            raise ValueError("Duplicate local aliases or weight identities")
        aliases.add(config["model"])
        weights.add(config["expected_digest"])
        condition = canonical_bytes({key: config[key] for key in ("settings", "command_format")})
        if common is not None and common != condition:
            raise ValueError(
                "This common-condition cohort requires identical settings and command format"
            )
        common = condition
        models[identifier] = config
    if type(plan["cases"]) is not list or not plan["cases"]:
        raise ValueError("An explicit nonempty case roster is required")
    selected = {}
    for entry in plan["cases"]:
        _keys(entry, {"case_id", "initial_messages_sha256"})
        identifier = entry["case_id"]
        if type(identifier) is not str or identifier not in cases or identifier in selected:
            raise ValueError("Unknown or duplicate case identifier")
        context = public_case_context(cases[identifier]["scenario"]["target"])
        if entry["initial_messages_sha256"] != context["initial_messages_sha256"]:
            raise ValueError("Frozen initial prompt differs from the public case context")
        selected[identifier] = cases[identifier]
    if type(plan["roster"]) is not list:
        raise ValueError("An explicit ordered attempt roster is required")
    pairs = set()
    for row in plan["roster"]:
        _keys(row, {"id", "case_id", "model_id"})
        if (
            type(row["case_id"]) is not str
            or type(row["model_id"]) is not str
            or row["case_id"] not in selected
            or row["model_id"] not in models
        ):
            raise ValueError("Attempt refers to an unknown case or model")
        pair = row["case_id"], row["model_id"]
        if pair in pairs or row["id"] != f"{pair[0]}/{pair[1]}":
            raise ValueError("Duplicate attempt or uncontrolled output path")
        pairs.add(pair)
    if pairs != {(case_id, model_id) for case_id in selected for model_id in models}:
        raise ValueError("Roster must retain every selected case/model pair exactly once")
    return plan, selected, models, hashlib.sha256(raw).hexdigest()


def _observed_actions(evidence: dict) -> dict:
    """Describe literal stored notes/readbacks independently of content correctness."""
    notes = list(evidence["after"]["entities"]["clinical_note"].values())
    stored = Counter((note["patient_id"], note["encounter_id"], note["content"]) for note in notes)
    reads = Counter()
    for call in evidence["calls"]:
        if (
            call.get("name") != "getEncounterDetails"
            or call.get("response", {}).get("status") != "ok"
        ):
            continue
        data = call["response"].get("data", {})
        contents = Counter(
            entry[1]
            for entry in data.get("clinical_notes", [])
            if type(entry) is list
            and len(entry) == 2
            and entry[0] == "Progress Note"
            and type(entry[1]) is str
        )
        for key in stored:
            patient, encounter, content = key
            if data.get("id") == encounter and data.get("patient_id") == patient:
                reads[key] = max(reads[key], min(stored[key], contents[content]))
    return {
        "stored_note_count": len(notes),
        "stored_note_readback_count": sum(reads.values()),
        "clinical_assessment": "unassessed",
    }


def _validate_verification(case: dict, report: dict) -> None:
    axes = {"provenance", "source_fidelity", "persisted_action", "readback", "execution_complete"}
    checks = report.get("checks")
    if (
        report.get("schema_version") != "healthcraft-reconciliation-verification/v2"
        or type(checks) is not dict
        or set(checks) != axes
        or any(type(value) is not bool for value in checks.values())
        or report.get("mechanical_passed") is not all(checks.values())
        or report.get("status") != ("verified" if all(checks.values()) else "not_verified")
        or canonical_bytes(report.get("case_binding"))
        != canonical_bytes({key: case[key] for key in _BINDINGS})
        or report.get("benchmark_score") is not None
        or report.get("grading_complete") is not False
    ):
        raise ValueError("Mechanical verification receipt is malformed or inconsistent")


def run_model_cohort(
    plan_path: Path,
    output_dir: Path,
    *,
    expected_sha256: str,
    casebook_path: Path | None = None,
    attempt_runner=None,
) -> dict:
    """Run one frozen roster without retries, dropping failures, or score claims."""
    plan, cases, models, raw_plan_hash = load_plan(
        plan_path, expected_sha256=expected_sha256, casebook_path=casebook_path
    )
    output = Path(output_dir)
    for source in (Path(plan_path).parent, (casebook_path or DEFAULT_CASEBOOK_PATH).parent):
        if output.resolve().is_relative_to(source.resolve()):
            raise ValueError("Output cannot be inside the source plan or casebook directory")
    runner = run_model_case if attempt_runner is None else attempt_runner
    if not callable(runner):
        raise ValueError("Attempt runner must be callable")
    before = _source_hashes()
    output.mkdir(parents=True, exist_ok=False)
    _write(output / "plan.json", plan)
    _write(output / "cases.json", list(cases.values()))
    _write(output / "source-identity-before.json", before)
    started = datetime.now(timezone.utc).isoformat()
    outcomes, interrupted = [], False
    for row in plan["roster"]:
        outcome = {
            **row,
            "status": "not_attempted",
            "attempted": False,
            "model_calls": None,
            "mechanical_passed": None,
            "verification_status": None,
            "observed_actions": None,
            "error": None,
            "grading_error": None,
        }
        directory = output / row["id"]
        if interrupted:
            outcome["reason"] = "cohort_interrupted_before_attempt"
            outcomes.append(outcome)
            continue
        case, config = cases[row["case_id"]], models[row["model_id"]]
        try:
            outcome["attempted"] = True
            receipt = runner(case, config, directory)
            if (
                type(receipt) is not dict
                or receipt.get("schema_version") != "healthcraft-reconciliation-model-attempt/v2"
                or receipt.get("status") not in {"completed", "failed", "interrupted"}
                or canonical_bytes(receipt.get("model_config")) != canonical_bytes(config)
                or canonical_bytes(receipt.get("case_binding"))
                != canonical_bytes({key: case[key] for key in _BINDINGS})
            ):
                raise ValueError("Attempt receipt does not match its scheduled model/case")
            count = receipt.get("model_calls")
            if count is not None and (type(count) is not int or count < 0):
                raise ValueError("Model request count must be nonnegative or unknown")
            detail = receipt.get("error")
            if (detail is not None and (type(detail) is not dict or not detail)) or (
                receipt["status"] == "completed" and detail is not None
            ):
                raise ValueError("Attempt completion/error receipt is inconsistent")
            outcome.update(status=receipt["status"], model_calls=count, error=receipt.get("error"))
            interrupted = receipt["status"] == "interrupted"
            try:
                _, evidence = _read(directory / "execution.json")
                if evidence.get("completion", {}).get("status") != receipt["status"]:
                    raise ValueError("Native execution completion contradicts the attempt receipt")
                verification = verify_case(case, evidence)
                _write(directory / "verification.json", verification)
                if verification.get("status") == "provenance_error":
                    raise ValueError("Native execution provenance cannot support grading")
                _validate_verification(case, verification)
                outcome["mechanical_passed"] = verification["mechanical_passed"]
                outcome["verification_status"] = verification["status"]
                outcome["observed_actions"] = _observed_actions(evidence)
            except (Exception, KeyboardInterrupt) as exc:
                outcome["grading_error"] = {"type": type(exc).__name__, "message": str(exc)}
                if isinstance(exc, KeyboardInterrupt):
                    interrupted = True
        except (Exception, KeyboardInterrupt) as exc:
            interrupted = isinstance(exc, KeyboardInterrupt)
            outcome.update(
                status="interrupted" if interrupted else "failed",
                error={"type": type(exc).__name__, "message": str(exc)},
            )
        outcomes.append(outcome)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            _write(directory / "cohort-outcome.json", outcome)
        except (OSError, KeyboardInterrupt) as exc:
            outcome["capture_error"] = {"type": type(exc).__name__, "message": str(exc)}
            if isinstance(exc, KeyboardInterrupt):
                interrupted = True
                outcome["status"] = "interrupted"
            elif outcome["status"] != "interrupted":
                outcome["status"] = "failed"
            # The global manifest retains this capture error. Never overwrite
            # an existing per-attempt record or abandon later scheduled cases.
    source_error = None
    try:
        after = _source_hashes()
    except (OSError, ValueError) as exc:
        after = None
        source_error = {"type": type(exc).__name__, "message": str(exc)}
    unchanged = before == after
    _write(
        output / "source-identity.json", {"before": before, "after": after, "error": source_error}
    )
    counts = {
        "scheduled": len(plan["roster"]),
        "attempted": sum(row["attempted"] for row in outcomes),
        **{
            status: sum(row["status"] == status for row in outcomes)
            for status in ("completed", "failed", "interrupted", "not_attempted")
        },
        "grading_errors": sum(row["grading_error"] is not None for row in outcomes),
        "mechanical_passed": sum(row["mechanical_passed"] is True for row in outcomes),
        "mechanical_not_verified": sum(row["mechanical_passed"] is False for row in outcomes),
    }
    state = (
        "completed"
        if counts["completed"] == counts["scheduled"] and not counts["grading_errors"]
        else "incomplete"
    )
    state = "interrupted" if interrupted else state
    state = "implementation_changed" if not unchanged else state
    manifest = {
        "schema_version": "healthcraft-reconciliation-model-cohort/v2",
        "status": state,
        "exposure": "development",
        "plan_sha256": expected_sha256,
        "plan_file_sha256": raw_plan_hash,
        "casebook_sha256": plan["casebook_sha256"],
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "outcomes": outcomes,
        "sources_unchanged": unchanged,
        "benchmark_score": None,
        "benchmark_comparable": False,
        "grading_complete": False,
        "clinical_criteria": 0,
        "safety_criteria": 0,
        "limitations": [
            "Exposed development attempts; reliability and clinical validity are unassessed.",
            "Scenarios and expectations share an authoring ledger. Independent review is pending.",
            "Request counts record attempts, not attested server inference executions.",
            "Literal storage/readback and controller completion are distinct from correct content.",
        ],
        "files": {
            p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(output.rglob("*"))
            if p.is_file()
        },
    }
    _write(output / "manifest.json", manifest)
    return manifest
