"""Actual in-process retrieval witnesses for six ungraded roster profiles."""

from __future__ import annotations

import hashlib
import platform
import sys
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from healthcraft.llm.checkpoint import content_digest, environment_digest
from healthcraft.mcp.server import create_server
from healthcraft.tasks.history_execution import ExecutionRecorder
from healthcraft.tasks.loader import load_task
from healthcraft.tasks.roster_certificate import verify_roster_retrieval
from healthcraft.tasks.roster_profile import (
    PROFILE_VERSION,
    build_roster_profile,
    supported_roster_tasks,
)
from healthcraft.world.seed import WorldSeeder
from healthcraft.world.state import WorldState

ROOT = Path(__file__).resolve().parents[3]
WORLD_PATH = ROOT / "configs/world/mercy_point_v1.yaml"
TASK_PATHS = {
    "CC-022": "clinical_communication/task_022_nurse_delegation.yaml",
    "CC-027": "clinical_communication/task_027_ambulance_diversion.yaml",
    "CC-028": "clinical_communication/task_028_surge_capacity.yaml",
    "IR-018": "information_retrieval/task_018_supply_shortage.yaml",
    "IR-023": "information_retrieval/task_023_shortage_impact.yaml",
    "IR-025": "information_retrieval/task_025_multi_patient_triage.yaml",
}
_LIMITATIONS = (
    "Engineering-authored, in-process tool witnesses for an opt-in source-observation profile. "
    "No model calls, clinical correctness, prioritization, treatment, safety, patient outcomes, "
    "network MCP transport, or full-task solvability are evaluated. Every benchmark criterion "
    "remains unassessed. Source assessments are not clinical ground truth. Recorded hashes "
    "detect content drift; they do not authenticate third-party evidence."
)


