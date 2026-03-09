"""Tests for Supply entity."""

from __future__ import annotations

from healthcraft.entities.base import EntityType
from healthcraft.entities.supplies import Supply, load_supplies


class TestLoadSupplies:
    """Test bundled supply loading."""

    def test_load_returns_dict(self) -> None:
        supplies = load_supplies()
        assert isinstance(supplies, dict)

    def test_load_returns_at_least_25(self) -> None:
        supplies = load_supplies()
        assert len(supplies) >= 25

    def test_all_values_are_supply(self) -> None:
        supplies = load_supplies()
        for s in supplies.values():
            assert isinstance(s, Supply)

    def test_supply_entity_type(self) -> None:
        supplies = load_supplies()
        for s in supplies.values():
            assert s.entity_type == EntityType.SUPPLY

    def test_supply_has_required_fields(self) -> None:
        supplies = load_supplies()
        for s in supplies.values():
            assert s.id
            assert s.name
            assert s.category in ("medication", "blood_product", "equipment", "supply")
            assert isinstance(s.available, bool)
            assert isinstance(s.contraindications, tuple)

    def test_has_emergency_medications(self) -> None:
        supplies = load_supplies()
        names = [s.name.lower() for s in supplies.values()]
        assert any("epinephrine" in n for n in names)

    def test_has_antibiotics(self) -> None:
        supplies = load_supplies()
        subcats = [s.subcategory.lower() for s in supplies.values()]
        assert any("antibiotic" in sc for sc in subcats)

    def test_has_blood_products(self) -> None:
        supplies = load_supplies()
        blood = [s for s in supplies.values() if s.category == "blood_product"]
        assert len(blood) >= 3

    def test_some_on_shortage(self) -> None:
        """Noise: some supplies should be on shortage."""
        supplies = load_supplies()
        shortages = [s for s in supplies.values() if s.shortage]
        assert len(shortages) >= 1

    def test_high_alert_medications_exist(self) -> None:
        supplies = load_supplies()
        high_alert = [s for s in supplies.values() if s.high_alert]
        assert len(high_alert) >= 3

    def test_supply_is_frozen(self) -> None:
        import pytest

        supplies = load_supplies()
        s = next(iter(supplies.values()))
        with pytest.raises(AttributeError):
            s.name = "Modified"  # type: ignore[misc]
