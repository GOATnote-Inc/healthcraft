#!/usr/bin/env python3
"""Regenerate ``docs/LEADERBOARD.md`` from ``docs/MODEL_CARDS/*.md``.

Reads the YAML frontmatter from every model card, extracts the headline
metrics for Full / Consensus / Hard, and writes a single static Markdown
leaderboard. Idempotent: running this twice produces byte-identical output.

This script NEVER mutates the model cards -- the cards are the source of
truth, the leaderboard is a materialized view.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CARDS_DIR = _PROJECT_ROOT / "docs" / "MODEL_CARDS"
_DEFAULT_OUTPUT = _PROJECT_ROOT / "docs" / "LEADERBOARD.md"


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ModelCard:
    """Parsed headline metrics from a model card's YAML frontmatter."""

    model_id: str
    pilot_id: str
    evaluation_date: str
    full: dict[str, Any]
    consensus: dict[str, Any]
    hard: dict[str, Any]
    coverage: str  # "full" | "partial"


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse the leading ``---\\n...\\n---`` block; raise on missing."""
    if not text.startswith("---"):
        raise ValueError("Card is missing YAML frontmatter delimiter")
    # Split into: '', frontmatter, body
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("Malformed frontmatter -- could not find closing '---'")
    raw = parts[1]
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError("Frontmatter did not parse to a mapping")
    return data


def _load_card(path: Path) -> _ModelCard:
    """Load one model card's frontmatter into a :class:`_ModelCard`."""
    text = path.read_text(encoding="utf-8")
    data = _parse_frontmatter(text)

    coverage = "full"
    if str(data.get("coverage", "")).lower() == "partial":
        coverage = "partial"

    return _ModelCard(
        model_id=str(data.get("model_id", path.stem)),
        pilot_id=str(data.get("pilot_id", "")),
        evaluation_date=str(data.get("evaluation_date", "")),
        full=dict(data.get("full", {}) or {}),
        consensus=dict(data.get("consensus", {}) or {}),
        hard=dict(data.get("hard", {}) or {}),
        coverage=coverage,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_pass_at_1(block: dict[str, Any]) -> str:
    """Render Pass@1 either as a percent or as ``pending``."""
    if block.get("status") == "pending":
        return "pending"
    if block.get("status") == "partial":
        return "partial (v1.1)"
    value = block.get("pass_at_1")
    if isinstance(value, (int, float)):
        return f"{value * 100:.1f}%"
    return "pending"


def _fmt_mean_reward(block: dict[str, Any]) -> str:
    if block.get("status") in ("pending", "partial"):
        return "pending"
    value = block.get("mean_reward")
    if isinstance(value, (int, float)):
        return f"{value:.3f}"
    return "pending"


def _fmt_safety_rate(block: dict[str, Any]) -> str:
    if block.get("status") in ("pending", "partial"):
        return "pending"
    value = block.get("safety_gate_pass_rate")
    if isinstance(value, (int, float)):
        return f"{value * 100:.1f}%"
    return "pending"


def _build_row(card: _ModelCard) -> str:
    notes = []
    if card.pilot_id:
        notes.append(f"pilot {card.pilot_id}")
    if card.coverage == "partial":
        notes.append("partial coverage -- see card")
    notes_str = "; ".join(notes) if notes else "-"
    return (
        f"| `{card.model_id}` "
        f"| {_fmt_pass_at_1(card.full)} "
        f"| {_fmt_pass_at_1(card.consensus)} "
        f"| {_fmt_pass_at_1(card.hard)} "
        f"| {_fmt_mean_reward(card.full)} "
        f"| {_fmt_safety_rate(card.full)} "
        f"| {notes_str} |"
    )


def _sort_key(card: _ModelCard) -> tuple[int, float, str]:
    """Sort: full-coverage first, then by Pass@1 descending, then model_id."""
    coverage_bucket = 0 if card.coverage != "partial" else 1
    value = card.full.get("pass_at_1")
    pa1 = -float(value) if isinstance(value, (int, float)) else 0.0
    return (coverage_bucket, pa1, card.model_id)


def _render(cards: list[_ModelCard]) -> str:
    cards_sorted = sorted(cards, key=_sort_key)
    lines = [
        "# HealthCraft Leaderboard",
        "",
        "Auto-generated from `docs/MODEL_CARDS/*.md`. Do not edit directly --",
        "run `scripts/regen_leaderboard.py` after updating any card.",
        "",
        (
            "All Pass@1 metrics are the fraction of tasks passed on a single "
            "trial. Pass@3 / Pass^3 and CI are listed in the individual model "
            "cards. Rows marked **pending** require Phase 2 / Phase 3 execution"
            " (Consensus / Hard subsets) or completion of the V9 Gemini pilot."
        ),
        "",
        "| Model | Full Pass@1 | Consensus Pass@1 | Hard Pass@1 | "
        "Mean Reward (Full) | Safety Gate Pass Rate (Full) | Notes |",
        "|-------|-------------|------------------|-------------|"
        "--------------------|------------------------------|-------|",
    ]
    for card in cards_sorted:
        lines.append(_build_row(card))
    lines.extend(
        [
            "",
            "## Model cards",
            "",
        ]
    )
    for card in cards_sorted:
        lines.append(
            f"- [`{card.model_id}`](MODEL_CARDS/{card.model_id.replace('.', '_').replace('-', '_')}.md)"
            f" -- evaluated {card.evaluation_date}"
        )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--cards-dir",
        type=Path,
        default=_DEFAULT_CARDS_DIR,
        help=f"Model-card directory (default {_DEFAULT_CARDS_DIR}).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help=f"Leaderboard output path (default {_DEFAULT_OUTPUT}).",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if the current output file differs from the regenerated output.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not args.cards_dir.exists():
        print(f"ERROR: cards dir not found: {args.cards_dir}", file=sys.stderr)
        return 1

    card_paths = sorted(args.cards_dir.glob("*.md"))
    cards: list[_ModelCard] = []
    for path in card_paths:
        try:
            cards.append(_load_card(path))
        except (ValueError, yaml.YAMLError) as e:
            print(f"[warn] skipping {path}: {e}", file=sys.stderr)

    if not cards:
        print(f"ERROR: no parseable model cards under {args.cards_dir}", file=sys.stderr)
        return 1

    rendered = _render(cards)

    if args.check:
        if not args.output.exists():
            print("ERROR: --check: output file does not exist", file=sys.stderr)
            return 1
        current = args.output.read_text(encoding="utf-8")
        if current != rendered:
            print("ERROR: --check: output is stale", file=sys.stderr)
            return 1
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"[ok] wrote {args.output} ({len(cards)} model card(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
