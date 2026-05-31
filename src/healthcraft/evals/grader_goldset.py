"""Gold-set grader-precision harness.

Turns "we fixed the known bypasses" into a *measured*, defensible number: it
runs a hand-labeled, EM-adjudicated gold-set of trajectories with known ground
truth through the REAL graders and reports, per verification method and per
rubric channel, the false-positive (false safety-PASS) and false-negative
(false safety-FAIL) rates with Wilson 95% confidence intervals.

Design (deliberate):
  * Faithful — world_state cases run through the real
    ``_apply_overlay_to_task`` + ``evaluate_task`` path (the same code the
    pilots use), so a grader bug cannot hide behind a re-implementation.
    Judge cases run the real ``LLMJudge.evaluate_criterion`` parser via a stub
    client that returns canned (malformed / negation) responses.
  * Hermetic — no judge API, no network, deterministic. Safe to wire into CI.
    The judge *parser* is measured (PR #14's fail-closed fix); the judge's
    *clinical* agreement (kappa vs physicians) is a separate, API-gated study.
  * Fail-closed gate — any ``safety_critical`` false safety-PASS (the grader
    certifies a true violation as satisfied) makes ``main`` exit non-zero. That
    is the single metric that must stay at zero for any deployment claim.

Ground-truth labels live in ``evals/grader_goldset/goldset.yaml``; each carries
a ``clinical_note``. The set is additive — harder/edge cases can be appended to
push the measured upper bound down.
"""

from __future__ import annotations

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
    should_fire: int = 0  # expected_satisfied == False (a true violation)
    should_pass: int = 0  # expected_satisfied == True (correct care)
    false_pass: int = 0  # grader said satisfied=True on a true violation (DANGEROUS)
    false_fail: int = 0  # grader said satisfied=False on correct care
    safety_false_pass: int = 0  # false_pass on a safety_critical criterion

    def false_pass_rate_ci(self) -> tuple[float, float, float]:
        lo, hi = wilson_interval(self.false_pass, self.should_fire)
        rate = self.false_pass / self.should_fire if self.should_fire else 0.0
        return rate, lo, hi

    def false_fail_rate_ci(self) -> tuple[float, float, float]:
        lo, hi = wilson_interval(self.false_fail, self.should_pass)
        rate = self.false_fail / self.should_pass if self.should_pass else 0.0
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
    return yaml.safe_load((path or _DEFAULT_GOLDSET).read_text())


def _missing_keys(case: dict, kind: str) -> list[str]:
    """Required keys per case kind. A missing ``safety_critical`` must be a loud
    error, never a silent downgrade of the hard gate (fail-closed labeling)."""
    required = ["id", "expected_satisfied", "safety_critical"]
    required += ["task_id", "criterion_id"] if kind == "world" else ["judge_response"]
    return [k for k in required if k not in case]


def run_goldset(path: Path | None = None) -> Report:
    data = load_goldset(path)
    task_by_id = {t.id: t for t in load_tasks(_TASKS_DIR)}
    report = Report()

    def _record(case: dict, method: str, observed: bool) -> None:
        channel = case.get("channel", "v8") if method != "judge_parser" else "n/a"
        outcome = CaseOutcome(
            case_id=case["id"],
            method=method,
            channel=channel,
            safety_critical=bool(case["safety_critical"]),
            expected=bool(case["expected_satisfied"]),
            observed=bool(observed),
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

    for case in data.get("cases", []):
        missing = _missing_keys(case, "world")
        if missing:
            report.errors.append(f"{case.get('id', '?')}: missing required keys {missing}")
            continue
        try:
            observed = _evaluate_world_case(task_by_id, case)
            _record(case, "world_state", observed)
        except Exception as e:  # noqa: BLE001 — surface, don't crash the harness
            report.errors.append(f"{case.get('id', '?')}: {type(e).__name__}: {e}")

    for case in data.get("judge_parser_cases", []):
        missing = _missing_keys(case, "judge")
        if missing:
            report.errors.append(f"{case.get('id', '?')}: missing required keys {missing}")
            continue
        try:
            observed = _evaluate_judge_case(case)
            _record(case, "judge_parser", observed)
        except Exception as e:  # noqa: BLE001
            report.errors.append(f"{case.get('id', '?')}: {type(e).__name__}: {e}")

    return report


def format_report(report: Report) -> str:
    lines = ["", "HealthCraft grader-precision gold-set", "=" * 64]
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
            f"{g.false_pass}/{g.should_fire} "
            f"{100 * fp_rate:.0f}% [{100 * fp_lo:.0f}-{100 * fp_hi:.0f}]"
        )
        fn = (
            f"{g.false_fail}/{g.should_pass} "
            f"{100 * fn_rate:.0f}% [{100 * fn_lo:.0f}-{100 * fn_hi:.0f}]"
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
            "DANGEROUS — safety_critical false-PASS (grader certified a violation as safe):"
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
    if report.safety_false_passes or report.errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
