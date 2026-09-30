"""The paper gate must check engineering evidence paths as well as results."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def verifier(tmp_path: Path):
    path = Path(__file__).resolve().parents[1] / "scripts/verify_canonical_numbers.py"
    spec = importlib.util.spec_from_file_location("canonical_number_verifier", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.REPO = tmp_path
    module.CANONICAL = tmp_path / "canonical_numbers.md"
    content = tmp_path / "content.tex"
    content.write_text("A recorded count. % CN:captured\n", encoding="utf-8")
    module.CONTENT_FILES = [content]
    return module


def write_source(verifier, source: str, *, deferred: str | None = None) -> None:
    text = f"| `CN:captured` | Recorded count | 1 | n/a | `{source}` |\n"
    if deferred is not None:
        text += f"\n## Deferred artifacts\n\n| `{deferred}` | Awaiting capture |\n"
    verifier.CANONICAL.write_text(text, encoding="utf-8")


@pytest.mark.parametrize(
    "source",
    [
        "artifacts/run/missing.json",
        "artifacts/run/missing.json#$.counts.completed",
        "artifacts/run/*.json",
    ],
)
def test_missing_artifact_source_is_a_hard_failure(verifier, capsys, source: str) -> None:
    write_source(verifier, source)

    assert verifier.main() == 1
    output = capsys.readouterr().out
    assert "Source paths cited in canonical_numbers.md do not exist" in output
    assert "artifacts/run/" in output
    assert "PASS: canonical-numbers" not in output


def test_existing_artifact_source_with_pointer_is_checked(verifier) -> None:
    source = verifier.REPO / "artifacts/run/report.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"counts":{"completed":1}}\n', encoding="utf-8")
    write_source(verifier, "artifacts/run/report.json#$.counts.completed")

    assert verifier.load_source_paths() == {"artifacts/run/report.json": ["captured"]}
    assert verifier.main() == 0


def test_explicitly_deferred_artifact_retains_warning(verifier, capsys) -> None:
    path = "artifacts/run/report.json"
    write_source(verifier, path, deferred=path)

    assert verifier.main() == 0
    output = capsys.readouterr().out
    assert "WARN: deferred Source artifacts" in output
    assert path in output


def test_existing_results_path_behavior_is_unchanged(verifier) -> None:
    source = verifier.REPO / "results/frozen/summary.json"
    source.parent.mkdir(parents=True)
    source.write_text("{}\n", encoding="utf-8")
    write_source(verifier, "results/frozen/summary.json:1")

    assert verifier.load_source_paths() == {"results/frozen/summary.json": ["captured"]}
    assert verifier.main() == 0
