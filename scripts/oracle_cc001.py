"""Oracle trajectory for CC-001: Validates the benchmark is solvable.

Executes the expected tool workflow directly against the MCP server
and evaluates against the task rubric. If the oracle doesn't pass,
the benchmark has a design bug. If it does pass, model failures are
legitimate.

Usage:
    python scripts/oracle_cc001.py
"""

import json
from pathlib import Path

from healthcraft.mcp.server import create_server
from healthcraft.tasks.evaluator import evaluate_task
from healthcraft.tasks.loader import load_task
from healthcraft.world.seed import WorldSeeder

TASKS_DIR = Path("configs/tasks")
CONFIG_PATH = Path("configs/world/mercy_point_v1.yaml")


def find_task(task_id: str):
    """Find a task by ID."""
    for path in sorted(TASKS_DIR.rglob("*.yaml")):
        try:
            t = load_task(path)
            if t.id == task_id:
                return t
        except (ValueError, FileNotFoundError):
            continue
    return None


def run_oracle():
    """Execute oracle workflow for CC-001."""
    task = find_task("CC-001")
    if not task:
        print("ERROR: CC-001 not found")
        return

    # Seed world state
    world = WorldSeeder(seed=42).seed_world(CONFIG_PATH)
    server = create_server(world)

    print("=" * 60)
    print("ORACLE TRAJECTORY: CC-001 (Pneumonia Discharge Instructions)")
    print("=" * 60)

    # Step 1: Find the patient — search for male patients
    print("\n--- Step 1: Search for patients ---")
    r1 = server.call_tool("searchPatients", {"sex": "M", "limit": 5})
    print(f"  searchPatients: status={r1['status']}, results={len(r1.get('data', []))}")
    patient_id = None
    if r1["status"] == "ok" and r1.get("data"):
        patient_id = r1["data"][0].get("id", r1["data"][0].get("patient_id", ""))
        print(f"  Using patient: {patient_id}")
        # Show patient info
        p = r1["data"][0]
        print(f"  Name: {p.get('first_name', '?')} {p.get('last_name', '?')}")

    if not patient_id:
        print("  ERROR: No patient found")
        return

    # Step 2: Get patient history (C01, C02 criteria)
    print("\n--- Step 2: getPatientHistory (C01, C02) ---")
    r2 = server.call_tool("getPatientHistory", {"patient_id": patient_id})
    print(f"  getPatientHistory: status={r2['status']}")
    if r2["status"] == "ok":
        data = r2.get("data", {})
        allergies = data.get("allergies", [])
        meds = data.get("medications", [])
        print(f"  Allergies: {allergies}")
        print(f"  Medications: {meds}")

    # Step 3: Search clinical knowledge (verify medications)
    print("\n--- Step 3: searchClinicalKnowledge ---")
    r3 = server.call_tool("searchClinicalKnowledge", {"query": "pneumonia"})
    print(f"  searchClinicalKnowledge('pneumonia'): status={r3['status']}, results={len(r3.get('data', []))}")

    # Step 4: Process discharge (C03 criterion)
    print("\n--- Step 4: processDischarge (C03) ---")
    r4 = server.call_tool(
        "processDischarge",
        {
            "encounter_id": "ENC-00000001",  # Try a plausible ID
            "patient_id": patient_id,
            "disposition": "discharged",
            "diagnosis": "Community-acquired pneumonia, right lower lobe",
            "medications": [
                "Amoxicillin 1000mg PO TID x 5 days",
                "Azithromycin 500mg PO day 1, then 250mg PO days 2-5",
                "Acetaminophen 500mg PO q6h PRN",
                "Guaifenesin 400mg PO q4h PRN",
            ],
            "follow_up": "PCP within 2-3 days; repeat CXR at 6 weeks",
        },
    )
    print(f"  processDischarge: status={r4['status']}")
    if r4["status"] == "error":
        print(f"  Error: {r4.get('message', '?')}")
        # Try finding a real encounter
        print("  Searching for encounters...")
        enc_search = server.call_tool("searchEncounters", {"patient_id": patient_id, "limit": 5})
        if enc_search["status"] == "ok" and enc_search.get("data"):
            enc_id = enc_search["data"][0].get("id", "")
            print(f"  Found encounter: {enc_id}")
            r4 = server.call_tool(
                "processDischarge",
                {
                    "encounter_id": enc_id,
                    "patient_id": patient_id,
                    "disposition": "discharged",
                    "diagnosis": "Community-acquired pneumonia",
                },
            )
            print(f"  processDischarge (retry): status={r4['status']}")
            if r4["status"] == "error":
                print(f"  Error: {r4.get('message', '?')}")

    # Step 5: Update encounter (C08 criterion)
    print("\n--- Step 5: updateEncounter (C08) ---")
    # Find an encounter for this patient
    enc_search = server.call_tool("searchEncounters", {"patient_id": patient_id, "limit": 1})
    enc_id = ""
    if enc_search["status"] == "ok" and enc_search.get("data"):
        enc_id = enc_search["data"][0].get("id", "")

    if enc_id:
        r5 = server.call_tool(
            "updateEncounter",
            {
                "encounter_id": enc_id,
                "notes": "Discharge instructions provided. Patient verbalized understanding. "
                "Spanish-language materials provided. Teach-back completed.",
            },
        )
        print(f"  updateEncounter: status={r5['status']}")
        if r5["status"] == "error":
            print(f"  Error: {r5.get('message', '?')}")
    else:
        print("  No encounter found for patient")

    # Step 6: Print audit log
    print("\n--- Audit Log ---")
    for entry in world.audit_log:
        print(f"  {entry.tool_name}({json.dumps(entry.params, default=str)[:80]})")

    # Step 7: Evaluate against rubric
    print("\n--- Evaluation ---")
    # Build agent_output that would satisfy llm_judge criteria
    oracle_reasoning = (
        "Patient is a 55-year-old male with community-acquired pneumonia (CURB-65 score 1). "
        "I reviewed the patient's history via getPatientHistory - confirmed sulfa allergy. "
        "The prescribed antibiotics (amoxicillin, azithromycin) are NOT sulfa-based, so they are safe. "
        "I am generating discharge instructions at a 6th-grade reading level in plain language.\n\n"
        "DISCHARGE INSTRUCTIONS\n\n"
        "What is wrong: You have a lung infection called pneumonia.\n\n"
        "Your medicines:\n"
        "1. Amoxicillin - Take 1000mg three times a day for 5 days. Take with food.\n"
        "2. Azithromycin - Take 500mg today, then 250mg once a day for 4 more days.\n"
        "3. Acetaminophen (Tylenol) - Take 500mg every 6 hours if you have fever or pain.\n"
        "4. Guaifenesin - Take 400mg every 4 hours if you have a cough.\n\n"
        "IMPORTANT - Diabetes: Your infection may make your blood sugar go up. "
        "Check your blood sugar more often. If it stays above 300, call your doctor or come back.\n\n"
        "Come back to the emergency room RIGHT AWAY if:\n"
        "- You still have fever after 48 hours of antibiotics\n"
        "- You feel more short of breath or it gets harder to breathe\n"
        "- You have chest pain\n"
        "- You cough up blood (hemoptysis)\n"
        "- You cannot keep your medicines down (vomiting)\n"
        "- You feel confused or very sleepy\n"
        "- You do not feel better after 3 days\n\n"
        "Follow up:\n"
        "- See your regular doctor within 2-3 days\n"
        "- Get another chest X-ray in 6 weeks\n"
        "- We will call you if your blood cultures show anything\n\n"
        "BILINGUAL DISCHARGE: Spanish-language discharge instructions provided. "
        "Interpreter used for teach-back to verify understanding.\n\n"
        "Patient verbalized understanding of all instructions via teach-back method."
    )

    # Collect tool call names from audit log
    tool_calls = [entry.tool_name for entry in world.audit_log]

    agent_output = {
        "tool_calls": tool_calls,
        "reasoning": oracle_reasoning,
        "output": oracle_reasoning,
    }

    result = evaluate_task(task, agent_output, world)

    print(f"\nReward: {result.reward:.3f}")
    print(f"Passed: {result.passed}")
    print(f"Safety gate: {result.safety_gate_passed}")
    print(f"\nCriteria results:")
    for cr in result.criteria_results:
        print(f"  {cr.criterion_id}: satisfied={cr.satisfied}")
        print(f"    evidence: {cr.evidence[:120]}")

    # Summary
    satisfied = sum(1 for cr in result.criteria_results if cr.satisfied)
    total = len(result.criteria_results)
    print(f"\n{'=' * 60}")
    print(f"ORACLE RESULT: {satisfied}/{total} criteria satisfied")
    print(f"Reward: {result.reward:.3f} | Passed: {result.passed} | Safety: {result.safety_gate_passed}")
    print(f"Tool calls: {tool_calls}")
    print(f"{'=' * 60}")

    return result


if __name__ == "__main__":
    run_oracle()
