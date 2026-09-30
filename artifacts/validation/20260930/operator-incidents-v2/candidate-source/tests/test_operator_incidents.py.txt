"""Public-only v2 packets and structurally checked, unadjudicated reports."""

import hashlib
import importlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTED = ROOT / "artifacts/reconciliation/20260930/casebook-native-v2/run"
MODELS = ROOT / "artifacts/reconciliation/20260930/local-casebook-pilot-v1/run"
PROTOCOL = {"protocol_id": "dev-1", "purpose": "engineering_development"}
ASSIGNMENT = {"assignment_id": "assignment-1", "operator_id": "operator-1", "presentation": "raw"}


def api():
    return importlib.import_module("healthcraft.operator_incidents")


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False))


def source(tmp_path, *, model=False, case="REC2-008"):
    original = MODELS if model else SCRIPTED
    attempt = case + ("/medgemma" if model else "/designated")
    manifest = json.loads((original / "manifest.json").read_text())
    files = {
        name: digest
        for name, digest in manifest["files"].items()
        if name.startswith(attempt + "/") or name == case + "/case.json"
    }
    if model:
        files.update({name: manifest["files"][name] for name in ["plan.json", "cases.json"]})
    out = tmp_path / "source"
    out.mkdir()
    for name in files:
        p = out / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes((original / name).read_bytes())
    manifest["files"] = files
    if not model:
        manifest["roster"] = [r for r in manifest["roster"] if r["id"] == attempt]
    else:
        plan = json.loads((out / "plan.json").read_text())
        plan["roster"] = [r for r in plan["roster"] if r["id"] == attempt]
        write(out / "plan.json", plan)
        manifest["files"]["plan.json"] = sha(out / "plan.json")
    manifest["outcomes"] = [r for r in manifest["outcomes"] if r["id"] == attempt]
    write(out / "manifest.json", manifest)
    return out / "manifest.json", attempt


def repin(manifest):
    value = json.loads(manifest.read_text())
    value["files"] = {
        p.relative_to(manifest.parent).as_posix(): sha(p)
        for p in manifest.parent.rglob("*")
        if p.is_file() and p != manifest
    }
    write(manifest, value)


def build(tmp_path, monkeypatch, *, model=False, case="REC2-008", presentation="raw"):
    module = api()
    # Rendering is separately owned; these tests isolate the core content contract.
    monkeypatch.setattr(module, "_render", lambda packet, template: json.dumps([packet, template]))
    manifest, attempt = source(tmp_path, model=model, case=case)
    packet = module.build_incident_packet(
        manifest,
        tmp_path / "packet",
        expected_sha256=sha(manifest),
        selections={"opaque-1": attempt},
        protocol=PROTOCOL,
        assignment={**ASSIGNMENT, "presentation": presentation},
    )
    return module, packet, manifest


def test_real_incomplete_capture_public_projection_has_no_hidden_original(tmp_path, monkeypatch):
    module, packet, manifest = build(tmp_path, monkeypatch)
    row = packet["cases"][0]
    assert row["review_case_id"] == "opaque-1"
    assert row["documents"]["evidence"]["after"] is None
    assert row["availability"]["evidence"]["status"] == "available"
    assert row["documents"]["task"]["not_presented_to_original_agent"] is True
    assert row["documents"]["task"]["provenance"] == "retrospective_review_contract"
    assert row["assistance"] is None
    assert "expectations" not in row["documents"]
    assert "designated_control" not in row["documents"]["scenario"]
    assert "original_evidence" not in row["documents"]["runtime"]
    public = b"".join(
        p.read_bytes() for p in (tmp_path / "packet/public").rglob("*") if p.is_file()
    )
    assert b"REC2-008/designated" not in public and str(manifest).encode() not in public
    assert "original-execution.json" not in [p.name for p in (tmp_path / "packet").rglob("*")]
    loaded, receipt, raw = module.validate_incident_packet(tmp_path / "packet/manifest.json")
    assert (
        loaded == packet
        and receipt["packet_sha256"] == module.incident_response_template(packet)["packet_sha256"]
    )
    assert raw == (tmp_path / "packet/manifest.json").read_bytes()


