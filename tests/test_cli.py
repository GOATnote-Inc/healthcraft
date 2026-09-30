"""Public commands must execute the advertised workflow or report a failure."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from healthcraft import cli
from healthcraft.llm import orchestrator

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/world/mercy_point_v1.yaml"


def test_evaluate_delegates_exact_arguments_to_the_real_orchestrator(monkeypatch):
    seen = []
    monkeypatch.setattr(orchestrator, "main", lambda argv, **kwargs: seen.append((argv, kwargs)))
    arguments = [
        "--agent-model",
        "ollama:installed-local",
        "--tasks",
        "IR-001",
        "--trials",
        "1",
        "--results-dir",
        "/tmp/new-run",
        "--rubric-channel",
        "v10",
        "--retry-errors",
    ]
    assert cli.main(["evaluate", *arguments]) == 0
    assert seen == [(arguments, {"prog": "healthcraft evaluate"})]


def test_evaluate_cannot_succeed_by_merely_listing_tasks(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["evaluate", "--tasks", "configs/tasks"])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "--agent-model" in captured.err
    assert "Loaded" not in captured.out


def test_evaluate_help_uses_real_options_without_provider_access(capsys, monkeypatch):
    monkeypatch.setattr(orchestrator, "_api_preflight", lambda **kw: pytest.fail("provider access"))
    with pytest.raises(SystemExit) as exc:
        cli.main(["evaluate", "--help"])
    assert exc.value.code == 0
    text = capsys.readouterr().out
    assert "healthcraft evaluate" in text
    assert "--agent-model" in text and "--scenario-profile" in text


def test_public_evaluate_reaches_live_runner_and_preserves_its_unassessed_summary(
    monkeypatch, tmp_path, capsys
):
    import json

    seen = []
    monkeypatch.setattr(orchestrator, "_api_preflight", lambda **kw: seen.append(("preflight", kw)))

    def evaluate(**kwargs):
        seen.append(("runner", kwargs))
        return {"evaluation_mode": "local_diagnostic", "pass_rate": None, "total_runs": 1}

    monkeypatch.setattr(orchestrator, "run_frontier_evaluation", evaluate)
    assert (
        cli.main(
            [
                "evaluate",
                "--agent-model",
                "ollama:installed-local",
                "--tasks",
                "IR-001",
                "--trials",
                "1",
                "--results-dir",
                str(tmp_path / "new-evaluation"),
            ]
        )
        == 0
    )
    assert [kind for kind, _ in seen] == ["preflight", "runner"]
    actual = seen[1][1]
    assert actual["agent_model"] == "ollama:installed-local"
    assert actual["judge_model"] is None and actual["task_filter"] == "IR-001"
    assert actual["trials"] == 1 and actual["results_dir"] == tmp_path / "new-evaluation"
    assert json.loads(capsys.readouterr().out)["pass_rate"] is None


@pytest.mark.parametrize(
    "flag,value", [("--trials", "0"), ("--trials", "-1"), ("--max-tasks", "0")]
)
def test_nonpositive_evaluation_counts_reject_before_preflight(monkeypatch, flag, value):
    monkeypatch.setattr(orchestrator, "_api_preflight", lambda **kw: pytest.fail("provider access"))
    with pytest.raises(SystemExit) as exc:
        cli.main(["evaluate", "--agent-model", "ollama:installed-local", flag, value])
    assert exc.value.code == 2


def test_evaluate_propagates_failure_exit_code(monkeypatch):
    def fail(*args, **kwargs):
        raise SystemExit(7)

    monkeypatch.setattr(orchestrator, "main", fail)
    with pytest.raises(SystemExit) as exc:
        cli.main(["evaluate", "--agent-model", "ollama:installed-local"])
    assert exc.value.code == 7


def test_simulation_routes_to_explicit_simulation_runner(monkeypatch):
    from healthcraft import eval_runner

    seen = []
    monkeypatch.setattr(eval_runner, "main", lambda argv: seen.append(argv) or 2)
    assert cli.main(["simulate", "--tasks", "IR-001"]) == 2
    assert seen == [["--tasks", "IR-001"]]


def test_list_tasks_retains_the_old_inventory_function_with_honest_name(capsys):
    path = next((ROOT / "configs/tasks/information_retrieval").glob("*.yaml"))
    assert cli.main(["list-tasks", "--tasks", str(path)]) == 0
    assert "Loaded 1 task(s)" in capsys.readouterr().out


def test_serve_runs_seeded_stdio_transport_without_stdout(monkeypatch, capsys):
    calls = []
    fake = SimpleNamespace(serve_stdio=lambda **kw: calls.append(kw))
    monkeypatch.setitem(sys.modules, "healthcraft.mcp.stdio", fake)
    assert cli.main(["serve", "--config", str(CONFIG), "--seed", "17"]) == 0
    assert calls == [{"config_path": CONFIG, "seed": 17}]
    assert capsys.readouterr().out == ""


def test_serve_reports_missing_dependency_failure_without_ready_message(monkeypatch, capsys):
    def unavailable(**kwargs):
        raise RuntimeError("Install healthcraft[mcp] to serve MCP over stdio")

    monkeypatch.setitem(
        sys.modules, "healthcraft.mcp.stdio", SimpleNamespace(serve_stdio=unavailable)
    )
    assert cli.main(["serve"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "healthcraft[mcp]" in captured.err


def test_serve_invalid_config_does_not_start_any_transport(monkeypatch, tmp_path):
    def forbidden(**kwargs):
        pytest.fail("transport started")

    monkeypatch.setitem(
        sys.modules, "healthcraft.mcp.stdio", SimpleNamespace(serve_stdio=forbidden)
    )
    assert cli.main(["serve", "--config", str(tmp_path / "missing.yaml")]) == 1


def test_stdio_refuses_http_port_instead_of_silently_ignoring_it(capsys):
    assert cli.main(["serve", "--port", "9000"]) != 0
    assert "--transport http" in capsys.readouterr().err


def test_explicit_http_transport_runs_existing_tool_api_and_propagates_exit(monkeypatch):
    seen = []
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())

    def run(argv, **kwargs):
        selected = {
            name: kwargs["env"][name]
            for name in (
                "HEALTHCRAFT_HOST",
                "HEALTHCRAFT_PORT",
                "HEALTHCRAFT_SEED",
                "HEALTHCRAFT_SEED_CONFIG",
            )
        }
        seen.append((argv, selected, kwargs.get("shell", False)))
        return SimpleNamespace(returncode=3)

    monkeypatch.setattr(subprocess, "run", run)
    assert cli.main(["serve", "--transport", "http", "--port", "9876", "--seed", "9"]) == 3
    assert seen == [
        (
            [sys.executable, "-m", "healthcraft.mcp.app"],
            {
                "HEALTHCRAFT_HOST": "127.0.0.1",
                "HEALTHCRAFT_PORT": "9876",
                "HEALTHCRAFT_SEED": "9",
                "HEALTHCRAFT_SEED_CONFIG": str(CONFIG),
            },
            False,
        )
    ]


def test_module_entrypoint_is_same_command_surface_as_installed_cli():
    completed = subprocess.run(
        [sys.executable, "-m", "healthcraft", "--help"],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0
    assert "evaluate" in completed.stdout and "serve" in completed.stdout
    assert "simulate" in completed.stdout and "list-tasks" in completed.stdout


def test_module_entrypoint_propagates_error_exit():
    completed = subprocess.run(
        [sys.executable, "-m", "healthcraft", "validate", "/nonexistent/healthcraft-input"],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 1
    assert "Path not found" in completed.stderr
