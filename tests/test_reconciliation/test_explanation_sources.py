"""Opt-in source drilldown binds captured values without changing explanations."""

import hashlib
import json
from copy import deepcopy
from html.parser import HTMLParser

import pytest

from healthcraft.reconciliation.explanation_report import render_reconciliation_explanation


def digest(value):
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def reference(pointer, decoded=None, document="evidence"):
    value = {"document": document, "pointer": pointer}
    if decoded is not None:
        value["decoded_json_pointer"] = decoded
    return value


@pytest.fixture
def captured():
    note = {"scope_exclusions": [{"source_id": "SRC-1", "value": None}], "a/b": {"~key": ["exact"]}}
    checks = dict(
        provenance=True,
        source_fidelity=False,
        persisted_action=False,
        readback=False,
        execution_complete=True,
    )
    documents = {
        "scenario": {"authored": "Source assertion"},
        "expectations": {"scope_exclusions": [{"source_id": "SRC-1", "value": "expected"}]},
        "evidence": {
            "calls": [{"params": {"notes": json.dumps(note)}}],
            "after": {"notes": [note]},
            "a/b": {"~key": ["exact"]},
            "~1": "one-pass decode",
            "empty": {},
            "nil": None,
        },
        "oracle": {"checks": checks},
    }
    write_ref = reference("/calls/0")
    explanation = {
        "schema_version": "healthcraft-reconciliation-explanation/v1",
        "status": "available",
        "bindings": {key + "_sha256": digest(value) for key, value in documents.items()},
        "oracle_checks": checks,
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
                    "call_id": "call-1",
                    "call_index": 0,
                    "encounter_id": "ENC-1",
                    "reference": write_ref,
                }
            ],
            "deduplicated_retries": [],
            "new_stored_notes": [
                {
                    "note_id": "NOTE-1",
                    "patient_id": "PAT-1",
                    "encounter_id": "ENC-1",
                    "reference": reference("/after/notes/0"),
                }
            ],
        },
        "notes": [
            {
                "call_id": "call-1",
                "reference": reference("/calls/0/params/notes"),
                "matching_stored_note_ids": ["NOTE-1"],
                "scope_exclusions": {
                    "status": "different",
                    "issues": [
                        {
                            "code": "exclusion_field_mismatch",
                            "source_id": "SRC-1",
                            "field": "value",
                            "observed": None,
                            "expected": "expected",
                            "evidence_refs": [
                                reference("/calls/0/params/notes", "/scope_exclusions/0/value")
                            ],
                            "expectation_refs": [
                                reference("/scope_exclusions/0/value", document="expectations")
                            ],
                        }
                    ],
                },
                "readback": {
                    "attempted_call_ids": [],
                    "successful_target_call_ids": [],
                    "stored_text_seen_call_ids": [],
                    "references": [],
                    "oracle_verified": False,
                },
            }
        ],
        "errors": [],
        "limitations": ["Engineering source comparison only."],
    }
    return explanation, documents


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags, self.text, self.card_text, self.card_attrs = [], [], {}, {}
        self.current_card = None
        self.in_details = 0
        self.hidden_targets = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        self.tags.append((tag, attrs))
        if tag == "details":
            self.in_details += 1
        if attrs.get("data-source-card"):
            self.current_card = attrs["id"]
            self.card_attrs[self.current_card] = attrs
            self.card_text[self.current_card] = []
            if self.in_details:
                self.hidden_targets.append(self.current_card)

    def handle_endtag(self, tag):
        if tag == "details":
            self.in_details -= 1
        if tag == "article" and self.current_card:
            self.current_card = None

    def handle_data(self, value):
        self.text.append(value)
        if self.current_card:
            self.card_text[self.current_card].append(value)


def render(captured):
    explanation, documents = captured
    return render_reconciliation_explanation(
        explanation, source_context=True, source_documents=documents
    )


def set_ref(captured, ref):
    captured[0]["observed_execution"]["successful_write_calls"][0]["reference"] = ref


def card(captured, pointer, decoded=None, document="evidence"):
    set_ref(captured, reference(pointer, decoded, document))
    page = Page(render(captured))
    selected = [
        key
        for key, attrs in page.card_attrs.items()
        if attrs["data-document"] == document
        and attrs["data-pointer"] == pointer
        and attrs.get("data-decoded-pointer") == decoded
    ]
    assert len(selected) == 1
    key = selected[0]
    return page.card_attrs[key], " ".join(page.card_text[key])


