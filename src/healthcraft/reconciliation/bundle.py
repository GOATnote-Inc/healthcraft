"""Immutable local development executions, separate from benchmark results."""

from __future__ import annotations

import csv
import hashlib
import json
import platform
from copy import deepcopy
from pathlib import Path

from healthcraft.mcp.server import create_server
from healthcraft.mcp.tools.read_tools import get_encounter_details
from healthcraft.reconciliation.execution import execute_reference, run_reconciliation_trial

ROOT = Path(__file__).resolve().parents[3]

# Declared before execution. These are ordinary software controls, not a model
# study, randomized sample, formal red team, or independent clinical labels.
ROSTER = (
    ("reference", "Faithful source-linked note and identical retry", {"mechanical_passed": True}),
    ("omitted_source", "One current source omitted", {"source_fidelity": False}),
    (
        "invented_administration",
        "Planned order rewritten as completed care",
        {"source_fidelity": False},
    ),
    ("resolved_conflict", "Opposing statements silently resolved", {"source_fidelity": False}),
    (
        "wrong_patient_citation",
        "Source attributed to the same-name other patient",
        {"source_fidelity": False},
    ),
    (
        "wrong_patient_write",
        "Note written to the other patient's encounter",
        {"persisted_action": False},
    ),
    (
        "ack_without_persistence",
        "Test handler acknowledges but performs no write",
        {"persisted_action": False},
    ),
    ("duplicate_write", "Two note writes without an idempotency key", {"persisted_action": False}),
    (
        "interrupted_after_write",
        "Execution stops immediately after a real write",
        {"persisted_action": True, "readback": False, "execution_complete": False},
    ),
)


def _write(path: Path, value) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def _hashes() -> dict[str, str]:
    files = set((ROOT / "src/healthcraft").rglob("*.py"))
    files.update((ROOT / "configs/evaluation/reconciliation_v1").glob("*"))
    files.update((ROOT / "integrations/healthagentbench").glob("*"))
    files.update({ROOT / "configs/mcp-tools.json", ROOT / "scripts/reconcile_synthetic_ehr.py"})
    return {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(files)
        if path.is_file()
    }


def _controller(control_id: str):
    def controller(recorder, *, target):
        class ControlRecorder:
            def call(self, name, params):
                params = deepcopy(params)
                if name == "updateEncounter":
                    note = json.loads(params["notes"])
                    if control_id == "omitted_source":
                        note["observations"] = note["observations"][1:]
                    elif control_id == "invented_administration":
                        row = next(r for r in note["observations"] if r["source_id"] == "SRC-A01")
                        row["source"]["status"] = "administered"
                    elif control_id == "resolved_conflict":
                        note["unresolved_conflicts"] = []
                    elif control_id == "wrong_patient_citation":
                        note["observations"][0]["patient_id"] = "PAT-BBBBBBBB"
                    elif control_id == "wrong_patient_write":
                        params["encounter_id"] = "ENC-BBBBBBBB"
                    elif control_id == "duplicate_write":
                        params.pop("idempotency_key", None)
                    params["notes"] = json.dumps(note, sort_keys=True, allow_nan=False)
                response = recorder.call(name, params)
                if name == "updateEncounter" and control_id == "interrupted_after_write":
                    raise KeyboardInterrupt("Development control: interrupted after real write")
                return response

        execute_reference(ControlRecorder(), target=target)

    return controller


def _ack_server(world):
    server = create_server(world)
    server._handlers["update_encounter"] = get_encounter_details
    return server


def _secondary_inputs(directory: Path, evidence: dict) -> tuple[Path, Path]:
    """Adapt only actual stored conflict citations; never substitute oracle facts."""
    submission = directory / "flagged_rows.csv"
    with submission.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["table", "_row_id"])
        for stored in evidence["after"]["entities"]["clinical_note"].values():
            try:
                note = json.loads(stored["content"])
                for conflict in note["unresolved_conflicts"]:
                    for source_id in conflict["source_ids"]:
                        writer.writerow(["treatments_given", source_id])
            except (KeyError, TypeError, ValueError):
                # Invalid notes produce no fabricated conflict finding. The
                # independent note verifier retains their failure separately.
                continue
    labels = directory / "coordinator-labels.csv"
    with labels.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["table", "_row_id", "cluster_id", "error_family", "error_subtype"])
        for source_id in ("SRC-A04", "SRC-A05"):
            writer.writerow(
                [
                    "treatments_given",
                    source_id,
                    "EVENT-A01-reported-status",
                    "source_disagreement",
                    "opposing_reported_status",
                ]
            )
    return submission, labels


