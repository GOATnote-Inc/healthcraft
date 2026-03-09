"""Protocol entity for the HEALTHCRAFT simulation."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from healthcraft.entities.base import Entity, EntityType


@dataclass(frozen=True)
class Protocol(Entity):
    """Immutable protocol entity representing a clinical protocol or guideline.

    Extends Entity with emergency-medicine protocol attributes including
    ordered steps, activation criteria, and time constraints.
    """

    protocol_id: str = ""
    name: str = ""
    category: str = ""  # sepsis, cardiac, stroke, trauma, transfusion, airway, resuscitation
    description: str = ""
    steps: tuple[dict[str, Any], ...] = ()
    activation_criteria: tuple[str, ...] = ()
    contraindications: tuple[str, ...] = ()
    time_critical: bool = False
    max_time_minutes: int | None = None
    required_resources: tuple[str, ...] = ()
    condition_refs: tuple[str, ...] = ()
    version: str = ""
    active: bool = True


# --- Bundled protocols ---

_BUNDLED_PROTOCOLS: dict[str, dict[str, Any]] = {
    "PROTO-SEPSIS-001": {
        "protocol_id": "PROTO-SEPSIS-001",
        "name": "Sepsis Hour-1 Bundle",
        "category": "sepsis",
        "description": (
            "CMS SEP-1 Hour-1 Bundle. All elements to be initiated within "
            "1 hour of sepsis recognition. Applies to patients meeting SIRS "
            "criteria with suspected infection or septic shock."
        ),
        "steps": (
            {
                "name": "Measure lactate",
                "description": "Obtain serum lactate level",
                "time_limit_minutes": 60,
            },
            {
                "name": "Blood cultures",
                "description": "Obtain blood cultures x2 before antibiotics",
                "time_limit_minutes": 60,
            },
            {
                "name": "Broad-spectrum antibiotics",
                "description": "Administer broad-spectrum IV antibiotics",
                "time_limit_minutes": 60,
            },
            {
                "name": "IV crystalloid bolus",
                "description": "30 mL/kg crystalloid for hypotension or lactate >= 4 mmol/L",
                "time_limit_minutes": 60,
            },
            {
                "name": "Vasopressors",
                "description": "Initiate vasopressors if hypotension persists after fluid resuscitation",
                "time_limit_minutes": 90,
            },
            {
                "name": "Repeat lactate",
                "description": "Repeat lactate if initial lactate >= 2 mmol/L",
                "time_limit_minutes": 360,
            },
        ),
        "activation_criteria": (
            "SIRS criteria met (>= 2 of: temp >38.3 or <36, HR >90, RR >20, WBC >12k or <4k)",
            "Suspected or confirmed source of infection",
            "Systolic BP < 90 mmHg or MAP < 65 mmHg after fluid challenge",
            "Lactate >= 2 mmol/L",
        ),
        "contraindications": (
            "Comfort-measures-only order in place",
            "Active DNR/DNI with family declining aggressive care",
        ),
        "time_critical": True,
        "max_time_minutes": 60,
        "required_resources": (
            "IV access (2 large-bore)",
            "Blood culture supplies",
            "Broad-spectrum antibiotics (piperacillin-tazobactam or meropenem)",
            "Crystalloid (lactated Ringer's or normal saline)",
            "Vasopressor infusion (norepinephrine)",
            "ICU bed availability",
        ),
        "condition_refs": ("SEPSIS",),
        "version": "2024.1",
        "active": True,
    },
    "PROTO-STEMI-001": {
        "protocol_id": "PROTO-STEMI-001",
        "name": "STEMI Alert — Door-to-Balloon",
        "category": "cardiac",
        "description": (
            "ST-Elevation Myocardial Infarction activation protocol. Target "
            "door-to-balloon time < 90 minutes. Immediate cath lab activation "
            "upon ECG confirmation of STEMI."
        ),
        "steps": (
            {
                "name": "12-lead ECG",
                "description": "Obtain and interpret 12-lead ECG",
                "time_limit_minutes": 10,
            },
            {
                "name": "STEMI activation",
                "description": "Activate cath lab team and interventional cardiology",
                "time_limit_minutes": 15,
            },
            {
                "name": "Aspirin",
                "description": "Aspirin 325 mg PO (chewed) unless true allergy",
                "time_limit_minutes": 15,
            },
            {
                "name": "Heparin",
                "description": "Unfractionated heparin IV bolus per protocol",
                "time_limit_minutes": 20,
            },
            {
                "name": "P2Y12 inhibitor",
                "description": "Load ticagrelor 180 mg or clopidogrel 600 mg per cardiology preference",
                "time_limit_minutes": 30,
            },
            {
                "name": "Cath lab transport",
                "description": "Patient transported to cath lab for PCI",
                "time_limit_minutes": 60,
            },
            {
                "name": "Balloon inflation",
                "description": "First balloon inflation (target < 90 min from door)",
                "time_limit_minutes": 90,
            },
        ),
        "activation_criteria": (
            "ST elevation >= 1 mm in 2 contiguous leads",
            "New or presumably new LBBB with ischemic symptoms",
            "Posterior STEMI pattern (ST depression V1-V3 with ST elevation V7-V9)",
        ),
        "contraindications": (
            "Known aortic dissection",
            "Active hemorrhagic stroke",
            "Comfort-measures-only order in place",
        ),
        "time_critical": True,
        "max_time_minutes": 90,
        "required_resources": (
            "12-lead ECG machine",
            "Cath lab team (interventional cardiologist, cath lab nurse, tech)",
            "Aspirin 325 mg",
            "Heparin IV",
            "P2Y12 inhibitor",
            "Transport to cath lab",
        ),
        "condition_refs": ("STEMI",),
        "version": "2024.1",
        "active": True,
    },
    "PROTO-STROKE-001": {
        "protocol_id": "PROTO-STROKE-001",
        "name": "Stroke Alert — Door-to-Needle",
        "category": "stroke",
        "description": (
            "Acute ischemic stroke protocol. Target door-to-needle time < 60 "
            "minutes for IV tPA. Includes assessment for large vessel occlusion "
            "and thrombectomy candidacy."
        ),
        "steps": (
            {
                "name": "Stroke team activation",
                "description": "Activate stroke team and neurology",
                "time_limit_minutes": 5,
            },
            {
                "name": "Glucose check",
                "description": "Point-of-care glucose to exclude hypoglycemia",
                "time_limit_minutes": 10,
            },
            {
                "name": "CT head",
                "description": "Non-contrast CT head to exclude hemorrhage",
                "time_limit_minutes": 25,
            },
            {
                "name": "NIHSS assessment",
                "description": "Complete NIH Stroke Scale scoring",
                "time_limit_minutes": 25,
            },
            {
                "name": "Establish time of onset",
                "description": "Determine symptom onset or last known well time",
                "time_limit_minutes": 10,
            },
            {
                "name": "tPA administration",
                "description": "IV alteplase 0.9 mg/kg (max 90 mg), 10% bolus + 60 min infusion",
                "time_limit_minutes": 60,
            },
            {
                "name": "CTA head/neck",
                "description": "CT angiography to evaluate for large vessel occlusion",
                "time_limit_minutes": 45,
            },
        ),
        "activation_criteria": (
            "Acute onset focal neurological deficit",
            "NIHSS >= 4 or significant functional deficit",
            "Symptom onset within 4.5 hours (tPA) or 24 hours (thrombectomy)",
            "Last known well time established",
        ),
        "contraindications": (
            "Hemorrhagic stroke on CT",
            "Platelet count < 100,000",
            "INR > 1.7 or PT > 15 seconds",
            "Major surgery or trauma within 14 days",
            "Active internal bleeding",
            "Systolic BP > 185 mmHg or diastolic > 110 mmHg unresponsive to treatment",
        ),
        "time_critical": True,
        "max_time_minutes": 60,
        "required_resources": (
            "CT scanner (immediate availability)",
            "Stroke team (neurologist, CT tech, stroke nurse)",
            "tPA (alteplase)",
            "Point-of-care glucose meter",
            "NIH Stroke Scale form",
            "Neurointerventional suite (if LVO)",
        ),
        "condition_refs": ("STROKE_ISCHEMIC",),
        "version": "2024.1",
        "active": True,
    },
    "PROTO-TRAUMA-I-001": {
        "protocol_id": "PROTO-TRAUMA-I-001",
        "name": "Trauma Activation Level I",
        "category": "trauma",
        "description": (
            "Highest-level trauma activation for patients meeting physiologic "
            "or anatomic criteria for major trauma. Full trauma team response "
            "including attending trauma surgeon."
        ),
        "steps": (
            {
                "name": "Primary survey (ABCDE)",
                "description": "Airway, Breathing, Circulation, Disability, Exposure",
                "time_limit_minutes": 5,
            },
            {
                "name": "C-spine immobilization",
                "description": "Maintain cervical spine precautions until cleared",
                "time_limit_minutes": 2,
            },
            {
                "name": "IV access and blood draw",
                "description": "2 large-bore IVs, type & screen, CBC, BMP, coags, lactate",
                "time_limit_minutes": 5,
            },
            {
                "name": "Chest and pelvis X-rays",
                "description": "Portable AP chest and pelvis radiographs in trauma bay",
                "time_limit_minutes": 10,
            },
            {
                "name": "FAST exam",
                "description": "Focused Assessment with Sonography for Trauma",
                "time_limit_minutes": 10,
            },
            {
                "name": "Secondary survey",
                "description": "Head-to-toe examination, log roll, complete exposure",
                "time_limit_minutes": 20,
            },
            {
                "name": "CT pan-scan",
                "description": "CT head, C-spine, chest, abdomen/pelvis with IV contrast",
                "time_limit_minutes": 30,
            },
        ),
        "activation_criteria": (
            "GCS <= 8 with mechanism attributed to trauma",
            "Systolic BP < 90 mmHg",
            "Respiratory compromise requiring intubation",
            "Penetrating injury to head, neck, torso, or proximal extremity",
            "Gunshot wound to head, neck, torso",
            "Amputation proximal to wrist or ankle",
            "Flail chest",
            "Pelvic fracture with hemodynamic instability",
        ),
        "contraindications": (),
        "time_critical": True,
        "max_time_minutes": 30,
        "required_resources": (
            "Trauma bay",
            "Trauma surgeon (attending)",
            "Emergency physician",
            "Anesthesiologist",
            "Trauma nurse (2)",
            "Respiratory therapist",
            "Radiology tech",
            "Blood bank (uncrossmatched O-neg available)",
            "OR availability",
        ),
        "condition_refs": ("PNEUMOTHORAX_TENSION",),
        "version": "2024.1",
        "active": True,
    },
    "PROTO-TRAUMA-II-001": {
        "protocol_id": "PROTO-TRAUMA-II-001",
        "name": "Trauma Activation Level II",
        "category": "trauma",
        "description": (
            "Intermediate trauma activation for patients with significant "
            "mechanism but stable vital signs. Trauma surgeon notified but "
            "not required at bedside immediately."
        ),
        "steps": (
            {
                "name": "Primary survey (ABCDE)",
                "description": "Airway, Breathing, Circulation, Disability, Exposure",
                "time_limit_minutes": 5,
            },
            {
                "name": "IV access and labs",
                "description": "1-2 large-bore IVs, type & screen, CBC, BMP, coags",
                "time_limit_minutes": 10,
            },
            {
                "name": "FAST exam",
                "description": "Focused Assessment with Sonography for Trauma",
                "time_limit_minutes": 15,
            },
            {
                "name": "Imaging as indicated",
                "description": "Targeted imaging based on mechanism and exam findings",
                "time_limit_minutes": 45,
            },
            {
                "name": "Secondary survey",
                "description": "Head-to-toe examination, log roll",
                "time_limit_minutes": 30,
            },
            {
                "name": "Trauma surgery notification",
                "description": "Update trauma surgeon on findings and disposition plan",
                "time_limit_minutes": 60,
            },
        ),
        "activation_criteria": (
            "MVC with ejection, rollover, or fatality in same vehicle",
            "Pedestrian struck > 20 mph",
            "Fall > 20 feet (adult) or > 10 feet (child)",
            "Motorcycle crash > 20 mph",
            "Auto vs. bicycle",
            "GCS 9-13 with mechanism",
            "Two or more proximal long-bone fractures",
        ),
        "contraindications": (),
        "time_critical": True,
        "max_time_minutes": 60,
        "required_resources": (
            "Trauma bay",
            "Emergency physician",
            "Trauma nurse",
            "Radiology tech",
            "Trauma surgeon (notified, not immediate)",
        ),
        "condition_refs": (),
        "version": "2024.1",
        "active": True,
    },
    "PROTO-MTP-001": {
        "protocol_id": "PROTO-MTP-001",
        "name": "Massive Transfusion Protocol",
        "category": "transfusion",
        "description": (
            "Balanced resuscitation protocol for life-threatening hemorrhage. "
            "1:1:1 ratio of packed RBCs, FFP, and platelets. Activated when "
            "massive blood loss anticipated or ABC score >= 2."
        ),
        "steps": (
            {
                "name": "MTP activation",
                "description": "Call blood bank to activate MTP; send runner",
                "time_limit_minutes": 5,
            },
            {
                "name": "Cooler 1 release",
                "description": "6 units pRBC (O-neg), 6 units FFP, 1 apheresis platelets",
                "time_limit_minutes": 10,
            },
            {
                "name": "TXA administration",
                "description": "Tranexamic acid 1g IV over 10 min (if within 3 hours of injury)",
                "time_limit_minutes": 15,
            },
            {
                "name": "Labs and monitoring",
                "description": "Repeat CBC, coags, fibrinogen, ionized calcium, ABG every 30 min",
                "time_limit_minutes": 30,
            },
            {
                "name": "Cooler 2 release",
                "description": "6 units pRBC (type-specific), 6 units FFP, 1 apheresis platelets",
                "time_limit_minutes": 30,
            },
            {
                "name": "Calcium replacement",
                "description": "Calcium chloride 1g IV per 4 units pRBC (citrate toxicity prevention)",
                "time_limit_minutes": 30,
            },
            {
                "name": "Reassessment",
                "description": "Reassess need for continued MTP; deactivate when hemostasis achieved",
                "time_limit_minutes": 60,
            },
        ),
        "activation_criteria": (
            "ABC score >= 2 (penetrating mechanism, SBP <= 90, HR >= 120, positive FAST)",
            "Estimated blood loss > 1500 mL or ongoing hemorrhage",
            "Anticipated need for > 10 units pRBC in 24 hours",
            "Hemodynamic instability despite crystalloid resuscitation",
        ),
        "contraindications": (
            "Comfort-measures-only order in place",
            "Known refusal of blood products (document and honor; offer alternatives)",
        ),
        "time_critical": True,
        "max_time_minutes": None,
        "required_resources": (
            "Blood bank (MTP cooler protocol)",
            "O-negative pRBC (minimum 6 units immediate)",
            "Thawed FFP (6 units)",
            "Apheresis platelets",
            "Tranexamic acid",
            "Calcium chloride",
            "Rapid infuser / pressure bags",
            "Arterial line for continuous BP monitoring",
        ),
        "condition_refs": (),
        "version": "2024.1",
        "active": True,
    },
    "PROTO-AIRWAY-001": {
        "protocol_id": "PROTO-AIRWAY-001",
        "name": "Difficult Airway",
        "category": "airway",
        "description": (
            "Structured approach to predicted or encountered difficult airway. "
            "Includes preparation, backup plans, and surgical airway readiness. "
            "Based on ASA/ACS difficult airway algorithm."
        ),
        "steps": (
            {
                "name": "Airway assessment",
                "description": "LEMON assessment (Look, Evaluate 3-3-2, Mallampati, Obstruction, Neck mobility)",
                "time_limit_minutes": 2,
            },
            {
                "name": "Equipment preparation",
                "description": "Video laryngoscope, bougie, supraglottic airway, surgical kit at bedside",
                "time_limit_minutes": 3,
            },
            {
                "name": "Preoxygenation",
                "description": "High-flow nasal cannula + NRB mask, target SpO2 > 95% (apneic oxygenation during attempt)",
                "time_limit_minutes": 5,
            },
            {
                "name": "RSI medications",
                "description": "Push-dose vasopressor ready, induction agent + paralytic per patient factors",
                "time_limit_minutes": 5,
            },
            {
                "name": "First attempt (video laryngoscopy)",
                "description": "Direct or video laryngoscopy with bougie; limit attempt to 60 seconds",
                "time_limit_minutes": 2,
            },
            {
                "name": "Second attempt (adjust technique)",
                "description": "Reposition, different blade, external laryngeal manipulation; limit to 60 seconds",
                "time_limit_minutes": 3,
            },
            {
                "name": "Supraglottic airway",
                "description": "Place LMA or i-gel if intubation fails after 2 attempts",
                "time_limit_minutes": 2,
            },
            {
                "name": "Surgical airway",
                "description": "Cricothyrotomy if cannot intubate AND cannot oxygenate",
                "time_limit_minutes": 3,
            },
        ),
        "activation_criteria": (
            "Predicted difficult airway on assessment (LEMON score >= 3)",
            "Failed first intubation attempt",
            "Cannot-intubate-cannot-oxygenate (CICO) emergency",
            "Rapidly deteriorating airway (angioedema, expanding hematoma, burn)",
        ),
        "contraindications": (),
        "time_critical": True,
        "max_time_minutes": 10,
        "required_resources": (
            "Video laryngoscope (e.g., GlideScope, C-MAC)",
            "Bougie (endotracheal tube introducer)",
            "Supraglottic airway device (LMA or i-gel)",
            "Cricothyrotomy kit (scalpel, bougie, 6.0 cuffed ETT or Melker kit)",
            "Suction (Yankauer)",
            "Respiratory therapist",
            "Push-dose epinephrine",
            "End-tidal CO2 monitor",
        ),
        "condition_refs": ("PNEUMOTHORAX_TENSION",),
        "version": "2024.1",
        "active": True,
    },
    "PROTO-CODE-001": {
        "protocol_id": "PROTO-CODE-001",
        "name": "Cardiac Arrest / Code Blue",
        "category": "resuscitation",
        "description": (
            "ACLS-based cardiac arrest management protocol. Emphasis on "
            "high-quality CPR, early defibrillation, and reversible cause "
            "identification (H's and T's)."
        ),
        "steps": (
            {
                "name": "Recognize arrest and call code",
                "description": "Confirm pulselessness, activate code team, start timer",
                "time_limit_minutes": 1,
            },
            {
                "name": "Begin high-quality CPR",
                "description": "Rate 100-120/min, depth 2-2.4 inches, full recoil, minimize interruptions",
                "time_limit_minutes": 1,
            },
            {
                "name": "Rhythm check",
                "description": "Pause CPR briefly for rhythm analysis (shockable vs non-shockable)",
                "time_limit_minutes": 2,
            },
            {
                "name": "Defibrillation (if shockable)",
                "description": "Biphasic 200J for VF/pVT, resume CPR immediately after shock",
                "time_limit_minutes": 2,
            },
            {
                "name": "Epinephrine",
                "description": "Epinephrine 1 mg IV/IO every 3-5 minutes",
                "time_limit_minutes": 5,
            },
            {
                "name": "Advanced airway",
                "description": "Endotracheal intubation or supraglottic airway; waveform capnography",
                "time_limit_minutes": 10,
            },
            {
                "name": "Identify reversible causes",
                "description": "H's: Hypovolemia, Hypoxia, Hydrogen ion, Hypo/hyperK, Hypothermia. "
                "T's: Tension pneumothorax, Tamponade, Toxins, Thrombosis (PE/MI)",
                "time_limit_minutes": 10,
            },
            {
                "name": "Antiarrhythmics (if refractory VF/pVT)",
                "description": "Amiodarone 300 mg IV first dose, 150 mg IV second dose",
                "time_limit_minutes": 10,
            },
            {
                "name": "Post-ROSC care",
                "description": "12-lead ECG, targeted temperature management, hemodynamic support",
                "time_limit_minutes": 30,
            },
        ),
        "activation_criteria": (
            "Pulseless, unresponsive patient",
            "Witnessed cardiac arrest",
            "VF/pVT on monitor",
            "PEA or asystole",
        ),
        "contraindications": (
            "Valid DNR/DNAR order (verify immediately)",
            "Obvious signs of irreversible death (rigor mortis, dependent lividity, decomposition)",
        ),
        "time_critical": True,
        "max_time_minutes": None,
        "required_resources": (
            "Defibrillator/monitor",
            "CPR backboard",
            "Code cart (epinephrine, amiodarone, atropine, calcium, bicarb)",
            "Advanced airway equipment",
            "Waveform capnography",
            "IO drill (if IV access difficult)",
            "Code team (physician, 2 nurses, respiratory therapist, pharmacist, recorder)",
        ),
        "condition_refs": ("STEMI",),
        "version": "2024.1",
        "active": True,
    },
}


def load_protocols(
    protocol_data: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Protocol]:
    """Load protocol entities.

    When protocol_data is provided, converts all entries. Otherwise falls back
    to the bundled subset.

    Args:
        protocol_data: Optional dict of protocol_id -> protocol data.

    Returns:
        Dict of protocol_id -> Protocol.
    """
    now = datetime.now(timezone.utc)
    result: dict[str, Protocol] = {}

    source = protocol_data if protocol_data is not None else _BUNDLED_PROTOCOLS

    for pid, data in source.items():
        proto = Protocol(
            id=f"PG-{pid}",
            entity_type=EntityType.PROTOCOL,
            created_at=now,
            updated_at=now,
            protocol_id=data.get("protocol_id", pid),
            name=data.get("name", ""),
            category=data.get("category", ""),
            description=data.get("description", ""),
            steps=tuple(data.get("steps", ())),
            activation_criteria=tuple(data.get("activation_criteria", ())),
            contraindications=tuple(data.get("contraindications", ())),
            time_critical=data.get("time_critical", False),
            max_time_minutes=data.get("max_time_minutes"),
            required_resources=tuple(data.get("required_resources", ())),
            condition_refs=tuple(data.get("condition_refs", ())),
            version=data.get("version", ""),
            active=data.get("active", True),
        )
        result[pid] = proto

    return result


def generate_protocol(rng: random.Random) -> Protocol:
    """Generate a deterministic protocol entity by selecting from bundled protocols.

    Args:
        rng: Seeded Random instance for deterministic generation.

    Returns:
        A frozen Protocol instance.
    """
    pid = rng.choice(list(_BUNDLED_PROTOCOLS.keys()))
    data = _BUNDLED_PROTOCOLS[pid]

    # Generate a unique instance ID
    instance_id = f"PG-{uuid.UUID(int=rng.getrandbits(128)).hex[:8].upper()}"

    now = datetime.now(timezone.utc)
    return Protocol(
        id=instance_id,
        entity_type=EntityType.PROTOCOL,
        created_at=now,
        updated_at=now,
        protocol_id=data["protocol_id"],
        name=data["name"],
        category=data["category"],
        description=data["description"],
        steps=tuple(data["steps"]),
        activation_criteria=tuple(data["activation_criteria"]),
        contraindications=tuple(data["contraindications"]),
        time_critical=data["time_critical"],
        max_time_minutes=data["max_time_minutes"],
        required_resources=tuple(data["required_resources"]),
        condition_refs=tuple(data["condition_refs"]),
        version=data["version"],
        active=data["active"],
    )


def protocol_to_fhir(protocol: Protocol) -> dict:
    """Convert a Protocol entity to a FHIR R4 PlanDefinition resource.

    Args:
        protocol: The Protocol entity to convert.

    Returns:
        A dict representing a FHIR R4 PlanDefinition resource.
    """
    actions = []
    for i, step in enumerate(protocol.steps):
        action: dict[str, Any] = {
            "title": step.get("name", f"Step {i + 1}"),
            "description": step.get("description", ""),
        }
        time_limit = step.get("time_limit_minutes")
        if time_limit is not None:
            action["timingDuration"] = {
                "value": time_limit,
                "unit": "min",
                "system": "http://unitsofmeasure.org",
                "code": "min",
            }
        actions.append(action)

    resource: dict[str, Any] = {
        "resourceType": "PlanDefinition",
        "id": protocol.id,
        "identifier": [
            {
                "system": "urn:healthcraft:protocol",
                "value": protocol.protocol_id,
            }
        ],
        "version": protocol.version,
        "name": protocol.protocol_id,
        "title": protocol.name,
        "status": "active" if protocol.active else "retired",
        "description": protocol.description,
        "type": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/plan-definition-type",
                    "code": "clinical-protocol",
                    "display": "Clinical Protocol",
                }
            ]
        },
        "action": actions,
    }

    if protocol.condition_refs:
        resource["relatedArtifact"] = [
            {
                "type": "derived-from",
                "display": ref,
            }
            for ref in protocol.condition_refs
        ]

    return resource
