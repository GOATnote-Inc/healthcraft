"""FHIR R4 data store for the HEALTHCRAFT simulation.

Provides a dict-based in-memory store with an interface compatible with
a future PostgreSQL backend (via Docker).
"""

from __future__ import annotations

from typing import Any

# FHIR R4 resource type constants
PATIENT = "Patient"
ENCOUNTER = "Encounter"
CONDITION = "Condition"
OBSERVATION = "Observation"
DIAGNOSTIC_REPORT = "DiagnosticReport"
MEDICATION_REQUEST = "MedicationRequest"
MEDICATION_ADMINISTRATION = "MedicationAdministration"
PROCEDURE = "Procedure"
SERVICE_REQUEST = "ServiceRequest"
ALLERGY_INTOLERANCE = "AllergyIntolerance"
CARE_PLAN = "CarePlan"
LOCATION = "Location"
PRACTITIONER = "Practitioner"
ORGANIZATION = "Organization"

RESOURCE_TYPES: tuple[str, ...] = (
    PATIENT,
    ENCOUNTER,
    CONDITION,
    OBSERVATION,
    DIAGNOSTIC_REPORT,
    MEDICATION_REQUEST,
    MEDICATION_ADMINISTRATION,
    PROCEDURE,
    SERVICE_REQUEST,
    ALLERGY_INTOLERANCE,
    CARE_PLAN,
    LOCATION,
    PRACTITIONER,
    ORGANIZATION,
)


class FHIRStore:
    """In-memory FHIR R4 resource store.

    Wraps dict-based storage with a clean interface that can be swapped
    for a PostgreSQL-backed implementation in Docker.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, dict[str, Any]]] = {rt: {} for rt in RESOURCE_TYPES}

    def store_resource(
        self,
        resource_type: str,
        resource_id: str,
        resource_dict: dict[str, Any],
    ) -> None:
        """Store a FHIR resource.

        Args:
            resource_type: FHIR resource type (e.g. "Patient").
            resource_id: Unique resource identifier.
            resource_dict: The FHIR resource as a dict.

        Raises:
            KeyError: If resource_type is not a recognized FHIR type.
        """
        collection = self._store.get(resource_type)
        if collection is None:
            raise KeyError(
                f"Unknown FHIR resource type: {resource_type}. "
                f"Valid types: {', '.join(RESOURCE_TYPES)}"
            )
        resource_dict["resourceType"] = resource_type
        resource_dict["id"] = resource_id
        collection[resource_id] = resource_dict

    def get_resource(
        self,
        resource_type: str,
        resource_id: str,
    ) -> dict[str, Any] | None:
        """Retrieve a FHIR resource by type and ID.

        Args:
            resource_type: FHIR resource type.
            resource_id: Unique resource identifier.

        Returns:
            The resource dict if found, else None.
        """
        collection = self._store.get(resource_type)
        if collection is None:
            raise KeyError(f"Unknown FHIR resource type: {resource_type}")
        return collection.get(resource_id)

    def search_resources(
        self,
        resource_type: str,
        **params: Any,
    ) -> list[dict[str, Any]]:
        """Search FHIR resources by type and optional field-level filters.

        Each keyword argument is treated as a field name -> expected value
        filter. Only top-level fields are searched.

        Args:
            resource_type: FHIR resource type to search.
            **params: Field name / value pairs to filter on.

        Returns:
            List of matching resource dicts.
        """
        collection = self._store.get(resource_type)
        if collection is None:
            raise KeyError(f"Unknown FHIR resource type: {resource_type}")

        if not params:
            return list(collection.values())

        results: list[dict[str, Any]] = []
        for resource in collection.values():
            match = True
            for key, value in params.items():
                if resource.get(key) != value:
                    match = False
                    break
            if match:
                results.append(resource)
        return results

    def count(self, resource_type: str) -> int:
        """Count resources of a given type.

        Args:
            resource_type: FHIR resource type.

        Returns:
            Number of stored resources of that type.
        """
        collection = self._store.get(resource_type)
        if collection is None:
            raise KeyError(f"Unknown FHIR resource type: {resource_type}")
        return len(collection)

    def delete_resource(self, resource_type: str, resource_id: str) -> bool:
        """Remove a resource from the store.

        Args:
            resource_type: FHIR resource type.
            resource_id: Resource identifier.

        Returns:
            True if the resource was deleted, False if not found.
        """
        collection = self._store.get(resource_type)
        if collection is None:
            raise KeyError(f"Unknown FHIR resource type: {resource_type}")
        if resource_id in collection:
            del collection[resource_id]
            return True
        return False

    def __repr__(self) -> str:
        counts = {rt: len(v) for rt, v in self._store.items() if v}
        return f"FHIRStore({counts})"
