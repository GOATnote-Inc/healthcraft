"""The export command prepares a whole source-bound cohort before writing."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/export_roster_fhir.py"


def test_export_cli_writes_six_bundles_with_explicit_incomplete_validation(tmp_path):
    output = tmp_path / "export"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--output-dir", str(output)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    manifest = json.loads((output / "manifest.json").read_text())
    assert len(manifest["exports"]) == 6
    assert sum(row["coverage"]["resource_count"] for row in manifest["exports"]) == 99
    assert all(row["validation"]["structural_fhirpath"] == "not_run" for row in manifest["exports"])
    assert all(row["benchmark_score"] is None for row in manifest["exports"])
    assert all((output / row["bundle_file"]).exists() for row in manifest["exports"])
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    rerun = subprocess.run(
        [sys.executable, str(SCRIPT), "--output-dir", str(output)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert rerun.returncode != 0
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before
