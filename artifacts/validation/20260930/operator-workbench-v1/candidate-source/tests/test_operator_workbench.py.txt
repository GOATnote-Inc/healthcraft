"""A new review view preserves the original assignment and issuer artifacts."""

from __future__ import annotations

import hashlib
import importlib
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
ORIGINAL = ROOT / "artifacts/operator-review/20260930/incidents-v2"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def core(monkeypatch):
    module = importlib.import_module("healthcraft.operator_workbench")
    monkeypatch.setattr(module, "_implementation", lambda: {"synthetic-test-view": "a" * 64})
    monkeypatch.setattr(module, "_render", lambda p, t: json.dumps([p, t], sort_keys=True))
    return module


@pytest.fixture
def issuer(tmp_path):
    path = tmp_path / "issuer"
    shutil.copytree(ORIGINAL / "native-assisted", path)
    return path


def test_view_retains_exact_original_packet_template_and_complete_roster(core, issuer, tmp_path):
    before = {p.relative_to(issuer).as_posix(): digest(p) for p in issuer.rglob("*") if p.is_file()}
    value = core.build_workbench(issuer / "manifest.json", tmp_path / "view")
    assert value["issuer_kind"] == "incident"
    for name in ("packet.json", "response-template.json"):
        assert (tmp_path / "view/public" / name).read_bytes() == (
            issuer / "public" / name
        ).read_bytes()
    packet, manifest = core.validate_workbench(tmp_path / "view/manifest.json")
    assert len(packet["cases"]) == 4
    assert manifest["issuer_manifest_sha256"] == digest(issuer / "manifest.json")
    assert manifest["packet_sha256"] == value["packet_sha256"]
    assert {
        p.relative_to(issuer).as_posix(): digest(p) for p in issuer.rglob("*") if p.is_file()
    } == before
    assert set(manifest["files"]) == {
        "public/packet.json",
        "public/response-template.json",
        "public/report.html",
        "README.md",
    }


@pytest.mark.parametrize("kind", ["synthetic-reviewer-a", "synthetic-resolver"])
def test_adjudication_views_keep_original_reports_and_prior_judgments(core, tmp_path, kind):
    issuer = tmp_path / "issuer"
    shutil.copytree(ORIGINAL / kind, issuer)
    value = core.build_workbench(issuer / "manifest.json", tmp_path / "view")
    assert value["issuer_kind"] == "adjudication"
    packet, _ = core.validate_workbench(tmp_path / "view/manifest.json")
    original = json.loads((issuer / "public/packet.json").read_text())
    assert packet == original
    assert all(
        c["overall"] is None
        for c in json.loads((tmp_path / "view/public/response-template.json").read_text())["cases"]
    )


def test_output_inside_issuer_rejected_before_writes(core, issuer):
    with pytest.raises(ValueError):
        core.build_workbench(issuer / "manifest.json", issuer / "new-view")
    assert not (issuer / "new-view").exists()


def test_output_inside_original_source_override_rejected(core, issuer, tmp_path):
    original = ROOT / "artifacts/reconciliation/20260930/casebook-native-v2/run"
    source = tmp_path / "source"
    shutil.copytree(original, source)
    with pytest.raises(ValueError):
        core.build_workbench(
            issuer / "manifest.json",
            source / "view",
            source_manifest_override=source / "manifest.json",
        )
    assert not (source / "view").exists()


def test_output_is_exclusive(core, issuer, tmp_path):
    core.build_workbench(issuer / "manifest.json", tmp_path / "view")
    before = digest(tmp_path / "view/manifest.json")
    with pytest.raises(FileExistsError):
        core.build_workbench(issuer / "manifest.json", tmp_path / "view")
    assert digest(tmp_path / "view/manifest.json") == before


@pytest.mark.parametrize("target", ["issuer", "packet", "template", "html", "extra"])
def test_view_validation_rechecks_inputs_and_every_payload(core, issuer, tmp_path, target):
    core.build_workbench(issuer / "manifest.json", tmp_path / "view")
    path = {
        "issuer": issuer / "manifest.json",
        "packet": tmp_path / "view/public/packet.json",
        "template": tmp_path / "view/public/response-template.json",
        "html": tmp_path / "view/public/report.html",
        "extra": tmp_path / "view/public/extra.txt",
    }[target]
    path.write_bytes(path.read_bytes() + b" " if path.exists() else b"extra")
    with pytest.raises(ValueError):
        core.validate_workbench(tmp_path / "view/manifest.json")


def test_issuer_can_move_only_with_identical_manifest_override(core, issuer, tmp_path):
    core.build_workbench(issuer / "manifest.json", tmp_path / "view")
    moved = tmp_path / "moved"
    issuer.rename(moved)
    packet, _ = core.validate_workbench(
        tmp_path / "view/manifest.json", issuer_manifest_override=moved / "manifest.json"
    )
    assert len(packet["cases"]) == 4
    (moved / "manifest.json").write_bytes((moved / "manifest.json").read_bytes() + b" ")
    with pytest.raises(ValueError):
        core.validate_workbench(
            tmp_path / "view/manifest.json", issuer_manifest_override=moved / "manifest.json"
        )


def test_rehashed_altered_public_source_cannot_replace_original(core, issuer, tmp_path):
    core.build_workbench(issuer / "manifest.json", tmp_path / "view")
    path = tmp_path / "view/public/packet.json"
    value = json.loads(path.read_text())
    value["cases"][0]["documents"]["task"]["target"]["patient_id"] = "PAT-WRONG"
    path.write_text(json.dumps(value))
    manifest_path = tmp_path / "view/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["public/packet.json"] = digest(path)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        core.validate_workbench(manifest_path)


def test_issuing_view_implementation_must_match(core, issuer, tmp_path, monkeypatch):
    core.build_workbench(issuer / "manifest.json", tmp_path / "view")
    monkeypatch.setattr(core, "_implementation", lambda: {"synthetic-test-view": "b" * 64})
    with pytest.raises(ValueError):
        core.validate_workbench(tmp_path / "view/manifest.json")


@pytest.mark.parametrize("via_symlink", [False, True])
def test_output_cannot_invalidate_an_existing_unlisted_inventory(
    core, issuer, tmp_path, via_symlink
):
    prior = tmp_path / "prior-import"
    prior.mkdir()
    (prior / "submission.json").write_text("{}")
    (prior / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "healthcraft-operator-adjudication-import/v2",
                "files": {"submission.json": digest(prior / "submission.json")},
            }
        )
    )
    target = prior
    if via_symlink:
        target = tmp_path / "prior-link"
        target.symlink_to(prior, target_is_directory=True)
    before = {p.name: p.read_bytes() for p in prior.iterdir()}
    with pytest.raises(ValueError, match="inventory|manifest"):
        core.build_workbench(issuer / "manifest.json", target / "new-view")
    assert {p.name: p.read_bytes() for p in prior.iterdir()} == before