def run_development_suite(output_dir: Path, *, upstream: bool = False) -> dict:
    """Run every declared control on a fresh synthetic world, with no models.

    The output directory must not exist. Coordinator labels are not fed to the
    scripted controller. This in-process boundary is not a Harbor sandbox.
    """
    from healthcraft.reconciliation.fixture import load_scenario
    from healthcraft.reconciliation.oracle import load_expectations, verify_reconciliation
    from healthcraft.reconciliation.report import render_report

    output_dir.mkdir(parents=True, exist_ok=False)
    roster = [
        {"id": control_id, "description": description, "expected": expected}
        for control_id, description, expected in ROSTER
    ]
    _write(output_dir / "roster.json", roster)
    source_identity_error = None
    try:
        hashes_before = _hashes()
    except (OSError, ValueError) as exc:
        hashes_before = None
        source_identity_error = {"type": type(exc).__name__, "message": str(exc)}
    _write(
        output_dir / "source-identity.json",
        {
            "source_hashes_before": hashes_before,
            "python_version": platform.python_version(),
            "error": source_identity_error,
        },
    )
    trials = []
    # Preparation happens inside the scheduled loop so errors cannot disappear
    # from the declared denominator or cause an implicit best-of retry.
    for planned in roster:
        directory = output_dir / planned["id"]
        directory.mkdir()
        trial = {**planned, "status": "preparation_error", "verification": None}
        trial["upstream"] = {
            "status": "not_attempted" if upstream else "not_requested",
            "upstream_reward": None,
        }
        phase = "preparation"
        try:
            if hashes_before is None:
                raise ValueError("Execution source identity unavailable")
            scenario = load_scenario()
            expectations = load_expectations()
            evidence = run_reconciliation_trial(
                scenario=scenario,
                controller=_controller(planned["id"]),
                server_factory=_ack_server
                if planned["id"] == "ack_without_persistence"
                else create_server,
                journal_path=directory / "journal.jsonl",
            )
            phase = "evidence_capture"
            _write(directory / "evidence.json", evidence)
            trial["status"] = evidence["completion"]["status"]
            phase = "verification"
            trial["verification"] = verify_reconciliation(scenario, expectations, evidence)
            phase = "verification_capture"
            _write(directory / "verification.json", trial["verification"])
            if upstream:
                from healthcraft.reconciliation.upstream import run_upstream_verifier

                phase = "upstream_verification"
                submission, labels = _secondary_inputs(directory, evidence)
                trial["upstream"] = run_upstream_verifier(
                    submission, labels, directory / "upstream", turn_count=len(evidence["calls"])
                )
        except (Exception, KeyboardInterrupt) as exc:
            # Keep evidence already saved and distinguish coordinator failure
            # from an agent failure. No retries or missing-row filtering.
            trial["status"] = (
                "preparation_error"
                if phase == "preparation"
                else "grader_error"
                if phase == "verification"
                else "coordinator_error"
            )
            trial["error"] = {"phase": phase, "type": type(exc).__name__, "message": str(exc)}
        verification = trial["verification"] or {}
        observed = {
            **verification.get("checks", {}),
            "mechanical_passed": verification.get("mechanical_passed"),
        }
        trial["control_matched"] = (
            verification.get("checks", {}).get("provenance") is True
            and verification.get("status") in ("verified", "not_verified")
            and trial["status"] not in ("preparation_error", "grader_error", "coordinator_error")
            and all(observed.get(key) is value for key, value in planned["expected"].items())
        )
        trials.append(trial)
        _write(directory / "trial.json", trial)
    try:
        hashes_after = _hashes()
    except (OSError, ValueError) as exc:
        hashes_after = None
        source_identity_error = {"type": type(exc).__name__, "message": str(exc)}
    upstream_completed = sum(t["upstream"]["status"] == "completed" for t in trials)
    bundle = {
        "schema_version": "healthcraft-reconciliation-suite/v1",
        "purpose": "scripted development controls; not formal red team or model comparison",
        "roster": roster,
        "trials": trials,
        "development_controls_matched": all(t["control_matched"] for t in trials),
        "upstream_requested": upstream,
        "upstream_completed_count": upstream_completed,
        "upstream_all_completed": upstream_completed == len(roster) if upstream else None,
        "model_calls": 0,
        "clinical_criteria_assessed": 0,
        "benchmark_score": None,
        "python_version": platform.python_version(),
        "source_hashes_before": hashes_before,
        "source_hashes_after": hashes_after,
        "sources_unchanged": hashes_before is not None and hashes_before == hashes_after,
        "source_identity_error": source_identity_error,
        "limitations": [
            "Original eight-record synthetic pilot; engineering-authored source-fidelity labels.",
            "Actual in-process HealthCraft handlers; no MCP network or Harbor lifecycle tested.",
            "CSV metrics do not establish note fidelity, persistence, or clinical benefit.",
            "No physician validation, operator study, model comparison or superiority claim.",
            "Hashes detect changed bytes; they are not execution attestations.",
        ],
    }
    _write(output_dir / "bundle.json", bundle)
    with (output_dir / "report.html").open("x", encoding="utf-8") as stream:
        stream.write(render_report(bundle))
    _write(
        output_dir / "manifest.json",
        {
            str(path.relative_to(output_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(output_dir.rglob("*"))
            if path.is_file()
        },
    )
    return bundle
