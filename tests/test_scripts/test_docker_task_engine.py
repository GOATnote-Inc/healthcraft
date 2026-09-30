"""Execute the declared image entrypoint without building an image or running models."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from healthcraft import eval_runner

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "docker/task-engine/Dockerfile"


def image_entrypoint(tmp_path, arguments=(), *, status=0):
    """Materialize entrypoint COPY files, then record the real shell's invocation."""
    image = tmp_path / "image"
    image.mkdir()
    binary = tmp_path / "bin"
    binary.mkdir()
    recorder = binary / "python"
    recorder.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "pathlib.Path(os.environ['CAPTURE_JSON']).write_text(json.dumps(sys.argv[1:]))\n"
        "print('delegated stdout')\n"
        "print('delegated stderr', file=sys.stderr)\n"
        "sys.exit(int(os.environ['RECORDER_EXIT']))\n"
    )
    recorder.chmod(0o755)
    lines = DOCKERFILE.read_text().splitlines()
    for line in lines:
        if line.startswith("COPY docker/task-engine/"):
            _, source, destination = line.split()
            shutil.copyfile(ROOT / source, image / Path(destination).name)
    raw = next(line.removeprefix("ENTRYPOINT ") for line in lines if line.startswith("ENTRYPOINT "))
    entrypoint = [part.replace("/app/", str(image) + "/") for part in json.loads(raw)]
    capture = tmp_path / "invocation.json"
    environment = {
        **os.environ,
        "PATH": str(binary) + os.pathsep + os.environ["PATH"],
        "CAPTURE_JSON": str(capture),
        "RECORDER_EXIT": str(status),
        "HEALTHCRAFT_MODEL": "simulated",
        "HEALTHCRAFT_TRIALS": "7",
        "HEALTHCRAFT_SEED": "19",
        "HEALTHCRAFT_LOG_LEVEL": "DEBUG",
        "HEALTHCRAFT_RESULTS_DIR": str(tmp_path / "new-results"),
    }
    completed = subprocess.run(
        [*entrypoint, *arguments],
        cwd=image,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return completed, json.loads(capture.read_text())


def runner_options(monkeypatch, invocation):
    assert invocation[:3] == ["-m", "healthcraft", "simulate"]
    calls = []

    def record(*args):
        calls.append(args)
        return {"execution_error_runs": 0, "tool_error_runs": 0}

    monkeypatch.setattr(eval_runner, "run_evaluation", record)
    assert eval_runner.main(invocation[3:]) == 0
    assert len(calls) == 1
    return calls[0]


def test_declared_entrypoint_consumes_environment_and_positional_task(tmp_path, monkeypatch):
    completed, invocation = image_entrypoint(tmp_path, ["IR-001"])
    assert completed.returncode == 0
    task, model, trials, seed, output, _ = runner_options(monkeypatch, invocation)
    assert (task, model, trials, seed) == ("IR-001", "simulated", 7, 19)
    assert output == tmp_path / "new-results"
    assert invocation[invocation.index("--log-level") + 1] == "DEBUG"


def test_explicit_runner_flags_override_environment_defaults(tmp_path, monkeypatch):
    completed, invocation = image_entrypoint(
        tmp_path, ["--tasks", "CC-001", "--trials", "2", "--seed", "31"]
    )
    assert completed.returncode == 0
    task, model, trials, seed, output, _ = runner_options(monkeypatch, invocation)
    assert (task, model, trials, seed) == ("CC-001", "simulated", 2, 31)
    assert output == tmp_path / "new-results"


@pytest.mark.parametrize("status", [0, 1, 2, 47])
def test_entrypoint_preserves_child_status_and_streams(tmp_path, status):
    completed, _ = image_entrypoint(tmp_path, status=status)
    assert completed.returncode == status
    assert completed.stdout == "delegated stdout\n"
    assert completed.stderr == "delegated stderr\n"


def test_compose_task_engine_only_advertises_consumed_environment():
    compose = yaml.safe_load((ROOT / "docker/docker-compose.yaml").read_text())
    environment = compose["services"]["task-engine"]["environment"]
    assert set(environment) == {
        "HEALTHCRAFT_MODEL",
        "HEALTHCRAFT_TRIALS",
        "HEALTHCRAFT_SEED",
        "HEALTHCRAFT_LOG_LEVEL",
    }
