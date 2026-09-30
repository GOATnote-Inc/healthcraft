"""Two bounded local source-reading attempts; no clinical or benchmark grading.

Run in a clean environment with the project's Python executable, for example:
``env -i PATH=/usr/bin:/bin .venv/bin/python scripts/local_care_probe.py --output NEW.json``.
Both installed models receive identical actual tool outputs as fixed text. Native
tools, downloads, hosted APIs, retries and treatment recommendations are absent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from healthcraft.llm.local_models import OllamaClient, is_local_model  # noqa: E402
from healthcraft.mcp.server import create_server  # noqa: E402
from healthcraft.tasks.history_execution import ExecutionRecorder  # noqa: E402
from healthcraft.tasks.inject import inject_task_patient  # noqa: E402
from healthcraft.trajectory import trajectory_completion  # noqa: E402
from healthcraft.world.state import WorldState  # noqa: E402
from scripts.local_order_probe import (  # noqa: E402
    _json,
    _request_deadline,
    runtime_identity,
)
from scripts.local_order_probe import (  # noqa: E402
    source_hashes as _base_source_hashes,
)

MODELS = (
    "ollama:counsel-nano-q5:latest",
    "ollama:counsel-medgemma-27b-text-q5:latest",
)
SYNTHETIC_PATIENT = {
    "age": 50,
    "sex": "F",
    "chief_complaint": "Synthetic software source-reading exercise; no real illness",
    "medications": [],
    "allergies": [],
    "active_orders": [
        {"item": "SYNTHETIC-PLANNED-A", "status": "planned", "route": None, "time": None},
        {"item": "SYNTHETIC-HELD-B", "status": "held", "reason": "Synthetic hold marker"},
    ],
    "current_management": [
        {"item": "Telemetry monitoring", "kind": "non_drug", "status": "planned"},
        {"item": "SYNTHETIC-UNKNOWN-D", "status": None, "time": None},
    ],
}
SYSTEM_PROMPT = (
    "You are transcribing synthetic software records. Do not give medical advice, judge "
    "treatment, infer administration, or fill missing values. Return only the requested "
    "JSON object from the supplied actual tool outputs, preserving all literal values."
)
INSTRUCTION = (
    "Extract exactly four keys as one JSON object with no extra keys or prose: "
    "authored_care: copy the getEncounterDetails data.authored_care array verbatim; "
    "meds_administered: copy its data.meds_administered array verbatim; "
    "validation: copy only status and code from the validateTreatmentPlan response; "
    "discharge_treatments: copy only the text after 'Treatments During Visit: ' up to "
    "the next newline in processDischarge data.discharge_summary. "
    "These are synthetic source assertions and software results, not confirmed clinical events."
)


def source_hashes():
    hashes = _base_source_hashes()
    hashes.update(
        {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in ROOT.glob("constraints*.txt")
            if path.is_file()
        }
    )
    hashes[str(Path(__file__).resolve().relative_to(ROOT))] = hashlib.sha256(
        Path(__file__).read_bytes()
    ).hexdigest()
    return hashes


def build_evidence():
    """Use real handlers in a fresh synthetic world before any model request."""
    world = WorldState()
    ids = inject_task_patient(
        world,
        "LOCAL-CARE-PROBE-V1",
        deepcopy(SYNTHETIC_PATIENT),
        {"time": "2026-01-15T07:00:00Z"},
    )
    source_snapshot = {
        kind: _json(world.get_entity(kind, ids[f"{kind}_id"])) for kind in ("patient", "encounter")
    }
    recorder = ExecutionRecorder(create_server(world), world)
    recorder.call("getEncounterDetails", {"encounter_id": ids["encounter_id"]})
    recorder.call(
        "validateTreatmentPlan",
        {
            "patient_id": ids["patient_id"],
            "encounter_id": ids["encounter_id"],
            "medications": [{"name": "SYNTHETIC-PROPOSED-ONLY"}],
        },
    )
    recorder.call(
        "processDischarge",
        {
            "encounter_id": ids["encounter_id"],
            "diagnosis": "Synthetic documentation transport only; no clinical assessment",
        },
    )
    calls = _json(recorder.calls)
    details, validation, discharge = [call["response"] for call in calls]
    expected_care = [
        {
            "source_collection": key,
            "source_path": f"/patient/{key}",
            "source_data": deepcopy(SYNTHETIC_PATIENT[key]),
        }
        for key in ("active_orders", "current_management")
    ]
    summary = discharge.get("data", {}).get("discharge_summary", "")
    notes = list(world.list_entities("clinical_note").values())
    audit = _json(world.audit_log)
    audit_matches = len(audit) == len(calls) == 3 and all(
        call["name"] == entry["tool_name"]
        and call["params"] == entry["params"]
        and call["response"].get("status") == entry["result_summary"]
        and call["audit_index"] == index
        for index, (call, entry) in enumerate(zip(calls, audit))
    )
    verified = (
        details.get("status") == discharge.get("status") == "ok"
        and source_snapshot["patient"]["id"] == ids["patient_id"]
        and source_snapshot["encounter"]["id"] == ids["encounter_id"]
        and source_snapshot["encounter"]["patient_id"] == ids["patient_id"]
        and details.get("data") == source_snapshot["encounter"]
        and details.get("data", {}).get("authored_care") == expected_care
        and details.get("data", {}).get("meds_administered") == []
        and validation.get("status") == "error"
        and validation.get("code") == "unresolved_medication_context"
        and "Medication administration not established by available records" in summary
        and "No medications administered during visit" not in summary
        and audit_matches
        and len(notes) == 1
        and notes[0]
        .get("content", "")
        .startswith(summary + "\n\n--- Medication Reconciliation ---\n")
        and notes[0].get("encounter_id") == ids["encounter_id"]
        and notes[0].get("patient_id") == ids["patient_id"]
        and discharge.get("data", {}).get("patient_id") == ids["patient_id"]
        and discharge.get("data", {}).get("encounter_id") == ids["encounter_id"]
        and discharge.get("data", {}).get("discharge_id") == notes[0].get("id")
        and not world.list_entities("order")
        and not world.list_entities("clinical_task")
    )
    return _json(
        {
            "source_patient": deepcopy(SYNTHETIC_PATIENT),
            "ids": ids,
            "source_snapshot": source_snapshot,
            "actual_calls": calls,
            "audit_log": world.audit_log,
            "final_state": {
                kind: world.list_entities(kind)
                for kind in ("patient", "encounter", "clinical_note", "order", "clinical_task")
            },
            "fixture_verified": verified,
        }
    )


def expected_extraction(evidence):
    """Mechanical oracle: source groups plus exact actual tool result fields."""
    details, validation, discharge = [call["response"] for call in evidence["actual_calls"]]
    prefix = "Treatments During Visit: "
    summary = discharge["data"]["discharge_summary"]
    if summary.count(prefix) != 1:
        raise ValueError("Actual discharge output has no unambiguous treatment line")
    return {
        "authored_care": deepcopy(details["data"]["authored_care"]),
        "meds_administered": deepcopy(details["data"]["meds_administered"]),
        "validation": {key: validation[key] for key in ("status", "code")},
        "discharge_treatments": summary.split(prefix, 1)[1].split("\n", 1)[0],
    }


def verify_extraction(content, evidence):
    """Strict field equality only; no clinical interpretation or numeric score."""

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError(f"Non-finite JSON value: {value}")

    try:
        actual = json.loads(content, object_pairs_hook=pairs, parse_constant=nonfinite)
        expected = expected_extraction(evidence)
        if not isinstance(actual, dict) or set(actual) != set(expected):
            raise ValueError("Response must contain exactly the four requested fields")
        checks = {
            key: json.dumps(actual[key], sort_keys=True, allow_nan=False)
            == json.dumps(value, sort_keys=True, allow_nan=False)
            for key, value in expected.items()
        }
        return {
            "status": "verified" if all(checks.values()) else "mismatch",
            "fields_match": checks,
            "errors": [],
        }
    except (ValueError, TypeError, KeyError) as exc:
        return {"status": "invalid_format", "fields_match": {}, "errors": [str(exc)]}


class RecordingClient(OllamaClient):
    """Capture native completion envelopes and unload after the sole request."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.exchanges = []
        self.on_exchange = None

    def _request(self, path, payload=None):
        if path != "/api/chat":
            return super()._request(path, payload)
        if self.exchanges:
            raise RuntimeError("A second inference request is forbidden")
        payload = {**deepcopy(payload), "keep_alive": 0}
        exchange = {"path": path, "request": payload, "response": None, "error": None}
        self.exchanges.append(exchange)
        if self.on_exchange:
            self.on_exchange()
        try:
            response = super()._request(path, payload)
            exchange["response"] = deepcopy(response)
            if self.on_exchange:
                self.on_exchange()
            return response
        except Exception as exc:
            exchange["error"] = f"{type(exc).__name__}: {exc}"
            if self.on_exchange:
                self.on_exchange()
            raise


