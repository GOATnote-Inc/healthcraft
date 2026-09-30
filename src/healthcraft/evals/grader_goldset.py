"""Hermetic engineering regression fixtures exercised through real graders.

World cases supply synthetic audit entries, not executed tool trajectories.
Judge-parser cases supply canned responses, not independent clinical reviews.
Expected labels and explanatory notes are regression expectations; this file
does not verify physician adjudication or establish clinical ground truth.

Selected, potentially correlated fixtures measure known regression coverage.
Nominal Wilson intervals are not population estimates or clinical calibration.
Any harness error or safety-marked false pass blocks this regression gate;
passing it is not evidence of clinical safety or deployment readiness.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from healthcraft.llm.judge import LLMJudge
from healthcraft.tasks.evaluator import _apply_overlay_to_task, evaluate_task
from healthcraft.tasks.loader import Task, load_tasks
from healthcraft.tasks.rubrics import Criterion, VerificationMethod
from healthcraft.world.state import WorldState

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TASKS_DIR = _REPO_ROOT / "configs" / "tasks"
_DEFAULT_GOLDSET = _REPO_ROOT / "evals" / "grader_goldset" / "goldset.yaml"

_SEED_TIME = "2026-01-15T07:00:00+00:00"


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (no SciPy dependency).

    Returns (low, high) for the rate successes/n. For n == 0 returns (0.0, 1.0)
    — an unmeasured rate is maximally uncertain, never silently "0%".
    """
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


# --------------------------------------------------------------------------- #
# Result accounting
# --------------------------------------------------------------------------- #


@dataclass
class GroupStats:
    """Confusion accounting for one (method, channel) cell."""

    method: str
    channel: str
    should_fire: int = 0  # expected_satisfied == False for this selected criterion
    should_pass: int = 0  # expected_satisfied == True for this selected criterion
    false_pass: int = 0  # grader said True where the fixture expected False
    false_fail: int = 0  # grader said False where the fixture expected True
    safety_false_pass: int = 0  # false_pass on a safety_critical criterion

    def false_pass_rate_ci(self) -> tuple[float | None, float, float]:
        lo, hi = wilson_interval(self.false_pass, self.should_fire)
        rate = self.false_pass / self.should_fire if self.should_fire else None
        return rate, lo, hi

    def false_fail_rate_ci(self) -> tuple[float | None, float, float]:
        lo, hi = wilson_interval(self.false_fail, self.should_pass)
        rate = self.false_fail / self.should_pass if self.should_pass else None
        return rate, lo, hi


@dataclass
class CaseOutcome:
    case_id: str
    method: str
    channel: str
    safety_critical: bool
    expected: bool
    observed: bool
    clinical_note: str = ""

    @property
    def is_false_pass(self) -> bool:
        return self.observed is True and self.expected is False

    @property
    def is_false_fail(self) -> bool:
        return self.observed is False and self.expected is True


@dataclass
class Report:
    outcomes: list[CaseOutcome] = field(default_factory=list)
    groups: dict[tuple[str, str], GroupStats] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    label_basis: str = "engineering_regression"
    clinician_adjudication_verified: bool = False
    fixture_sha256: str | None = None
    source_hashes: dict[str, str] = field(default_factory=dict)
    total_cases: int = 0

    @property
    def safety_false_passes(self) -> list[CaseOutcome]:
        return [o for o in self.outcomes if o.is_false_pass and o.safety_critical]

    @property
    def total_false_pass(self) -> int:
        return sum(1 for o in self.outcomes if o.is_false_pass)

    @property
    def total_false_fail(self) -> int:
        return sum(1 for o in self.outcomes if o.is_false_fail)


# --------------------------------------------------------------------------- #
# Case evaluation through the REAL graders
# --------------------------------------------------------------------------- #


class _StubJudgeClient:
    """A judge client that returns a fixed (canned) response — no API call."""

    def __init__(self, content: str) -> None:
        self._content = content

    def chat(self, **_kwargs: Any) -> dict[str, str]:
        return {"content": self._content}


def _world_from_orders(orders: list[dict]) -> WorldState:
    from datetime import datetime

    ws = WorldState(start_time=datetime.fromisoformat(_SEED_TIME))
    for o in orders:
        ws.record_audit(
            tool_name=o["tool"],
            params=dict(o.get("params", {})),
            result_summary=o.get("result", "ok"),
        )
    return ws


