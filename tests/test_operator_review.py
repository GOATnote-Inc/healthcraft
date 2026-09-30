"""Operator submissions preserve assignments and evidence, without grading people."""

from __future__ import annotations

import hashlib
import importlib
import json
from copy import deepcopy

import pytest

from healthcraft.reconciliation.diagnostics import explain_reconciliation
from healthcraft.reconciliation.execution import run_reconciliation_trial
from healthcraft.reconciliation.fixture import load_scenario
from healthcraft.reconciliation.oracle import load_expectations, verify_reconciliation

AXES = (
    "execution_completion",
    "write_acknowledgement",
    "storage",
    "readback",
    "reconciliation_correctness",
    "evidence_sufficiency",
)


def encode(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def write(path, value):
    path.write_bytes(encode(value))


def read(path):
    return json.loads(path.read_bytes())


def files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def core(monkeypatch):
    module = importlib.import_module("healthcraft.operator_review")
    # Renderer behavior has its own tests; this exercises exact output binding.
    monkeypatch.setattr(
        module, "_render_packet", lambda packet, template: encode([packet, template]).decode()
    )
    return module


@pytest.fixture
def bundle(tmp_path):
    scenario, expected = load_scenario(), load_expectations()
    evidence = run_reconciliation_trial(scenario=scenario)
    return make_bundle(tmp_path / "bundle", scenario, expected, evidence)


def make_bundle(path, scenario, expected, evidence):
    path.mkdir()
    (path / "inputs").mkdir()
    oracle = verify_reconciliation(scenario, expected, evidence)
    explanation = explain_reconciliation(scenario, expected, evidence)
    documents = dict(scenario=scenario, expectations=expected, evidence=evidence, oracle=oracle)
    for key in ("scenario", "expectations", "evidence"):
        write(path / f"inputs/{key}.json", documents[key])
    write(path / "verification.json", oracle)
    write(path / "explanation.json", explanation)
    (path / "report.html").write_text("<html>Original captured tutorial report.</html>")
    manifest = {
        "schema_version": "healthcraft-reconciliation-explanation-bundle/v1",
        "status": "complete",
        "explanation_status": explanation["status"],
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in files(path).items()},
        "source_files": {"src/healthcraft/reconciliation/oracle.py": "a" * 64},
        "input_paths": {key: f"/original/{key}.json" for key in documents if key != "oracle"},
        "bindings": {key + "_sha256": digest(value) for key, value in documents.items()},
        "supplied_verification_matched": False,
        "model_calls": 0,
        "limitations": ["Engineering test fixture, not independent clinical review."],
        "source_context": {
            "enabled": True,
            "schema_version": "healthcraft-reconciliation-source-context/v1",
        },
    }
    write(path / "manifest.json", manifest)
    return path


def rehash_bundle(path):
    manifest = read(path / "manifest.json")
    manifest["files"] = {
        name: hashlib.sha256(raw).hexdigest()
        for name, raw in files(path).items()
        if name != "manifest.json"
    }
    write(path / "manifest.json", manifest)


def build(core, bundle, tmp_path, **kwargs):
    return core.build_operator_packet(
        {"case-a": bundle},
        tmp_path / "packet",
        protocol=kwargs.get(
            "protocol", {"protocol_id": "tutorial-1", "purpose": "engineering_tutorial"}
        ),
        assignment=kwargs.get(
            "assignment",
            {"assignment_id": "assignment-1", "reviewer_id": "operator-1", "presentation": "raw"},
        ),
    )


def submit(core, tmp_path, response, *, raw=None):
    path = tmp_path / "response.json"
    path.write_bytes(raw if raw is not None else encode(response))
    return core.import_operator_response(
        tmp_path / "packet/manifest.json", path, tmp_path / "import"
    )


def answer(template, axis=0, *, judgment="yes", ref=None):
    row = template["cases"][0]["axes"][axis]
    row.update(judgment=judgment, rationale="Operator-authored engineering interpretation.")
    row["evidence_refs"] = [ref or {"document": "evidence", "pointer": "/completion"}]
    if judgment == "unassessed":
        row["unassessed_reason"] = "reviewer_abstention"


