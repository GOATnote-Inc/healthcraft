"""Insurance & Coverage entity for the HEALTHCRAFT simulation."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from healthcraft.entities.base import Entity, EntityType


@dataclass(frozen=True)
class Insurance(Entity):
    """Immutable insurance entity with coverage details and prior auth requirements.

    Extends Entity with emergency-medicine-relevant insurance attributes.
    """

    insurance_id: str = ""
    patient_id: str = ""
    plan_name: str = ""
    plan_type: str = ""  # commercial, medicare, medicaid, tricare, self_pay, uninsured
    group_number: str = ""
    member_id: str = ""
    active: bool = True
    effective_date: str = ""
    expiration_date: str = ""
    copay_er: str = ""  # e.g., "$250", "$0", "20%"
    prior_auth_required: tuple[str, ...] = ()
    covered_medications: str = ""  # full_formulary, restricted, generic_only
    out_of_network: bool = False
    notes: str = ""


# --- Generation data ---

_COMMERCIAL_PLANS = (
    "Blue Cross PPO",
    "Blue Cross HMO",
    "Aetna PPO",
    "Aetna HMO",
    "UnitedHealthcare Choice Plus",
    "UnitedHealthcare HMO",
    "Cigna Open Access",
    "Cigna Connect",
    "Humana Gold Plus",
    "Anthem Blue Preferred",
    "Kaiser Permanente HMO",
    "Oscar Health PPO",
)
_MEDICARE_PLANS = (
    "Medicare Part A/B",
    "Medicare Advantage (Humana)",
    "Medicare Advantage (Aetna)",
    "Medicare Advantage (UHC)",
    "Medicare Part A/B + Medigap F",
    "Medicare Part A/B + Medigap G",
)
_MEDICAID_PLANS = (
    "Medicaid Fee-for-Service",
    "Medicaid Managed Care (Centene)",
    "Medicaid Managed Care (Molina)",
    "Medicaid Managed Care (Anthem)",
)
_TRICARE_PLANS = (
    "TRICARE Prime",
    "TRICARE Select",
    "TRICARE for Life",
)

_COMMERCIAL_COPAYS = ("$150", "$200", "$250", "$300", "$350", "$500", "20%", "25%")
_MEDICARE_COPAYS = ("$0", "$0", "$0", "$50", "20%")
_MEDICAID_COPAYS = ("$0", "$0", "$0", "$0", "$3")

_PRIOR_AUTH_PROCEDURES = (
    "MRI",
    "CT with contrast",
    "admission",
    "cardiac catheterization",
    "thrombolytics",
    "surgical consult",
    "transfer to tertiary center",
    "PET scan",
    "interventional radiology",
    "blood products > 4 units",
)

_COVERED_MED_OPTIONS = ("full_formulary", "restricted", "generic_only")

_CONTRADICTORY_NOTES = (
    "Plan active per employer; member services reports terminated 2025-12-31",
    "Group number valid but member ID not found in payer database",
    "Pre-auth approved per phone; no written confirmation on file",
    "Patient states coverage is active; last eligibility check returned inactive",
    "Copay waived per charity care — but plan type is commercial PPO",
    "Out-of-network flagged but facility listed as in-network on payer website",
    "Medicare Part A only; patient believes they have Part B coverage",
    "Secondary insurance on file but coordination of benefits not confirmed",
)
_NORMAL_NOTES = (
    "",
    "",
    "",
    "",
    "Verified via real-time eligibility check",
    "Coverage confirmed at registration",
    "Patient provided updated insurance card",
    "Employer group — large employer exemption applies",
    "Patient has secondary dental plan (not relevant to ED visit)",
    "Annual deductible met as of 2026-01-15",
    "High-deductible health plan — $3,500 remaining deductible",
)


def generate_insurance(
    rng: random.Random,
    patient_id: str,
) -> Insurance:
    """Generate a deterministic insurance entity for a patient.

    Args:
        rng: Seeded Random instance for deterministic generation.
        patient_id: The patient this insurance record belongs to.

    Returns:
        A frozen Insurance instance.
    """
    entity_id = f"COV-{uuid.UUID(int=rng.getrandbits(128)).hex[:8].upper()}"
    insurance_id = f"INS-{rng.randint(100000000, 999999999)}"

    # Plan type distribution: 50% commercial, 25% medicare, 15% medicaid,
    # 5% self_pay/uninsured, 5% tricare/other
    plan_type_roll = rng.random()
    if plan_type_roll < 0.50:
        plan_type = "commercial"
    elif plan_type_roll < 0.75:
        plan_type = "medicare"
    elif plan_type_roll < 0.90:
        plan_type = "medicaid"
    elif plan_type_roll < 0.95:
        plan_type = rng.choice(["self_pay", "uninsured"])
    else:
        plan_type = "tricare"

    # Dates — most effective in recent years, most expiring in future
    eff_year = rng.choice([2023, 2024, 2025, 2026])
    eff_month = rng.randint(1, 12)
    effective_date = f"{eff_year}-{eff_month:02d}-01"

    # Expiration: usually 1 year after effective date
    exp_year = eff_year + 1
    expiration_date = f"{exp_year}-{eff_month:02d}-01"

    # 5% chance of expired/stale coverage
    is_expired = rng.random() < 0.05
    if is_expired:
        effective_date = f"{rng.choice([2021, 2022, 2023])}-{rng.randint(1, 12):02d}-01"
        expiration_date = f"{rng.choice([2024, 2025])}-{rng.randint(1, 6):02d}-01"

    active = not is_expired

    # Self-pay / uninsured: sparse fields
    if plan_type in ("self_pay", "uninsured"):
        plan_name = "Self-Pay" if plan_type == "self_pay" else ""
        group_number = ""
        member_id = "" if rng.random() < 0.6 else f"MBR-{rng.randint(10000, 99999)}"
        copay_er = ""
        prior_auth_required: tuple[str, ...] = ()
        covered_medications = ""
        out_of_network = False
        # Some self-pay patients have an insurance_id but empty details (noise)
        if rng.random() < 0.4:
            insurance_id = ""
        notes = rng.choice(
            (
                "",
                "Patient declined to provide insurance information",
                "Self-pay rate sheet provided at registration",
                "Financial counselor referral placed",
                "Charity care application pending",
            )
        )
        now = datetime.now(timezone.utc)
        return Insurance(
            id=entity_id,
            entity_type=EntityType.INSURANCE,
            created_at=now,
            updated_at=now,
            insurance_id=insurance_id,
            patient_id=patient_id,
            plan_name=plan_name,
            plan_type=plan_type,
            group_number=group_number,
            member_id=member_id,
            active=active,
            effective_date=effective_date,
            expiration_date=expiration_date,
            copay_er=copay_er,
            prior_auth_required=prior_auth_required,
            covered_medications=covered_medications,
            out_of_network=out_of_network,
            notes=notes,
        )

    # Insured patients
    if plan_type == "commercial":
        plan_name = rng.choice(_COMMERCIAL_PLANS)
        copay_er = rng.choice(_COMMERCIAL_COPAYS)
    elif plan_type == "medicare":
        plan_name = rng.choice(_MEDICARE_PLANS)
        copay_er = rng.choice(_MEDICARE_COPAYS)
    elif plan_type == "medicaid":
        plan_name = rng.choice(_MEDICAID_PLANS)
        copay_er = rng.choice(_MEDICAID_COPAYS)
    else:  # tricare
        plan_name = rng.choice(_TRICARE_PLANS)
        copay_er = rng.choice(("$0", "$0", "$30"))

    group_number = f"GRP-{rng.randint(100000, 999999)}"
    member_id = f"MBR-{rng.randint(100000, 999999)}"

    # Prior auth: commercial most restrictive, medicare/medicaid moderate, tricare least
    if plan_type == "commercial":
        auth_count = rng.choices([0, 1, 2, 3], weights=[20, 35, 30, 15], k=1)[0]
    elif plan_type in ("medicare", "medicaid"):
        auth_count = rng.choices([0, 1, 2], weights=[40, 40, 20], k=1)[0]
    else:
        auth_count = rng.choices([0, 1], weights=[70, 30], k=1)[0]
    prior_auth_required = tuple(
        rng.sample(_PRIOR_AUTH_PROCEDURES, min(auth_count, len(_PRIOR_AUTH_PROCEDURES)))
    )

    # Covered medications
    if plan_type == "commercial":
        covered_medications = rng.choices(_COVERED_MED_OPTIONS, weights=[50, 35, 15], k=1)[0]
    elif plan_type == "medicare":
        covered_medications = rng.choices(_COVERED_MED_OPTIONS, weights=[40, 40, 20], k=1)[0]
    elif plan_type == "medicaid":
        covered_medications = rng.choices(_COVERED_MED_OPTIONS, weights=[20, 30, 50], k=1)[0]
    else:
        covered_medications = rng.choices(_COVERED_MED_OPTIONS, weights=[60, 30, 10], k=1)[0]

    # Out-of-network: ~15% of commercial, rare for others
    if plan_type == "commercial":
        out_of_network = rng.random() < 0.15
    elif plan_type in ("medicare", "medicaid"):
        out_of_network = rng.random() < 0.03
    else:
        out_of_network = rng.random() < 0.05

    # Notes: ~10% contradictory (noise), ~30% have a normal note, rest empty
    notes_roll = rng.random()
    if notes_roll < 0.10:
        notes = rng.choice(_CONTRADICTORY_NOTES)
    else:
        notes = rng.choice(_NORMAL_NOTES)

    now = datetime.now(timezone.utc)
    return Insurance(
        id=entity_id,
        entity_type=EntityType.INSURANCE,
        created_at=now,
        updated_at=now,
        insurance_id=insurance_id,
        patient_id=patient_id,
        plan_name=plan_name,
        plan_type=plan_type,
        group_number=group_number,
        member_id=member_id,
        active=active,
        effective_date=effective_date,
        expiration_date=expiration_date,
        copay_er=copay_er,
        prior_auth_required=prior_auth_required,
        covered_medications=covered_medications,
        out_of_network=out_of_network,
        notes=notes,
    )