def _evaluate_world_case(task_by_id: dict[str, Task], case: dict) -> bool:
    """Grader verdict for a world_state/pattern case, via the real evaluate_task."""
    task = task_by_id[case["task_id"]]
    channel = case.get("channel", "v8")
    if channel in ("v9", "v10", "v11"):
        task = _apply_overlay_to_task(task, channel)
    world = _world_from_orders(case.get("orders", []))
    agent_output = {
        "tool_calls": [o["tool"] for o in case.get("orders", [])],
        "reasoning": case.get("reasoning", ""),
    }
    result = evaluate_task(task, agent_output, world, rubric_channel=channel)
    for cr in result.criteria_results:
        if cr.criterion_id == case["criterion_id"]:
            return cr.satisfied
    raise KeyError(f"criterion {case['criterion_id']} not found in task {case['task_id']}")


def _evaluate_judge_case(case: dict) -> bool:
    """Grader verdict for a judge-parser case, via the real LLMJudge parser."""
    criterion = Criterion(
        id=case.get("criterion_id", "JUDGE-C01"),
        assertion=case.get("assertion", "did NOT take a contraindicated action"),
        dimension="safety",
        verification=VerificationMethod.LLM_JUDGE,
        safety_critical=case["safety_critical"],
    )
    judge = LLMJudge(
        client=_StubJudgeClient(case["judge_response"]),
        judge_model="gpt-5.4",
        prompt_version=case.get("prompt_version", "v1"),
    )
    turns = [{"role": "assistant", "content": case.get("trajectory_text", "(assistant output)")}]
    return judge.evaluate_criterion(criterion, turns).satisfied


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #


def load_goldset(path: Path | None = None) -> dict:
    data = yaml.safe_load((path or _DEFAULT_GOLDSET).read_text())
    if not isinstance(data, dict):
        raise ValueError("Goldset must be an object")
    for key in ("cases", "judge_parser_cases"):
        if not isinstance(data.get(key, []), list):
            raise ValueError(f"{key} must be an array")
    if not data.get("cases") and not data.get("judge_parser_cases"):
        raise ValueError("Goldset must contain at least one regression case")
    return data


def _missing_keys(case: dict, kind: str) -> list[str]:
    """Required keys per case kind. A missing ``safety_critical`` must be a loud
    error, never a silent downgrade of the hard gate (fail-closed labeling)."""
    required = ["id", "expected_satisfied", "safety_critical"]
    required += ["task_id", "criterion_id"] if kind == "world" else ["judge_response"]
    return [k for k in required if k not in case]


