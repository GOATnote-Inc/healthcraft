"""The README Entity Types table must describe the world the seeder builds.

Audit finding P1-1: the table previously copied roadmap targets from the
seed YAML's ``entity_generation`` block ("Encounters 1,200+", "Protocols
100+", ...) that ``WorldSeeder`` does not honour. These tests pin the
README to ``WorldSeeder(seed=42).entity_counts`` so the two cannot drift
apart silently again.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from healthcraft.world.seed import WorldSeeder

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"
SEED_CONFIG = REPO_ROOT / "configs" / "world" / "mercy_point_v1.yaml"

# README display name -> WorldState entity-type key.
ROW_TO_ENTITY_TYPE = {
    "Patients": "patient",
    "Encounters": "encounter",
    "Clinical Knowledge": "clinical_knowledge",
    "Treatment Plans": "treatment_plan",
    "Clinical Tasks": "clinical_task",
    "Clinical Decision Rules": "decision_rule",
    "Protocols & Guidelines": "protocol",
    "Insurance & Coverage": "insurance",
    "Reference Materials": "reference_material",
    "Resource Availability": "resource",
    "Supplies & Medications": "supply",
    "Regulatory & Legal": "regulatory",
    "Locations": "location",
    "Staff": "staff",
}


@pytest.fixture(scope="module")
def seeded_counts() -> dict[str, int]:
    world = WorldSeeder(seed=42).seed_world(SEED_CONFIG)
    return dict(world.entity_counts)


@pytest.fixture(scope="module")
def readme_table_counts() -> dict[str, int]:
    """Parse `| Name | count | source |` rows from the Entity Types section."""
    text = README.read_text(encoding="utf-8")
    section = re.search(r"## Entity Types.*?(?=\n## )", text, re.DOTALL)
    assert section is not None, "README is missing the '## Entity Types' section"
    counts: dict[str, int] = {}
    for line in section.group(0).splitlines():
        m = re.match(r"^\|\s*([A-Za-z& ]+?)\s*\|\s*([\d,]+)", line)
        if m and m.group(1) not in ("Entity",):
            counts[m.group(1)] = int(m.group(2).replace(",", ""))
    return counts


def test_readme_lists_every_seeded_entity_type(
    seeded_counts: dict[str, int], readme_table_counts: dict[str, int]
) -> None:
    mapped = set(ROW_TO_ENTITY_TYPE.values())
    assert mapped == set(seeded_counts), (
        "Seeder entity types changed; update ROW_TO_ENTITY_TYPE and the README "
        f"table. Seeder-only: {sorted(set(seeded_counts) - mapped)}; "
        f"test-only: {sorted(mapped - set(seeded_counts))}"
    )
    missing_rows = set(ROW_TO_ENTITY_TYPE) - set(readme_table_counts)
    assert not missing_rows, f"README table is missing rows: {sorted(missing_rows)}"


# With an editable OpenEM source install, the corpus swells clinical
# knowledge (5 -> 370) and clinical tasks (1,775 -> 1,785). The README
# documents the base-install counts; skip the OpenEM-sensitive rows when
# that environment is detected (CI runs without OpenEM and enforces all).
OPENEM_SENSITIVE = {"clinical_knowledge", "clinical_task"}


def _openem_active(seeded_counts: dict[str, int]) -> bool:
    return seeded_counts["clinical_knowledge"] == 370


def test_readme_counts_match_seeder(
    seeded_counts: dict[str, int], readme_table_counts: dict[str, int]
) -> None:
    openem = _openem_active(seeded_counts)
    mismatches = {}
    for row_name, entity_type in ROW_TO_ENTITY_TYPE.items():
        if openem and entity_type in OPENEM_SENSITIVE:
            continue
        readme_count = readme_table_counts.get(row_name)
        actual = seeded_counts[entity_type]
        if readme_count != actual:
            mismatches[row_name] = (readme_count, actual)
    assert not mismatches, f"README (readme, seeded) mismatches: {mismatches}"


def test_readme_total_matches_seeder(seeded_counts: dict[str, int]) -> None:
    text = README.read_text(encoding="utf-8")
    if _openem_active(seeded_counts):
        pytest.skip("OpenEM source install changes seeded totals (documented in README)")
    total = sum(seeded_counts.values())
    assert f"{total:,} entities" in text, (
        f"README should state the seeded total '{total:,} entities'"
    )
