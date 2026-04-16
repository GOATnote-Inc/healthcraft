"""Generate whitepaper figures 3, 4, 5 from pilot summary + experiments.jsonl.

Figure 3: per-category Pass@1 bar chart with Wilson 95% CIs (V8 two-model).
Figure 4: pilot progression v2-v8 (Pass@1 and avg reward, two lines per model).
Figure 5: safety-gate dominance scatter (per-task avg reward vs criterion-satisfaction rate).

Read-only over results/. Writes to docs/whitepaper/figures/.
Deterministic. No network. Matplotlib only.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt

matplotlib.use("Agg")

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "results"
FIGURES = REPO / "docs" / "whitepaper" / "figures"

# Matches V8_ANALYSIS.md ordering so paper narrative stays consistent.
CATEGORIES = [
    "clinical_communication",
    "clinical_reasoning",
    "information_retrieval",
    "multi_step_workflows",
    "safety_critical_judgment",
    "temporal_reasoning",
]

# Pretty labels for the two V8 models used in the main table.
V8_MODELS = [
    ("pilot-v8-claude-opus", "Claude Opus 4.6"),
    ("pilot-v8-gpt54", "GPT-5.4"),
]

# Pilot series for figure 4. v2 absent (pre-v3 experiments structure differs);
# reports from v3 onward per docs/EVALUATION_INTEGRITY.md.
PILOT_SERIES = ["v3", "v4", "v5", "v6", "v7", "v8"]


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% CI. Matches src/metrics/confidence_intervals.py."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    halfwidth = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return (max(0.0, center - halfwidth), min(1.0, center + halfwidth))


def load_entries(pilot_dir: Path) -> list[dict]:
    """Load experiments.jsonl; attach derived category from trajectory_path."""
    jsonl = pilot_dir / "experiments.jsonl"
    if not jsonl.exists():
        return []
    entries = []
    for line in jsonl.read_text().splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if "category" not in entry and entry.get("trajectory_path"):
            parts = entry["trajectory_path"].split("/")
            if len(parts) >= 2:
                entry["category"] = parts[1]
        entries.append(entry)
    return entries


def per_category_pass_rate(entries: list[dict]) -> dict[str, tuple[int, int]]:
    """Return {category: (passes, trials)} aggregated across all trials."""
    agg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for entry in entries:
        cat = entry.get("category", "unknown")
        agg[cat][1] += 1
        if entry.get("passed", False):
            agg[cat][0] += 1
    return {cat: (passes, trials) for cat, (passes, trials) in agg.items()}


def overall_pass_rate(pilot_dir: Path) -> float:
    """Read pass_rate from summary.json if present, else compute from entries."""
    summary = pilot_dir / "summary.json"
    if summary.exists():
        return float(json.loads(summary.read_text())["pass_rate"])
    entries = load_entries(pilot_dir)
    if not entries:
        return float("nan")
    passes = sum(1 for e in entries if e.get("passed", False))
    return passes / len(entries)


def overall_avg_reward(pilot_dir: Path) -> float:
    summary = pilot_dir / "summary.json"
    if summary.exists():
        return float(json.loads(summary.read_text())["avg_reward"])
    entries = load_entries(pilot_dir)
    if not entries:
        return float("nan")
    return sum(e.get("reward", 0.0) for e in entries) / len(entries)


def figure_3_per_category() -> Path:
    """Grouped bar: Pass@1 per category per V8 model with Wilson error bars."""
    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    n_cats = len(CATEGORIES)
    x = list(range(n_cats))
    width = 0.38

    for idx, (pilot_name, label) in enumerate(V8_MODELS):
        entries = load_entries(RESULTS / pilot_name)
        agg = per_category_pass_rate(entries)
        means, lows, highs = [], [], []
        for cat in CATEGORIES:
            passes, trials = agg.get(cat, (0, 0))
            rate = passes / trials if trials else 0.0
            lo, hi = wilson_ci(passes, trials)
            means.append(rate * 100)
            lows.append((rate - lo) * 100)
            highs.append((hi - rate) * 100)
        offsets = [xi + (idx - 0.5) * width for xi in x]
        ax.bar(
            offsets,
            means,
            width=width,
            label=label,
            yerr=[lows, highs],
            capsize=3,
            edgecolor="black",
            linewidth=0.5,
        )

    ax.set_xticks(x)
    ax.set_xticklabels(
        [c.replace("_", " ") for c in CATEGORIES],
        rotation=20,
        ha="right",
        fontsize=9,
    )
    ax.set_ylabel("Pass@1 (\\%)")
    ax.set_ylim(0, 60)
    ax.set_title("V8 Pass@1 by Task Category (Wilson 95\\% CIs)")
    ax.legend(loc="upper right", frameon=False)
    ax.grid(axis="y", linestyle=":", linewidth=0.5, alpha=0.6)
    fig.tight_layout()

    out = FIGURES / "fig3_per_category_results.pdf"
    fig.savefig(out)
    plt.close(fig)
    return out


def figure_4_pilot_progression() -> Path:
    """Two subplots: Pass@1 and avg reward across pilots v3..v8 for each model."""
    fig, (ax_pass, ax_reward) = plt.subplots(1, 2, figsize=(10, 3.8))

    for suffix, label, marker in [
        ("claude-opus", "Claude Opus 4.6", "o"),
        ("gpt54", "GPT-5.4", "s"),
    ]:
        passes, rewards, labels = [], [], []
        for v in PILOT_SERIES:
            pilot = RESULTS / f"pilot-{v}-{suffix}"
            if not pilot.exists():
                passes.append(float("nan"))
                rewards.append(float("nan"))
            else:
                passes.append(overall_pass_rate(pilot) * 100)
                rewards.append(overall_avg_reward(pilot))
            labels.append(v.upper())
        ax_pass.plot(labels, passes, marker=marker, label=label)
        ax_reward.plot(labels, rewards, marker=marker, label=label)

    ax_pass.set_title("Pass@1 across pilots")
    ax_pass.set_ylabel("Pass@1 (\\%)")
    ax_pass.set_xlabel("Pilot")
    ax_pass.grid(linestyle=":", linewidth=0.5, alpha=0.6)
    ax_pass.legend(frameon=False)

    ax_reward.set_title("Average reward across pilots")
    ax_reward.set_ylabel("Avg reward")
    ax_reward.set_xlabel("Pilot")
    ax_reward.grid(linestyle=":", linewidth=0.5, alpha=0.6)
    ax_reward.legend(frameon=False)

    fig.tight_layout()
    out = FIGURES / "fig4_pilot_progression.pdf"
    fig.savefig(out)
    plt.close(fig)
    return out


def figure_5_safety_gate_scatter() -> Path:
    """Per-task scatter: avg reward vs criterion satisfaction rate.

    The safety gate produces a visible band along reward=0 for tasks with
    high satisfaction but one unsatisfied safety-critical criterion. This is
    the paper's illustration of safety-gate dominance.
    """
    fig, ax = plt.subplots(figsize=(6.5, 4.2))

    for suffix, label, marker in [
        ("claude-opus", "Claude Opus 4.6", "o"),
        ("gpt54", "GPT-5.4", "^"),
    ]:
        pilot = RESULTS / f"pilot-v8-{suffix}"
        entries = load_entries(pilot)
        by_task: dict[str, list[dict]] = defaultdict(list)
        for e in entries:
            by_task[e["task_id"]].append(e)
        xs, ys = [], []
        for tid, runs in by_task.items():
            rewards = [r.get("reward", 0.0) for r in runs]
            safety_ok = [r.get("safety_gate_passed", True) for r in runs]
            # Use min safety-gate-passed fraction as proxy for unsatisfied
            # safety-critical criteria. For a gate-agnostic "raw criterion
            # satisfaction", use avg reward across runs where safety gate did
            # not trigger zero.
            safety_rate = sum(safety_ok) / len(safety_ok) if safety_ok else 0.0
            avg_r = sum(rewards) / len(rewards) if rewards else 0.0
            xs.append(safety_rate)
            ys.append(avg_r)
        ax.scatter(xs, ys, label=label, marker=marker, alpha=0.55, s=18)

    ax.set_xlabel("Safety-gate pass fraction (per task)")
    ax.set_ylabel("Average reward (per task)")
    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-0.05, 1.05)
    ax.set_title("Safety-gate dominance: reward collapses when gate fails")
    ax.grid(linestyle=":", linewidth=0.5, alpha=0.6)
    ax.legend(frameon=False, loc="lower right")
    fig.tight_layout()
    out = FIGURES / "fig5_safety_gate_dominance.pdf"
    fig.savefig(out)
    plt.close(fig)
    return out


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    paths = [figure_3_per_category(), figure_4_pilot_progression(), figure_5_safety_gate_scatter()]
    for p in paths:
        print(f"wrote {p.relative_to(REPO)}")


if __name__ == "__main__":
    main()