def test_default_remains_inert_and_explicit_false_is_identical(captured):
    explanation, _ = captured
    before = deepcopy(captured)
    old = render_reconciliation_explanation(explanation)
    explicit = render_reconciliation_explanation(explanation, source_context=False)
    assert old == explicit
    assert hashlib.sha256(old.encode("utf-8")).hexdigest() == (
        "08d6b230f24f58a35bbf15b4e9eadc4532277763b7037ba80af93605d7d911fc"
    )
    assert not [attrs for tag, attrs in Page(old).tags if tag == "a"]
    assert "Source pointers are inert text" in old
    assert captured == before


def test_every_reference_links_to_one_visible_deduplicated_exact_card(captured):
    before = deepcopy(captured)
    refs = captured[0]["notes"][0]["scope_exclusions"]["issues"][0]["evidence_refs"]
    refs.extend(deepcopy(refs))
    expected = deepcopy(captured)
    page = Page(render(captured))
    links = [attrs["href"] for tag, attrs in page.tags if tag == "a"]
    ids = [attrs["id"] for _, attrs in page.tags if "id" in attrs]
    assert links and all(link.startswith("#") and link[1:] in page.card_attrs for link in links)
    assert len(ids) == len(set(ids))
    assert len(page.card_attrs) == 5
    assert page.hidden_targets == []
    assert "Observed evidence" in " ".join(page.text)
    assert "Expected contract" in " ".join(page.text)
    assert captured == expected and captured != before


@pytest.mark.parametrize(
    "pointer,decoded,expected",
    [
        ("/a~1b/~0key/0", None, '"exact"'),
        ("/~01", None, '"one-pass decode"'),
        ("/calls/0/params/notes", "/a~1b/~0key/0", '"exact"'),
        ("", None, '"one-pass decode"'),
        ("/nil", None, "null"),
    ],
)
def test_rfc6901_values_and_embedded_note_paths_are_exact(captured, pointer, decoded, expected):
    attrs, text = card(captured, pointer, decoded)
    assert attrs["data-resolution"] == "available"
    assert "Exact captured value" in text and expected in text
    assert "context" in text.lower()
    if decoded is not None:
        assert "Raw captured JSON note" in text


@pytest.mark.parametrize(
    "pointer,decoded,reason",
    [
        ("/empty/missing/child", None, "Missing object member"),
        ("/calls/9/name", None, "Array index out of range"),
        ("/calls/01", None, "Invalid array index"),
        ("/calls/-", None, "Invalid array index"),
        ("/nil/value", None, "Cannot descend into a scalar"),
        ("/calls/0/params/notes", "/scope_exclusions/0/missing", "Missing object member"),
    ],
)
def test_missing_is_unavailable_with_nearest_context_not_an_invented_null(
    captured, pointer, decoded, reason
):
    attrs, text = card(captured, pointer, decoded)
    assert attrs["data-resolution"] == "unavailable"
    assert "Exact captured value" not in text
    assert reason in text and "Nearest existing context" in text
    # A real null may occur in the surrounding context; it must not be supplied
    # as the missing location's exact value.
    assert "Source value unavailable" in text


@pytest.mark.parametrize(
    "raw", ["not-json<script>alert(1)</script>", '{"x":1,"x":2}', '{"x":1e400}', "NaN"]
)
def test_invalid_embedded_note_retains_raw_text_and_reason(captured, raw):
    explanation, documents = captured
    documents["evidence"]["calls"][0]["params"]["notes"] = raw
    explanation["bindings"]["evidence_sha256"] = digest(documents["evidence"])
    attrs, text = card(captured, "/calls/0/params/notes", "/x")
    assert attrs["data-resolution"] == "unavailable"
    assert "Embedded JSON unavailable" in text and raw in text
    assert "Raw captured JSON note" in text
    assert not any(tag == "script" for tag, _ in Page(render(captured)).tags)


def test_natural_bare_note_reference_keeps_raw_malformed_text_and_parse_reason(captured):
    explanation, documents = captured
    raw = "not-json<script>untrusted</script>"
    documents["evidence"]["calls"][0]["params"]["notes"] = raw
    explanation["bindings"]["evidence_sha256"] = digest(documents["evidence"])
    explanation["notes"][0]["scope_exclusions"] = {
        "status": "malformed",
        "issues": [
            {
                "code": "exclusions_not_parseable",
                "message": "Recorded parse error",
                "evidence_refs": [reference("/calls/0/params/notes")],
            }
        ],
    }
    attrs, text = card(captured, "/calls/0/params/notes")
    assert attrs["data-resolution"] == "available"
    assert attrs["data-note-resolution"] == "unavailable"
    assert "Exact captured value" in text
    assert "Raw captured JSON note" in text and raw in text
    assert "JSONDecodeError" in text and "Embedded JSON unavailable" in text