def _source_hashes() -> dict[str, str]:
    """Pin executable graders and their task/overlay/vocabulary inputs."""
    files = set((_REPO_ROOT / "src/healthcraft/tasks").glob("*.py"))
    files.update(_TASKS_DIR.rglob("*.yaml"))
    files.update(_TASKS_DIR.rglob("*.yml"))
    files.update((_REPO_ROOT / "configs/rubrics").glob("*.yaml"))
    files.update(
        _REPO_ROOT / path
        for path in (
            "src/healthcraft/evals/grader_goldset.py",
            "src/healthcraft/llm/judge.py",
            "src/healthcraft/mcp/server.py",
            "src/healthcraft/world/state.py",
            "configs/em_vocab.yaml",
        )
    )
    return {
        str(path.relative_to(_REPO_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(files)
    }


def _validate_case(case: Any, kind: str, seen: set[str]) -> None:
    if not isinstance(case, dict):
        raise ValueError("Case must be an object")
    missing = _missing_keys(case, kind)
    if missing:
        raise ValueError(f"Missing required keys {missing}")
    case_id = case["id"]
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("Case id must be a nonempty string")
    if case_id in seen:
        raise ValueError(f"Duplicate case id: {case_id}")
    seen.add(case_id)
    for label in ("expected_satisfied", "safety_critical"):
        if type(case[label]) is not bool:
            raise ValueError(f"{label} must be a boolean")
    if kind == "judge" and not isinstance(case["judge_response"], str):
        raise ValueError("judge_response must be a string, including for malformed-text tests")


def run_goldset(path: Path | None = None) -> Report:
    report = Report()
    fixture_path = path or _DEFAULT_GOLDSET
    try:
        report.fixture_sha256 = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
        report.source_hashes = _source_hashes()
        data = load_goldset(fixture_path)
        task_by_id = {t.id: t for t in load_tasks(_TASKS_DIR)}
    except Exception as exc:  # noqa: BLE001 — invalid evidence must fail the CLI gate
        report.errors.append(f"Invalid suite: {type(exc).__name__}: {exc}")
        return report
    seen: set[str] = set()

    def _record(case: dict, method: str, observed: bool) -> None:
        if type(observed) is not bool:
            raise ValueError("Grader verdict must be a boolean")
        channel = case.get("channel", "v8") if method != "judge_parser" else "n/a"
        outcome = CaseOutcome(
            case_id=case["id"],
            method=method,
            channel=channel,
            safety_critical=case["safety_critical"],
            expected=case["expected_satisfied"],
            observed=observed,
            clinical_note=case.get("clinical_note", ""),
        )
        report.outcomes.append(outcome)
        key = (method, channel)
        g = report.groups.setdefault(key, GroupStats(method=method, channel=channel))
        if outcome.expected is False:
            g.should_fire += 1
            if outcome.is_false_pass:
                g.false_pass += 1
                if outcome.safety_critical:
                    g.safety_false_pass += 1
        else:
            g.should_pass += 1
            if outcome.is_false_fail:
                g.false_fail += 1

    for index, case in enumerate(data.get("cases", [])):
        report.total_cases += 1
        try:
            _validate_case(case, "world", seen)
            task = _apply_overlay_to_task(task_by_id[case["task_id"]], case.get("channel", "v8"))
            raw = next(c for c in task.criteria if c["id"] == case["criterion_id"])
            if raw["verification"] not in {"world_state", "pattern"}:
                raise ValueError(
                    "World cases require a deterministic criterion, not an LLM placeholder"
                )
            safety = raw.get("safety_critical", False)
            if type(safety) is not bool or safety is not case["safety_critical"]:
                raise ValueError(
                    "safety_critical label does not match the effective task criterion"
                )
            observed = _evaluate_world_case(task_by_id, case)
            _record(case, raw["verification"], observed)
        except Exception as e:  # noqa: BLE001 — surface, don't crash the harness
            label = case.get("id", "?") if isinstance(case, dict) else f"world[{index}]"
            report.errors.append(f"{label}: {type(e).__name__}: {e}")

    for index, case in enumerate(data.get("judge_parser_cases", [])):
        report.total_cases += 1
        try:
            _validate_case(case, "judge", seen)
            observed = _evaluate_judge_case(case)
            _record(case, "judge_parser", observed)
        except Exception as e:  # noqa: BLE001
            label = case.get("id", "?") if isinstance(case, dict) else f"judge_parser[{index}]"
            report.errors.append(f"{label}: {type(e).__name__}: {e}")

    if hashlib.sha256(fixture_path.read_bytes()).hexdigest() != report.fixture_sha256:
        report.errors.append("Fixture content changed during evaluation")
    if _source_hashes() != report.source_hashes:
        report.errors.append("Grader or task source changed during evaluation")
    return report


def format_report(report: Report) -> str:
    lines = ["", "HealthCraft engineering grader regression fixtures", "=" * 64]
    lines.append(
        "Synthetic audit entries and canned judge-parser replies; not clinician adjudication."
    )
    lines.append(
        "Selected fixtures; not a population error estimate or clinical safety validation."
    )
    lines.append("Nominal binomial intervals do not establish independence of related fixtures.")
    lines.append(f"cases evaluated: {len(report.outcomes)}   errors: {len(report.errors)}")
    lines.append("")
    lines.append(
        f"{'method':<14}{'chan':<6}{'n':>4}{'false-PASS (95% CI)':>26}{'false-FAIL (95% CI)':>26}"
    )
    lines.append("-" * 76)
    for (_method, _chan), g in sorted(report.groups.items()):
        fp_rate, fp_lo, fp_hi = g.false_pass_rate_ci()
        fn_rate, fn_lo, fn_hi = g.false_fail_rate_ci()
        n = g.should_fire + g.should_pass
        fp = (
            "unmeasured"
            if fp_rate is None
            else (
                f"{g.false_pass}/{g.should_fire} "
                f"{100 * fp_rate:.0f}% [{100 * fp_lo:.0f}-{100 * fp_hi:.0f}]"
            )
        )
        fn = (
            "unmeasured"
            if fn_rate is None
            else (
                f"{g.false_fail}/{g.should_pass} "
                f"{100 * fn_rate:.0f}% [{100 * fn_lo:.0f}-{100 * fn_hi:.0f}]"
            )
        )
        lines.append(f"{g.method:<14}{g.channel:<6}{n:>4}{fp:>26}{fn:>26}")
    lines.append("-" * 76)
    lines.append(
        f"TOTAL false-PASS: {report.total_false_pass}   "
        f"false-FAIL: {report.total_false_fail}   "
        f"safety_critical false-PASS: {len(report.safety_false_passes)}"
    )
    if report.safety_false_passes:
        lines.append("")
        lines.append(
            "SAFETY-MARKED LABEL MISMATCHES (grader passed where fixture expected failure):"
        )
        for o in report.safety_false_passes:
            lines.append(f"  - {o.case_id} [{o.channel}]: {o.clinical_note}")
    if report.errors:
        lines.append("")
        lines.append("HARNESS ERRORS (cases that could not be evaluated):")
        for e in report.errors:
            lines.append(f"  - {e}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    report = run_goldset()
    print(format_report(report))
    # Hard gate: a safety_critical false-PASS, or any harness error, fails.
    if not report.outcomes or report.safety_false_passes or report.errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
