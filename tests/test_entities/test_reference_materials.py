"""Tests for ReferenceMaterial entity."""

from __future__ import annotations

import pytest

from healthcraft.entities.base import EntityType
from healthcraft.entities.reference_materials import ReferenceMaterial, load_reference_materials


class TestLoadReferenceMaterials:
    """Test bundled reference material loading."""

    def test_load_returns_dict(self) -> None:
        refs = load_reference_materials()
        assert isinstance(refs, dict)

    def test_load_returns_at_least_10(self) -> None:
        refs = load_reference_materials()
        assert len(refs) >= 10

    def test_all_values_are_reference_material(self) -> None:
        refs = load_reference_materials()
        for ref in refs.values():
            assert isinstance(ref, ReferenceMaterial)

    def test_reference_entity_type(self) -> None:
        refs = load_reference_materials()
        for ref in refs.values():
            assert ref.entity_type == EntityType.REFERENCE_MATERIAL

    def test_reference_has_required_fields(self) -> None:
        refs = load_reference_materials()
        for ref in refs.values():
            assert ref.id
            assert ref.title
            assert ref.material_type in (
                "drug_monograph",
                "procedure_guide",
                "dosing_reference",
                "clinical_guideline",
                "calculator",
            )
            assert ref.content  # Should have actual content
            assert isinstance(ref.keywords, tuple)

    def test_has_drug_monographs(self) -> None:
        refs = load_reference_materials()
        monographs = [r for r in refs.values() if r.material_type == "drug_monograph"]
        assert len(monographs) >= 3

    def test_has_procedure_guides(self) -> None:
        refs = load_reference_materials()
        guides = [r for r in refs.values() if r.material_type == "procedure_guide"]
        assert len(guides) >= 2

    def test_alteplase_monograph_exists(self) -> None:
        refs = load_reference_materials()
        titles = [r.title.lower() for r in refs.values()]
        assert any("alteplase" in t or "tpa" in t.lower() for t in titles)

    def test_rsi_guide_exists(self) -> None:
        refs = load_reference_materials()
        titles = [r.title.lower() for r in refs.values()]
        assert any("intubation" in t or "rsi" in t for t in titles)

    def test_reference_is_frozen(self) -> None:
        refs = load_reference_materials()
        ref = next(iter(refs.values()))
        with pytest.raises(AttributeError):
            ref.title = "Modified"  # type: ignore[misc]

    def test_content_is_substantial(self) -> None:
        """Each reference should have meaningful content, not just a title."""
        refs = load_reference_materials()
        for ref in refs.values():
            assert len(ref.content) >= 50, f"{ref.title} has insufficient content"