def test_valid_bare_note_reference_includes_literal_readable_multiline_text(captured):
    explanation, documents = captured
    raw = json.dumps(json.loads(documents["evidence"]["calls"][0]["params"]["notes"]), indent=2)
    documents["evidence"]["calls"][0]["params"]["notes"] = raw
    explanation["bindings"]["evidence_sha256"] = digest(documents["evidence"])
    attrs, text = card(captured, "/calls/0/params/notes")
    assert attrs["data-resolution"] == "available"
    assert attrs["data-note-resolution"] == "available"
    assert "Exact captured value" in text
    assert "Raw captured JSON note" in text and raw in text


def test_oracle_checks_reject_python_boolean_integer_equivalence(captured):
    explanation, documents = captured
    documents["oracle"] = deepcopy(documents["oracle"])
    documents["oracle"]["checks"]["provenance"] = 1
    explanation["bindings"]["oracle_sha256"] = digest(documents["oracle"])
    with pytest.raises(ValueError, match="oracle checks"):
        render(captured)


@pytest.mark.parametrize("document", ["scenario", "expectations", "evidence", "oracle"])
def test_each_original_document_is_required_and_hash_bound(captured, document):
    explanation, documents = captured
    documents[document]["changed"] = True
    with pytest.raises(ValueError, match="binding"):
        render(captured)
    documents.pop(document)
    with pytest.raises(ValueError, match="documents"):
        render(captured)


def test_unavailable_explanation_still_requires_complete_valid_bindings(captured):
    explanation, documents = captured
    explanation.update(
        status="unavailable",
        observed_execution=None,
        notes=[],
        errors=[{"message": "Synthetic unavailable provenance"}],
    )
    html = render(captured)
    assert "Event counts unavailable" in html
    assert not Page(html).card_attrs
    explanation["bindings"] = {}
    with pytest.raises(ValueError, match="binding"):
        render(captured)
    with pytest.raises(ValueError, match="documents"):
        render_reconciliation_explanation(explanation, source_context=True)


@pytest.mark.parametrize("flag", [None, 0, 1, "true"])
def test_source_context_flag_is_an_actual_boolean(captured, flag):
    with pytest.raises(ValueError, match="source_context"):
        render_reconciliation_explanation(captured[0], source_context=flag)


def test_hostile_source_is_text_and_only_local_fragments_are_active(captured):
    explanation, documents = captured
    value = '</pre><script>alert(1)</script><img src="https://invalid.test/x" onerror="x">'
    documents["scenario"]["authored"] = value
    explanation["bindings"]["scenario_sha256"] = digest(documents["scenario"])
    attrs, text = card(captured, "/authored", document="scenario")
    page = Page(render(captured))
    assert attrs["data-resolution"] == "available" and json.dumps(value) in text
    assert "Authored scenario" in text
    for tag, attributes in page.tags:
        assert tag not in {"script", "img", "iframe", "object", "embed", "link"}
        assert all(not key.lower().startswith("on") for key in attributes)
        assert "src" not in attributes
        if "href" in attributes:
            assert attributes["href"].startswith("#")


@pytest.mark.parametrize("mode", ["original", "decoded", "decoded_malformed_note"])
def test_bare_newline_is_not_a_pointer_even_when_an_empty_key_exists(captured, mode):
    explanation, documents = captured
    documents["evidence"][""] = "Must not resolve through a malformed pointer"
    note = {"": "Must not resolve through a malformed decoded pointer"}
    documents["evidence"]["calls"][0]["params"]["notes"] = (
        "not-json" if mode == "decoded_malformed_note" else json.dumps(note)
    )
    explanation["bindings"]["evidence_sha256"] = digest(documents["evidence"])
    set_ref(
        captured,
        reference("\n") if mode == "original" else reference("/calls/0/params/notes", "\n"),
    )
    with pytest.raises(ValueError, match="RFC6901"):
        render(captured)


@pytest.mark.parametrize("decoded", [False, True])
def test_newline_inside_a_valid_member_pointer_is_preserved(captured, decoded):
    explanation, documents = captured
    documents["evidence"]["line\n"] = "Literal newline member"
    documents["evidence"]["calls"][0]["params"]["notes"] = json.dumps(
        {"line\n": "Literal newline member"}
    )
    explanation["bindings"]["evidence_sha256"] = digest(documents["evidence"])
    attrs, text = card(
        captured, "/calls/0/params/notes" if decoded else "/line\n", "/line\n" if decoded else None
    )
    assert attrs["data-resolution"] == "available"
    assert "Literal newline member" in text and "Exact captured value" in text
