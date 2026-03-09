"""Supplies & Medications entity for the HEALTHCRAFT simulation."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from healthcraft.entities.base import Entity, EntityType


@dataclass(frozen=True)
class Supply(Entity):
    """Immutable supply entity representing medications and supplies in the ED.

    Extends Entity with formulary information, availability, shortage status,
    and Pyxis dispensing metadata.
    """

    supply_id: str = ""
    name: str = ""
    category: str = ""  # medication, blood_product, equipment, supply
    subcategory: str = ""  # anticoagulant, analgesic, antibiotic, vasopressor, etc.
    available: bool = True
    quantity: int = 0
    unit: str = ""  # vials, units, each
    location: str = ""  # Pyxis Main, Blood Bank, Trauma Bay 1
    requires_override: bool = False
    high_alert: bool = False
    shortage: bool = False
    shortage_alternative: str = ""
    formulary_status: str = ""  # formulary, non_formulary, restricted
    dosing_info: str = ""
    contraindications: tuple[str, ...] = ()
    interactions: tuple[str, ...] = ()


# --- Bundled ED supplies ---

_BUNDLED_SUPPLIES: dict[str, dict[str, Any]] = {
    # --- Emergency medications ---
    "MED-EPINEPHRINE-001": {
        "name": "Epinephrine 1mg/10mL",
        "category": "medication",
        "subcategory": "vasopressor",
        "quantity": 20,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": False,
        "high_alert": True,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "Cardiac arrest: 1mg IV q3-5min. Anaphylaxis: 0.3mg IM",
        "contraindications": (),
        "interactions": ("Beta-blockers", "MAOIs", "Tricyclic antidepressants"),
    },
    "MED-ATROPINE-001": {
        "name": "Atropine Sulfate 1mg/mL",
        "category": "medication",
        "subcategory": "anticholinergic",
        "quantity": 15,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": False,
        "high_alert": False,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "Bradycardia: 0.5mg IV q3-5min, max 3mg",
        "contraindications": ("Glaucoma",),
        "interactions": ("Antihistamines", "Phenothiazines"),
    },
    "MED-AMIODARONE-001": {
        "name": "Amiodarone 150mg/3mL",
        "category": "medication",
        "subcategory": "antiarrhythmic",
        "quantity": 10,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": False,
        "high_alert": True,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "VF/pVT: 300mg IV push, repeat 150mg. Stable VT: 150mg over 10min",
        "contraindications": (
            "Cardiogenic shock",
            "Severe sinus node dysfunction",
            "2nd/3rd degree heart block",
        ),
        "interactions": ("Digoxin", "Warfarin", "Simvastatin", "QT-prolonging agents"),
    },
    "MED-ADENOSINE-001": {
        "name": "Adenosine 6mg/2mL",
        "category": "medication",
        "subcategory": "antiarrhythmic",
        "quantity": 8,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": False,
        "high_alert": True,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "SVT: 6mg rapid IV push, may repeat 12mg x2",
        "contraindications": ("2nd/3rd degree heart block", "Sick sinus syndrome", "Asthma"),
        "interactions": ("Dipyridamole", "Carbamazepine", "Caffeine"),
    },
    # --- Analgesics ---
    "MED-MORPHINE-001": {
        "name": "Morphine Sulfate 4mg/mL",
        "category": "medication",
        "subcategory": "analgesic",
        "quantity": 25,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": True,
        "high_alert": True,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "2-4mg IV q5-15min PRN pain",
        "contraindications": ("Respiratory depression", "Paralytic ileus", "MAOIs within 14 days"),
        "interactions": ("Benzodiazepines", "Other opioids", "MAOIs", "CNS depressants"),
    },
    "MED-FENTANYL-001": {
        "name": "Fentanyl Citrate 100mcg/2mL",
        "category": "medication",
        "subcategory": "analgesic",
        "quantity": 20,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": True,
        "high_alert": True,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "25-100mcg IV q30-60min PRN pain",
        "contraindications": ("Respiratory depression", "MAOIs within 14 days"),
        "interactions": (
            "Benzodiazepines",
            "Other opioids",
            "CYP3A4 inhibitors",
            "CNS depressants",
        ),
    },
    "MED-KETOROLAC-001": {
        "name": "Ketorolac Tromethamine 30mg/mL",
        "category": "medication",
        "subcategory": "analgesic",
        "quantity": 30,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": False,
        "high_alert": False,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "15-30mg IV/IM q6h, max 5 days",
        "contraindications": (
            "Renal impairment",
            "Active GI bleeding",
            "Coagulopathy",
            "Aspirin allergy",
        ),
        "interactions": ("Anticoagulants", "SSRIs", "Lithium", "Methotrexate"),
    },
    "MED-ACETAMINOPHEN-001": {
        "name": "Acetaminophen 1000mg/100mL IV",
        "category": "medication",
        "subcategory": "analgesic",
        "quantity": 40,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": False,
        "high_alert": False,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "1000mg IV q6h, max 4g/day. <50kg: 15mg/kg",
        "contraindications": ("Severe hepatic impairment",),
        "interactions": ("Warfarin",),
    },
    # --- Antibiotics ---
    "MED-CEFTRIAXONE-001": {
        "name": "Ceftriaxone 1g",
        "category": "medication",
        "subcategory": "antibiotic",
        "quantity": 30,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": False,
        "high_alert": False,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "1-2g IV q24h. Meningitis: 2g IV q12h",
        "contraindications": ("Cephalosporin allergy", "Neonates with hyperbilirubinemia"),
        "interactions": ("Calcium-containing IV solutions",),
    },
    "MED-PIPTAZO-001": {
        "name": "Piperacillin-Tazobactam 3.375g",
        "category": "medication",
        "subcategory": "antibiotic",
        "quantity": 20,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": False,
        "high_alert": False,
        "shortage": True,
        "shortage_alternative": "Meropenem 1g IV or Cefepime 2g IV + Metronidazole 500mg IV",
        "formulary_status": "formulary",
        "dosing_info": "3.375g IV q6h. Extended infusion: 3.375g over 4h q8h",
        "contraindications": ("Penicillin allergy",),
        "interactions": ("Methotrexate", "Vancomycin (nephrotoxicity)", "Probenecid"),
    },
    "MED-VANCOMYCIN-001": {
        "name": "Vancomycin 1g",
        "category": "medication",
        "subcategory": "antibiotic",
        "quantity": 15,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": False,
        "high_alert": False,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "15-20mg/kg IV q8-12h. Load 25-30mg/kg for severe infection",
        "contraindications": (),
        "interactions": (
            "Aminoglycosides (nephrotoxicity)",
            "Piperacillin-tazobactam (nephrotoxicity)",
        ),
    },
    "MED-AZITHROMYCIN-001": {
        "name": "Azithromycin 500mg",
        "category": "medication",
        "subcategory": "antibiotic",
        "quantity": 25,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": False,
        "high_alert": False,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "500mg IV/PO x1, then 250mg PO daily x4 days",
        "contraindications": ("Hepatic impairment", "QT prolongation"),
        "interactions": ("QT-prolonging agents", "Warfarin", "Digoxin"),
    },
    # --- Sedatives ---
    "MED-MIDAZOLAM-001": {
        "name": "Midazolam 5mg/mL",
        "category": "medication",
        "subcategory": "sedative",
        "quantity": 15,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": True,
        "high_alert": True,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "Sedation: 0.5-2mg IV titrated. Seizure: 10mg IM",
        "contraindications": ("Acute narrow-angle glaucoma", "Severe respiratory insufficiency"),
        "interactions": ("Opioids", "CNS depressants", "CYP3A4 inhibitors"),
    },
    "MED-PROPOFOL-001": {
        "name": "Propofol 10mg/mL 20mL",
        "category": "medication",
        "subcategory": "sedative",
        "quantity": 10,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": True,
        "high_alert": True,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "PSA: 0.5-1mg/kg IV, repeat 0.5mg/kg q3min. RSI: 1.5-2.5mg/kg IV",
        "contraindications": ("Egg/soy allergy", "Severe cardiac dysfunction"),
        "interactions": ("Opioids", "Benzodiazepines", "Antihypertensives"),
    },
    "MED-KETAMINE-001": {
        "name": "Ketamine 500mg/10mL",
        "category": "medication",
        "subcategory": "sedative",
        "quantity": 8,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": True,
        "high_alert": True,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "PSA: 1-2mg/kg IV. Analgesia: 0.1-0.3mg/kg IV. RSI: 1.5-2mg/kg IV",
        "contraindications": ("Age <3 months", "Schizophrenia", "Elevated ICP (relative)"),
        "interactions": ("MAOIs", "Thyroid hormones"),
    },
    "MED-ETOMIDATE-001": {
        "name": "Etomidate 2mg/mL 10mL",
        "category": "medication",
        "subcategory": "sedative",
        "quantity": 6,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": True,
        "high_alert": True,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "RSI: 0.3mg/kg IV push",
        "contraindications": ("Adrenal insufficiency", "Septic shock (relative)"),
        "interactions": ("Opioids", "Benzodiazepines"),
    },
    # --- Anticoagulants ---
    "MED-HEPARIN-001": {
        "name": "Heparin Sodium 1000 units/mL",
        "category": "medication",
        "subcategory": "anticoagulant",
        "quantity": 12,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": True,
        "high_alert": True,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "ACS: 60 units/kg bolus (max 4000), 12 units/kg/hr. PE: 80 units/kg bolus, 18 units/kg/hr",
        "contraindications": ("Active bleeding", "HIT", "Severe thrombocytopenia"),
        "interactions": ("Antiplatelets", "Thrombolytics", "NSAIDs"),
    },
    "MED-ENOXAPARIN-001": {
        "name": "Enoxaparin 40mg/0.4mL",
        "category": "medication",
        "subcategory": "anticoagulant",
        "quantity": 20,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": True,
        "high_alert": True,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "DVT/PE treatment: 1mg/kg SQ q12h. Prophylaxis: 40mg SQ daily",
        "contraindications": ("Active bleeding", "HIT", "CrCl <30 (adjust dose)"),
        "interactions": ("Antiplatelets", "Thrombolytics", "NSAIDs"),
    },
    "MED-ALTEPLASE-001": {
        "name": "Alteplase (tPA) 100mg",
        "category": "medication",
        "subcategory": "thrombolytic",
        "quantity": 4,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": True,
        "high_alert": True,
        "shortage": True,
        "shortage_alternative": "Tenecteplase (TNKase) weight-based single bolus",
        "formulary_status": "restricted",
        "dosing_info": "Stroke: 0.9mg/kg (max 90mg), 10% bolus over 1min, remainder over 60min",
        "contraindications": (
            "Active internal bleeding",
            "Recent surgery/trauma <3 months",
            "History of hemorrhagic stroke",
            "Intracranial neoplasm",
            "Severe uncontrolled hypertension",
        ),
        "interactions": ("Anticoagulants", "Antiplatelets", "NSAIDs"),
    },
    # --- Vasopressors ---
    "MED-NOREPINEPHRINE-001": {
        "name": "Norepinephrine 4mg/4mL",
        "category": "medication",
        "subcategory": "vasopressor",
        "quantity": 12,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": False,
        "high_alert": True,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "0.1-0.5 mcg/kg/min IV infusion, titrate to MAP >65",
        "contraindications": ("Mesenteric/peripheral vascular thrombosis (relative)",),
        "interactions": ("MAOIs", "Tricyclic antidepressants", "Beta-blockers"),
    },
    "MED-PHENYLEPHRINE-001": {
        "name": "Phenylephrine 10mg/mL",
        "category": "medication",
        "subcategory": "vasopressor",
        "quantity": 10,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": False,
        "high_alert": True,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "Bolus: 100-200mcg IV q1-2min. Infusion: 0.1-0.5 mcg/kg/min",
        "contraindications": ("Severe hypertension",),
        "interactions": ("MAOIs", "Oxytocin", "Tricyclic antidepressants"),
    },
    "MED-VASOPRESSIN-001": {
        "name": "Vasopressin 20 units/mL",
        "category": "medication",
        "subcategory": "vasopressor",
        "quantity": 8,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": False,
        "high_alert": True,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "Septic shock: 0.03-0.04 units/min IV. Cardiac arrest: 40 units IV x1",
        "contraindications": (),
        "interactions": ("Carbamazepine", "Chlorpropamide", "Fludrocortisone"),
    },
    # --- Blood products ---
    "BLD-PRBC-001": {
        "name": "Packed Red Blood Cells (PRBCs)",
        "category": "blood_product",
        "subcategory": "red_cells",
        "quantity": 6,
        "unit": "units",
        "location": "Blood Bank",
        "requires_override": False,
        "high_alert": True,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "1 unit over 1-2h. MTP: 6 units uncrossmatched O-neg STAT",
        "contraindications": (),
        "interactions": (),
    },
    "BLD-FFP-001": {
        "name": "Fresh Frozen Plasma (FFP)",
        "category": "blood_product",
        "subcategory": "plasma",
        "quantity": 4,
        "unit": "units",
        "location": "Blood Bank",
        "requires_override": False,
        "high_alert": True,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "10-15 mL/kg. MTP: 1:1 ratio with PRBCs",
        "contraindications": ("IgA deficiency (use IgA-depleted)",),
        "interactions": (),
    },
    "BLD-PLATELETS-001": {
        "name": "Platelets (Apheresis)",
        "category": "blood_product",
        "subcategory": "platelets",
        "quantity": 3,
        "unit": "units",
        "location": "Blood Bank",
        "requires_override": False,
        "high_alert": True,
        "shortage": True,
        "shortage_alternative": "Pooled platelets (4-6 units random donor)",
        "formulary_status": "formulary",
        "dosing_info": "1 apheresis unit over 30-60min. Target >50k for procedures, >100k for neurosurgery",
        "contraindications": ("TTP (relative)",),
        "interactions": (),
    },
    "BLD-CRYO-001": {
        "name": "Cryoprecipitate",
        "category": "blood_product",
        "subcategory": "cryo",
        "quantity": 10,
        "unit": "units",
        "location": "Blood Bank",
        "requires_override": False,
        "high_alert": True,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "10 units (1 pool). Target fibrinogen >150-200 mg/dL",
        "contraindications": (),
        "interactions": (),
    },
    # --- RSI drugs ---
    "MED-SUCCINYLCHOLINE-001": {
        "name": "Succinylcholine 200mg/10mL",
        "category": "medication",
        "subcategory": "neuromuscular_blocker",
        "quantity": 10,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": True,
        "high_alert": True,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "RSI: 1.5mg/kg IV push",
        "contraindications": (
            "Hyperkalemia",
            "Burns >24h",
            "Crush injury >24h",
            "Denervation injury",
            "Malignant hyperthermia history",
        ),
        "interactions": ("Anticholinesterases", "Aminoglycosides"),
    },
    "MED-ROCURONIUM-001": {
        "name": "Rocuronium 50mg/5mL",
        "category": "medication",
        "subcategory": "neuromuscular_blocker",
        "quantity": 10,
        "unit": "vials",
        "location": "Pyxis Main",
        "requires_override": True,
        "high_alert": True,
        "shortage": False,
        "shortage_alternative": "",
        "formulary_status": "formulary",
        "dosing_info": "RSI: 1.2mg/kg IV push. Onset 45-60sec. Sugammadex reversal available",
        "contraindications": (),
        "interactions": ("Aminoglycosides", "Magnesium", "Lithium"),
    },
}


def load_supplies() -> dict[str, Supply]:
    """Load the bundled ED supplies and medications.

    Returns:
        Dict of supply_id -> Supply entity.
    """
    now = datetime.now(timezone.utc)
    result: dict[str, Supply] = {}

    for supply_id, data in _BUNDLED_SUPPLIES.items():
        supply = Supply(
            id=f"SUP-{supply_id}",
            entity_type=EntityType.SUPPLY,
            created_at=now,
            updated_at=now,
            supply_id=supply_id,
            name=data["name"],
            category=data["category"],
            subcategory=data["subcategory"],
            available=not data["shortage"] or data["quantity"] > 0,
            quantity=data["quantity"],
            unit=data["unit"],
            location=data["location"],
            requires_override=data["requires_override"],
            high_alert=data["high_alert"],
            shortage=data["shortage"],
            shortage_alternative=data["shortage_alternative"],
            formulary_status=data["formulary_status"],
            dosing_info=data["dosing_info"],
            contraindications=tuple(data.get("contraindications", ())),
            interactions=tuple(data.get("interactions", ())),
        )
        result[supply_id] = supply

    return result


def generate_supply(
    rng: random.Random,
    supply_id: str | None = None,
) -> Supply:
    """Generate a deterministic supply entity, optionally from bundled data.

    Args:
        rng: Seeded Random instance for deterministic generation.
        supply_id: Optional bundled supply ID to use as base (with randomized quantity).

    Returns:
        A frozen Supply instance.
    """
    now = datetime.now(timezone.utc)

    if supply_id and supply_id in _BUNDLED_SUPPLIES:
        data = _BUNDLED_SUPPLIES[supply_id]
        # Randomize quantity around the base value
        base_qty = data["quantity"]
        quantity = max(0, base_qty + rng.randint(-base_qty // 2, base_qty // 2))
        shortage = data["shortage"] or quantity == 0

        return Supply(
            id=f"SUP-{supply_id}",
            entity_type=EntityType.SUPPLY,
            created_at=now,
            updated_at=now,
            supply_id=supply_id,
            name=data["name"],
            category=data["category"],
            subcategory=data["subcategory"],
            available=quantity > 0,
            quantity=quantity,
            unit=data["unit"],
            location=data["location"],
            requires_override=data["requires_override"],
            high_alert=data["high_alert"],
            shortage=shortage,
            shortage_alternative=data["shortage_alternative"],
            formulary_status=data["formulary_status"],
            dosing_info=data["dosing_info"],
            contraindications=tuple(data.get("contraindications", ())),
            interactions=tuple(data.get("interactions", ())),
        )

    # Fully random supply from the bundled pool
    chosen_id = rng.choice(list(_BUNDLED_SUPPLIES.keys()))
    return generate_supply(rng, supply_id=chosen_id)