def test_actual_model_context_and_error_are_not_recreated_or_hidden(tmp_path, monkeypatch):
    _, packet, manifest = build(tmp_path, monkeypatch, model=True, case="REC2-001")
    d = packet["cases"][0]["documents"]
    expected = json.loads((manifest.parent / "REC2-001/medgemma/public-context.json").read_text())
    assert d["task"] == expected
    original = json.loads((manifest.parent / "REC2-001/medgemma/receipt.json").read_text())
    assert d["runtime"]["receipt"] == original
    assert d["runtime"]["receipt"]["error"] is not None
    assert (
        d["runtime"]["journals"]["model"]
        == (manifest.parent / "REC2-001/medgemma/worker/model.jsonl").read_text()
    )


@pytest.mark.parametrize(
    "change",
    [
        "wrong_pin",
        "tamper",
        "unlisted",
        "symlink",
        "unknown",
        "duplicate",
        "empty",
        "case_collision",
        "inside_source",
        "existing",
    ],
)
def test_preflight_rejects_before_output(tmp_path, monkeypatch, change):
    module = api()
    monkeypatch.setattr(module, "_render", lambda p, t: "html")
    manifest, attempt = source(tmp_path)
    selection = {"opaque-1": attempt}
    output = tmp_path / "packet"
    pin = sha(manifest)
    if change == "wrong_pin":
        pin = "0" * 64
    elif change == "tamper":
        (manifest.parent / "REC2-008/designated/execution.json").write_text("{}")
    elif change == "unlisted":
        (manifest.parent / "extra").write_text("extra")
    elif change == "symlink":
        (manifest.parent / "link").symlink_to(manifest)
    elif change == "unknown":
        selection = {"opaque-1": "REC2-999/designated"}
    elif change == "duplicate":
        selection["opaque-2"] = attempt
    elif change == "empty":
        selection = {}
    elif change == "case_collision":
        selection["OPAQUE-1"] = attempt
    elif change == "inside_source":
        output = manifest.parent / "new"
    elif change == "existing":
        output.mkdir()
        (output / "original").write_text("keep")
    with pytest.raises((ValueError, FileExistsError)):
        module.build_incident_packet(
            manifest,
            output,
            expected_sha256=pin,
            selections=selection,
            protocol=PROTOCOL,
            assignment=ASSIGNMENT,
        )
    assert not output.exists() or change == "existing"


def test_missing_bound_capture_stays_assigned_and_unavailable(tmp_path, monkeypatch):
    m = api()
    monkeypatch.setattr(m, "_render", lambda p, t: "html")
    manifest, attempt = source(tmp_path)
    (manifest.parent / (attempt + "/execution.json")).unlink()
    repin(manifest)
    packet = m.build_incident_packet(
        manifest,
        tmp_path / "packet",
        expected_sha256=sha(manifest),
        selections={"opaque-1": attempt},
        protocol=PROTOCOL,
        assignment=ASSIGNMENT,
    )
    row = packet["cases"][0]
    assert row["documents"]["evidence"] is None
    assert row["availability"]["evidence"]["status"] == "unavailable"
    with pytest.raises(ValueError):
        m.validate_incident_references([{"document": "evidence", "pointer": ""}], row["documents"])


def complete_response(module, packet):
    response = module.incident_response_template(packet)
    row = response["cases"][0]
    refs = [{"document": "scenario", "pointer": "/target"}]
    row["identified_target"] = {
        "status": "identified",
        "patient_id": "PAT-WRONG",
        "encounter_id": "ENC-WRONG",
        "unassessed_reason": None,
        "rationale": "Deliberately wrong but structurally supplied.",
        "evidence_refs": refs,
    }
    for axis in row["axes"]:
        axis.update(judgment="yes", rationale="Claim for later human review.", evidence_refs=refs)
    row["incident_assessment"] = {
        "status": "none_identified",
        "summary": "Claim for later review.",
        "findings": [],
        "unassessed_reason": None,
        "evidence_refs": refs,
    }
    return response


