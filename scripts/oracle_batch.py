"""Batch oracle: per-task world_state satisfiability on a seeded+injected world.

Generalizes ``scripts/oracle_cc001.py`` from a single hand-crafted walkthrough
to an automated, per-task diagnostic. For each task requested via ``--tasks``
(or ``--all``), this script:

  1. Seeds a fresh world at seed=42 and injects the task's patient/encounter.
  2. Walks the task's ``world_state`` criteria and dispatches each referenced
     tool with minimally valid parameters, pulling real entity IDs from the
     seeded+injected world when possible.
  3. Evaluates the resulting audit log against the task rubric and prints a
     one-line summary per task plus an aggregate.

Use it when authoring or refactoring tasks: if a world_state criterion is
unsolvable with a "perfect" tool-call sequence, the criterion itself has a
design bug -- not the model.

Limitations:
  * ``llm_judge`` criteria are NOT evaluated by this oracle; it focuses on the
    deterministic channel. The per-task reward printed is world_state-only.
  * Qualifier-bound tools (e.g. createClinicalOrder with a specific
    ``order_type``) are exercised with the qualifier value when detectable;
    free-form ``_match`` qualifiers are best-effort.
  * Hand-crafted oracle walkthroughs for individual tasks (e.g.
    ``scripts/oracle_cc001.py``) remain useful for exercising the judge
    channel and should not be replaced by this automation.

Usage:
    python scripts/oracle_batch.py --tasks CC-001,MW-013,SCJ-002
    python scripts/oracle_batch.py --all
    python scripts/oracle_batch.py --tasks CR-001 --verbose
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from healthcraft.mcp.server import create_server  # noqa: E402
from healthcraft.tasks.evaluator import (  # noqa: E402
    _expand_tool_alternatives,
    _extract_tool_and_params,
    _parse_criteria,
    _split_compound,
    evaluate_task,
)
from healthcraft.tasks.inject import inject_task_patient  # noqa: E402
from healthcraft.tasks.loader import Task, load_tasks  # noqa: E402
from healthcraft.tasks.rubrics import VerificationMethod  # noqa: E402
from healthcraft.world.seed import WorldSeeder  # noqa: E402
from healthcraft.world.state import WorldState  # noqa: E402

TASK_DIR = PROJECT_ROOT / "configs" / "tasks"
WORLD_CONFIG = PROJECT_ROOT / "configs" / "world" / "mercy_point_v1.yaml"


# ---------------------------------------------------------------------------
# Tool parameter templates — minimal valid inputs per tool.
# Entity-id placeholders (PATIENT_ID, ENCOUNTER_ID) are substituted per task.
# ---------------------------------------------------------------------------

_PARAM_TEMPLATES: dict[str, dict[str, Any]] = {
    "searchEncounters": {},
    "searchPatients": {},
    "searchClinicalKnowledge": {"query": "chest pain"},
    "searchReferenceMaterials": {"query": "aspirin"},
    "searchAvailableResources": {"resource_type": "bed"},
    "getEncounterDetails": {"encounter_id": "<ENCOUNTER_ID>"},
    "getConditionDetails": {"condition_name": "pneumonia"},
    "getPatientHistory": {"patient_id": "<PATIENT_ID>"},
    "getProtocolDetails": {"protocol_name": "sepsis_bundle"},
    "getTransferStatus": {},
    "getInsuranceCoverage": {"patient_id": "<PATIENT_ID>"},
    "getReferenceArticle": {"article_id": "REF-001"},
    "checkResourceAvailability": {"resource_type": "bed"},
    "calculateTransferTime": {"destination_facility": "General Hospital"},
    "runDecisionRule": {"rule_name": "qSOFA", "variables": {"sbp": 90}},
    "validateTreatmentPlan": {"patient_id": "<PATIENT_ID>"},
    "createClinicalOrder": {
        "encounter_id": "<ENCOUNTER_ID>",
        "order_type": "lab",
        "details": {"test": "CBC"},
    },
    "updateTaskStatus": {"task_id": "<TASK_ID>", "status": "pending"},
    "updateEncounter": {"encounter_id": "<ENCOUNTER_ID>", "notes": "oracle"},
    "updatePatientRecord": {
        "patient_id": "<PATIENT_ID>",
        "allergies": ["oracle"],
    },
    "registerPatient": {"first_name": "Oracle", "last_name": "Patient"},
    "applyProtocol": {
        "encounter_id": "<ENCOUNTER_ID>",
        "protocol_name": "sepsis_bundle",
    },
    "processDischarge": {
        "encounter_id": "<ENCOUNTER_ID>",
        "diagnosis": "oracle diagnosis",
    },
    "processTransfer": {
        "encounter_id": "<ENCOUNTER_ID>",
        "destination_facility": "General Hospital",
        "reason": "oracle",
    },
}


@dataclass
class TaskOracleResult:
    task_id: str
    world_state_total: int
    world_state_satisfied: int
    reward: float
    passed: bool
    safety_gate_passed: bool
    unsatisfied_criteria: list[str]


# ---------------------------------------------------------------------------
# Per-task oracle
# ---------------------------------------------------------------------------


def _referenced_tools(task: Task) -> list[tuple[str, dict[str, str]]]:
    """Collect (camelCase_tool, qualifier_params) pairs from world_state checks."""
    tools: list[tuple[str, dict[str, str]]] = []
    tool_name_lookup = {name.lower(): name for name in _PARAM_TEMPLATES}
    for crit in _parse_criteria(task.criteria):
        if crit.verification != VerificationMethod.WORLD_STATE:
            continue
        expanded = _expand_tool_alternatives(crit.check)
        clauses = _split_compound(expanded, "AND")
        if len(clauses) == 1:
            clauses = _split_compound(expanded, "OR")
        for clause in clauses:
            lower = clause.lower()
            # Skip negations — the agent should NOT call these.
            if "does not contain" in lower or "not contain" in lower:
                continue
            if "contains" not in lower:
                continue
            tool_lc, params = _extract_tool_and_params(lower, "contains")
            camel = tool_name_lookup.get(tool_lc)
            if camel:
                tools.append((camel, params))
    return tools


def _materialize_params(
    tool: str,
    qualifier_params: dict[str, str],
    patient_id: str,
    encounter_id: str,
) -> dict[str, Any]:
    """Substitute <PATIENT_ID>, <ENCOUNTER_ID> placeholders and apply qualifiers."""
    template = _PARAM_TEMPLATES.get(tool, {})
    materialized: dict[str, Any] = {}
    for k, v in template.items():
        if v == "<PATIENT_ID>":
            materialized[k] = patient_id or "PAT-00000000"
        elif v == "<ENCOUNTER_ID>":
            materialized[k] = encounter_id or "ENC-00000000"
        elif v == "<TASK_ID>":
            materialized[k] = "TSK-00000000"
        else:
            materialized[k] = v
    # Overlay any structured qualifier (e.g. order_type=lab from "for lab").
    for key, val in qualifier_params.items():
        if not key.startswith("_"):
            materialized[key] = val
    return materialized


def _first_encounter_id(world: WorldState) -> str:
    encounters = world.list_entities("encounter") or {}
    for eid, _ in encounters.items():
        return eid
    return ""


def _first_patient_id(world: WorldState) -> str:
    patients = world.list_entities("patient") or {}
    for pid, _ in patients.items():
        return pid
    return ""


def run_oracle(task: Task, verbose: bool = False) -> TaskOracleResult:
    world = WorldSeeder(seed=42).seed_world(WORLD_CONFIG)
    injected: dict[str, str] = {}
    if task.patient:
        try:
            injected = inject_task_patient(world, task.id, task.patient, task.initial_state)
        except Exception as e:  # noqa: BLE001 — diagnostic tool
            if verbose:
                print(f"  inject_task_patient failed: {e}")

    patient_id = injected.get("patient_id", "") or _first_patient_id(world)
    encounter_id = injected.get("encounter_id", "") or _first_encounter_id(world)

    server = create_server(world)
    for tool, qualifier in _referenced_tools(task):
        params = _materialize_params(tool, qualifier, patient_id, encounter_id)
        try:
            result = server.call_tool(tool, params)
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"  {tool} raised: {e}")
            continue
        if verbose:
            code = result.get("code", "")
            print(f"  {tool} -> {result.get('status')} {code}")

    # Evaluate using an empty agent_output — llm_judge and pattern criteria
    # will fail, but world_state criteria reflect the audit log we built.
    agent_output = {
        "tool_calls": [e.tool_name for e in world.audit_log],
        "reasoning": "",
        "output": "",
    }
    eval_result = evaluate_task(task, agent_output, world)

    ws_crits = [
        c
        for c in _parse_criteria(task.criteria)
        if c.verification == VerificationMethod.WORLD_STATE
    ]
    ws_ids = {c.id for c in ws_crits}
    ws_results = [r for r in eval_result.criteria_results if r.criterion_id in ws_ids]
    satisfied = sum(1 for r in ws_results if r.satisfied)
    unsatisfied = [r.criterion_id for r in ws_results if not r.satisfied]

    return TaskOracleResult(
        task_id=task.id,
        world_state_total=len(ws_crits),
        world_state_satisfied=satisfied,
        reward=eval_result.reward,
        passed=eval_result.passed,
        safety_gate_passed=eval_result.safety_gate_passed,
        unsatisfied_criteria=unsatisfied,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--tasks",
        default="",
        help="Comma-separated task IDs (e.g. CC-001,MW-013,SCJ-002)",
    )
    parser.add_argument(
        "--all", action="store_true", help="Run oracle on every task in configs/tasks"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Print per-tool dispatch results"
    )
    args = parser.parse_args()

    all_tasks = {t.id: t for t in load_tasks(TASK_DIR)}
    if args.all:
        requested_ids = sorted(all_tasks)
    else:
        requested_ids = [t.strip() for t in args.tasks.split(",") if t.strip()]
    if not requested_ids:
        parser.error("Specify --tasks A,B,C or --all")

    missing = [tid for tid in requested_ids if tid not in all_tasks]
    if missing:
        print(f"Unknown task(s): {missing}")
        return 2

    results: list[TaskOracleResult] = []
    for tid in requested_ids:
        if args.verbose:
            print(f"\n=== {tid} ===")
        r = run_oracle(all_tasks[tid], verbose=args.verbose)
        results.append(r)
        line = (
            f"{r.task_id:12s} "
            f"world_state {r.world_state_satisfied}/{r.world_state_total:<3d}"
            f"  reward={r.reward:.3f}"
            f"  safety={'PASS' if r.safety_gate_passed else 'FAIL'}"
        )
        if r.unsatisfied_criteria and args.verbose:
            line += f"  unmet={r.unsatisfied_criteria}"
        print(line)

    # Aggregate
    total_ws = sum(r.world_state_total for r in results)
    satisfied_ws = sum(r.world_state_satisfied for r in results)
    full_solve = sum(1 for r in results if r.world_state_satisfied == r.world_state_total)
    safety_pass = sum(1 for r in results if r.safety_gate_passed)
    print(
        f"\nSummary: {len(results)} task(s) | "
        f"world_state {satisfied_ws}/{total_ws} | "
        f"{full_solve} fully-solvable | "
        f"{safety_pass} safety-gate-pass"
    )
    # Exit 0 if every task hit 100% world_state; otherwise 1 (diagnostic).
    return 0 if satisfied_ws == total_ws else 1


if __name__ == "__main__":
    sys.exit(main())
