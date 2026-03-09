"""Tests for Regulatory entity."""

from __future__ import annotations

import pytest

from healthcraft.entities.base import EntityType
from healthcraft.entities.regulatory import Regulatory, load_regulations


class TestLoadRegulations:
    """Test bundled regulation loading."""

    def test_load_returns_dict(self) -> None:
        regs = load_regulations()
        assert isinstance(regs, dict)

    def test_load_returns_at_least_8(self) -> None:
        regs = load_regulations()
        assert len(regs) >= 8

    def test_all_values_are_regulatory(self) -> None:
        regs = load_regulations()
        for reg in regs.values():
            assert isinstance(reg, Regulatory)

    def test_regulatory_entity_type(self) -> None:
        regs = load_regulations()
        for reg in regs.values():
            assert reg.entity_type == EntityType.REGULATORY

    def test_regulatory_has_required_fields(self) -> None:
        regs = load_regulations()
        for reg in regs.values():
            assert reg.id
            assert reg.name
            assert reg.regulation_type in ("federal", "state", "institutional", "accreditation")
            assert isinstance(reg.requirements, tuple)
            assert isinstance(reg.documentation_elements, tuple)

    def test_emtala_exists(self) -> None:
        regs = load_regulations()
        names = [r.name.lower() for r in regs.values()]
        assert any("emtala" in n for n in names)

    def test_consent_exists(self) -> None:
        regs = load_regulations()
        categories = [r.category.lower() for r in regs.values()]
        assert any("consent" in c for c in categories)

    def test_restraint_exists(self) -> None:
        regs = load_regulations()
        categories = [r.category.lower() for r in regs.values()]
        assert any("restraint" in c for c in categories)

    def test_regulatory_is_frozen(self) -> None:
        regs = load_regulations()
        reg = next(iter(regs.values()))
        with pytest.raises(AttributeError):
            reg.name = "Modified"  # type: ignore[misc]

    def test_regulations_have_requirements(self) -> None:
        regs = load_regulations()
        for reg in regs.values():
            assert len(reg.requirements) >= 1, f"{reg.name} has no requirements"
