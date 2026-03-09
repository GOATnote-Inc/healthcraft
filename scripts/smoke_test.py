"""HEALTHCRAFT smoke test.

Validates that task YAML definitions load correctly, conform to the JSON
schema, and that the core world-state and rubric-scoring machinery works.

Usage:
    python scripts/smoke_test.py
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve project root so imports work when invoked from any directory.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

TASK_DIR = PROJECT_ROOT / "configs" / "tasks"
TASK_SCHEMA_PATH = PROJECT_ROOT / "configs" / "schemas" / "task.schema.json"
WORLD_SCHEMA_PATH = PROJECT_ROOT / "configs" / "schemas" / "world_config.schema.json"
WORLD_CONFIG_PATH = PROJECT_ROOT / "configs" / "world" / "mercy_point_v1.yaml"


def _load_schema(path: Path) -> dict:
    """Load a JSON Schema file."""
    return json.loads(path.read_text(encoding="utf-8"))


def _stringify_keys(obj):
    """Recursively convert all dict keys to strings.

    YAML parses numeric keys (0.0, 0.25, etc.) as floats, but JSON Schema
    patternProperties expects string keys.
    """
    if isinstance(obj, dict):
        return {str(k): _stringify_keys(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stringify_keys(item) for item in obj]
    return obj


def _validate_yaml_against_schema(yaml_data: dict, schema: dict, source: str) -> list[str]:
    """Validate a parsed YAML dict against a JSON Schema.

    Returns a list of error strings (empty if valid).
    """
    try:
        import jsonschema
    except ImportError:
        return [f"{source}: jsonschema not installed, skipping schema validation"]

    # Convert float keys to strings for JSON Schema compatibility
    normalized = _stringify_keys(yaml_data)

    errors: list[str] = []
    validator = jsonschema.Draft202012Validator(schema)
    for error in validator.iter_errors(normalized):
        path = ".".join(str(p) for p in error.absolute_path) or "(root)"
        errors.append(f"{source} [{path}]: {error.message}")
    return errors


def smoke_test() -> bool:
    """Run the full smoke test suite. Returns True if all checks pass."""
    import yaml

    from healthcraft.entities.encounters import generate_encounter
    from healthcraft.entities.patients import generate_patient
    from healthcraft.tasks.loader import load_tasks
    from healthcraft.tasks.rubrics import DIMENSIONS, compute_weighted_score
    from healthcraft.world.state import WorldState
    from healthcraft.world.timeline import SimulationClock

    passed = 0
    failed = 0
    warnings = 0

    def check(label: str, condition: bool, detail: str = "") -> None:
        nonlocal passed, failed
        status = "PASS" if condition else "FAIL"
        msg = f"  [{status}] {label}"
        if detail:
            msg += f" -- {detail}"
        print(msg)
        if condition:
            passed += 1
        else:
            failed += 1

    def warn(label: str, detail: str = "") -> None:
        nonlocal warnings
        msg = f"  [WARN] {label}"
        if detail:
            msg += f" -- {detail}"
        print(msg)
        warnings += 1

    print("=" * 70)
    print("HEALTHCRAFT Smoke Test")
    print("=" * 70)

    # ------------------------------------------------------------------
    # 1. Load all task YAML files
    # ------------------------------------------------------------------
    print("\n--- Task Loading ---")
    check("Task directory exists", TASK_DIR.exists(), str(TASK_DIR))

    task_files = sorted(TASK_DIR.rglob("*.yaml"))
    check("Task YAML files found", len(task_files) > 0, f"found {len(task_files)}")

    tasks = load_tasks(TASK_DIR)
    check("Tasks loaded without fatal errors", len(tasks) > 0, f"loaded {len(tasks)} tasks")

    # Print task inventory
    print("\n  Task inventory:")
    for task in tasks:
        print(f"    {task.id:10s}  L{task.level}  {task.category:30s}  {task.title}")

    # ------------------------------------------------------------------
    # 2. Validate tasks against JSON Schema
    # ------------------------------------------------------------------
    print("\n--- Schema Validation ---")
    schema_exists = TASK_SCHEMA_PATH.exists()
    check("Task schema exists", schema_exists, str(TASK_SCHEMA_PATH))

    if schema_exists:
        task_schema = _load_schema(TASK_SCHEMA_PATH)
        schema_errors: list[str] = []
        tasks_validated = 0

        for task_file in task_files:
            raw = yaml.safe_load(task_file.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                schema_errors.append(f"{task_file.name}: not a YAML mapping")
                continue
            errs = _validate_yaml_against_schema(raw, task_schema, task_file.name)
            if errs:
                schema_errors.extend(errs)
            else:
                tasks_validated += 1

        check(
            "All tasks pass schema validation",
            len(schema_errors) == 0,
            f"{tasks_validated}/{len(task_files)} valid",
        )
        if schema_errors:
            for err in schema_errors[:10]:
                print(f"    ERROR: {err}")
            if len(schema_errors) > 10:
                print(f"    ... and {len(schema_errors) - 10} more errors")

    # Validate world config schema
    world_schema_exists = WORLD_SCHEMA_PATH.exists()
    check("World config schema exists", world_schema_exists, str(WORLD_SCHEMA_PATH))

    # ------------------------------------------------------------------
    # 3. Create WorldState with seed=42
    # ------------------------------------------------------------------
    print("\n--- World State ---")
    start_time = datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
    world = WorldState(start_time=start_time)
    check("WorldState created", world is not None, repr(world))
    check("WorldState timestamp correct", world.timestamp == start_time)

    # ------------------------------------------------------------------
    # 4. Generate sample patients and encounters
    # ------------------------------------------------------------------
    print("\n--- Entity Generation ---")
    rng = random.Random(42)
    clock = SimulationClock(start_time=start_time)

    patients = []
    for i in range(10):
        patient = generate_patient(rng)
        world.put_entity("patient", patient.id, patient)
        patients.append(patient)

    patient_count = len(world.list_entities("patient"))
    check("Patients generated", patient_count == 10, f"{patient_count} patients in world")

    encounters = []
    for patient in patients:
        encounter = generate_encounter(rng, patient, condition_id=None, clock=clock)
        world.put_entity("encounter", encounter.id, encounter)
        encounters.append(encounter)

    encounter_count = len(world.list_entities("encounter"))
    check("Encounters generated", encounter_count == 10, f"{encounter_count} encounters in world")

    # Verify entity properties
    sample_patient = patients[0]
    check(
        "Patient has required fields",
        bool(sample_patient.id and sample_patient.mrn and sample_patient.first_name),
        f"id={sample_patient.id}, mrn={sample_patient.mrn}, "
        f"name={sample_patient.first_name} {sample_patient.last_name}",
    )

    sample_encounter = encounters[0]
    check(
        "Encounter has required fields",
        bool(
            sample_encounter.id and sample_encounter.patient_id and sample_encounter.chief_complaint
        ),
        f"id={sample_encounter.id}, cc={sample_encounter.chief_complaint}",
    )
    check(
        "Encounter has initial vitals",
        len(sample_encounter.vitals) > 0,
        f"{len(sample_encounter.vitals)} vital sign set(s)",
    )

    # Verify determinism
    rng2 = random.Random(42)
    patient_2 = generate_patient(rng2)
    check(
        "Entity generation is deterministic",
        patient_2.id == patients[0].id and patient_2.mrn == patients[0].mrn,
        f"seed=42 reproduces {patient_2.id}",
    )

    # ------------------------------------------------------------------
    # 5. Verify rubric scoring
    # ------------------------------------------------------------------
    print("\n--- Rubric Scoring ---")
    check(
        "Rubric has 6 dimensions",
        len(DIMENSIONS) == 6,
        f"found {len(DIMENSIONS)}: {[d.name for d in DIMENSIONS]}",
    )

    weights_sum = sum(d.weight for d in DIMENSIONS)
    check(
        "Dimension weights sum to 1.0",
        abs(weights_sum - 1.0) < 0.001,
        f"sum={weights_sum:.3f}",
    )

    # Perfect score
    perfect_scores = {d.name: 1.0 for d in DIMENSIONS}
    perfect_total = compute_weighted_score(perfect_scores)
    check(
        "Perfect score computes to 1.0",
        abs(perfect_total - 1.0) < 0.001,
        f"total={perfect_total:.3f}",
    )

    # Zero safety score triggers safety gate
    safety_zero_scores = {d.name: 1.0 for d in DIMENSIONS}
    safety_zero_scores["safety"] = 0.0
    safety_total = compute_weighted_score(safety_zero_scores)
    check(
        "Safety gate: safety=0.0 zeroes total",
        safety_total == 0.0,
        f"total={safety_total:.3f}",
    )

    # Partial scores
    partial_scores = {
        "clinical_completeness": 0.75,
        "clinical_correctness": 0.50,
        "protocol_adherence": 0.75,
        "documentation_quality": 0.50,
        "safety": 1.0,
        "temporal_sequencing": 0.75,
    }
    partial_total = compute_weighted_score(partial_scores)
    check(
        "Partial score is in valid range",
        0.0 < partial_total < 1.0,
        f"total={partial_total:.3f}",
    )

    # Verify task rubrics have all 6 dimensions
    tasks_with_full_rubric = 0
    for task in tasks:
        dim_names = set(task.rubric.keys())
        expected = {d.name for d in DIMENSIONS}
        if expected.issubset(dim_names):
            tasks_with_full_rubric += 1
        else:
            missing = expected - dim_names
            warn(f"Task {task.id} missing rubric dimensions", f"missing: {missing}")

    check(
        "All tasks have complete rubrics (6 dimensions)",
        tasks_with_full_rubric == len(tasks),
        f"{tasks_with_full_rubric}/{len(tasks)} complete",
    )

    # ------------------------------------------------------------------
    # 6. Verify task metadata
    # ------------------------------------------------------------------
    print("\n--- Task Metadata ---")
    categories_found = {task.category for task in tasks}
    check(
        "Multiple categories represented",
        len(categories_found) >= 3,
        f"categories: {sorted(categories_found)}",
    )

    levels_found = {task.level for task in tasks}
    check(
        "Multiple difficulty levels represented",
        len(levels_found) >= 3,
        f"levels: {sorted(levels_found)}",
    )

    tasks_with_tools = sum(1 for t in tasks if t.expected_tools)
    check(
        "All tasks specify expected tools",
        tasks_with_tools == len(tasks),
        f"{tasks_with_tools}/{len(tasks)} have tools",
    )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("SMOKE TEST SUMMARY")
    print(f"  Tasks loaded:         {len(tasks)}")
    print(f"  Entities generated:   {patient_count} patients, {encounter_count} encounters")
    print(
        f"  Scoring verified:     perfect={perfect_total:.1f}, "
        f"safety_gate={safety_total:.1f}, partial={partial_total:.3f}"
    )
    print(f"  Checks passed:        {passed}")
    print(f"  Checks failed:        {failed}")
    print(f"  Warnings:             {warnings}")
    print(f"  Result:               {'ALL PASS' if failed == 0 else 'FAILURES DETECTED'}")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = smoke_test()
    sys.exit(0 if success else 1)
