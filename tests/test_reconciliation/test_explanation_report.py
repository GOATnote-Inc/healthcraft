"""Offline reports distinguish recorded events, oracle intent, and unavailable evidence."""

from copy import deepcopy
from html.parser import HTMLParser

import pytest

from healthcraft.reconciliation.diagnostics import explain_reconciliation
from healthcraft.reconciliation.execution import run_reconciliation_trial
from healthcraft.reconciliation.fixture import load_scenario
from healthcraft.reconciliation.oracle import load_expectations


def ref(pointer, decoded=None, document="evidence"):
    result = {"document": document, "pointer": pointer}
    if decoded is not None:
        result["decoded_json_pointer"] = decoded
    return result


def sample(*, read=True):
    """Independently authored valid sidecar; deliberately failed intended note contract."""
    return {
        "schema_version": "healthcraft-reconciliation-explanation/v1",
        "status": "available",
        "bindings": {
            key + "_sha256": "a" * 64 for key in ("scenario", "expectations", "evidence", "oracle")
        },
        "oracle_checks": {
            "provenance": True,
            "source_fidelity": False,
            "persisted_action": False,
            "readback": False,
            "execution_complete": True,
        },
        "coverage": {
            "assessed": [
                "successful_write_calls",
                "new_stored_notes",
                "postwrite_readback",
                "scope_exclusions",
            ],
            "unassessed": [
                "observations",
                "unresolved_conflicts",
                "retrieval_coverage",
                "clinical_validity",
            ],
        },
        "observed_execution": {
            "successful_write_calls": [
                {
                    "call_id": "call-0004",
                    "call_index": 3,
                    "encounter_id": "ENC-AAAAAAAA",
                    "reference": ref("/calls/3"),
                }
            ],
            "deduplicated_retries": [],
            "new_stored_notes": [
                {
                    "note_id": "NOTE-1",
                    "patient_id": "PAT-AAAAAAAA",
                    "encounter_id": "ENC-AAAAAAAA",
                    "reference": ref("/after/entities/clinical_note/NOTE-1"),
                }
            ],
        },
        "notes": [
            {
                "call_id": "call-0004",
                "reference": ref("/calls/3/params/notes"),
                "matching_stored_note_ids": ["NOTE-1"],
                "scope_exclusions": {
                    "status": "different",
                    "issues": [
                        {
                            "code": "exclusion_field_mismatch",
                            "source_id": "SRC-B01",
                            "field": "encounter_id",
                            "observed": "ENC-DDDDDDDD",
                            "expected": "ENC-BBBBBBBB",
                            "evidence_refs": [
                                ref("/calls/3/params/notes", "/scope_exclusions/1/encounter_id")
                            ],
                            "expectation_refs": [
                                ref("/scope_exclusions/1/encounter_id", document="expectations")
                            ],
                        }
                    ],
                },
                "readback": {
                    "attempted_call_ids": ["call-0005"] if read else [],
                    "successful_target_call_ids": ["call-0005"] if read else [],
                    "stored_text_seen_call_ids": ["call-0005"] if read else [],
                    "references": [ref("/calls/4")] if read else [],
                    "oracle_verified": False,
                },
            }
        ],
        "errors": [],
        "limitations": ["Final-state matches are not unique call attribution."],
    }


def render(value, **kwargs):
    from healthcraft.reconciliation.explanation_report import render_reconciliation_explanation

    return render_reconciliation_explanation(value, **kwargs)


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.data = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.data.append(data)

    @property
    def text(self):
        return " ".join(self.data)


def test_readable_sections_keep_events_separate_from_correct_note_checks():
    html = render(sample())
    text = Document(html).text
    assert "Write acknowledgements" in text
    assert "New stored notes" in text
    assert "Actual post-write target reads" in text
    assert "Correct note verified by readback" in text
    assert "Stored text was returned in a later target read" in text
    assert "Not verified" in text
    assert "No clinical assessment or benchmark score" in text
    assert "Unassessed by this sidecar" in text
    assert "Observation content" in text and "Source retrieval coverage" in text
    assert "Required value" in text and "Observed value" in text
    assert "ENC-DDDDDDDD" in text and "ENC-BBBBBBBB" in text
    assert "/calls/3/params/notes" in text
    assert "/scope_exclusions/1/encounter_id" in text
    assert "Inside the JSON note" in text
    assert html.startswith("<!doctype html>")
    assert any(tag == "main" for tag, _ in Document(html).tags)
    assert any(tag == "th" and attrs.get("scope") for tag, attrs in Document(html).tags)


def test_no_readback_is_distinct_from_actual_readback_with_failed_oracle():
    absent, present = Document(render(sample(read=False))).text, Document(render(sample())).text
    assert "No post-write target read recorded" in absent
    assert "Stored text was returned in a later target read" not in absent
    assert "Stored text was returned in a later target read" in present
    assert "Not verified" in absent and "Not verified" in present


def test_failed_or_nonmatching_readback_is_not_described_as_stored_text_seen():
    data = sample()
    data["notes"][0]["readback"]["stored_text_seen_call_ids"] = []
    text = Document(render(data)).text
    assert "Target read completed; matching stored text not established" in text
    data["notes"][0]["readback"]["successful_target_call_ids"] = []
    text = Document(render(data)).text
    assert "Readback attempted; no successful target read recorded" in text


