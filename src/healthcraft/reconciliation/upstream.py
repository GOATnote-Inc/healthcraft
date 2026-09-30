"""Optional unchanged HealthAgentBench CSV verifier, separate from workflow validity.

Only the code/license are vendored. No upstream data or bootstrap is used. The
wrapper runs from a source checkout; pandas is imported only when explicitly run.
Content hashes detect drift, not independent authentication or clinical validity.
"""

from __future__ import annotations

import csv
import hashlib
import importlib
import importlib.util
import io
import json
import math
import platform
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any

VENDOR_DIR = Path(__file__).resolve().parents[3] / "integrations" / "healthagentbench"
SOURCE_SHA256 = "7ce0c9808afb5efb031c04e535e22f4fd8cad093b6bd500681c87fef2a8fde5d"
LICENSE_SHA256 = "646f8936b8ddcd14e13e578ff6857e368780b0d1a4f6066bee89211923a373e2"
PROVENANCE_SHA256 = "50d551db084236bad581ae4fd24e3f1e64365b93b05a0b581453affa341150aa"
VENDOR_HASHES = {
    "harbor_evaluator.py.txt": SOURCE_SHA256,
    "LICENSE": LICENSE_SHA256,
    "provenance.json": PROVENANCE_SHA256,
}
LABEL_COLUMNS = {"table", "_row_id", "cluster_id", "error_family", "error_subtype"}
LIMITATIONS = [
    "Secondary CSV compatibility metric on original synthetic labels; not an official "
    "HealthAgentBench result or a comparison of model performance.",
    "Upstream reward requires all labeled clusters and only 1% row precision; either source "
    "in a disagreement cluster can catch it. Neither source is thereby declared clinically false.",
    "This metric cannot establish source interpretation, note content, persistence, clinical "
    "correctness, safety, or readiness. These require separate evidence.",
    "Input/source snapshots and hashes bind local content; they are not independent attestation. "
    "No runtime isolation of hidden labels from an agent is provided by this function.",
]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _verified_vendor() -> dict[str, bytes]:
    files = {name: (VENDOR_DIR / name).read_bytes() for name in VENDOR_HASHES}
    if any(_sha(data) != VENDOR_HASHES[name] for name, data in files.items()):
        raise ValueError("Vendored verifier, MIT license, or provenance differs from pinned bytes")
    return files


def _validate_labels(data: bytes) -> int:
    rows = list(csv.reader(io.StringIO(data.decode("utf-8"), newline=""), strict=True))
    if not rows or len(rows[0]) != len(LABEL_COLUMNS) or set(rows[0]) != LABEL_COLUMNS:
        raise ValueError("Labels require exactly the five documented unique column names")
    if len(rows) < 2:
        raise ValueError("Labels require at least one authored contradiction row")
    seen: set[tuple[str, str]] = set()
    cluster_kinds: dict[str, tuple[str, str]] = {}
    for values in rows[1:]:
        if len(values) != len(rows[0]) or any(
            not value or value != value.strip() or "\x00" in value for value in values
        ):
            raise ValueError("Labels require complete nonempty cells without padding or NUL")
        row = dict(zip(rows[0], values))
        identity = (row["table"], row["_row_id"])
        if identity in seen:
            raise ValueError("Duplicate labeled source-row identity")
        seen.add(identity)
        kind = (row["error_family"], row["error_subtype"])
        if cluster_kinds.setdefault(row["cluster_id"], kind) != kind:
            raise ValueError("One cluster cannot have conflicting family/subtype labels")
    return len(rows) - 1


def _pandas_version() -> str:
    return str(importlib.import_module("pandas").__version__)


def _load_verifier(path: Path) -> Any:
    """Execute verified source bytes via SourceFileLoader, without cached bytecode."""
    loader = SourceFileLoader("_healthcraft_pinned_healthagentbench_verifier", str(path))
    source = loader.get_data(str(path))
    if _sha(source) != SOURCE_SHA256:
        raise ValueError("Verifier snapshot changed before import")
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise ImportError("Unable to build pinned verifier module spec")
    module = importlib.util.module_from_spec(spec)
    exec(loader.source_to_code(source, str(path)), module.__dict__)
    return module


