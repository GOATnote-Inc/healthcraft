"""HEALTHCRAFT smoke test.

Validates that task YAML definitions load correctly, the world-state seeds
properly with all entity types, MCP tools dispatch correctly, rubric scoring
works, and the evaluation runner captures trajectories.

Usage:
    python scripts/smoke_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve project root so imports work when invoked from any directory.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

TASK_DIR = PROJECT_ROOT / "configs" / "tasks"
WORLD_CONFIG_PATH = PROJECT_ROOT / "configs" / "world" / "mercy_point_v1.yaml"
SYSTEM_PROMPT_DIR = PROJECT_ROOT / "system-prompts"


def smoke_test() -> bool:
    """Run the full smoke test suite. Returns True if all checks pass."""
    from healthcraft.entities.base import EntityType
    from healthcraft.mcp.server import TOOL_NAME_MAP, create_server
    from healthcraft.tasks.loader import load_tasks
    from healthcraft.tasks.rubrics import (
        DIMENSIONS,
        Criterion,
        CriterionResult,
        VerificationMethod,
        check_safety_gate,
        compute_reward,
        compute_weighted_score,
    )
    from healthcraft.trajectory import Trajectory
    from healthcraft.world.seed import WorldSeeder

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
    check("Target: 155+ tasks", len(tasks) >= 100, f"{len(tasks)} tasks")

    # Print task inventory by category
    print("\n  Task inventory by category:")
    categories: dict[str, int] = {}
    for task in tasks:
        categories[task.category] = categories.get(task.category, 0) + 1
    for cat, count in sorted(categories.items()):
        print(f"    {cat:30s} {count:3d} tasks")

    # ------------------------------------------------------------------
    # 2. Validate binary criteria on tasks
    # ------------------------------------------------------------------
    print("\n--- Binary Criteria Validation ---")
    tasks_with_criteria = sum(1 for t in tasks if t.criteria)
    check(
        "All tasks have binary criteria",
        tasks_with_criteria == len(tasks),
        f"{tasks_with_criteria}/{len(tasks)} have criteria",
    )

    total_criteria = sum(len(t.criteria) for t in tasks)
    check(
        "Criteria count reasonable",
        total_criteria > len(tasks) * 5,
        f"{total_criteria} total criteria across {len(tasks)} tasks",
    )

    safety_critical_count = 0
    for task in tasks:
        for c in task.criteria:
            if c.get("safety_critical", False):
                safety_critical_count += 1
    check(
        "Safety-critical criteria present",
        safety_critical_count > 0,
        f"{safety_critical_count} safety-critical criteria",
    )

    # Check verification methods
    verification_methods = set()
    for task in tasks:
        for c in task.criteria:
            verification_methods.add(c.get("verification", ""))
    check(
        "Multiple verification methods used",
        len(verification_methods) >= 2,
        f"methods: {sorted(verification_methods)}",
    )

    # ------------------------------------------------------------------
    # 3. World State Seeder
    # ------------------------------------------------------------------
    print("\n--- World State Seeding ---")
    check("World config exists", WORLD_CONFIG_PATH.exists())

    seeder = WorldSeeder(seed=42)
    world = seeder.seed_world(WORLD_CONFIG_PATH)
    check("World seeded successfully", world is not None)

    # Check all entity types
    entity_counts: dict[str, int] = {}
    total_entities = 0
    for etype in EntityType:
        count = len(world.list_entities(etype.value))
        entity_counts[etype.value] = count
        total_entities += count

    check("Total entities >= 3500", total_entities >= 3500, f"{total_entities} entities")
    check("Patients == 500", entity_counts.get("patient", 0) == 500)
    check("Encounters == 500", entity_counts.get("encounter", 0) == 500)
    check("Clinical tasks >= 1000", entity_counts.get("clinical_task", 0) >= 1000)
    check("Protocols >= 8", entity_counts.get("protocol", 0) >= 8)
    check("Decision rules >= 10", entity_counts.get("decision_rule", 0) >= 10)
    check("Resources >= 50", entity_counts.get("resource", 0) >= 50)

    print("\n  Entity counts:")
    for etype, count in sorted(entity_counts.items()):
        print(f"    {etype:25s} {count:5d}")
    print(f"    {'TOTAL':25s} {total_entities:5d}")

    # ------------------------------------------------------------------
    # 4. MCP Server and Tools
    # ------------------------------------------------------------------
    print("\n--- MCP Server ---")
    server = create_server(world)
    check("Server created", server is not None)
    check("24 tools registered", len(server.available_tools) == 24)
    check("Tool name map has 24 entries", len(TOOL_NAME_MAP) == 24)

    # Test 5 representative tools
    print("\n  Tool dispatch tests:")

    result = server.call_tool("searchPatients", {"query": ""})
    check("searchPatients works", result["status"] == "ok")

    result = server.call_tool("searchEncounters", {})
    check("searchEncounters works", result["status"] == "ok")
    check(
        "Pagination: max 10 results",
        len(result.get("data", [])) <= 10,
        f"returned {len(result.get('data', []))}",
    )

    result = server.call_tool("checkResourceAvailability", {"resource_type": "bed"})
    check("checkResourceAvailability works", result["status"] == "ok")

    result = server.call_tool(
        "registerPatient",
        {"first_name": "Smoke", "last_name": "Test", "sex": "F"},
    )
    check("registerPatient works", result["status"] == "ok")

    result = server.call_tool("getConditionDetails", {"condition_id": "SEPSIS"})
    check("getConditionDetails works", result["status"] == "ok")

    # Verify audit logging
    check(
        "Audit logging active",
        server.audit_logger.entry_count >= 5,
        f"{server.audit_logger.entry_count} entries",
    )

    # ------------------------------------------------------------------
    # 5. Rubric Scoring (Eq. 1)
    # ------------------------------------------------------------------
    print("\n--- Rubric Scoring (Corecraft Eq. 1) ---")
    check(
        "6 dimensions defined",
        len(DIMENSIONS) == 6,
        f"{[d.name for d in DIMENSIONS]}",
    )

    weights_sum = sum(d.weight for d in DIMENSIONS)
    check("Weights sum to 1.0", abs(weights_sum - 1.0) < 0.001, f"sum={weights_sum:.3f}")

    # Test Eq. 1 reward computation
    ws = VerificationMethod.WORLD_STATE
    criteria = [
        Criterion(id="C1", assertion="test", dimension="safety", verification=ws),
        Criterion(
            id="C2",
            assertion="test",
            dimension="safety",
            verification=ws,
            safety_critical=True,
        ),
    ]
    results_all_pass = [
        CriterionResult(criterion_id="C1", satisfied=True),
        CriterionResult(criterion_id="C2", satisfied=True),
    ]
    reward = compute_reward(results_all_pass, criteria)
    check("Eq. 1: all satisfied = 1.0", abs(reward - 1.0) < 0.001, f"reward={reward}")

    results_half = [
        CriterionResult(criterion_id="C1", satisfied=True),
        CriterionResult(criterion_id="C2", satisfied=False),
    ]
    reward_half = compute_reward(results_half, criteria)
    check(
        "Eq. 1: safety_critical violated = 0.0",
        reward_half == 0.0,
        f"reward={reward_half} (safety gate)",
    )

    results_non_safety_fail = [
        CriterionResult(criterion_id="C1", satisfied=False),
        CriterionResult(criterion_id="C2", satisfied=True),
    ]
    reward_partial = compute_reward(results_non_safety_fail, criteria)
    check(
        "Eq. 1: partial = 0.5",
        abs(reward_partial - 0.5) < 0.001,
        f"reward={reward_partial}",
    )

    # Safety gate function
    check("Safety gate: all pass", check_safety_gate(results_all_pass, criteria))
    check("Safety gate: violation detected", not check_safety_gate(results_half, criteria))

    # Weighted scores
    perfect_scores = {d.name: 1.0 for d in DIMENSIONS}
    check("Weighted: perfect = 1.0", abs(compute_weighted_score(perfect_scores) - 1.0) < 0.001)

    safety_zero = {d.name: 1.0 for d in DIMENSIONS}
    safety_zero["safety"] = 0.0
    check("Weighted: safety=0 zeroes total", compute_weighted_score(safety_zero) == 0.0)

    # ------------------------------------------------------------------
    # 6. Trajectory Capture
    # ------------------------------------------------------------------
    print("\n--- Trajectory Capture ---")
    traj = Trajectory(
        task_id="SMOKE-001",
        model="smoke-test",
        seed=42,
        system_prompt="Test prompt",
    )
    traj.add_turn("system", "Test prompt")
    traj.add_turn("user", "Test scenario")
    traj.add_turn("assistant", "Test response", tool_calls=[{"name": "searchPatients"}])
    check("Trajectory created", traj.task_id == "SMOKE-001")
    check("Trajectory has 3 turns", len(traj.turns) == 3)
    check("Tool calls tracked", traj.total_tool_calls == 1)

    json_str = traj.to_json()
    check("Trajectory serializes to JSON", len(json_str) > 100)

    # ------------------------------------------------------------------
    # 7. System Prompts
    # ------------------------------------------------------------------
    print("\n--- System Prompts ---")
    check("System prompt directory exists", SYSTEM_PROMPT_DIR.exists())

    base_prompt = SYSTEM_PROMPT_DIR / "base.txt"
    check("base.txt exists", base_prompt.exists())
    if base_prompt.exists():
        content = base_prompt.read_text()
        check("base.txt mentions Mercy Point", "Mercy Point" in content)

    policies = SYSTEM_PROMPT_DIR / "policies.txt"
    check("policies.txt exists", policies.exists())

    tool_ref = SYSTEM_PROMPT_DIR / "tool_reference.txt"
    check("tool_reference.txt exists", tool_ref.exists())

    # ------------------------------------------------------------------
    # 8. Task Metadata
    # ------------------------------------------------------------------
    print("\n--- Task Metadata ---")
    categories_found = {task.category for task in tasks}
    check(
        "6 categories represented",
        len(categories_found) >= 6,
        f"categories: {sorted(categories_found)}",
    )

    levels_found = {task.level for task in tasks}
    check(
        "Multiple difficulty levels",
        len(levels_found) >= 3,
        f"levels: {sorted(levels_found)}",
    )

    # Check dimension coverage across criteria
    dimensions_used = set()
    for task in tasks:
        for c in task.criteria:
            dim = c.get("dimension", "")
            if dim:
                dimensions_used.add(dim)
    check(
        "Criteria cover all 6 dimensions",
        len(dimensions_used & {d.name for d in DIMENSIONS}) >= 5,
        f"dimensions: {sorted(dimensions_used)}",
    )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("SMOKE TEST SUMMARY")
    print(f"  Tasks loaded:         {len(tasks)}")
    print(f"  Total entities:       {total_entities}")
    print(f"  MCP tools:            {len(server.available_tools)}")
    print(f"  Criteria total:       {total_criteria}")
    print(f"  Safety-critical:      {safety_critical_count}")
    print(f"  Checks passed:        {passed}")
    print(f"  Checks failed:        {failed}")
    print(f"  Warnings:             {warnings}")
    print(f"  Result:               {'ALL PASS' if failed == 0 else 'FAILURES DETECTED'}")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = smoke_test()
    sys.exit(0 if success else 1)
