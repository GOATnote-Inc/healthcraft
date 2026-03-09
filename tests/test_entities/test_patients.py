"""Tests for Patient entity."""

from __future__ import annotations

import random
from datetime import date

import pytest

from healthcraft.entities.base import EntityType
from healthcraft.entities.patients import Patient, generate_patient, patient_to_fhir


class TestPatientGeneration:
    """Test deterministic patient generation."""

    def test_generate_patient_returns_patient(self) -> None:
        rng = random.Random(42)
        patient = generate_patient(rng)
        assert isinstance(patient, Patient)

    def test_generate_patient_deterministic(self) -> None:
        p1 = generate_patient(random.Random(42))
        p2 = generate_patient(random.Random(42))
        assert p1.id == p2.id
        assert p1.first_name == p2.first_name
        assert p1.last_name == p2.last_name
        assert p1.mrn == p2.mrn
        assert p1.dob == p2.dob
        assert p1.sex == p2.sex

    def test_different_seeds_different_patients(self) -> None:
        p1 = generate_patient(random.Random(42))
        p2 = generate_patient(random.Random(99))
        # Extremely unlikely to be identical with different seeds
        assert p1.id != p2.id

    def test_patient_has_required_fields(self) -> None:
        rng = random.Random(42)
        patient = generate_patient(rng)
        assert patient.id.startswith("PAT-")
        assert patient.entity_type == EntityType.PATIENT
        assert patient.mrn.startswith("MRN-")
        assert patient.first_name
        assert patient.last_name
        assert isinstance(patient.dob, date)
        assert patient.sex in ("M", "F")
        assert patient.insurance_id.startswith("INS-")
        assert patient.created_at is not None
        assert patient.updated_at is not None

    def test_patient_is_frozen(self) -> None:
        rng = random.Random(42)
        patient = generate_patient(rng)
        with pytest.raises(AttributeError):
            patient.first_name = "Modified"  # type: ignore[misc]

    def test_patient_allergies_are_tuple(self) -> None:
        rng = random.Random(42)
        patient = generate_patient(rng)
        assert isinstance(patient.allergies, tuple)

    def test_patient_medications_are_tuple(self) -> None:
        rng = random.Random(42)
        patient = generate_patient(rng)
        assert isinstance(patient.medications, tuple)

    def test_patient_pmh_are_tuple(self) -> None:
        rng = random.Random(42)
        patient = generate_patient(rng)
        assert isinstance(patient.pmh, tuple)


class TestPatientToFHIR:
    """Test FHIR R4 conversion."""

    def test_fhir_resource_type(self) -> None:
        patient = generate_patient(random.Random(42))
        fhir = patient_to_fhir(patient)
        assert fhir["resourceType"] == "Patient"

    def test_fhir_has_id(self) -> None:
        patient = generate_patient(random.Random(42))
        fhir = patient_to_fhir(patient)
        assert fhir["id"] == patient.id

    def test_fhir_has_name(self) -> None:
        patient = generate_patient(random.Random(42))
        fhir = patient_to_fhir(patient)
        names = fhir["name"]
        assert len(names) >= 1
        assert names[0]["family"] == patient.last_name
        assert patient.first_name in names[0]["given"]

    def test_fhir_gender_mapping(self) -> None:
        patient = generate_patient(random.Random(42))
        fhir = patient_to_fhir(patient)
        valid_genders = {"male", "female", "other", "unknown"}
        assert fhir["gender"] in valid_genders

    def test_fhir_has_mrn_identifier(self) -> None:
        patient = generate_patient(random.Random(42))
        fhir = patient_to_fhir(patient)
        identifiers = fhir["identifier"]
        mrn_ids = [i for i in identifiers if i["type"]["coding"][0]["code"] == "MR"]
        assert len(mrn_ids) == 1
        assert mrn_ids[0]["value"] == patient.mrn

    def test_fhir_has_birthdate(self) -> None:
        patient = generate_patient(random.Random(42))
        fhir = patient_to_fhir(patient)
        assert "birthDate" in fhir
        assert fhir["birthDate"] == patient.dob.isoformat()