def test_packet_preserves_exact_sources_blank_axes_and_declared_tutorial_scope(
    core, bundle, tmp_path
):
    before = files(bundle)
    packet = build(core, bundle, tmp_path)
    assert tuple(core.AXES) == AXES
    assert packet["scope"] == "exposed_tutorial_operator_review"
    assert packet["cases"][0]["scenario_family_id"] == load_scenario()["id"]
    assert [row["axis_id"] for row in packet["cases"][0]["axes"]] == list(AXES)
    assert packet["cases"][0]["documents"]["evidence"] == read(bundle / "inputs/evidence.json")
    assert files(bundle) == before
    for name, raw in before.items():
        assert (tmp_path / "packet/sources/case-a" / name).read_bytes() == raw
    template = read(tmp_path / "packet/response-template.json")
    assert template["packet_sha256"] == digest(packet)
    assert all(row["judgment"] is None for row in template["cases"][0]["axes"])
    assert template["cases"][0]["timing"]["active_seconds"] is None
    packet["cases"][0]["documents"]["evidence"].clear()
    assert read(tmp_path / "packet/packet.json")["cases"][0]["documents"]["evidence"]


@pytest.mark.parametrize("field", ["purpose", "extra", "assignment_extra", "presentation"])
def test_strict_protocol_and_assignment_preflight(core, bundle, tmp_path, field):
    protocol = {"protocol_id": "p", "purpose": "engineering_tutorial"}
    assignment = {"assignment_id": "a", "reviewer_id": "r", "presentation": "raw"}
    if field == "purpose":
        protocol["purpose"] = "clinical_validation"
    elif field == "extra":
        protocol["registered"] = True
    elif field == "assignment_extra":
        assignment["independent"] = True
    else:
        assignment["presentation"] = "unknown"
    with pytest.raises(ValueError):
        build(core, bundle, tmp_path, protocol=protocol, assignment=assignment)
    assert not (tmp_path / "packet").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "bytes",
        "missing",
        "unlisted",
        "traversal",
        "symlink",
        "incomplete",
        "no_context",
        "wrong_source_hash",
        "duplicate_json",
    ],
)
def test_bad_source_inventory_rejected_without_partial_packet(core, bundle, tmp_path, mutation):
    manifest = read(bundle / "manifest.json")
    if mutation == "bytes":
        (bundle / "report.html").write_text("changed")
    elif mutation == "missing":
        (bundle / "inputs/evidence.json").unlink()
    elif mutation == "unlisted":
        (bundle / "extra.json").write_text("{}")
    elif mutation == "traversal":
        manifest["files"]["../outside.json"] = "a" * 64
    elif mutation == "symlink":
        original = (bundle / "report.html").read_bytes()
        outside = tmp_path / "outside.html"
        outside.write_bytes(original)
        (bundle / "report.html").unlink()
        (bundle / "report.html").symlink_to(outside)
    elif mutation == "incomplete":
        manifest["status"] = "partial"
    elif mutation == "no_context":
        del manifest["source_context"]
    elif mutation == "wrong_source_hash":
        manifest["source_files"]["src/healthcraft/reconciliation/oracle.py"] = "invalid"
    elif mutation == "duplicate_json":
        (bundle / "inputs/scenario.json").write_text('{"id":"first","id":"second"}')
        rehash_bundle(bundle)
    if mutation in {"traversal", "incomplete", "no_context", "wrong_source_hash"}:
        write(bundle / "manifest.json", manifest)
    with pytest.raises(ValueError):
        build(core, bundle, tmp_path)
    assert not (tmp_path / "packet").exists()