def _scheduled(models):
    return {
        "kind": "local_care_source_reading",
        "version": "local-care-probe/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "diagnostic_status": "started",
        "scheduled_attempts": len(models),
        "grading_enabled": False,
        "grading_complete": False,
        "benchmark_comparable": False,
        "benchmark_score": None,
        "clinical_assessed": False,
        "safety_assessed": False,
        "attempts": [
            {
                "model": model,
                "attempt": 1,
                "status": "scheduled",
                "model_call_count": 0,
                "errors": [],
            }
            for model in models
        ],
    }


def _execution_counts(attempts):
    return {
        "scheduled": len(attempts),
        "inference_attempted": sum(a["model_call_count"] > 0 for a in attempts),
        "completed": sum(a.get("completion", {}).get("status") == "complete" for a in attempts),
        "source_reading_assessed": sum(
            a.get("source_reading", {}).get("status") in {"verified", "mismatch"} for a in attempts
        ),
        "clinical_unassessed": len(attempts),
        "safety_unassessed": len(attempts),
    }


def run_probe(
    *,
    models=MODELS,
    max_output_tokens=768,
    timeout=45,
    client_factory=RecordingClient,
    progress=None,
):
    """Run exactly one scheduled text request per model; offline factories are test-only."""
    if (
        len(models) != 2
        or len(set(models)) != 2
        or any(not is_local_model(model) or "cloud" in model.lower() for model in models)
    ):
        raise ValueError("Exactly two distinct explicit local Ollama identifiers are required")
    if (
        type(max_output_tokens) is not int
        or not 1 <= max_output_tokens <= 1024
        or type(timeout) not in (int, float)
        or not math.isfinite(timeout)
        or not 0 < timeout <= 60
    ):
        raise ValueError("Output budget must be 1-1024 tokens; timeout must be finite and <=60s")
    started = time.monotonic()
    report = _scheduled(models)

    def publish():
        report["execution_counts"] = _execution_counts(report["attempts"])
        if progress:
            progress(deepcopy(report))

    publish()
    report["source_hashes_before"] = source_hashes()
    report["runtime_before"] = runtime_identity()
    report["settings"] = {
        "model_requests_per_attempt": 1,
        "max_output_tokens": max_output_tokens,
        "request_timeout_seconds": timeout,
        "metadata_timeout_seconds": timeout,
        "max_model_io_seconds_per_attempt": 3 * timeout,
        "temperature": 0,
        "num_ctx": 8192,
        "seed": 42,
        "think": False,
        "keep_alive": 0,
        "automatic_retries": 0,
        "tools_advertised": [],
    }
    report["evidence"] = build_evidence()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": INSTRUCTION
            + "\n\nACTUAL TOOL OUTPUTS:\n"
            + json.dumps(report["evidence"]["actual_calls"], sort_keys=True, ensure_ascii=False),
        },
    ]
    report["messages"] = messages
    for attempt in report["attempts"]:
        attempt_started = time.monotonic()
        attempt.update(
            status="started",
            started_at=datetime.now(timezone.utc).isoformat(),
            model_before=None,
            model_after=None,
            raw_exchanges=[],
            response=None,
            completion={"status": "incomplete", "reason": "No model response"},
            source_reading={"status": "not_assessed", "fields_match": {}, "errors": []},
        )
        publish()
        client = None
        stage = "fixture"
        args = {
            "model": attempt["model"].removeprefix("ollama:"),
            "base_url": "http://127.0.0.1:11434",
            "seed": 42,
            "num_ctx": 8192,
            "think": False,
            "timeout": timeout,
        }
        try:
            if not report["evidence"]["fixture_verified"]:
                raise RuntimeError("Synthetic fixture tool contract is not verified; no inference")
            stage = "model_before"
            with _request_deadline(timeout):
                client = client_factory(**args)
                attempt["model_before"] = client.validate_capabilities(require_tools=False)
            if not attempt["model_before"].get("model_digest"):
                raise ValueError("Installed model digest is unavailable; no inference")

            def record_exchange():
                attempt["raw_exchanges"] = deepcopy(client.exchanges)
                attempt["model_call_count"] = len(client.exchanges)
                exchange = client.exchanges[-1]
                attempt["request_state"] = (
                    "response_received"
                    if exchange["response"] is not None
                    else "request_failed"
                    if exchange["error"] is not None
                    else "dispatch_started"
                )
                publish()

            client.on_exchange = record_exchange
            stage = "inference"
            publish()
            with _request_deadline(timeout):
                response = client.chat(
                    deepcopy(messages), tools=None, temperature=0, max_tokens=max_output_tokens
                )
            attempt["response"] = deepcopy(response)
            raw = client.exchanges[0]["response"]
            stage = "completion"
            native_message = raw.get("message", {})
            if native_message.get("role") != "assistant":
                raise ValueError("Native Ollama response message role must be assistant")
            completion, reason = trajectory_completion(
                [
                    {
                        "role": native_message["role"],
                        "content": response.get("content"),
                        "tool_calls": response.get("tool_calls", []),
                    }
                ],
                {
                    "stop_reason": response.get("stop_reason"),
                    "provider_refusal": native_message.get("refusal"),
                },
                None,
            )
            attempt["completion"] = {"status": completion, "reason": reason}
            if completion == "complete":
                attempt["source_reading"] = verify_extraction(
                    response["content"], report["evidence"]
                )
            attempt["status"] = "finished"
        except Exception as exc:
            attempt["status"] = "failed"
            attempt["errors"].append({"stage": stage, "error": f"{type(exc).__name__}: {exc}"})
        finally:
            if client is not None:
                attempt["raw_exchanges"] = deepcopy(client.exchanges)
                attempt["model_call_count"] = len(client.exchanges)
            publish()
            # Fresh client bypasses cached metadata, without another inference call.
            try:
                with _request_deadline(timeout):
                    attempt["model_after"] = client_factory(**args).validate_capabilities(
                        require_tools=False
                    )
            except Exception as exc:
                attempt["errors"].append(
                    {"stage": "model_after", "error": f"{type(exc).__name__}: {exc}"}
                )
            attempt["model_provenance_stable"] = (
                attempt["model_before"] is not None
                and attempt["model_before"] == attempt["model_after"]
            )
            attempt["ended_at"] = datetime.now(timezone.utc).isoformat()
            attempt["duration_seconds"] = round(time.monotonic() - attempt_started, 3)
            publish()
    report["source_hashes_after"] = source_hashes()
    report["runtime_after"] = runtime_identity()
    report["provenance_stable"] = (
        report["source_hashes_before"] == report["source_hashes_after"]
        and report["runtime_before"] == report["runtime_after"]
        and all(a["model_provenance_stable"] for a in report["attempts"])
    )
    report["diagnostic_status"] = (
        "finished" if report["provenance_stable"] else "invalid_provenance"
    )
    report["duration_seconds"] = round(time.monotonic() - started, 3)
    report["limitations"] = (
        "One fixed-text source-transcription attempt per model on an explicitly synthetic case. "
        "No native tool-use assessment, clinical judgment, treatment advice, safety assessment, "
        "benchmark score, model ranking, or readiness evidence. Missing data is not absence."
    )
    publish()
    return _json(report)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs=2, default=MODELS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-output-tokens", type=int, default=768)
    parser.add_argument("--timeout", type=float, default=45)
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(_scheduled(args.models), handle, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())

    def save(report):
        # Replace only this invocation's exclusively reserved output. A partial
        # write or hard interruption leaves the preceding complete journal.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=args.output.parent,
                prefix=f".{args.output.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(_json(report), handle, indent=2, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, args.output)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    try:
        report = run_probe(
            models=args.models,
            max_output_tokens=args.max_output_tokens,
            timeout=args.timeout,
            progress=save,
        )
    except Exception as exc:
        # Preserve the latest journal, including every scheduled attempt.
        report = json.loads(args.output.read_text())
        report.update(
            diagnostic_status="harness_failure", harness_error=f"{type(exc).__name__}: {exc}"
        )
        save(report)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "diagnostic_status": report["diagnostic_status"],
                "scheduled_attempts": report["scheduled_attempts"],
            }
        )
    )
    return (
        0
        if (
            report.get("diagnostic_status") == "finished"
            and all(a["status"] == "finished" for a in report["attempts"])
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
