"""Malformed completion receipts cannot turn missing/error evidence into success."""

from __future__ import annotations

from copy import deepcopy

import pytest

from healthcraft.reconciliation.execution import execute_reference, run_reconciliation_trial
from healthcraft.reconciliation.fixture import load_scenario
from healthcraft.reconciliation.oracle import load_expectations, verify_reconciliation
from healthcraft.reconciliation.service import ReconciliationSession


@pytest.fixture
def capture():
    scenario = load_scenario()
    return scenario, load_expectations(), run_reconciliation_trial(scenario=scenario)


@pytest.mark.parametrize("field", ["error", "controller_error"])
@pytest.mark.parametrize("value", [False, 0, "", [], {}, "failed", ["failure"]])
def test_malformed_error_receipt_is_provenance_failure(capture, field, value):
    scenario, expected, evidence = capture
    evidence["completion"][field] = value
    result = verify_reconciliation(scenario, expected, evidence)
    assert result["status"] == "provenance_error"
    assert result["checks"]["provenance"] is False
    assert result["checks"]["execution_complete"] is False
    assert result["mechanical_passed"] is False


@pytest.mark.parametrize("value", [None, False, [], {}, {"status": "running"}, {"status": True}])
def test_invalid_completion_shape_is_not_success(capture, value):
    scenario, expected, evidence = capture
    evidence["completion"] = value
    result = verify_reconciliation(scenario, expected, evidence)
    assert result["status"] == "provenance_error"
    assert result["mechanical_passed"] is False


@pytest.mark.parametrize(
    "completion",
    [
        {"status": "completed"},
        {"status": "completed", "error": None},
        {"status": "completed", "reason": "model_finish"},
        {"status": "completed", "error": None, "controller_error": None},
    ],
)
def test_normal_completion_absent_or_explicit_null_error_preserves_valid_result(
    capture, completion
):
    scenario, expected, evidence = capture
    baseline = verify_reconciliation(scenario, expected, evidence)
    evidence["completion"] = completion
    assert verify_reconciliation(scenario, expected, evidence) == baseline
    assert baseline["mechanical_passed"] is True


@pytest.mark.parametrize("status", ["completed", "failed", "interrupted"])
@pytest.mark.parametrize("field", ["error", "controller_error"])
def test_real_error_preserves_completed_actions_but_prevents_execution_complete(
    capture, status, field
):
    scenario, expected, evidence = capture
    evidence["completion"] = {
        "status": status,
        field: {"type": "RuntimeError", "message": "After successful write/readback"},
    }
    result = verify_reconciliation(scenario, expected, evidence)
    assert result["checks"]["provenance"] is True
    assert result["checks"]["persisted_action"] is True
    assert result["checks"]["readback"] is True
    assert result["checks"]["execution_complete"] is False


@pytest.mark.parametrize("status", ["failed", "interrupted"])
def test_incomplete_without_known_error_does_not_invent_one(capture, status):
    scenario, expected, evidence = capture
    evidence["completion"] = {"status": status}
    result = verify_reconciliation(scenario, expected, evidence)
    assert result["checks"]["provenance"] is True
    assert result["checks"]["persisted_action"] is True
    assert result["checks"]["execution_complete"] is False


def test_real_service_transport_failure_and_controller_error_remain_supported():
    import json

    scenario = load_scenario()
    session = ReconciliationSession(scenario=scenario, token="test-token")

    class Recorder:
        def call(self, name, params):
            status, response = session.handle(
                "POST",
                "/call",
                json.dumps({"name": name, "params": params}).encode(),
                "Bearer test-token",
            )
            assert status == 200
            return response

    execute_reference(Recorder(), target=deepcopy(scenario["target"]))
    session.handle("GET", "/unknown", authorization="Bearer test-token")
    evidence = session.finalize(
        "completed", error={"type": "ControllerError", "message": "Transport reported a failure."}
    )
    assert evidence["completion"]["controller_error"]
    result = verify_reconciliation(scenario, load_expectations(), evidence)
    assert result["checks"]["provenance"] is True
    assert result["checks"]["persisted_action"] is True
    assert result["checks"]["execution_complete"] is False