@pytest.mark.parametrize("mutation", ["oracle_bool", "explanation", "binding"])
def test_rehashed_forged_reports_rejected_by_recomputation(core, bundle, tmp_path, mutation):
    manifest = read(bundle / "manifest.json")
    if mutation == "oracle_bool":
        value = read(bundle / "verification.json")
        value["checks"]["provenance"] = 1  # Python equality must not accept bool == int.
        write(bundle / "verification.json", value)
        manifest["bindings"]["oracle_sha256"] = digest(value)
    elif mutation == "explanation":
        value = read(bundle / "explanation.json")
        value["notes"] = []
        write(bundle / "explanation.json", value)
    else:
        manifest["bindings"]["evidence_sha256"] = "0" * 64
    write(bundle / "manifest.json", manifest)
    rehash_bundle(bundle)
    with pytest.raises(ValueError):
        build(core, bundle, tmp_path)


def test_unavailable_case_is_retained_not_dropped(core, bundle, tmp_path):
    evidence = read(bundle / "inputs/evidence.json")
    evidence["scenario_sha256"] = "0" * 64
    bad = make_bundle(tmp_path / "unavailable", load_scenario(), load_expectations(), evidence)
    packet = build(core, bad, tmp_path)
    assert len(packet["cases"]) == 1
    assert packet["cases"][0]["explanation"]["status"] == "unavailable"
    assert len(packet["cases"][0]["axes"]) == 6


@pytest.mark.parametrize("case_id", ["../x", "", "a/b", "a\\b", "a\n", 1])
def test_case_ids_are_safe_opaque_strings(core, bundle, tmp_path, case_id):
    with pytest.raises(ValueError):
        core.build_operator_packet(
            {case_id: bundle},
            tmp_path / "packet",
            protocol={"protocol_id": "p", "purpose": "engineering_tutorial"},
            assignment={"assignment_id": "a", "reviewer_id": "r", "presentation": "raw"},
        )
    assert not (tmp_path / "packet").exists()


def test_duplicate_evidence_under_distinct_case_names_is_not_independent(core, bundle, tmp_path):
    other = make_bundle(
        tmp_path / "copy",
        load_scenario(),
        load_expectations(),
        read(bundle / "inputs/evidence.json"),
    )
    with pytest.raises(ValueError, match="duplicate|Duplicate"):
        core.build_operator_packet(
            {"first": bundle, "second": other},
            tmp_path / "packet",
            protocol={"protocol_id": "p", "purpose": "engineering_tutorial"},
            assignment={"assignment_id": "a", "reviewer_id": "r", "presentation": "raw"},
        )


def test_missing_and_partial_axes_preserve_all_assigned_denominators(core, bundle, tmp_path):
    build(core, bundle, tmp_path)
    template = read(tmp_path / "packet/response-template.json")
    answer(template)
    template["cases"][0]["axes"] = template["cases"][0]["axes"][:1]
    result = submit(core, tmp_path, template)
    assert result["status"] == "recorded"
    assert result["counts"] == {
        "assigned_cases": 1,
        "submitted_cases": 0,
        "abstained_cases": 0,
        "unassessed_cases": 0,
        "pending_cases": 1,
        "partial_cases": 1,
        "assigned_axes": 6,
        "assessed_axes": 1,
        "unassessed_axes": 0,
        "pending_axes": 5,
    }
    assert len(result["cases"][0]["axes"]) == 6
    assert result["cases"][0]["axes"][0]["response"]["judgment"] == "yes"
    assert result["cases"][0]["axes"][1]["response"] is None


@pytest.mark.parametrize("kind", ["omitted", "blank", "abstained", "submitted"])
def test_case_states_do_not_imply_correctness(core, bundle, tmp_path, kind):
    build(core, bundle, tmp_path)
    template = read(tmp_path / "packet/response-template.json")
    if kind == "omitted":
        template["cases"] = []
    elif kind != "blank":
        for index in range(6):
            answer(template, index, judgment="unassessed" if kind == "abstained" else "no")
    result = submit(core, tmp_path, template)
    assert result["cases"][0]["status"] == ("pending" if kind in {"blank", "omitted"} else kind)
    assert result["counts"]["assigned_axes"] == 6
    assert not {"score", "passed", "clinical_validation"} & result.keys()
    assert (tmp_path / "import/submission.json").read_bytes() == (
        tmp_path / "response.json"
    ).read_bytes()