def test_blank_omitted_and_wrong_but_wellformed_reports_keep_denominators(tmp_path, monkeypatch):
    m, packet, _ = build(tmp_path, monkeypatch)
    blank = m.incident_response_template(packet)
    assert m.validate_incident_response(blank, packet)["opaque-1"]["status"] == "pending"
    blank["cases"] = []
    write(tmp_path / "blank.json", blank)
    receipt = m.import_incident_response(
        tmp_path / "packet/manifest.json", tmp_path / "blank.json", tmp_path / "blank-import"
    )
    assert receipt["counts"]["pending_cases"] == 1 and receipt["counts"]["pending_axes"] == 6
    response = complete_response(m, packet)
    write(tmp_path / "wrong.json", response)
    receipt = m.import_incident_response(
        tmp_path / "packet/manifest.json", tmp_path / "wrong.json", tmp_path / "wrong-import"
    )
    assert receipt["status"] == "recorded" and receipt["counts"]["submitted_cases"] == 1
    assert receipt["cases"][0]["response"] == response["cases"][0]
    assert receipt["cases"][0]["adjudication_status"] == "pending"


@pytest.mark.parametrize(
    "change",
    [
        "foreign_case",
        "duplicate_case",
        "bad_category",
        "missing_claim",
        "bad_reference",
        "wrong_binding",
        "duplicate_json",
    ],
)
def test_invalid_submissions_exact_bytes_retained_all_pending(tmp_path, monkeypatch, change):
    m, packet, _ = build(tmp_path, monkeypatch)
    value = complete_response(m, packet)
    row = value["cases"][0]
    finding = {
        "finding_id": "F1",
        "category": "target",
        "claim": "A claim",
        "observed_target": {"patient_id": "PAT-WRONG", "encounter_id": None},
        "source_ids": [],
        "evidence_refs": [{"document": "scenario", "pointer": "/target"}],
    }
    row["incident_assessment"].update(status="findings_identified", findings=[finding])
    if change == "foreign_case":
        row["review_case_id"] = "foreign"
    elif change == "duplicate_case":
        value["cases"].append(deepcopy(row))
    elif change == "bad_category":
        finding["category"] = "clinical_score"
    elif change == "missing_claim":
        finding["claim"] = ""
    elif change == "bad_reference":
        finding["evidence_refs"][0]["pointer"] = "/absent"
    elif change == "wrong_binding":
        value["packet_sha256"] = "0" * 64
    raw = json.dumps(value).encode()
    if change == "duplicate_json":
        raw = raw.replace(
            b'"schema_version":', b'"schema_version":"duplicate", "schema_version":', 1
        )
    (tmp_path / "response.json").write_bytes(raw)
    receipt = m.import_incident_response(
        tmp_path / "packet/manifest.json", tmp_path / "response.json", tmp_path / "import"
    )
    assert receipt["status"] == "invalid_submission"
    assert receipt["counts"]["pending_cases"] == 1 and receipt["counts"]["pending_axes"] == 6
    assert (tmp_path / "import/submission.json").read_bytes() == raw


@pytest.mark.parametrize(
    "timing",
    [
        None,
        {"method": "instrumented_session"},
        {"method": "self_reported", "elapsed_seconds": 2, "active_seconds": 3, "note": "declared"},
    ],
)
def test_invalid_timing_does_not_erase_report(tmp_path, monkeypatch, timing):
    m, packet, _ = build(tmp_path, monkeypatch)
    value = complete_response(m, packet)
    value["cases"][0]["timing"] = timing
    result = m.validate_incident_response(value, packet)["opaque-1"]
    assert result["status"] == "submitted" and result["timing_error"]
    assert result["response"]["timing"] == timing


def test_known_partial_target_and_unknown_active_time_survive(tmp_path, monkeypatch):
    m, packet, _ = build(tmp_path, monkeypatch)
    value = complete_response(m, packet)
    row = value["cases"][0]
    row["identified_target"].update(
        status="unassessed", encounter_id="", unassessed_reason="insufficient_evidence"
    )
    row["timing"] = {
        "method": "self_reported",
        "elapsed_seconds": 12,
        "active_seconds": None,
        "note": "operator declaration",
    }
    result = m.validate_incident_response(value, packet)["opaque-1"]
    assert result["response"]["identified_target"]["patient_id"] == "PAT-WRONG"
    assert result["timing_error"] is None and result["response"]["timing"]["active_seconds"] is None


@pytest.mark.parametrize("pointer", ["/missing", "\n", "/a~2b", "/list/01"])
def test_strict_references_reject_missing_or_malformed(pointer):
    with pytest.raises(ValueError):
        api().validate_incident_references(
            [{"document": "evidence", "pointer": pointer}], {"evidence": {"list": [1]}}
        )


