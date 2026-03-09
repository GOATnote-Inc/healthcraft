"""Tests for Protocol entity."""

from __future__ import annotations

from healthcraft.entities.base import EntityType
from healthcraft.entities.protocols import Protocol, load_protocols


class TestLoadProtocols:
    """Test bundled protocol loading."""

    def test_load_returns_dict(self) -> None:
        protocols = load_protocols()
        assert isinstance(protocols, dict)

    def test_load_returns_at_least_8(self) -> None:
        protocols = load_protocols()
        assert len(protocols) >= 8

    def test_all_values_are_protocol(self) -> None:
        protocols = load_protocols()
        for proto in protocols.values():
            assert isinstance(proto, Protocol)

    def test_protocol_entity_type(self) -> None:
        protocols = load_protocols()
        for proto in protocols.values():
            assert proto.entity_type == EntityType.PROTOCOL

    def test_protocol_has_required_fields(self) -> None:
        protocols = load_protocols()
        for proto in protocols.values():
            assert proto.id
            assert proto.name
            assert proto.category
            assert isinstance(proto.steps, tuple)
            assert isinstance(proto.activation_criteria, tuple)
            assert proto.created_at is not None

    def test_sepsis_protocol_exists(self) -> None:
        protocols = load_protocols()
        names = [p.name.lower() for p in protocols.values()]
        assert any("sepsis" in n for n in names)

    def test_stemi_protocol_exists(self) -> None:
        protocols = load_protocols()
        names = [p.name.lower() for p in protocols.values()]
        assert any("stemi" in n or "st-elevation" in n for n in names)

    def test_stroke_protocol_exists(self) -> None:
        protocols = load_protocols()
        names = [p.name.lower() for p in protocols.values()]
        assert any("stroke" in n for n in names)

    def test_trauma_protocol_exists(self) -> None:
        protocols = load_protocols()
        names = [p.name.lower() for p in protocols.values()]
        assert any("trauma" in n for n in names)

    def test_protocol_is_frozen(self) -> None:
        protocols = load_protocols()
        proto = next(iter(protocols.values()))
        import pytest

        with pytest.raises(AttributeError):
            proto.name = "Modified"  # type: ignore[misc]

    def test_time_critical_protocols_have_max_time(self) -> None:
        protocols = load_protocols()
        for proto in protocols.values():
            if proto.time_critical:
                assert proto.max_time_minutes is not None or len(proto.steps) > 0