@pytest.mark.parametrize(
    "raw",
    [
        b'{"cases": [], "cases": []}',
        b'{"x":NaN}',
        b'{"x":1e999}',
        b"[]",
        b"\xff",
        b'{"x":"\\ud800"}',
        b"{",
    ],
)
def test_malformed_raw_submission_preserved_with_every_assignment_pending(
    core, bundle, tmp_path, raw
):
    build(core, bundle, tmp_path)
    result = submit(core, tmp_path, None, raw=raw)
    assert result["status"] == "invalid_submission"
    assert result["errors"]
    assert result["counts"]["pending_axes"] == 6
    assert result["counts"]["pending_cases"] == 1
    assert (tmp_path / "import/submission.json").read_bytes() == raw


@pytest.mark.parametrize(
    "mutation",
    [
        "identity",
        "digest",
        "foreign_case",
        "duplicate_case",
        "duplicate_axis",
        "foreign_axis",
        "bool_judgment",
        "no_rationale",
        "no_ref",
        "extra",
        "partial_blank",
    ],
)
def test_structural_submission_failure_cannot_import_partial_judgments(
    core, bundle, tmp_path, mutation
):
    build(core, bundle, tmp_path)
    response = read(tmp_path / "packet/response-template.json")
    answer(response)
    case, row = response["cases"][0], response["cases"][0]["axes"][0]
    if mutation == "identity":
        response["reviewer_id"] = "somebody-else"
    elif mutation == "digest":
        response["packet_sha256"] = "0" * 64
    elif mutation == "foreign_case":
        case["case_id"] = "not-assigned"
    elif mutation == "duplicate_case":
        response["cases"].append(deepcopy(case))
    elif mutation == "duplicate_axis":
        case["axes"].append(deepcopy(row))
    elif mutation == "foreign_axis":
        row["axis_id"] = "clinical_readiness"
    elif mutation == "bool_judgment":
        row["judgment"] = True
    elif mutation == "no_rationale":
        row["rationale"] = " "
    elif mutation == "no_ref":
        row["evidence_refs"] = []
    elif mutation == "extra":
        row["correct"] = True
    else:
        row["judgment"] = None
    result = submit(core, tmp_path, response)
    assert result["status"] == "invalid_submission"
    assert result["counts"]["assessed_axes"] == 0
    assert result["counts"]["pending_axes"] == 6


@pytest.mark.parametrize(
    "pointer",
    [
        "/not-there",
        "/calls/01",
        "/calls/-1",
        "/calls/-",
        "/calls/0~2",
        "not/a/pointer",
        "/completion\n",
    ],
)
def test_refs_must_resolve_with_strict_rfc6901(core, bundle, tmp_path, pointer):
    build(core, bundle, tmp_path)
    response = read(tmp_path / "packet/response-template.json")
    answer(response, ref={"document": "evidence", "pointer": pointer})
    assert submit(core, tmp_path, response)["status"] == "invalid_submission"


def test_explicit_null_and_decoded_note_are_real_resolvable_references(core, bundle, tmp_path):
    packet = build(core, bundle, tmp_path)
    evidence = packet["cases"][0]["documents"]["evidence"]
    index = next(i for i, call in enumerate(evidence["calls"]) if call["name"] == "updateEncounter")
    response = read(tmp_path / "packet/response-template.json")
    answer(
        response,
        ref={
            "document": "evidence",
            "pointer": f"/calls/{index}/params/notes",
            "decoded_json_pointer": "/scope_exclusions/0/source_id",
        },
    )
    answer(response, 1, ref={"document": "scenario", "pointer": "/patients/0/date_of_birth"})
    assert submit(core, tmp_path, response)["status"] == "recorded"


