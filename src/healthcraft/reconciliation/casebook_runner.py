"""Immutable offline development-control rosters for the exposed casebook.

These constructed controls are neither model trials nor clinical validation.
Scenario and expectation documents share an authoring ledger; separate files
and verifier implementation do not establish independent label adjudication.
"""

from __future__ import annotations

import hashlib
import platform
import sys
from pathlib import Path

from healthcraft.reconciliation.case_controls import run_control
from healthcraft.reconciliation.casebook import (
    DEFAULT_CASEBOOK_PATH,
    canonical_bytes,
    load_cases,
)
from healthcraft.reconciliation.oracle_v2 import verify_case

ROOT = Path(__file__).resolve().parents[3]
_AXES = ("provenance", "source_fidelity", "persisted_action", "readback", "execution_complete")
# Declared engineering expectations, not generated from the verifier's answers.
_EXPECTED = {
    "valid": "TTTTT",
    "wrong_exclusion": "TFFFT",
    "wrong_target": "TFFFT",
    "incorrect_content_readback": "TFFFT",
    "ack_without_storage": "TTFFT",
    "duplicate_notes": "TTFFT",
    "interrupted_after_write": "TTTFF",
    "incomplete_capture": "FFFFF",
}


def _write(path: Path, value: object) -> None:
    payload = canonical_bytes(value) + b"\n"
    with path.open("xb") as stream:
        stream.write(payload)