def _strict_json(text: str) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate key in upstream metrics")
            result[key] = value
        return result

    def number(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("Nonfinite value in upstream metrics")
        return parsed

    def constant(value):
        raise ValueError(f"Nonfinite constant in upstream metrics: {value}")

    return json.loads(text, object_pairs_hook=pairs, parse_float=number, parse_constant=constant)


def _read_outputs(logs: Path, reward: Any, turn_count: int) -> dict[str, Any]:
    metrics = _strict_json((logs / "metrics.json").read_text())
    saved_reward = float((logs / "reward.txt").read_text().strip())
    if (
        type(reward) not in (int, float)
        or reward not in (0, 1)
        or not isinstance(metrics, dict)
        or type(metrics.get("reward")) not in (int, float)
        or metrics["reward"] != reward
        or saved_reward != reward
        or type(metrics.get("turn_count")) is not int
        or metrics["turn_count"] != turn_count
        or ((logs / "verifier_error.txt").exists() and reward != 0)
    ):
        raise ValueError("Upstream return, raw metrics, reward file, or declared turns disagree")
    return metrics


def run_upstream_verifier(
    submission_csv: Path,
    labels_csv: Path,
    output_dir: Path,
    *,
    turn_count: int,
) -> dict[str, Any]:
    """Preserve one scheduled secondary evaluation in a new exclusive directory.

    Existing output directories (including empty ones) and invalid caller turn
    counts raise before work. Other failures are returned and saved with distinct
    statuses. Invalid grader inputs/dependencies/provenance never become reward 0.
    A missing/malformed agent submission keeps the upstream reward/error artifacts.
    Labels must be original synthetic inputs supplied by the coordinator.
    """
    if type(turn_count) is not int or turn_count < 0:
        raise ValueError("turn_count must be an explicitly declared nonnegative integer")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    result: dict[str, Any] = {
        "schema_version": "healthagentbench-verifier-adapter/v1",
        "status": "started",
        "scheduled_evaluations": 1,
        "attempted_evaluations": 0,
        "declared_turn_count": turn_count,
        "upstream_reward": None,
        "metrics": None,
        "error": None,
        "clinical_assessment": False,
        "persistence_assessment": False,
        "official_benchmark_result": False,
        "provenance": {
            "source_sha256": SOURCE_SHA256,
            "license_sha256": LICENSE_SHA256,
            "provenance_sha256": PROVENANCE_SHA256,
            "wrapper_sha256": _sha(Path(__file__).read_bytes()),
            "python_version": platform.python_version(),
            "pandas_version": None,
            "target_runtime_matches": False,
        },
        "inputs": {},
        "artifacts": {},
        "artifact_errors": [],
        "limitations": LIMITATIONS.copy(),
    }
    report = output_dir / "report.json"
    _write_json(report, result)
    stage = "provenance"
    status = "provenance_error"
    baseline: dict[str, str] = {}
    try:
        vendor = _verified_vendor()
        source_dir = output_dir / "vendor"
        source_dir.mkdir()
        for name, data in vendor.items():
            (source_dir / name).write_bytes(data)
            baseline[f"vendor/{name}"] = _sha(data)
        result["provenance"]["upstream"] = json.loads(vendor["provenance.json"])
        stage, status = "labels", "invalid_labels"
        inputs_dir = output_dir / "inputs"
        inputs_dir.mkdir()
        data = Path(labels_csv).read_bytes()
        (inputs_dir / "labels.csv").write_bytes(data)
        baseline["inputs/labels.csv"] = _sha(data)
        result["inputs"]["labels"] = {"sha256": _sha(data), "available": True}
        result["inputs"]["labels"]["rows"] = _validate_labels(data)
        stage, status = "submission_snapshot", "grader_error"
        try:
            data = Path(submission_csv).read_bytes()
        except FileNotFoundError:
            result["inputs"]["submission"] = {"sha256": None, "available": False}
        else:
            (inputs_dir / "submission.csv").write_bytes(data)
            baseline["inputs/submission.csv"] = _sha(data)
            result["inputs"]["submission"] = {"sha256": _sha(data), "available": True}
        stage, status = "dependency", "unavailable_dependency"
        version = _pandas_version()
        result["provenance"]["pandas_version"] = version
        result["provenance"]["target_runtime_matches"] = (
            platform.python_version_tuple()[:2] == ("3", "12") and version == "3.0.1"
        )
        stage, status = "verifier_import", "grader_error"
        module = _load_verifier(source_dir / "harbor_evaluator.py.txt")
        stage = "verifier_execution"
        logs = output_dir / "upstream"
        result["attempted_evaluations"] = 1
        _write_json(report, result)
        reward = module.evaluate(
            inputs_dir / "submission.csv",
            inputs_dir / "labels.csv",
            logs,
            turn_count_override=turn_count,
        )
        stage = "verifier_outputs"
        metrics = _read_outputs(logs, reward, turn_count)
        stage, status = "postflight_provenance", "provenance_error"
        _verified_vendor()
        if any(_sha((output_dir / name).read_bytes()) != sha for name, sha in baseline.items()):
            raise ValueError("Verifier or input snapshot changed during execution")
        result.update(
            status="invalid_submission" if (logs / "verifier_error.txt").exists() else "completed",
            upstream_reward=reward,
            metrics=metrics,
        )
    except Exception as exc:
        result.update(
            status=status, error={"stage": stage, "type": type(exc).__name__, "message": str(exc)}
        )
    try:
        for path in sorted(output_dir.rglob("*")):
            if not path.is_file() or path == report:
                continue
            relative = str(path.relative_to(output_dir))
            try:
                result["artifacts"][relative] = _sha(path.read_bytes())
            except OSError as exc:
                result["artifact_errors"].append(
                    {"path": relative, "type": type(exc).__name__, "message": str(exc)}
                )
    except OSError as exc:
        result["artifact_errors"].append(
            {"path": ".", "type": type(exc).__name__, "message": str(exc)}
        )
    if result["artifact_errors"]:
        result.update(status="provenance_error", upstream_reward=None, metrics=None)
        if result["error"] is None:
            result["error"] = {
                "stage": "artifact_inventory",
                "type": "ArtifactReadError",
                "message": "Raw artifact inventory incomplete; see artifact_errors",
            }
    _write_json(report, result)
    return result