@pytest.mark.parametrize(
    "timing",
    [
        {"method": "self_reported", "elapsed_seconds": True, "active_seconds": 1, "note": "self"},
        {"method": "self_reported", "elapsed_seconds": 1, "active_seconds": 2, "note": "self"},
        {"method": "self_reported", "elapsed_seconds": -1, "active_seconds": None, "note": "self"},
        {"method": "instrumented", "elapsed_seconds": 3, "active_seconds": 1, "note": "claimed"},
        {"method": "not_collected", "elapsed_seconds": 0, "active_seconds": None, "note": ""},
    ],
)
def test_timing_does_not_invent_measurement_or_accept_invalid_numbers(
    core, bundle, tmp_path, timing
):
    build(core, bundle, tmp_path)
    response = read(tmp_path / "packet/response-template.json")
    response["cases"][0]["timing"] = timing
    assert submit(core, tmp_path, response)["status"] == "invalid_submission"


def test_self_reported_elapsed_never_fills_unknown_active_time(core, bundle, tmp_path):
    build(core, bundle, tmp_path)
    response = read(tmp_path / "packet/response-template.json")
    response["cases"][0]["timing"] = {
        "method": "self_reported",
        "elapsed_seconds": 12.5,
        "active_seconds": None,
        "note": "Wall clock estimate; active time unknown.",
    }
    result = submit(core, tmp_path, response)
    assert result["status"] == "recorded"
    assert result["cases"][0]["timing"]["active_seconds"] is None
    assert result["cases"][0]["timing"]["elapsed_seconds"] == 12.5


@pytest.mark.parametrize(
    "path",
    [
        "packet.json",
        "response-template.json",
        "report.html",
        "sources/case-a/inputs/evidence.json",
        "manifest.json",
    ],
)
def test_invalid_packet_raises_before_receipt_and_does_not_consume_submission(
    core, bundle, tmp_path, path
):
    build(core, bundle, tmp_path)
    response = read(tmp_path / "packet/response-template.json")
    (tmp_path / "packet" / path).write_text("{}")
    with pytest.raises(ValueError):
        submit(core, tmp_path, response)
    assert not (tmp_path / "import").exists()


@pytest.mark.parametrize("destination", ["directory", "file", "dangling"])
def test_outputs_are_exclusive_and_preserve_existing_destinations(
    core, bundle, tmp_path, destination
):
    output = tmp_path / "packet"
    if destination == "directory":
        output.mkdir()
        (output / "keep").write_bytes(b"original")
    elif destination == "file":
        output.write_bytes(b"original")
    else:
        output.symlink_to(tmp_path / "missing")
    with pytest.raises(FileExistsError):
        build(core, bundle, tmp_path)
    if destination == "directory":
        assert (output / "keep").read_bytes() == b"original"
    elif destination == "file":
        assert output.read_bytes() == b"original"
    else:
        assert output.is_symlink() and not (tmp_path / "missing").exists()


def test_import_receipt_is_exclusive_and_repeat_identity_is_stable(core, bundle, tmp_path):
    build(core, bundle, tmp_path)
    response = read(tmp_path / "packet/response-template.json")
    first = submit(core, tmp_path, response)
    before = files(tmp_path / "import")
    with pytest.raises(FileExistsError):
        core.import_operator_response(
            tmp_path / "packet/manifest.json", tmp_path / "response.json", tmp_path / "import"
        )
    second = core.import_operator_response(
        tmp_path / "packet/manifest.json", tmp_path / "response.json", tmp_path / "another-import"
    )
    assert first == second
    assert files(tmp_path / "import") == before


def test_incorrect_human_answers_are_preserved_without_adjudication(core, bundle, tmp_path):
    packet = build(core, bundle, tmp_path)
    assert packet["cases"][0]["documents"]["oracle"]["checks"]["execution_complete"] is True
    response = read(tmp_path / "packet/response-template.json")
    for index in range(6):
        answer(response, index, judgment="no")
    raw = json.dumps(response, indent=3).encode() + b"\n\n"
    result = submit(core, tmp_path, None, raw=raw)
    assert result["status"] == "recorded"
    assert result["cases"][0]["status"] == "submitted"
    assert all(row["response"]["judgment"] == "no" for row in result["cases"][0]["axes"])
    assert result["counts"]["assessed_axes"] == 6
    assert (tmp_path / "import/submission.json").read_bytes() == raw


