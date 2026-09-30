"""Transfer heuristics must not invent observation order or numeric certainty."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from healthcraft.entities.base import EntityType
from healthcraft.entities.encounters import Encounter, VitalSigns
from healthcraft.mcp.server import create_server
from healthcraft.mcp.tools.workflow_tools import _assess_stabilization
from healthcraft.tasks.inject import inject_task_patient
from healthcraft.tasks.loader import load_task
from healthcraft.world.state import WorldState

EARLIER = "2026-01-15T08:00:00Z"
LATER = "2026-01-15T09:00:00Z"


def reading(timestamp=LATER, **changes):
    return SimpleNamespace(
        **{
            "timestamp": timestamp,
            "heart_rate": 80,
            "systolic_bp": 120,
            "spo2": 98,
            "gcs": 15,
            **changes,
        }
    )


def assessed(*observations):
    return _assess_stabilization(SimpleNamespace(vitals=observations))


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("latest_stable", [False, True])
def test_transfer_uses_actual_latest_observation_in_either_storage_order(reverse, latest_stable):
    now = datetime(2026, 1, 15, 10, tzinfo=timezone.utc)
    world = WorldState(start_time=now)
    observations = [
        VitalSigns(
            timestamp=datetime(2026, 1, 15, 8, tzinfo=timezone.utc),
            heart_rate=80,
            systolic_bp=70 if latest_stable else 120,
            spo2=98,
            gcs=15,
        ),
        VitalSigns(
            timestamp=datetime(2026, 1, 15, 9, tzinfo=timezone.utc),
            heart_rate=80,
            systolic_bp=120 if latest_stable else 70,
            spo2=98,
            gcs=15,
        ),
    ]
    if reverse:
        observations.reverse()
    encounter = Encounter(
        id="ENC-12345678",
        entity_type=EntityType.ENCOUNTER,
        created_at=now,
        updated_at=now,
        patient_id="PAT-12345678",
        vitals=tuple(observations),
    )
    world.put_entity("encounter", encounter.id, encounter)
    response = create_server(world).call_tool(
        "processTransfer",
        {
            "encounter_id": encounter.id,
            "destination_facility": "University Medical Center",
            "reason": "Synthetic offline contract test",
            "clinical_summary": "Synthetic record",
        },
    )
    assert response["status"] == "ok", response
    assert response["data"]["emtala_compliant"] is latest_stable
    transfer = next(iter(world.list_entities("transfer").values()))
    assert transfer.emtala_compliant is latest_stable
    assert world.audit_log[-1].result_summary == "ok"


@pytest.mark.parametrize(
    "timestamp", [None, "unknown", "2026-01-15", "08:00", "2026-01-15T08:00:00"]
)
def test_any_unresolved_observation_time_prevents_claiming_latest(timestamp):
    assert assessed(reading(timestamp), reading(LATER)) is False


@pytest.mark.parametrize(
    "status",
    [
        "missing",
        "date_only",
        "time_only",
        "naive",
        "unresolved",
        "invalid",
        "unsupported",
        "conflicting",
    ],
)
def test_timing_provenance_cannot_be_overridden_by_parseable_timestamp(status):
    assert assessed(reading(EARLIER, timing_status=status), reading(LATER)) is False


@pytest.mark.parametrize("status", ["", "explicit"])
def test_explicit_and_legacy_timing_are_supported(status):
    assert assessed(reading(timing_status=status)) is True


def test_equal_instants_allow_duplicate_agreement_but_not_conflicting_latest_values():
    same_in_offset = "2026-01-15T06:00:00-03:00"
    assert assessed(reading(LATER), reading(same_in_offset)) is True
    assert assessed(reading(LATER), reading(same_in_offset, heart_rate=90)) is False


def test_fractional_precision_determines_latest_without_microsecond_rounding():
    assert (
        assessed(
            reading("2026-01-15T09:00:00.0000001Z", systolic_bp=70),
            reading("2026-01-15T09:00:00.0000000Z"),
        )
        is False
    )


@pytest.mark.parametrize("field", ["heart_rate", "systolic_bp", "spo2", "gcs"])
@pytest.mark.parametrize("value", [None, "80", "3T", True, float("nan"), float("inf")])
def test_missing_or_nonfinite_nonnumeric_measurements_cannot_certify_stability(field, value):
    assert assessed(reading(**{field: value})) is False


def test_absent_observations_and_fully_unknown_reading_are_not_stable():
    assert assessed() is False
    assert assessed(VitalSigns(timestamp=datetime.now(timezone.utc))) is False


@pytest.mark.parametrize(
    "changes",
    [
        {"heart_rate": 49},
        {"heart_rate": 141},
        {"systolic_bp": 79},
        {"spo2": 87},
        {"gcs": 8},
    ],
)
def test_existing_instability_thresholds_are_preserved(changes):
    assert assessed(reading(**changes)) is False


def test_existing_threshold_boundaries_are_preserved_without_new_medical_rules():
    assert assessed(reading(heart_rate=50, systolic_bp=80, spo2=88, gcs=9)) is True
    assert assessed(reading(heart_rate=140)) is True


def test_transfer_handles_authored_qualified_gcs_without_numeric_coercion_or_crash():
    task = load_task(
        Path("configs/tasks/safety_critical_judgment/task_016_hipaa_breach_trauma.yaml")
    )
    assert task.patient["vitals"]["gcs"] == "3T"
    world = WorldState()
    ids = inject_task_patient(world, task.id, task.patient, task.initial_state)
    response = create_server(world).call_tool(
        "processTransfer",
        {
            "encounter_id": ids["encounter_id"],
            "destination_facility": "University Medical Center",
            "reason": "Offline source-type contract test",
        },
    )
    assert response["status"] == "ok", response
    assert response["data"]["emtala_compliant"] is False
    assert len(world.list_entities("transfer")) == 1