def test_references_real_null_and_decoded_arrays_and_slash_newline_keys():
    m = api()
    docs = {"evidence": {"unknown": None, "text": '[null,{"a/b\\n":3}]'}}
    m.validate_incident_references(
        [
            {"document": "evidence", "pointer": "/unknown"},
            {"document": "evidence", "pointer": "/text", "decoded_json_pointer": "/1/a~1b\n"},
        ],
        docs,
    )
    docs["evidence"]["text"] = '{"x":1,"x":2}'
    with pytest.raises(ValueError):
        m.validate_incident_references(
            [{"document": "evidence", "pointer": "/text", "decoded_json_pointer": "/x"}], docs
        )


def test_self_rehashed_packet_tampering_cannot_replace_source(tmp_path, monkeypatch):
    m, packet, _ = build(tmp_path, monkeypatch)
    p = tmp_path / "packet"
    path = p / "public/packet.json"
    value = json.loads(path.read_text())
    value["cases"][0]["documents"]["evidence"]["after"] = {}
    write(path, value)
    manifest = json.loads((p / "manifest.json").read_text())
    manifest["files"]["public/packet.json"] = sha(path)
    unsigned = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    manifest["manifest_sha256"] = m._digest(unsigned)
    write(p / "manifest.json", manifest)
    with pytest.raises(ValueError):
        m.validate_incident_packet(p / "manifest.json")


def minimal_packet():
    return {
        "packet_id": "packet-1",
        "assignment_id": "assignment-1",
        "operator_id": "operator-1",
        "cases": [
            {
                "review_case_id": "opaque-1",
                "documents": {
                    "scenario": {"target": {"patient_id": "P", "encounter_id": "E"}},
                    "task": None,
                    "evidence": None,
                    "runtime": None,
                },
            }
        ],
    }


def test_missing_timing_is_an_independent_error_without_losing_report():
    m = api()
    packet = minimal_packet()
    value = complete_response(m, packet)
    del value["cases"][0]["timing"]
    result = m.validate_incident_response(value, packet)["opaque-1"]
    assert result["status"] == "submitted" and result["timing_error"]
    assert "timing" not in result["response"]


def test_partial_draft_content_is_retained_without_inferred_judgments():
    m = api()
    packet = minimal_packet()
    response = m.incident_response_template(packet)
    row = response["cases"][0]
    row["identified_target"].update(
        patient_id="P",
        rationale="Working interpretation.",
        evidence_refs=[{"document": "scenario", "pointer": "/target"}],
    )
    row["axes"][0]["rationale"] = "Review still in progress."
    row["incident_assessment"]["summary"] = "Draft, not an incident conclusion."
    result = m.validate_incident_response(response, packet)["opaque-1"]
    assert result["status"] == result["target_status"] == result["incident_status"] == "pending"
    assert result["response"] == row


def test_portable_source_override_requires_the_same_raw_pin(tmp_path, monkeypatch):
    m, packet, manifest = build(tmp_path, monkeypatch)
    relocated = tmp_path / "relocated"
    manifest.parent.rename(relocated)
    with pytest.raises((ValueError, FileNotFoundError)):
        m.validate_incident_packet(tmp_path / "packet/manifest.json")
    loaded, _, _ = m.validate_incident_packet(
        tmp_path / "packet/manifest.json", source_manifest_override=relocated / "manifest.json"
    )
    assert loaded == packet
    changed = json.loads((relocated / "manifest.json").read_text())
    changed["status"] = "changed"
    write(relocated / "manifest.json", changed)
    with pytest.raises(ValueError):
        m.validate_incident_packet(
            tmp_path / "packet/manifest.json", source_manifest_override=relocated / "manifest.json"
        )


def test_raw_and_assisted_have_identical_public_documents(tmp_path, monkeypatch):
    m, raw, manifest = build(tmp_path, monkeypatch)
    assisted = m.build_incident_packet(
        manifest,
        tmp_path / "assisted",
        expected_sha256=sha(manifest),
        selections={"opaque-1": "REC2-008/designated"},
        protocol=PROTOCOL,
        assignment={**ASSIGNMENT, "presentation": "assisted"},
    )
    assert raw["cases"][0]["documents"] == assisted["cases"][0]["documents"]
    assert raw["cases"][0]["availability"] == assisted["cases"][0]["availability"]
    assert (
        assisted["cases"][0]["assistance"]["schema_version"] == "healthcraft-incident-evidence/v1"
    )
    assert (
        m.incident_response_template(assisted)["cases"]
        == m.incident_response_template(raw)["cases"]
    )