def test_output_inside_source_is_rejected_before_any_source_mutation(core, bundle):
    before = files(bundle)
    with pytest.raises(ValueError, match="inside|contain"):
        core.build_operator_packet(
            {"case-a": bundle},
            bundle / "new-packet",
            protocol={"protocol_id": "p", "purpose": "engineering_tutorial"},
            assignment={"assignment_id": "a", "reviewer_id": "r", "presentation": "raw"},
        )
    assert files(bundle) == before


def test_import_inside_packet_is_rejected_without_invalidating_packet(core, bundle, tmp_path):
    build(core, bundle, tmp_path)
    path = tmp_path / "response.json"
    path.write_bytes((tmp_path / "packet/response-template.json").read_bytes())
    before = files(tmp_path / "packet")
    with pytest.raises(ValueError, match="inside|contain"):
        core.import_operator_response(
            tmp_path / "packet/manifest.json", path, tmp_path / "packet/new-import"
        )
    assert files(tmp_path / "packet") == before


def test_case_order_and_family_grouping_are_preserved(core, bundle, tmp_path):
    evidence = read(bundle / "inputs/evidence.json")
    evidence["completion"] = {
        "status": "interrupted",
        "error": {"code": "test", "message": "A distinct captured attempt."},
    }
    other = make_bundle(tmp_path / "other", load_scenario(), load_expectations(), evidence)
    packet = core.build_operator_packet(
        {"z-last": bundle, "a-first": other},
        tmp_path / "packet",
        protocol={"protocol_id": "p", "purpose": "engineering_tutorial"},
        assignment={"assignment_id": "a", "reviewer_id": "r", "presentation": "assisted"},
    )
    assert [case["case_id"] for case in packet["cases"]] == ["z-last", "a-first"]
    assert len({case["scenario_family_id"] for case in packet["cases"]}) == 1
    response = read(tmp_path / "packet/response-template.json")
    response["cases"] = []
    receipt = submit(core, tmp_path, response)
    assert receipt["counts"]["assigned_cases"] == 2
    assert receipt["counts"]["pending_axes"] == 12
    assert [case["case_id"] for case in receipt["cases"]] == ["z-last", "a-first"]


def test_exclusive_final_creation_preserves_race_winner(core, bundle, tmp_path, monkeypatch):
    output = tmp_path / "packet"

    def competitor(packet, template):
        output.mkdir()
        (output / "winner").write_bytes(b"preserve this")
        return "report"

    monkeypatch.setattr(core, "_render_packet", competitor)
    with pytest.raises(FileExistsError):
        build(core, bundle, tmp_path)
    assert files(output) == {"winner": b"preserve this"}


@pytest.mark.parametrize("changed", ["packet", "template", "report"])
def test_rehashed_packet_representations_must_match_recomputed_content(
    core, bundle, tmp_path, changed
):
    build(core, bundle, tmp_path)
    response = read(tmp_path / "packet/response-template.json")
    root = tmp_path / "packet"
    if changed == "packet":
        value = read(root / "packet.json")
        value["cases"][0]["documents"]["oracle"]["checks"]["provenance"] = 1
        write(root / "packet.json", value)
    elif changed == "template":
        value = read(root / "response-template.json")
        answer(value)
        write(root / "response-template.json", value)
    else:
        (root / "report.html").write_text("A different operator presentation")
    manifest = read(root / "manifest.json")
    manifest["files"] = {
        name: hashlib.sha256(raw).hexdigest()
        for name, raw in files(root).items()
        if name != "manifest.json"
    }
    del manifest["manifest_sha256"]
    manifest["manifest_sha256"] = digest(manifest)
    write(root / "manifest.json", manifest)
    with pytest.raises(ValueError):
        submit(core, tmp_path, response)
    assert not (tmp_path / "import").exists()


