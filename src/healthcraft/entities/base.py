"""Base entity definitions for the 14 HEALTHCRAFT entity types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EntityType(Enum):
    """All 14 entity types in the HEALTHCRAFT simulation."""

    PATIENT = "patient"
    ENCOUNTER = "encounter"
    STAFF = "staff"
    LOCATION = "location"
    VITAL_SIGNS = "vital_signs"
    LAB_RESULT = "lab_result"
    IMAGING_STUDY = "imaging_study"
    MEDICATION = "medication"
    PROCEDURE = "procedure"
    CLINICAL_NOTE = "clinical_note"
    ORDER = "order"
    ALLERGY = "allergy"
    CLINICAL_KNOWLEDGE = "clinical_knowledge"
    DISPOSITION = "disposition"


@dataclass(frozen=True)
class Entity:
    """Base frozen dataclass for all HEALTHCRAFT entities.

    All entities are immutable once created. Updates produce new instances.
    """

    id: str
    entity_type: EntityType
    created_at: datetime
    updated_at: datetime

    @classmethod
    def _now(cls) -> datetime:
        """Return the current UTC time. Overridable for testing."""
        return datetime.now(timezone.utc)


class EntityRegistry:
    """Registry for entity type -> dataclass class mappings.

    Allows lookup of entity classes by EntityType and validation of
    entity instances against their registered types.
    """

    def __init__(self) -> None:
        self._registry: dict[EntityType, type] = {}

    def register(self, entity_type: EntityType, cls: type) -> None:
        """Register a dataclass class for an entity type.

        Args:
            entity_type: The EntityType enum value.
            cls: The frozen dataclass class for this entity type.

        Raises:
            ValueError: If the entity type is already registered.
        """
        if entity_type in self._registry:
            raise ValueError(f"Entity type already registered: {entity_type}")
        self._registry[entity_type] = cls

    def get_class(self, entity_type: EntityType) -> type | None:
        """Look up the registered class for an entity type.

        Args:
            entity_type: The EntityType to look up.

        Returns:
            The registered class, or None if not registered.
        """
        return self._registry.get(entity_type)

    def validate(self, entity: Any) -> bool:
        """Check that an entity is an instance of its registered class.

        Args:
            entity: The entity to validate.

        Returns:
            True if the entity matches its registered type.
        """
        if not isinstance(entity, Entity):
            return False
        cls = self._registry.get(entity.entity_type)
        if cls is None:
            return False
        return isinstance(entity, cls)

    @property
    def registered_types(self) -> list[EntityType]:
        """All registered entity types."""
        return list(self._registry.keys())

    def __repr__(self) -> str:
        return f"EntityRegistry(types={[t.value for t in self._registry]})"


# Module-level registry instance
REGISTRY = EntityRegistry()