@pytest.mark.parametrize("presentation", ["raw", "assisted"])
@pytest.mark.parametrize(
    "private_key", ["expectations", "verification", "designated_control", "original_evidence"]
)
def test_public_projection_rejects_structured_private_data_before_output(
    tmp_path, monkeypatch, presentation, private_key
):
    m = api()
    monkeypatch.setattr(m, "_render", lambda p, t: "html")
    manifest, attempt = source(tmp_path, model=True, case="REC2-001")
    filename = (
        manifest.parent / attempt / "case.json"
        if private_key in ("expectations", "designated_control")
        else manifest.parent / attempt / "receipt.json"
    )
    value = json.loads(filename.read_text())
    target = value["scenario"] if filename.name == "case.json" else value
    target["extra_capture"] = [{"nested": {private_key: {"secret": "PRIVATE_SENTINEL"}}}]
    write(filename, value)
    repin(manifest)
    original = {p: p.read_bytes() for p in manifest.parent.rglob("*") if p.is_file()}
    output = tmp_path / "packet"
    with pytest.raises(ValueError, match="structured private"):
        m.build_incident_packet(
            manifest,
            output,
            expected_sha256=sha(manifest),
            selections={"opaque-1": attempt},
            protocol=PROTOCOL,
            assignment={**ASSIGNMENT, "presentation": presentation},
        )
    assert not output.exists()
    assert all(p.read_bytes() == raw for p, raw in original.items())


@pytest.mark.parametrize("presentation", ["raw", "assisted"])
def test_public_projection_preserves_literal_private_field_mentions(
    tmp_path, monkeypatch, presentation
):
    m = api()
    monkeypatch.setattr(m, "_render", lambda p, t: "html")
    manifest, attempt = source(tmp_path, model=True, case="REC2-001")
    filename = manifest.parent / attempt / "receipt.json"
    value = json.loads(filename.read_text())
    captured = '{"original_evidence": "verbatim error mentioning expectations and verification"}'
    value["error"] = {"type": "CapturedError", "message": captured}
    write(filename, value)
    repin(manifest)
    packet = m.build_incident_packet(
        manifest,
        tmp_path / "packet",
        expected_sha256=sha(manifest),
        selections={"opaque-1": attempt},
        protocol=PROTOCOL,
        assignment={**ASSIGNMENT, "presentation": presentation},
    )
    assert packet["cases"][0]["documents"]["runtime"]["receipt"]["error"] == value["error"]


def test_import_cannot_modify_packet_or_original_source(tmp_path, monkeypatch):
    m, packet, manifest = build(tmp_path, monkeypatch)
    response = tmp_path / "response.json"
    write(response, m.incident_response_template(packet))
    for output in [tmp_path / "packet/import", manifest.parent / "import"]:
        with pytest.raises(ValueError):
            m.import_incident_response(tmp_path / "packet/manifest.json", response, output)
        assert not output.exists()


def test_full_immutable_native_manifest_builds_all_explicit_attempts(tmp_path, monkeypatch):
    m = api()
    monkeypatch.setattr(m, "_render", lambda p, t: "html")
    path = SCRIPTED / "manifest.json"
    original = path.read_bytes()
    manifest = json.loads(original)
    choices = {f"opaque-{i}": row["id"] for i, row in enumerate(manifest["roster"])}
    packet = m.build_incident_packet(
        path,
        tmp_path / "packet",
        expected_sha256=sha(path),
        selections=choices,
        protocol=PROTOCOL,
        assignment=ASSIGNMENT,
    )
    assert len(packet["cases"]) == 16 and len({r["attempt_sha256"] for r in packet["cases"]}) == 16
    assert path.read_bytes() == original