def test_outcome_questions_separate_storage_and_actual_text_readback_from_correctness(
    core, bundle, tmp_path
):
    packet = build(core, bundle, tmp_path)
    questions = {row["axis_id"]: row for row in packet["cases"][0]["axes"]}
    assert questions["storage"]["question"] == "Does the captured final state contain any new note?"
    assert "wrong patient or encounter" in questions["storage"]["scope_note"]
    assert (
        questions["readback"]["question"]
        == "Did a later successful retrieval return the stored note text?"
    )
    assert "correctness" in questions["readback"]["scope_note"]


def test_changed_implementation_binding_rejected_before_recomputation(
    core, bundle, tmp_path, monkeypatch
):
    build(core, bundle, tmp_path)
    response = read(tmp_path / "packet/response-template.json")
    manifest = read(tmp_path / "packet/manifest.json")
    expected = {
        "src/healthcraft/operator_review.py",
        "src/healthcraft/operator_review_report.py",
        "src/healthcraft/reconciliation/diagnostics.py",
        "src/healthcraft/reconciliation/oracle.py",
    }
    assert expected <= manifest["implementation_sha256"].keys()
    manifest["implementation_sha256"]["src/healthcraft/reconciliation/oracle.py"] = "0" * 64
    del manifest["manifest_sha256"]
    manifest["manifest_sha256"] = digest(manifest)
    write(tmp_path / "packet/manifest.json", manifest)

    def forbidden(*args, **kwargs):
        raise AssertionError("recomputation must not run after implementation drift")

    monkeypatch.setattr(core, "verify_reconciliation", forbidden)
    with pytest.raises(ValueError, match="[Ii]mplementation"):
        submit(core, tmp_path, response)
    assert not (tmp_path / "import").exists()


@pytest.mark.parametrize("operation", ["build", "import"])
def test_source_change_during_derivation_does_not_seal_a_misbound_artifact(
    core, bundle, tmp_path, monkeypatch, operation
):
    if operation == "import":
        build(core, bundle, tmp_path)
    original = core._implementation()
    reads = 0

    def drifting_source():
        nonlocal reads
        reads += 1
        value = deepcopy(original)
        if reads > 1:
            value["src/healthcraft/operator_review.py"] = "0" * 64
        return value

    monkeypatch.setattr(core, "_implementation", drifting_source)
    with pytest.raises(ValueError, match="[Ii]mplementation"):
        if operation == "build":
            build(core, bundle, tmp_path)
        else:
            submit(core, tmp_path, read(tmp_path / "packet/response-template.json"))
    assert not (tmp_path / ("packet" if operation == "build" else "import")).exists()


def test_actual_renderer_packet_and_import_without_stub(bundle, tmp_path):
    from healthcraft import operator_review as core

    packet = build(core, bundle, tmp_path)
    html = (tmp_path / "packet/report.html").read_text()
    assert "<!doctype html>" in html.casefold()
    assert packet["cases"][0]["case_id"] in html
    response = read(tmp_path / "packet/response-template.json")
    answer(response)
    assert submit(core, tmp_path, response)["status"] == "recorded"


@pytest.mark.parametrize("reason", ["insufficient_evidence", "mixed"])
def test_unassessed_evidence_is_not_inferred_to_be_reviewer_abstention(
    core, bundle, tmp_path, reason
):
    build(core, bundle, tmp_path)
    response = read(tmp_path / "packet/response-template.json")
    for index in range(6):
        answer(response, index, judgment="unassessed")
        if reason == "insufficient_evidence" or index == 0:
            response["cases"][0]["axes"][index]["unassessed_reason"] = "insufficient_evidence"
    result = submit(core, tmp_path, response)
    assert result["cases"][0]["status"] == "unassessed"
    assert result["counts"]["unassessed_cases"] == 1
    assert result["counts"]["abstained_cases"] == 0
    assert result["counts"]["unassessed_axes"] == 6
