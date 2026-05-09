"""Clinical coverage matrix loader for the ED Decision Rules Superpower.

Loads ``configs/agents_assemble/coverage_matrix.yaml`` into typed query
objects so:

1. The Reasoner can pull ``rules_for_complaint("chest pain")`` instead of
   regex-matching on free text.
2. A downstream A2A agent can fan-out N rules in parallel for any given
   chief complaint — every rule listed for a context is INDEPENDENT, so a
   parallel scorer can submit them concurrently and synthesize on return.
3. The model card / Devpost reviewer can audit *what's covered* and
   *what isn't* without reading 5,000 lines of YAML by hand.

Tests pin every rule named in the matrix to a real bundled rule, and pin
``gaps`` entries to genuinely-not-bundled candidates. The matrix can never
drift out of sync with the library.

Two surfaces:

- ``CoverageMatrix.load()`` — Python API.
- ``python -m healthcraft.agents_assemble.coverage --complaint "chest pain"``
  — CLI for the demo and for ad-hoc clinician inspection.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Default location relative to repo root. Test override via ``CoverageMatrix.load(path=...)``.
_DEFAULT_PATH = (
    Path(__file__).resolve().parents[3] / "configs" / "agents_assemble" / "coverage_matrix.yaml"
)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class ComplaintCoverage:
    """Routing entry for one chief complaint."""

    slug: str
    description: str
    primary: list[str] = field(default_factory=list)
    secondary: list[str] = field(default_factory=list)
    qualifiers: dict[str, list[str]] = field(default_factory=dict)

    def all_rules(self, *, qualifier: str | None = None) -> list[str]:
        """Flatten primary + secondary + (optional) one qualifier branch.

        Order is preserved: primary first, then secondary, then qualifier
        rules. Duplicates de-deduped while preserving first-seen order.
        """
        seen: set[str] = set()
        out: list[str] = []
        for r in (*self.primary, *self.secondary):
            if r not in seen:
                seen.add(r)
                out.append(r)
        if qualifier and qualifier in self.qualifiers:
            for r in self.qualifiers[qualifier]:
                if r not in seen:
                    seen.add(r)
                    out.append(r)
        return out


@dataclass
class CoverageMatrix:
    """In-memory view of the YAML matrix."""

    version: int
    library_size: int
    complaints: dict[str, ComplaintCoverage] = field(default_factory=dict)
    organ_systems: dict[str, list[str]] = field(default_factory=dict)
    age_bands: dict[str, list[str]] = field(default_factory=dict)
    age_bands_notes: dict[str, str] = field(default_factory=dict)
    gaps: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | str | None = None) -> CoverageMatrix:
        """Parse the YAML matrix from disk."""
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - hard dep at install time
            raise RuntimeError(
                "PyYAML is required to load the coverage matrix; install with `pip install pyyaml`"
            ) from exc

        resolved = Path(path) if path else _DEFAULT_PATH
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
        return cls._from_dict(raw)

    @classmethod
    def _from_dict(cls, raw: dict[str, Any]) -> CoverageMatrix:
        complaints: dict[str, ComplaintCoverage] = {}
        for slug, entry in (raw.get("chief_complaints") or {}).items():
            entry = entry or {}
            complaints[slug] = ComplaintCoverage(
                slug=slug,
                description=str(entry.get("description") or ""),
                primary=list(entry.get("primary") or []),
                secondary=list(entry.get("secondary") or []),
                qualifiers={
                    str(k): list(v or []) for k, v in (entry.get("qualifiers") or {}).items()
                },
            )

        organ_systems: dict[str, list[str]] = {}
        for slug, entry in (raw.get("organ_systems") or {}).items():
            entry = entry or {}
            organ_systems[slug] = list(entry.get("rules") or [])

        age_bands: dict[str, list[str]] = {}
        age_bands_notes: dict[str, str] = {}
        for slug, entry in (raw.get("age_bands") or {}).items():
            entry = entry or {}
            rules = entry.get("rules")
            if isinstance(rules, list):
                age_bands[slug] = list(rules)
            elif rules == "ALL_REMAINING":
                age_bands[slug] = ["ALL_REMAINING"]
            else:
                age_bands[slug] = []
            if entry.get("notes"):
                age_bands_notes[slug] = str(entry["notes"]).strip()

        return cls(
            version=int(raw.get("version") or 0),
            library_size=int(raw.get("library_size") or 0),
            complaints=complaints,
            organ_systems=organ_systems,
            age_bands=age_bands,
            age_bands_notes=age_bands_notes,
            gaps=list(raw.get("gaps") or []),
        )

    # ------------------------------------------------------------------
    # Query API — used by Reasoner, demo CLI, and tests.
    # ------------------------------------------------------------------

    def all_named_rules(self) -> set[str]:
        """Every rule name referenced anywhere in the matrix (sans ALL_REMAINING)."""
        out: set[str] = set()
        for c in self.complaints.values():
            out.update(c.primary)
            out.update(c.secondary)
            for qrules in c.qualifiers.values():
                out.update(qrules)
        for rules in self.organ_systems.values():
            out.update(rules)
        for rules in self.age_bands.values():
            out.update(r for r in rules if r != "ALL_REMAINING")
        return out

    def rules_for_complaint(self, complaint: str, *, qualifier: str | None = None) -> list[str]:
        """Rules ranked for ``complaint`` (slug or free-text).

        Free text is normalized via ``_complaint_slug``. If no exact slug
        match, falls back to keyword match on description / slug.
        """
        slug = _complaint_slug(complaint)
        coverage = self.complaints.get(slug)
        if coverage is None:
            coverage = self._fuzzy_complaint(complaint)
        if coverage is None:
            return []
        return coverage.all_rules(qualifier=qualifier)

    def rules_for_organ(self, system: str) -> list[str]:
        return list(self.organ_systems.get(_complaint_slug(system), []))

    def rules_for_age_band(self, band: str) -> list[str]:
        return list(self.age_bands.get(_complaint_slug(band), []))

    def gap_for_context(self, context: str) -> dict[str, Any] | None:
        """Look up a gap entry by its ``context`` key (e.g. 'chief_complaint.back_pain')."""
        for entry in self.gaps:
            if entry.get("context") == context:
                return dict(entry)
        return None

    def _fuzzy_complaint(self, query: str) -> ComplaintCoverage | None:
        """Best-effort match of a free-text complaint to a slug.

        Scores by token overlap between query and (slug | description). Used
        as a last-resort lookup so callers can pass real chief complaints
        without knowing the slug vocabulary.
        """
        q_tokens = set(_tokenize(query))
        if not q_tokens:
            return None
        best: tuple[int, ComplaintCoverage | None] = (0, None)
        for c in self.complaints.values():
            haystack = set(_tokenize(c.slug)) | set(_tokenize(c.description))
            score = len(q_tokens & haystack)
            if score > best[0]:
                best = (score, c)
        return best[1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _complaint_slug(text: str) -> str:
    """Lower / replace non-word with underscores, collapse repeats."""
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return re.sub(r"_+", "_", s)


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--complaint",
        help=(
            "Chief complaint slug or free text "
            "(e.g. 'chest pain', 'pediatric_respiratory_distress')"
        ),
    )
    parser.add_argument(
        "--qualifier",
        help="Optional qualifier branch (e.g. 'pleuritic_or_dyspnea', 'lbbb_on_ecg')",
    )
    parser.add_argument("--organ", help="Organ-system slug (e.g. 'cardiovascular', 'pulmonary')")
    parser.add_argument("--age-band", help="Age band slug (pediatric / adult_default / elderly)")
    parser.add_argument("--gaps", action="store_true", help="List uncovered contexts (gap report)")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args(argv)

    matrix = CoverageMatrix.load()

    output: dict[str, Any] = {
        "library_size": matrix.library_size,
        "matrix_version": matrix.version,
    }
    if args.complaint:
        output["complaint"] = args.complaint
        output["rules"] = matrix.rules_for_complaint(args.complaint, qualifier=args.qualifier)
    if args.organ:
        output["organ_system"] = args.organ
        output["rules_for_organ"] = matrix.rules_for_organ(args.organ)
    if args.age_band:
        output["age_band"] = args.age_band
        output["rules_for_age_band"] = matrix.rules_for_age_band(args.age_band)
    if args.gaps:
        output["gaps"] = matrix.gaps
    if not (args.complaint or args.organ or args.age_band or args.gaps):
        output["complaints"] = sorted(matrix.complaints)
        output["organ_systems"] = sorted(matrix.organ_systems)
        output["age_bands"] = sorted(matrix.age_bands)

    if args.json:
        json.dump(output, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return 0

    for k, v in output.items():
        if isinstance(v, list):
            print(f"{k}:")
            for item in v:
                print(f"  - {item if not isinstance(item, dict) else json.dumps(item)}")
        else:
            print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