def test_unavailable_status_does_not_turn_unknown_events_into_zero_counts():
    unavailable = explain_reconciliation(None, {}, {})
    doc = Document(render(unavailable))
    assert "Explanation unavailable" in doc.text
    assert "Event counts unavailable" in doc.text
    assert "0 write" not in doc.text.lower()
    assert any(attrs.get("role") == "alert" for _, attrs in doc.tags)
    assert "Unsupported JSON value" not in doc.text or "unavailable" in doc.text.lower()


def test_all_untrusted_text_is_inert_including_title_values_and_pointers():
    data = sample()
    attack = '<img src=x onerror="alert(1)"><script>alert(2)</script>'
    data["limitations"] = [attack]
    issue = data["notes"][0]["scope_exclusions"]["issues"][0]
    issue["observed"] = attack
    issue["source_id"] = attack
    issue["field"] = attack
    issue["evidence_refs"][0]["pointer"] = "/" + attack
    issue["evidence_refs"][0]["decoded_json_pointer"] = "/" + attack
    html = render(data, title=attack)
    doc = Document(html)
    assert attack in doc.text
    assert "&lt;script&gt;" in html
    assert not {"script", "img", "iframe", "a", "link", "form"} & {tag for tag, _ in doc.tags}
    assert all(not (set(attrs) & {"href", "src", "onerror", "onclick"}) for _, attrs in doc.tags)


def test_null_false_and_absent_expected_values_remain_distinct():
    data = sample()
    issue = data["notes"][0]["scope_exclusions"]["issues"][0]
    issue["observed"], issue["expected"] = None, False
    text = Document(render(data)).text
    assert "null" in text and "false" in text
    issue["code"] = "exclusion_field_unexpected"
    del issue["expected"]
    assert "Not supplied" in Document(render(data)).text


def test_summary_read_counts_do_not_double_count_one_read_after_two_writes():
    data = sample()
    duplicate = deepcopy(data["observed_execution"]["successful_write_calls"][0])
    duplicate.update(call_id="call-0003", call_index=2, reference=ref("/calls/2"))
    data["observed_execution"]["successful_write_calls"].insert(0, duplicate)
    second = deepcopy(data["notes"][0])
    second.update(call_id="call-0003", reference=ref("/calls/2/params/notes"))
    data["notes"].insert(0, second)
    doc = Document(render(data))
    assert 'data-count="write-acknowledgements">2<' in render(data)
    assert 'data-count="target-reads">1<' in render(data)
    assert "not unique call attribution" in doc.text


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(schema_version="future/v2"),
        lambda d: d.update(status="complete"),
        lambda d: d.pop("coverage"),
        lambda d: d.update(reward=1),
        lambda d: d["oracle_checks"].update(readback="false"),
        lambda d: d["oracle_checks"].update(provenance=False),
        lambda d: d["bindings"].update(evidence_sha256="invalid"),
        lambda d: d["notes"][0]["readback"].update(oracle_verified=True),
        lambda d: d["notes"][0]["readback"].update(stored_text_seen_call_ids=["unknown"]),
        lambda d: d["notes"][0]["readback"].update(references=[]),
        lambda d: d["notes"][0].update(matching_stored_note_ids=["unknown"]),
        lambda d: d["notes"][0]["reference"].update(document="javascript:alert(1)"),
        lambda d: d["notes"][0]["reference"].update(pointer="/bad~escape"),
        lambda d: d["notes"][0]["scope_exclusions"].update(status="matched"),
        lambda d: d["notes"][0]["scope_exclusions"]["issues"][0].update(code="unknown"),
        lambda d: d["observed_execution"]["successful_write_calls"][0].update(call_index=True),
        lambda d: d["notes"].clear(),
        lambda d: d["observed_execution"]["successful_write_calls"].append(
            deepcopy(d["observed_execution"]["successful_write_calls"][0])
        ),
        lambda d: d["notes"][0]["scope_exclusions"]["issues"][0].update(observed=float("nan")),
    ],
)
def test_malformed_or_unsupported_shape_is_rejected_explicitly(mutate):
    data = sample()
    mutate(data)
    with pytest.raises(ValueError):
        render(data)


@pytest.mark.parametrize(
    "value", [None, [], "text", {"schema_version": "healthcraft-reconciliation-explanation/v1"}]
)
def test_invalid_top_level_inputs_raise_value_error(value):
    with pytest.raises(ValueError):
        render(value)


def test_real_default_reference_and_unavailable_sidecars_are_supported_without_mutation():
    scenario, expected = load_scenario(), load_expectations()
    evidence = run_reconciliation_trial(scenario=scenario)
    explanation = explain_reconciliation(scenario, expected, evidence)
    before = deepcopy(explanation)
    html = render(explanation)
    assert "Verified" in Document(html).text
    assert "Exclusion records match supplied expectations" in Document(html).text
    assert "Identical retries acknowledged" in Document(html).text
    assert explanation == before and render(explanation) == html
    for invalid in (None, {}, {"bad": float("nan")}):
        assert "Explanation unavailable" in render(explain_reconciliation(invalid, expected, {}))