def _source_hashes() -> dict[str, str]:
    paths = set((ROOT / "src").rglob("*.py"))
    paths.update({ROOT / "configs/mcp-tools.json", ROOT / "scripts/reconciliation_casebook.py"})
    return {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def _expected(control: str) -> dict:
    return {
        "checks": {
            axis: value == "T" for axis, value in zip(_AXES, _EXPECTED[control], strict=True)
        },
        "status": "verified"
        if control == "valid"
        else ("provenance_error" if control == "incomplete_capture" else "not_verified"),
        "mechanical_passed": control == "valid",
    }


def _matches(verification: dict, expected: dict) -> bool:
    checks = verification.get("checks")
    return (
        type(checks) is dict
        and set(checks) == set(_AXES)
        and all(checks[axis] is expected["checks"][axis] for axis in _AXES)
        and verification.get("status") == expected["status"]
        and verification.get("mechanical_passed") is expected["mechanical_passed"]
    )


def _error(exc: BaseException, stage: str) -> dict:
    return {"stage": stage, "type": type(exc).__name__, "message": str(exc)}


def _file_hashes(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Output inventory cannot include symlinks")
        if path.is_file() and path != root / "manifest.json":
            result[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return result


def run_casebook(
    output_dir: Path,
    *,
    casebook_path: Path | None = None,
    expected_sha256: str | None = None,
    case_ids: list[str] | tuple[str, ...] | None = None,
    mode: str = "both",
) -> dict:
    """Execute a fully preflighted, fixed roster once in fresh native worlds.

    All source cases are checked before selection or output creation. Each
    preparation/execution/verification failure remains in the denominator;
    later scheduled attempts continue. Individual files and the output root
    are exclusive. A catastrophic output filesystem failure may prevent final
    manifest creation; earlier files/journals remain, and the CLI exits 2.
    """
    if mode not in ("reference", "designated", "both"):
        raise ValueError("mode must be reference, designated or both")
    cases = load_cases(casebook_path, expected_sha256=expected_sha256)
    available = {case["case_id"] for case in cases}
    if case_ids is not None:
        if type(case_ids) not in (list, tuple) or not case_ids:
            raise ValueError("case_ids must be a nonempty list of distinct case identifiers")
        if any(type(value) is not str or not value or value not in available for value in case_ids):
            raise ValueError("Empty, malformed or unknown case identifier")
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("Duplicate requested case identifier")
        cases = tuple(case for case in cases if case["case_id"] in case_ids)
    input_path = Path(casebook_path) if casebook_path is not None else DEFAULT_CASEBOOK_PATH
    output = Path(output_dir)
    if output.resolve().is_relative_to(input_path.parent.resolve()):
        raise ValueError("Output cannot be inside the input casebook directory")
    hashes_before = _source_hashes()
    runtime = {
        "python_version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "executable": sys.executable,
    }
    roster = []
    modes = ("reference", "designated") if mode == "both" else (mode,)
    for case in cases:
        for arm in modes:
            control = "valid" if arm == "reference" else case["designated_control"]
            roster.append(
                {
                    "id": f"{case['case_id']}/{arm}",
                    "case_id": case["case_id"],
                    "mode": arm,
                    "control": control,
                    "expected": _expected(control),
                }
            )
    output.mkdir(parents=True, exist_ok=False)
    _write(output / "roster.json", roster)
    _write(output / "source-identity-before.json", {"before": hashes_before, "runtime": runtime})
    cases_by_id = {case["case_id"]: case for case in cases}
    outcomes = []
    for planned in roster:
        case = cases_by_id[planned["case_id"]]
        directory = output / planned["id"]
        outcome = {
            **planned,
            "status": "not_started",
            "attempted": False,
            "matched": False,
            "error": None,
        }
        stage = "preparation"
        try:
            directory.mkdir(parents=True, exist_ok=False)
            case_file = directory.parent / "case.json"
            if not case_file.exists():
                _write(case_file, case)
            elif case_file.read_bytes() != canonical_bytes(case) + b"\n":
                raise ValueError("Existing case snapshot differs from the scheduled case")
            stage = "execution"
            outcome["attempted"] = True
            capture = run_control(
                case, control=planned["control"], journal_path=directory / "journal.jsonl"
            )
            stage = "capture_persistence"
            metadata = {
                key: value
                for key, value in capture.items()
                if key not in {"evidence", "original_evidence"}
            }
            _write(directory / "control.json", metadata)
            evidence = capture["evidence"]
            _write(directory / "execution.json", evidence)
            if capture.get("original_evidence") is not None:
                _write(directory / "original-execution.json", capture["original_evidence"])
            stage = "verification"
            verification = verify_case(case, evidence)
            _write(directory / "verification.json", verification)
            outcome["verification_status"] = verification.get("status")
            outcome["checks"] = verification.get("checks")
            outcome["matched"] = _matches(verification, planned["expected"])
            if planned["control"] == "incomplete_capture":
                original = capture.get("original_evidence")
                transformation = capture.get("capture_transformation")
                faithful_original = False
                if type(original) is dict:
                    original_verification = verify_case(case, original)
                    _write(directory / "original-verification.json", original_verification)
                    faithful_original = _matches(original_verification, _expected("valid"))
                applied = (
                    type(transformation) is dict
                    and transformation.get("kind") == "deliberate_capture_omission"
                )
                outcome["original_capture_verified"] = faithful_original
                outcome["capture_omission_applied"] = applied
                outcome["matched"] = outcome["matched"] and applied and faithful_original
            outcome["status"] = "matched" if outcome["matched"] else "mismatch"
            completion = evidence.get("completion", {})
            if completion.get("status") == "failed" or (
                completion.get("status") == "interrupted"
                and planned["control"] not in {"interrupted_after_write", "incomplete_capture"}
            ):
                outcome["status"] = "execution_error"
                outcome["matched"] = False
                outcome["error"] = {
                    "stage": "execution",
                    "type": "ExecutionIncomplete",
                    "message": "Unexpected execution failure; see execution.json completion",
                    "completion": completion,
                }
                _write(directory / "error.json", outcome["error"])
        except (Exception, KeyboardInterrupt) as exc:
            outcome["error"] = _error(exc, stage)
            outcome["status"] = "io_error" if isinstance(exc, OSError) else f"{stage}_error"
            outcome["matched"] = False
            if directory.is_dir():
                try:
                    _write(directory / "error.json", outcome["error"])
                except OSError as receipt_error:
                    outcome["receipt_error"] = _error(receipt_error, "error_persistence")
        outcomes.append(outcome)
        if directory.is_dir():
            try:
                _write(directory / "attempt.json", outcome)
            except OSError as exc:
                outcome["status"] = "io_error"
                outcome["matched"] = False
                outcome["error"] = _error(exc, "attempt_persistence")
    source_error = None
    try:
        hashes_after = _source_hashes()
    except (OSError, ValueError) as exc:
        hashes_after = None
        source_error = _error(exc, "source_verification")
    unchanged = hashes_before == hashes_after
    _write(
        output / "source-identity.json",
        {"before": hashes_before, "after": hashes_after, "error": source_error, "runtime": runtime},
    )
    errors = sum(outcome["error"] is not None for outcome in outcomes)
    matched = sum(outcome["matched"] for outcome in outcomes)
    status = (
        "implementation_changed"
        if not unchanged
        else ("run_error" if errors else ("completed" if matched == len(roster) else "mismatch"))
    )
    manifest = {
        "schema_version": "healthcraft-reconciliation-casebook-run/v2",
        "purpose": "development_controls",
        "status": status,
        "casebook_sha256": cases[0]["casebook_sha256"],
        "casebook_path": str(input_path.resolve()),
        "label_status": "engineering_authored_independent_review_pending",
        "mode": mode,
        "roster": roster,
        "outcomes": outcomes,
        "counts": {
            "scheduled": len(roster),
            "attempted": sum(o["attempted"] for o in outcomes),
            "recorded": len(outcomes),
            "matched": matched,
            "mismatched": len(outcomes) - matched - errors,
            "errors": errors,
        },
        "sources_unchanged": unchanged,
        "development_controls_matched": unchanged and matched == len(roster),
        "source_identity_error": source_error,
        "runtime": runtime,
        "clinical_validated": False,
        "benchmark_score": None,
        "benchmark_comparable": False,
        "grading_complete": False,
        "model_calls": 0,
        "limitations": [
            "Exposed engineering development controls; not held-out model trials, "
            "clinical validation or formal red team.",
            "Scenarios and expectations share an authoring ledger; "
            "independent label review remains pending.",
            "Exact hashes establish content consistency, "
            "not independent adjudication or execution authentication.",
            "Expected failures are constructed controls, not a score or model-comparison result.",
        ],
        "files": _file_hashes(output),
    }
    _write(output / "manifest.json", manifest)
    return manifest