def _provenance() -> dict:
    files = set((ROOT / "src/healthcraft").rglob("*.py"))
    files.update((ROOT / "configs/world").rglob("*.yaml"))
    files.update((ROOT / "configs/tasks").rglob("*.yaml"))
    files.update((ROOT / "configs/schemas").rglob("*.json"))
    for relative in (
        "configs/mcp-tools.json",
        "configs/em_vocab.yaml",
        "configs/schemas/task.schema.json",
        "scripts/certify_roster_tasks.py",
        "pyproject.toml",
        "requirements-lock.txt",
    ):
        path = ROOT / relative
        if path.exists():
            files.add(path)
    source_hashes = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(files)
    }
    packages = {}
    for name in ("healthcraft", "pyyaml", "jsonschema", "openem", "mcp"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    runtime = {
        "python_version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "cache_tag": sys.implementation.cache_tag,
        "system": platform.system(),
        "machine": platform.machine(),
        "packages": packages,
    }
    return {
        "source_hashes": source_hashes,
        "source_sha256": content_digest(source_hashes),
        "runtime": runtime,
        "runtime_sha256": content_digest(runtime),
        "environment_sha256": environment_digest(ROOT),
    }


def execute_roster_reference(recorder: ExecutionRecorder, *, roster: list[dict[str, str]]) -> None:
    """Retrieve both record surfaces with only patient/encounter IDs as input.

    Returned identity, linkage, and cross-tool consistency are transport checks;
    the independent verifier decides whether the returned observations match
    authored source fields. No expected observations enter this controller.
    """
    if not isinstance(roster, list) or not roster:
        raise ValueError("Reference controller requires a nonempty roster of IDs only")
    patients, encounters = set(), set()
    for member in roster:
        if (
            not isinstance(member, dict)
            or set(member) != {"patient_id", "encounter_id"}
            or any(not isinstance(value, str) or not value for value in member.values())
        ):
            raise ValueError("Reference controller accepts patient and encounter IDs only")
        patient_id, encounter_id = member["patient_id"], member["encounter_id"]
        if patient_id in patients or encounter_id in encounters:
            raise ValueError("Reference controller requires distinct roster IDs only")
        patients.add(patient_id)
        encounters.add(encounter_id)
    for member in roster:
        patient_id, encounter_id = member["patient_id"], member["encounter_id"]
        detail = recorder.call("getEncounterDetails", {"encounter_id": encounter_id})
        history = recorder.call("getPatientHistory", {"patient_id": patient_id})
        for response in (detail, history):
            if (
                not isinstance(response, dict)
                or response.get("status") != "ok"
                or not isinstance(response.get("data"), dict)
            ):
                raise ValueError(
                    f"Roster retrieval returned a failed or missing response: {encounter_id}"
                )
        encounter, patient = detail["data"], history["data"]
        if (
            encounter.get("id") != encounter_id
            or encounter.get("patient_id") != patient_id
            or patient.get("id") != patient_id
            or not isinstance(patient.get("encounter_ids"), list)
            or encounter_id not in patient["encounter_ids"]
        ):
            raise ValueError(f"Roster retrieval response identity/link mismatch: {encounter_id}")
        observations = encounter.get("authored_observations")
        if (
            not isinstance(observations, dict)
            or not observations
            or content_digest(observations) != content_digest(patient.get("authored_observations"))
        ):
            raise ValueError(
                f"Roster response observations are missing or inconsistent: {encounter_id}"
            )


def _execute_task(task_id: str, *, world: WorldState | None, seed: int) -> dict:
    if task_id not in TASK_PATHS:
        raise ValueError(f"Unsupported roster task: {task_id}")
    task_path = ROOT / "configs/tasks" / TASK_PATHS[task_id]
    task = load_task(task_path)
    supplied_world = world is not None
    if world is None:
        world = WorldSeeder(seed=seed).seed_world(WORLD_PATH)
    context = build_roster_profile(world, task)
    recorder = ExecutionRecorder(create_server(world), world)
    execute_roster_reference(
        recorder,
        roster=[
            {key: member[key] for key in ("patient_id", "encounter_id")}
            for member in context["roster"]
        ],
    )
    calls = recorder.calls
    return {
        "task_id": task_id,
        "task_source": str(task_path.relative_to(ROOT)),
        "task_sha256": hashlib.sha256(task_path.read_bytes()).hexdigest(),
        "profile_version": PROFILE_VERSION,
        "world_preparation": "caller_supplied" if supplied_world else "seeded_mercy_point",
        "seed": None if supplied_world else seed,
        "world_time": world.timestamp.isoformat(),
        "context": context,
        "calls": calls,
        "trace_sha256": content_digest(calls),
        "verification": verify_roster_retrieval(task, context, calls, world),
        "benchmark_score": None,
    }


def run_roster_reference(task_id: str, *, world: WorldState | None = None, seed: int = 42) -> dict:
    """Execute one source-bound witness with optional caller-supplied test world."""
    before = _provenance()
    report = _execute_task(task_id, world=world, seed=seed)
    after = _provenance()
    if before != after:
        raise ValueError("Reference provenance changed during execution")
    report.update(
        schema_version="healthcraft-roster-reference/v1",
        execution_kind="in_process_mcp_handlers",
        provenance_before=before,
        provenance_after=after,
        limitations=_LIMITATIONS,
    )
    return report


def run_roster_references(
    *, seed: int = 42, world_factory: Callable[[], WorldState] | None = None
) -> dict:
    """Execute the whole registered six-task cohort under unchanged provenance."""
    if tuple(TASK_PATHS) != supported_roster_tasks():
        raise ValueError("Reference cohort differs from the registered roster profile")
    before = _provenance()
    reports, supplied_worlds = [], []
    for task_id in supported_roster_tasks():
        world = None if world_factory is None else world_factory()
        if world_factory is not None:
            if not isinstance(world, WorldState) or any(world is old for old in supplied_worlds):
                raise ValueError("Each reference task requires a fresh WorldState")
            supplied_worlds.append(world)
        reports.append(_execute_task(task_id, world=world, seed=seed))
    after = _provenance()
    if before != after:
        raise ValueError("Cohort provenance changed during execution")
    return {
        "schema_version": "healthcraft-roster-reference-cohort/v1",
        "kind": "roster_reference_cohort",
        "execution_kind": "in_process_mcp_handlers",
        "profile_version": PROFILE_VERSION,
        "task_ids": list(TASK_PATHS),
        "tasks": reports,
        "total_members": sum(len(report["context"]["roster"]) for report in reports),
        "total_tool_calls": sum(len(report["calls"]) for report in reports),
        "mechanical_passed": all(report["verification"]["mechanical_passed"] for report in reports),
        "benchmark_score": None,
        "coverage": {
            "measured_clinical_criteria": 0,
            "measured_safety_criteria": 0,
            "unassessed_criteria": [
                cid
                for report in reports
                for cid in report["verification"]["coverage"]["unassessed_criteria"]
            ],
        },
        "provenance_before": before,
        "provenance_after": after,
        "limitations": _LIMITATIONS,
    }
