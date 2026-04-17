"""Build T2 physician adjudication batch with gold-trajectory slots.

For each of the 27 Tier-2 (research-only) overlay criteria, emits a markdown
review file bundling the criterion, scenario, per-trial v8/v9 verdicts, and
physician signoff slots including a gold-trajectory designation.

Input:  scripts-output/kappa_report.json + configs/tasks/*/task_*.yaml
Output: scripts-output/adjudication/<CRITERION_ID>.md  (27 files)
        scripts-output/adjudication/manifest.csv
        scripts-output/adjudication/README.md
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
KAPPA_REPORT = ROOT / "scripts-output" / "kappa_report.json"
TASK_DIRS = ROOT / "configs" / "tasks"
OUT_DIR = ROOT / "scripts-output" / "adjudication"

SEED_FROM_TRAJ = re.compile(r"_(\d+)_t(\d+)\.json$")


def build_task_index() -> dict[str, Path]:
    idx: dict[str, Path] = {}
    for path in TASK_DIRS.rglob("task_*.yaml"):
        try:
            doc = yaml.safe_load(path.read_text())
        except Exception:
            continue
        tid = doc.get("id") if isinstance(doc, dict) else None
        if tid:
            idx[tid] = path
    return idx


def load_task(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text()) or {}


def trial_key(traj_path: str) -> tuple[str, str]:
    m = SEED_FROM_TRAJ.search(traj_path)
    if not m:
        return ("?", "?")
    return (m.group(1), m.group(2))


def render_scenario(task_doc: dict[str, Any]) -> str:
    desc = (task_doc.get("description") or "").strip()
    setting = task_doc.get("setting") or {}
    patient = task_doc.get("patient") or {}
    parts: list[str] = []
    if desc:
        parts.append(desc)
    if isinstance(setting, dict) and setting:
        facility = setting.get("facility") or setting.get("department") or ""
        time = setting.get("time") or ""
        if facility or time:
            parts.append(f"_Setting:_ {facility}  {time}".strip())
    if isinstance(patient, dict) and patient:
        cc = patient.get("chief_complaint") or ""
        age = patient.get("age") or ""
        sex = patient.get("sex") or ""
        if cc:
            parts.append(f"_Patient:_ {age}{sex} — {cc}".strip())
    return "\n\n".join(parts) if parts else "(no scenario text in task YAML)"


def render_criterion_markdown(
    criterion_id: str,
    cd: dict[str, Any],
    disagree_rows: list[dict[str, Any]],
    task_doc: dict[str, Any] | None,
) -> str:
    task_id = cd["task_id"]
    category = cd["category"]
    safety = "YES" if cd["safety_critical"] else "no"
    assertion = cd["assertion"]
    labels = sorted({r["label"] for r in disagree_rows}) or ["(agree only)"]
    n_obs = cd["n_obs"]
    n_disagree = cd["n_disagree"]

    scenario = render_scenario(task_doc) if task_doc else "(task YAML not found)"

    lines: list[str] = []
    lines.append(f"# {criterion_id} — {task_id}")
    lines.append("")
    lines.append(f"- **Category:** {category}")
    lines.append(f"- **Safety-critical:** {safety}")
    lines.append(f"- **Disagreement labels:** {', '.join(labels)}")
    lines.append(f"- **Trials disagreeing:** {n_disagree}/{n_obs}")
    if task_doc:
        title = task_doc.get("title") or ""
        if title:
            lines.append(f"- **Task title:** {title}")
    lines.append("")
    lines.append("## Assertion under review")
    lines.append("")
    lines.append(f"> {assertion}")
    lines.append("")
    lines.append("## Scenario")
    lines.append("")
    lines.append(scenario)
    lines.append("")
    lines.append("## Disagreeing trials")
    lines.append("")
    lines.append(
        "| # | Model | Seed/Trial | v8 | v9 | Label | Tool calls (ok / failed) | Classifier reason |"
    )
    lines.append(
        "|---|-------|-----------|----|----|-------|-------------------------|------------------|"
    )
    for idx, row in enumerate(
        sorted(disagree_rows, key=lambda r: (r["model"], r["trajectory"])), start=1
    ):
        seed, trial = trial_key(row["trajectory"])
        ok_calls = max(0, row["relevant_tool_calls_found"] - row["relevant_failed_calls_found"])
        lines.append(
            f"| {idx} | {row['model']} | {seed}/t{trial} | "
            f"{'PASS' if row['v8'] else 'FAIL'} | "
            f"{'PASS' if row['v9'] else 'FAIL'} | "
            f"{row['label']} | {ok_calls} / {row['relevant_failed_calls_found']} | "
            f"{row['reason_short']} |"
        )
    lines.append("")
    lines.append("### Trajectory paths (for review)")
    lines.append("")
    for row in sorted(disagree_rows, key=lambda r: (r["model"], r["trajectory"])):
        lines.append(f"- `{row['trajectory']}`")
    n_agree = n_obs - n_disagree
    if n_agree > 0:
        lines.append("")
        lines.append(
            f"_{n_agree} additional trial(s) agreed between v8 and v9 and are not listed; "
            "inspect in the matching results/pilot-v8-* directory if needed for gold selection._"
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Physician adjudication")
    lines.append("")
    lines.append("**Adjudicated verdict for this criterion** (independent of v8/v9):")
    lines.append("")
    lines.append("- [ ] PASS — at least one of the 6 trials meets the assertion as written")
    lines.append("- [ ] FAIL — none of the 6 trials meet the assertion")
    lines.append(
        "- [ ] CRITERION_NEEDS_REWRITE — assertion itself is ambiguous or clinically wrong"
    )
    lines.append("")
    lines.append(
        "**Gold trajectory** (reference solution per the eval-guide pattern: a known working"
    )
    lines.append("output that passes all graders). Paste one trajectory path, or `none`:")
    lines.append("")
    lines.append("```")
    lines.append("gold_trajectory: ")
    lines.append("```")
    lines.append("")
    lines.append(
        "**Rationale** (2–3 sentences — what the agent did right/wrong, what the judge missed):"
    )
    lines.append("")
    lines.append("```")
    lines.append("")
    lines.append("```")
    lines.append("")
    lines.append("**Reviewer / date:**")
    lines.append("")
    lines.append("```")
    lines.append("reviewer: ")
    lines.append("date: ")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = json.loads(KAPPA_REPORT.read_text())
    tier = report["tier_assignment"]
    cd_by_id = {c["criterion_id"]: c for c in report["criterion_disagreements"]}
    rows_by_crit: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in report["disagreement_rows"]:
        rows_by_crit[row["criterion_id"]].append(row)

    task_idx = build_task_index()
    t2 = sorted(cid for cid, t in tier.items() if t == "tier_2_research_only")

    manifest_rows: list[dict[str, Any]] = []
    for cid in t2:
        cd = cd_by_id.get(cid)
        if not cd:
            print(f"[warn] {cid} has no criterion_disagreements entry")
            continue
        rows = rows_by_crit.get(cid, [])
        task_path = task_idx.get(cd["task_id"])
        task_doc = load_task(task_path) if task_path else None
        md = render_criterion_markdown(cid, cd, rows, task_doc)
        (OUT_DIR / f"{cid}.md").write_text(md)
        labels = sorted({r["label"] for r in rows}) or ["(none)"]
        manifest_rows.append(
            {
                "criterion_id": cid,
                "task_id": cd["task_id"],
                "category": cd["category"],
                "safety_critical": cd["safety_critical"],
                "labels": ";".join(labels),
                "n_disagree": cd["n_disagree"],
                "n_obs": cd["n_obs"],
                "file": f"{cid}.md",
            }
        )

    manifest_path = OUT_DIR / "manifest.csv"
    with manifest_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(manifest_rows[0].keys()))
        writer.writeheader()
        writer.writerows(manifest_rows)

    by_cat: dict[str, list[str]] = defaultdict(list)
    for r in manifest_rows:
        by_cat[r["category"]].append(r["criterion_id"])

    readme_lines: list[str] = []
    readme_lines.append("# T2 physician adjudication batch")
    readme_lines.append("")
    readme_lines.append(
        f"{len(manifest_rows)} overlay criteria flagged Tier-2 research-only after the 2026-04-17 kappa validation."
    )
    readme_lines.append("")
    readme_lines.append(
        "For each criterion, adjudicate the assertion against the 6 trial trajectories and:"
    )
    readme_lines.append("1. Choose PASS / FAIL / NEEDS_REWRITE.")
    readme_lines.append(
        "2. Designate a **gold trajectory** (path) if one trial represents the reference solution."
    )
    readme_lines.append("3. Leave a short rationale.")
    readme_lines.append("")
    readme_lines.append(
        "The gold trajectory becomes the reusable calibration asset — any future grader must mark that trajectory PASS."
    )
    readme_lines.append("")
    readme_lines.append("## By category")
    readme_lines.append("")
    for cat in sorted(by_cat):
        readme_lines.append(f"### {cat} ({len(by_cat[cat])})")
        readme_lines.append("")
        for cid in sorted(by_cat[cat]):
            readme_lines.append(f"- [{cid}]({cid}.md)")
        readme_lines.append("")
    (OUT_DIR / "README.md").write_text("\n".join(readme_lines))

    print(f"Wrote {len(manifest_rows)} criterion files to {OUT_DIR}")
    print(f"Manifest: {manifest_path}")
    print(f"README:   {OUT_DIR / 'README.md'}")


if __name__ == "__main__":
    main()