def test_full_immutable_model_manifest_retains_failed_attempt(tmp_path, monkeypatch):
    m = api()
    monkeypatch.setattr(m, "_render", lambda p, t: "html")
    path = MODELS / "manifest.json"
    original = path.read_bytes()
    manifest = json.loads(original)
    choices = {f"opaque-{i}": row["id"] for i, row in enumerate(manifest["outcomes"])}
    packet = m.build_incident_packet(
        path,
        tmp_path / "packet",
        expected_sha256=sha(path),
        selections=choices,
        protocol=PROTOCOL,
        assignment=ASSIGNMENT,
    )
    assert len(packet["cases"]) == 16
    assert (
        sum(r["documents"]["runtime"]["receipt"]["status"] == "failed" for r in packet["cases"])
        == 1
    )
    assert path.read_bytes() == original


def test_real_renderer_roundtrip_keeps_blank_template(tmp_path):
    m = api()
    path = SCRIPTED / "manifest.json"
    packet = m.build_incident_packet(
        path,
        tmp_path / "packet",
        expected_sha256=sha(path),
        selections={"opaque-1": "REC2-007/designated"},
        protocol=PROTOCOL,
        assignment=ASSIGNMENT,
    )
    assert (tmp_path / "packet/public/report.html").is_file()
    validated, _, _ = m.validate_incident_packet(tmp_path / "packet/manifest.json")
    assert validated == packet
    receipt = m.import_incident_response(
        tmp_path / "packet/manifest.json",
        tmp_path / "packet/public/response-template.json",
        tmp_path / "import",
    )
    assert receipt["counts"]["pending_cases"] == 1 and receipt["counts"]["pending_axes"] == 6


def test_failed_worker_identity_files_survive_missing_final_receipts(tmp_path, monkeypatch):
    m = api()
    monkeypatch.setattr(m, "_render", lambda p, t: "html")
    manifest, attempt = source(tmp_path, model=True, case="REC2-001")
    for name in ["receipt.json", "worker-receipt.json", "worker/worker-receipt.json"]:
        (manifest.parent / attempt / name).unlink()
    repin(manifest)
    packet = m.build_incident_packet(
        manifest,
        tmp_path / "packet",
        expected_sha256=sha(manifest),
        selections={"opaque-1": attempt},
        protocol=PROTOCOL,
        assignment=ASSIGNMENT,
    )
    runtime = packet["cases"][0]["documents"]["runtime"]
    assert runtime["receipt"] is None and runtime["worker_receipt"] is None
    assert runtime["identities"]["before"] == json.loads(
        (manifest.parent / attempt / "worker/identity-before.json").read_text()
    )
    assert runtime["initial_prompt"] == json.loads(
        (manifest.parent / attempt / "worker/initial-prompt.json").read_text()
    )
    assert "receipt" in runtime["capture_errors"]


def test_no_runtime_capture_is_unavailable_not_empty_transcript(tmp_path, monkeypatch):
    m = api()
    monkeypatch.setattr(m, "_render", lambda p, t: "html")
    manifest, attempt = source(tmp_path, model=True, case="REC2-002")
    for p in (manifest.parent / attempt).rglob("*"):
        if p.is_file() and (
            p.parent.name == "worker" or p.name in ("receipt.json", "worker-receipt.json")
        ):
            p.unlink()
    repin(manifest)
    packet = m.build_incident_packet(
        manifest,
        tmp_path / "packet",
        expected_sha256=sha(manifest),
        selections={"opaque-1": attempt},
        protocol=PROTOCOL,
        assignment=ASSIGNMENT,
    )
    assert packet["cases"][0]["documents"]["runtime"] is None
    assert packet["cases"][0]["availability"]["runtime"]["status"] == "unavailable"


def test_explicit_assignment_order_survives_canonical_manifest_serialization(tmp_path, monkeypatch):
    m = api()
    monkeypatch.setattr(m, "_render", lambda p, t: "html")
    manifest = SCRIPTED / "manifest.json"
    selection = {"review-z": "REC2-002/designated", "review-a": "REC2-001/reference"}
    packet = m.build_incident_packet(
        manifest,
        tmp_path / "packet",
        expected_sha256=sha(manifest),
        selections=selection,
        protocol=PROTOCOL,
        assignment=ASSIGNMENT,
    )
    loaded, _, _ = m.validate_incident_packet(tmp_path / "packet/manifest.json")
    assert [row["review_case_id"] for row in loaded["cases"]] == ["review-z", "review-a"]
    assert loaded == packet
