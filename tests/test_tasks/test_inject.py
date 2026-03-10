"""Tests for task patient injection into world state."""

from __future__ import annotations

from pathlib import Path

import pytest

from healthcraft.tasks.inject import inject_task_patient
from healthcraft.world.seed import WorldSeeder

_CONFIG_PATH = Path(__file__).parents[2] / "configs" / "world" / "mercy_point_v1.yaml"


@pytest.fixture()
def seeded_world():
    """Create a fresh seeded world state."""
    return WorldSeeder(seed=42).seed_world(_CONFIG_PATH)


class TestInjectTaskPatient:
    """Tests for inject_task_patient."""

    def test_basic_injection(self, seeded_world):
        """Injected patient and encounter exist in world state."""
        patient_data = {
            "age": 62,
            "sex": "M",
            "allergies": ["Amiodarone (thyroid dysfunction)"],
            "medications": ["Metoprolol 50mg BID"],
            "chief_complaint": "Palpitations",
        }
        ids = inject_task_patient(seeded_world, "CC-002", patient_data)

        assert "patient_id" in ids
        assert "encounter_id" in ids

        patient = seeded_world.get_entity("patient", ids["patient_id"])
        assert patient is not None

        encounter = seeded_world.get_entity("encounter", ids["encounter_id"])
        assert encounter is not None

    def test_entity_ordering_patient_first(self, seeded_world):
        """Task patient appears FIRST in entity collection (before seeded patients)."""
        patient_data = {"age": 50, "sex": "F", "chief_complaint": "Chest pain"}
        ids = inject_task_patient(seeded_world, "TEST-001", patient_data)

        patients = list(seeded_world.list_entities("patient").keys())
        assert patients[0] == ids["patient_id"], (
            f"Task patient {ids['patient_id']} should be first, got {patients[0]}"
        )

    def test_entity_ordering_encounter_first(self, seeded_world):
        """Task encounter appears FIRST in entity collection."""
        patient_data = {"age": 50, "sex": "F", "chief_complaint": "Chest pain"}
        ids = inject_task_patient(seeded_world, "TEST-001", patient_data)

        encounters = list(seeded_world.list_entities("encounter").keys())
        assert encounters[0] == ids["encounter_id"], (
            f"Task encounter {ids['encounter_id']} should be first, got {encounters[0]}"
        )

    def test_search_finds_task_patient_first(self, seeded_world):
        """searchPatients returns task patient in first page of results."""
        from healthcraft.mcp.tools.read_tools import search_patients

        patient_data = {
            "age": 71,
            "sex": "F",
            "allergies": ["Penicillin (anaphylaxis)"],
            "chief_complaint": "Shortness of breath",
        }
        ids = inject_task_patient(seeded_world, "CC-003", patient_data)

        result = search_patients(seeded_world, {})
        assert result["status"] == "ok"
        assert result["data"][0]["id"] == ids["patient_id"]

    def test_allergies_preserved(self, seeded_world):
        """Patient allergies from task YAML are accessible via getPatientHistory."""
        from healthcraft.mcp.tools.read_tools import get_patient_history

        patient_data = {
            "age": 62,
            "sex": "M",
            "allergies": ["Amiodarone (thyroid dysfunction)"],
            "chief_complaint": "Palpitations",
        }
        ids = inject_task_patient(seeded_world, "CC-002", patient_data)

        result = get_patient_history(seeded_world, {"patient_id": ids["patient_id"]})
        assert result["status"] == "ok"
        allergies = result["data"]["allergies"]
        assert "Amiodarone (thyroid dysfunction)" in allergies

    def test_vitals_parsed(self, seeded_world):
        """Vitals from task YAML are accessible via getEncounterDetails."""
        from healthcraft.mcp.tools.read_tools import get_encounter_details

        patient_data = {
            "age": 62,
            "sex": "M",
            "chief_complaint": "Palpitations",
            "vitals": {
                "heart_rate": 142,
                "blood_pressure": "128/84",
                "respiratory_rate": 20,
                "spo2": 96,
                "temperature": 37.1,
            },
        }
        ids = inject_task_patient(seeded_world, "CC-002", patient_data)

        result = get_encounter_details(
            seeded_world, {"encounter_id": ids["encounter_id"]}
        )
        assert result["status"] == "ok"
        vitals = result["data"]["vitals"]
        assert len(vitals) >= 1
        assert vitals[0]["heart_rate"] == 142
        assert vitals[0]["systolic_bp"] == 128
        assert vitals[0]["diastolic_bp"] == 84

    def test_labs_parsed(self, seeded_world):
        """Labs from task YAML are accessible."""
        from healthcraft.mcp.tools.read_tools import get_encounter_details

        patient_data = {
            "age": 62,
            "sex": "M",
            "chief_complaint": "Palpitations",
            "labs": {
                "troponin_i": "0.02 ng/mL (normal <0.04)",
                "tsh": "0.15 mIU/L (low)",
            },
        }
        ids = inject_task_patient(seeded_world, "CC-002", patient_data)

        result = get_encounter_details(
            seeded_world, {"encounter_id": ids["encounter_id"]}
        )
        labs = result["data"]["labs"]
        assert len(labs) == 2
        lab_names = [lab["test_name"] for lab in labs]
        assert "Troponin I" in lab_names
        assert "Tsh" in lab_names

    def test_newborn_age_parsing(self, seeded_world):
        """Handles descriptive age strings like '0 minutes (newborn)'."""
        patient_data = {
            "age": "0 minutes (newborn)",
            "sex": "M",
            "chief_complaint": "Respiratory distress",
        }
        # Should not raise
        ids = inject_task_patient(seeded_world, "MW-030", patient_data)
        assert "patient_id" in ids

    def test_deterministic_ids(self, seeded_world):
        """Same task_id always produces same entity IDs."""
        patient_data = {"age": 50, "sex": "F", "chief_complaint": "Test"}
        ids1 = inject_task_patient(seeded_world, "CC-001", patient_data)

        world2 = WorldSeeder(seed=99).seed_world(_CONFIG_PATH)
        ids2 = inject_task_patient(world2, "CC-001", patient_data)

        assert ids1["patient_id"] == ids2["patient_id"]
        assert ids1["encounter_id"] == ids2["encounter_id"]

    def test_empty_patient_data(self, seeded_world):
        """Empty patient data returns empty dict without error."""
        result = inject_task_patient(seeded_world, "CC-001", {})
        assert result == {}

    def test_multiple_vitals_sets(self, seeded_world):
        """Multiple vitals (arrival, current, post-treatment) are all captured."""
        from healthcraft.mcp.tools.read_tools import get_encounter_details

        patient_data = {
            "age": 62,
            "sex": "M",
            "chief_complaint": "Palpitations",
            "vitals_on_arrival": {"heart_rate": 150, "blood_pressure": "140/90"},
            "vitals": {"heart_rate": 142, "blood_pressure": "128/84"},
            "vitals_post_diltiazem": {"heart_rate": 88, "blood_pressure": "118/72"},
        }
        ids = inject_task_patient(seeded_world, "CC-002", patient_data)

        result = get_encounter_details(
            seeded_world, {"encounter_id": ids["encounter_id"]}
        )
        vitals = result["data"]["vitals"]
        assert len(vitals) == 3, f"Expected 3 vitals sets, got {len(vitals)}"
