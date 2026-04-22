"""Agreement analysis for the PoC-validator shadow log.

Reads the append-only JSONL produced by shadow mode (default path:
``results/poc_validator_log.jsonl``) and emits per-criterion agreement
metrics:

    agreement_rate   = fraction of entries where judge and validator concur
    PPA              = P(validator_verdict=verified | judge_satisfied=True)
    NPA              = P(validator_verdict=contradicted | judge_satisfied=False)
    insufficient_ev  = fraction of entries where validator returned
                       INSUFFICIENT_EVIDENCE (validator abstained)

Usage:
    python scripts/analyze_shadow_log.py [--log PATH] [--min-n N]

Exit codes:
    0  log parsed successfully, report printed.
    2  log not found or empty.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--log",
        default="results/poc_validator_log.jsonl",
        help="Path to the shadow-mode JSONL log (default: %(default)s)",
    )
    p.add_argument(
        "--min-n",
        type=int,
        default=1,
        help=(
            "Minimum entries per criterion to include in the per-criterion "
            "report. Below this, the criterion aggregates into 'other' "
            "(default: %(default)s)"
        ),
    )
    return p.parse_args(argv)


def _load(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    records: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def _concur(judge_satisfied: bool, verdict: str) -> bool | None:
    """True if judge and validator agree; None if validator abstained."""
    if verdict == "verified":
        return judge_satisfied is True
    if verdict == "contradicted":
        return judge_satisfied is False
    return None  # insufficient_evidence -- no concurrence opinion


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return float("nan")
    return numerator / denominator


def _report(records: list[dict], min_n: int) -> str:
    """Build a plain-text agreement report."""
    if not records:
        return "no records in shadow log\n"

    by_crit: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_crit[r["criterion_id"]].append(r)

    lines: list[str] = []
    lines.append(f"total entries: {len(records)}")
    lines.append(f"criteria represented: {len(by_crit)}")
    lines.append("")
    lines.append("per-criterion agreement (judge vs validator):")
    lines.append(f"{'criterion':<18} {'n':>4} {'agree':>6} {'PPA':>6} {'NPA':>6} {'insuf':>6}")
    lines.append("-" * 54)

    for cid in sorted(by_crit):
        rows = by_crit[cid]
        if len(rows) < min_n:
            continue
        n = len(rows)
        n_insuf = sum(1 for r in rows if r["validator_verdict"] == "insufficient_evidence")
        # Agreement numerator/denominator ignore insufficient_evidence.
        decided = [r for r in rows if r["validator_verdict"] != "insufficient_evidence"]
        n_agree = sum(
            1 for r in decided if _concur(r["judge_satisfied"], r["validator_verdict"]) is True
        )
        # PPA: judge True -> validator verified
        judge_pos = [r for r in decided if r["judge_satisfied"] is True]
        ppa_num = sum(1 for r in judge_pos if r["validator_verdict"] == "verified")
        # NPA: judge False -> validator contradicted
        judge_neg = [r for r in decided if r["judge_satisfied"] is False]
        npa_num = sum(1 for r in judge_neg if r["validator_verdict"] == "contradicted")

        lines.append(
            f"{cid:<18} {n:>4} "
            f"{_rate(n_agree, len(decided)):>6.2f} "
            f"{_rate(ppa_num, len(judge_pos)):>6.2f} "
            f"{_rate(npa_num, len(judge_neg)):>6.2f} "
            f"{_rate(n_insuf, n):>6.2f}"
        )

    lines.append("")
    lines.append(
        "agreement = (#judge-verdict agrees with validator) / (n - #insufficient_evidence)"
    )
    lines.append("PPA = P(validator=verified | judge=True)")
    lines.append("NPA = P(validator=contradicted | judge=False)")
    lines.append("insuf = #INSUFFICIENT_EVIDENCE / n")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    records = _load(Path(args.log))
    if not records:
        print(f"shadow log empty or missing: {args.log}", file=sys.stderr)
        return 2
    sys.stdout.write(_report(records, args.min_n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
