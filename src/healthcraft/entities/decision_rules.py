"""Clinical decision rule entities for the HEALTHCRAFT simulation."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from healthcraft.entities.base import Entity, EntityType


@dataclass(frozen=True)
class DecisionRule(Entity):
    """Immutable clinical decision rule entity.

    Represents a validated scoring instrument used in emergency medicine
    to risk-stratify patients and guide disposition decisions.
    """

    rule_id: str = ""
    name: str = ""
    full_name: str = ""
    category: str = ""  # cardiac, pulmonary, neuro, trauma, etc.
    description: str = ""
    variables: tuple[dict[str, Any], ...] = ()
    score_ranges: tuple[dict[str, Any], ...] = ()
    condition_refs: tuple[str, ...] = ()  # ClinicalKnowledge condition IDs
    evidence_level: str = ""  # validated, derived, expert_consensus
    url: str = ""


# --- Bundled decision rules ---

_BUNDLED_RULES: dict[str, dict[str, Any]] = {
    "RULE-HEART-001": {
        "rule_id": "RULE-HEART-001",
        "name": "HEART Score",
        "full_name": "History, ECG, Age, Risk factors, Troponin Score",
        "category": "cardiac",
        "description": (
            "Risk stratification tool for chest pain patients presenting to the ED. "
            "Identifies patients at low, moderate, and high risk for major adverse "
            "cardiac events (MACE) at 6 weeks."
        ),
        "variables": (
            {
                "name": "History",
                "description": "Degree of suspicion based on history",
                "min_value": 0,
                "max_value": 2,
                "scoring": {
                    0: "Slightly suspicious",
                    1: "Moderately suspicious",
                    2: "Highly suspicious",
                },
            },
            {
                "name": "ECG",
                "description": "ECG interpretation",
                "min_value": 0,
                "max_value": 2,
                "scoring": {
                    0: "Normal",
                    1: "Non-specific repolarization disturbance",
                    2: "Significant ST deviation",
                },
            },
            {
                "name": "Age",
                "description": "Patient age",
                "min_value": 0,
                "max_value": 2,
                "scoring": {
                    0: "< 45 years",
                    1: "45-64 years",
                    2: ">= 65 years",
                },
            },
            {
                "name": "Risk factors",
                "description": "Number of risk factors present",
                "min_value": 0,
                "max_value": 2,
                "scoring": {
                    0: "No known risk factors",
                    1: "1-2 risk factors",
                    2: ">= 3 risk factors or history of atherosclerotic disease",
                },
            },
            {
                "name": "Troponin",
                "description": "Initial troponin level",
                "min_value": 0,
                "max_value": 2,
                "scoring": {
                    0: "<= normal limit",
                    1: "1-3x normal limit",
                    2: "> 3x normal limit",
                },
            },
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 3,
                "risk_level": "low",
                "recommendation": "Discharge with outpatient follow-up; 1.7% MACE risk",
            },
            {
                "min_score": 4,
                "max_score": 6,
                "risk_level": "moderate",
                "recommendation": "Observation and serial troponins; 12% MACE risk",
            },
            {
                "min_score": 7,
                "max_score": 10,
                "risk_level": "high",
                "recommendation": "Admit for early invasive strategy; 65% MACE risk",
            },
        ),
        "condition_refs": ("STEMI", "NSTEMI", "UNSTABLE_ANGINA"),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1752/heart-score-major-cardiac-events",
    },
    "RULE-WELLS-PE-001": {
        "rule_id": "RULE-WELLS-PE-001",
        "name": "Wells Criteria for PE",
        "full_name": "Wells Clinical Prediction Rule for Pulmonary Embolism",
        "category": "pulmonary",
        "description": (
            "Clinical prediction rule for estimating the pre-test probability of "
            "pulmonary embolism. Guides D-dimer testing and CT pulmonary angiography."
        ),
        "variables": (
            {
                "name": "Clinical signs/symptoms of DVT",
                "description": "Leg swelling, pain with palpation of deep veins",
                "min_value": 0,
                "max_value": 3,
                "scoring": {0: "Absent", 3: "Present"},
            },
            {
                "name": "PE is #1 diagnosis or equally likely",
                "description": "Clinical gestalt",
                "min_value": 0,
                "max_value": 3,
                "scoring": {0: "No", 3: "Yes"},
            },
            {
                "name": "Heart rate > 100",
                "description": "Tachycardia",
                "min_value": 0,
                "max_value": 1.5,
                "scoring": {0: "No", 1.5: "Yes"},
            },
            {
                "name": "Immobilization or surgery in past 4 weeks",
                "description": "Recent immobilization >= 3 days or surgery within 4 weeks",
                "min_value": 0,
                "max_value": 1.5,
                "scoring": {0: "No", 1.5: "Yes"},
            },
            {
                "name": "Previous PE or DVT",
                "description": "Prior venous thromboembolism",
                "min_value": 0,
                "max_value": 1.5,
                "scoring": {0: "No", 1.5: "Yes"},
            },
            {
                "name": "Hemoptysis",
                "description": "Coughing up blood",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Malignancy",
                "description": "Active cancer (treatment within 6 months or palliative)",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 1,
                "risk_level": "low",
                "recommendation": "D-dimer; if negative, PE excluded (1.3% prevalence)",
            },
            {
                "min_score": 2,
                "max_score": 6,
                "risk_level": "moderate",
                "recommendation": "D-dimer; if positive, CTPA (16.2% prevalence)",
            },
            {
                "min_score": 7,
                "max_score": 12.5,
                "risk_level": "high",
                "recommendation": "CTPA indicated (37.5% prevalence)",
            },
        ),
        "condition_refs": ("PULMONARY_EMBOLISM",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/115/wells-criteria-pulmonary-embolism",
    },
    "RULE-WELLS-DVT-001": {
        "rule_id": "RULE-WELLS-DVT-001",
        "name": "Wells Criteria for DVT",
        "full_name": "Wells Clinical Prediction Rule for Deep Vein Thrombosis",
        "category": "cardiac",
        "description": (
            "Clinical prediction rule for estimating the pre-test probability of "
            "deep vein thrombosis. Guides D-dimer testing and ultrasound imaging."
        ),
        "variables": (
            {
                "name": "Active cancer",
                "description": "Treatment or palliation within 6 months",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Paralysis, paresis, or recent cast",
                "description": "Lower extremity immobilization",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Bedridden > 3 days or major surgery within 12 weeks",
                "description": "Recent immobilization or surgery",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Localized tenderness along deep venous system",
                "description": "Tenderness along distribution of deep veins",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Entire leg swollen",
                "description": "Diffuse leg swelling",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Calf swelling > 3 cm compared to other leg",
                "description": "Measured 10 cm below tibial tuberosity",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Pitting edema",
                "description": "Greater in symptomatic leg",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Collateral superficial veins",
                "description": "Non-varicose collateral veins",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Previously documented DVT",
                "description": "Prior confirmed DVT",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Alternative diagnosis at least as likely",
                "description": "Alternative explanation for symptoms",
                "min_value": -2,
                "max_value": 0,
                "scoring": {0: "No", -2: "Yes"},
            },
        ),
        "score_ranges": (
            {
                "min_score": -2,
                "max_score": 0,
                "risk_level": "low",
                "recommendation": "D-dimer; if negative, DVT excluded (5% prevalence)",
            },
            {
                "min_score": 1,
                "max_score": 2,
                "risk_level": "moderate",
                "recommendation": "D-dimer; if positive, ultrasound (17% prevalence)",
            },
            {
                "min_score": 3,
                "max_score": 8,
                "risk_level": "high",
                "recommendation": "Ultrasound indicated (53% prevalence)",
            },
        ),
        "condition_refs": ("DVT",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/362/wells-criteria-dvt",
    },
    "RULE-OTTAWA-ANKLE-001": {
        "rule_id": "RULE-OTTAWA-ANKLE-001",
        "name": "Ottawa Ankle Rules",
        "full_name": "Ottawa Ankle Rules for Radiography",
        "category": "trauma",
        "description": (
            "Clinical decision rule to determine the need for ankle and foot "
            "radiography in patients with acute ankle injuries. Sensitivity approaches "
            "100% for clinically significant fractures."
        ),
        "variables": (
            {
                "name": "Bone tenderness at posterior edge of distal 6 cm of lateral malleolus",
                "description": "Palpation of lateral malleolus",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Bone tenderness at posterior edge of distal 6 cm of medial malleolus",
                "description": "Palpation of medial malleolus",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Bone tenderness at base of 5th metatarsal",
                "description": "Palpation of midfoot (foot series)",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Bone tenderness at navicular",
                "description": "Palpation of midfoot (foot series)",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Inability to bear weight for 4 steps",
                "description": "Both immediately and in the ED",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 0,
                "risk_level": "low",
                "recommendation": "No radiograph needed; fracture extremely unlikely",
            },
            {
                "min_score": 1,
                "max_score": 5,
                "risk_level": "high",
                "recommendation": "Obtain ankle and/or foot radiographs as indicated by tender zones",
            },
        ),
        "condition_refs": ("ANKLE_FRACTURE", "FOOT_FRACTURE"),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1670/ottawa-ankle-rule",
    },
    "RULE-OTTAWA-KNEE-001": {
        "rule_id": "RULE-OTTAWA-KNEE-001",
        "name": "Ottawa Knee Rules",
        "full_name": "Ottawa Knee Rules for Radiography",
        "category": "trauma",
        "description": (
            "Clinical decision rule to determine the need for knee radiography "
            "in patients with acute knee injuries. Reduces unnecessary imaging by "
            "identifying patients with very low fracture risk."
        ),
        "variables": (
            {
                "name": "Age >= 55 years",
                "description": "Patient age 55 or older",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Isolated tenderness of patella",
                "description": "No other bony knee tenderness",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Tenderness at head of fibula",
                "description": "Palpation of fibular head",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Inability to flex to 90 degrees",
                "description": "Cannot achieve 90 degrees of knee flexion",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Inability to bear weight for 4 steps",
                "description": "Both immediately and in the ED",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 0,
                "risk_level": "low",
                "recommendation": "No radiograph needed; fracture very unlikely",
            },
            {
                "min_score": 1,
                "max_score": 5,
                "risk_level": "high",
                "recommendation": "Obtain knee radiographs",
            },
        ),
        "condition_refs": ("KNEE_FRACTURE",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1054/ottawa-knee-rule",
    },
    "RULE-PECARN-001": {
        "rule_id": "RULE-PECARN-001",
        "name": "PECARN Head CT",
        "full_name": "PECARN Pediatric Head Injury/Trauma Algorithm",
        "category": "neuro",
        "description": (
            "Clinical decision rule for identifying children at very low risk of "
            "clinically important traumatic brain injuries after head trauma, "
            "reducing unnecessary CT scans. Validated for age < 18 years."
        ),
        "variables": (
            {
                "name": "GCS < 15",
                "description": "Altered mental status (GCS less than 15)",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Altered mental status",
                "description": "Agitation, somnolence, repetitive questioning, slow response",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Palpable skull fracture (< 2 yr) or signs of basilar skull fracture (>= 2 yr)",
                "description": "Age-dependent finding",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Loss of consciousness",
                "description": "Any duration of LOC",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Vomiting",
                "description": "Any post-traumatic vomiting",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Severe mechanism of injury",
                "description": "MVC with ejection/rollover/fatality, pedestrian/cyclist vs vehicle, fall > 5 ft (< 2 yr) or > 10 ft (>= 2 yr), head struck by high-impact object",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Severe or worsening headache",
                "description": "For children >= 2 years old",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Acting abnormally per parent",
                "description": "Parent reports child not acting normally",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 0,
                "risk_level": "very_low",
                "recommendation": "CT not recommended; ciTBI risk < 0.02%",
            },
            {
                "min_score": 1,
                "max_score": 2,
                "risk_level": "intermediate",
                "recommendation": "Observation vs CT based on clinical factors, experience, worsening symptoms",
            },
            {
                "min_score": 3,
                "max_score": 8,
                "risk_level": "high",
                "recommendation": "CT recommended; significant risk of ciTBI (4.4%)",
            },
        ),
        "condition_refs": ("HEAD_INJURY_PEDIATRIC", "TRAUMATIC_BRAIN_INJURY"),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/589/pecarn-pediatric-head-injury-trauma-algorithm",
    },
    "RULE-CCSR-001": {
        "rule_id": "RULE-CCSR-001",
        "name": "Canadian C-Spine Rule",
        "full_name": "Canadian C-Spine Rule for Cervical Spine Imaging",
        "category": "trauma",
        "description": (
            "Clinical decision rule to determine the need for cervical spine "
            "imaging in alert and stable trauma patients. More sensitive and "
            "specific than NEXUS criteria."
        ),
        "variables": (
            {
                "name": "Age >= 65 years",
                "description": "High-risk factor: age",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes — high risk, image"},
            },
            {
                "name": "Dangerous mechanism",
                "description": "Fall >= 1 m / 5 stairs, axial load (diving), MVC high speed/rollover/ejection, motorized recreational vehicle, bicycle collision",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes — high risk, image"},
            },
            {
                "name": "Paresthesias in extremities",
                "description": "Numbness or tingling",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes — high risk, image"},
            },
            {
                "name": "Simple rear-end MVC",
                "description": "Low-risk factor allowing range-of-motion assessment",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "Not applicable", 1: "Low-risk factor present"},
            },
            {
                "name": "Sitting position in ED",
                "description": "Low-risk factor allowing range-of-motion assessment",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "Not applicable", 1: "Low-risk factor present"},
            },
            {
                "name": "Ambulatory at any time",
                "description": "Low-risk factor allowing range-of-motion assessment",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "Not applicable", 1: "Low-risk factor present"},
            },
            {
                "name": "Delayed onset neck pain",
                "description": "Low-risk factor allowing range-of-motion assessment",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "Not applicable", 1: "Low-risk factor present"},
            },
            {
                "name": "Able to actively rotate neck 45 degrees left and right",
                "description": "Range of motion assessment (only if low-risk factors present)",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "Unable — image", 1: "Able — no imaging needed"},
            },
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 0,
                "risk_level": "low",
                "recommendation": "No imaging required if low-risk factor present AND able to rotate neck",
            },
            {
                "min_score": 1,
                "max_score": 8,
                "risk_level": "high",
                "recommendation": "Cervical spine imaging indicated if any high-risk factor or unable to rotate",
            },
        ),
        "condition_refs": ("CERVICAL_SPINE_FRACTURE", "SPINAL_CORD_INJURY"),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/696/canadian-c-spine-rule",
    },
    "RULE-QSOFA-001": {
        "rule_id": "RULE-QSOFA-001",
        "name": "qSOFA",
        "full_name": "Quick Sequential Organ Failure Assessment",
        "category": "infectious",
        "description": (
            "Bedside screening tool for identifying patients with suspected "
            "infection who are at risk for sepsis. Uses only clinical findings, "
            "no laboratory data required. Replaces SIRS for sepsis screening."
        ),
        "variables": (
            {
                "name": "Respiratory rate >= 22",
                "description": "Tachypnea",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Altered mentation",
                "description": "GCS < 15",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Systolic blood pressure <= 100 mmHg",
                "description": "Hypotension",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 1,
                "risk_level": "low",
                "recommendation": "Low risk; continue monitoring. Not outside ICU mortality > 3%",
            },
            {
                "min_score": 2,
                "max_score": 3,
                "risk_level": "high",
                "recommendation": "High risk of poor outcome; assess for organ dysfunction, consider ICU. Mortality 3-14x higher",
            },
        ),
        "condition_refs": ("SEPSIS", "SEPTIC_SHOCK"),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/2654/qsofa-quick-sofa-score-sepsis",
    },
    "RULE-OTTAWA-SAH-001": {
        "rule_id": "RULE-OTTAWA-SAH-001",
        "name": "Ottawa SAH Rule",
        "full_name": "Ottawa Subarachnoid Hemorrhage Rule",
        "category": "neuro",
        "description": (
            "Clinical decision rule for ruling out subarachnoid hemorrhage in "
            "ED patients with acute non-traumatic headache who are neurologically "
            "intact. 100% sensitivity for SAH when all criteria absent."
        ),
        "variables": (
            {
                "name": "Age >= 40 years",
                "description": "Patient age 40 or older",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Neck pain or stiffness",
                "description": "Meningismus on exam",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Witnessed loss of consciousness",
                "description": "Syncope at headache onset",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Onset during exertion",
                "description": "Headache began during physical activity",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Thunderclap headache",
                "description": "Instantly peaking headache",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Limited neck flexion on examination",
                "description": "Unable to touch chin to chest",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 0,
                "risk_level": "low",
                "recommendation": "SAH can be ruled out; 100% sensitivity",
            },
            {
                "min_score": 1,
                "max_score": 6,
                "risk_level": "high",
                "recommendation": "CT head required; if negative, LP or CTA. SAH cannot be excluded",
            },
        ),
        "condition_refs": ("SUBARACHNOID_HEMORRHAGE",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/3800/ottawa-subarachnoid-hemorrhage-rule",
    },
    "RULE-CURB65-001": {
        "rule_id": "RULE-CURB65-001",
        "name": "CURB-65",
        "full_name": "CURB-65 Severity Score for Community-Acquired Pneumonia",
        "category": "pulmonary",
        "description": (
            "Clinical prediction rule for estimating mortality risk in patients "
            "with community-acquired pneumonia. Guides disposition decisions: "
            "outpatient vs admission vs ICU."
        ),
        "variables": (
            {
                "name": "Confusion",
                "description": "New mental confusion (AMT <= 8 or new disorientation)",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "BUN > 19 mg/dL (7 mmol/L)",
                "description": "Elevated blood urea nitrogen",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Respiratory rate >= 30",
                "description": "Tachypnea",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Blood pressure (SBP < 90 or DBP <= 60)",
                "description": "Hypotension",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Age >= 65 years",
                "description": "Patient age 65 or older",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 1,
                "risk_level": "low",
                "recommendation": "Outpatient treatment; 30-day mortality < 3%",
            },
            {
                "min_score": 2,
                "max_score": 2,
                "risk_level": "moderate",
                "recommendation": "Consider short inpatient stay or supervised outpatient; mortality 9%",
            },
            {
                "min_score": 3,
                "max_score": 5,
                "risk_level": "high",
                "recommendation": "Hospitalize; consider ICU if score 4-5. Mortality 15-40%",
            },
        ),
        "condition_refs": ("PNEUMONIA_CAP",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/324/curb-65-score-pneumonia-severity",
    },
    "RULE-NEXUS-001": {
        "rule_id": "RULE-NEXUS-001",
        "name": "NEXUS C-Spine",
        "full_name": "National Emergency X-Radiography Utilization Study Criteria for C-Spine",
        "category": "trauma",
        "description": (
            "Clinical decision rule to identify trauma patients who do not require "
            "cervical spine imaging. All five low-risk criteria must be met to "
            "clear the cervical spine clinically."
        ),
        "variables": (
            {
                "name": "No posterior midline cervical spine tenderness",
                "description": "Absence of midline tenderness on palpation",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "Absent (low risk)", 1: "Present (image)"},
            },
            {
                "name": "No focal neurologic deficit",
                "description": "Normal neurologic examination",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "Absent (low risk)", 1: "Present (image)"},
            },
            {
                "name": "Normal alertness",
                "description": "GCS 15 without intoxication",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "Alert (low risk)", 1: "Not alert (image)"},
            },
            {
                "name": "No intoxication",
                "description": "Absence of drug or alcohol intoxication",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "Not intoxicated (low risk)", 1: "Intoxicated (image)"},
            },
            {
                "name": "No painful distracting injury",
                "description": "Absence of significant distracting injury",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "Absent (low risk)", 1: "Present (image)"},
            },
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 0,
                "risk_level": "low",
                "recommendation": "C-spine can be cleared clinically; no imaging needed (99.6% sensitivity)",
            },
            {
                "min_score": 1,
                "max_score": 5,
                "risk_level": "high",
                "recommendation": "Cervical spine imaging indicated",
            },
        ),
        "condition_refs": ("CERVICAL_SPINE_FRACTURE", "SPINAL_CORD_INJURY"),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/696/nexus-criteria-c-spine-imaging",
    },
    "RULE-ALVARADO-001": {
        "rule_id": "RULE-ALVARADO-001",
        "name": "Alvarado Score",
        "full_name": "Alvarado Score for Acute Appendicitis (MANTRELS)",
        "category": "gastrointestinal",
        "description": (
            "Clinical prediction rule for the likelihood of acute appendicitis. "
            "Uses the MANTRELS mnemonic: Migration, Anorexia, Nausea, Tenderness "
            "in RLQ, Rebound, Elevation of temperature, Leukocytosis, Shift to left."
        ),
        "variables": (
            {
                "name": "Migration of pain to RLQ",
                "description": "Pain migrating from periumbilical to right lower quadrant",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Anorexia",
                "description": "Loss of appetite",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Nausea or vomiting",
                "description": "GI symptoms",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "RLQ tenderness",
                "description": "Tenderness in the right lower quadrant",
                "min_value": 0,
                "max_value": 2,
                "scoring": {0: "No", 2: "Yes"},
            },
            {
                "name": "Rebound pain",
                "description": "Pain on release of pressure",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Elevated temperature (> 37.3 C / 99.1 F)",
                "description": "Low-grade fever",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
            {
                "name": "Leukocytosis (WBC > 10,000)",
                "description": "Elevated white blood cell count",
                "min_value": 0,
                "max_value": 2,
                "scoring": {0: "No", 2: "Yes"},
            },
            {
                "name": "Left shift (neutrophils > 75%)",
                "description": "Neutrophilic predominance",
                "min_value": 0,
                "max_value": 1,
                "scoring": {0: "No", 1: "Yes"},
            },
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 4,
                "risk_level": "low",
                "recommendation": "Appendicitis unlikely; consider discharge with follow-up",
            },
            {
                "min_score": 5,
                "max_score": 6,
                "risk_level": "moderate",
                "recommendation": "Equivocal; CT abdomen/pelvis recommended",
            },
            {
                "min_score": 7,
                "max_score": 10,
                "risk_level": "high",
                "recommendation": "Appendicitis probable; surgical consultation",
            },
        ),
        "condition_refs": ("APPENDICITIS",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/617/alvarado-score-acute-appendicitis",
    },
}


def load_decision_rules(
    rng: random.Random | None = None,
    external_rules: dict[str, dict[str, Any]] | None = None,
) -> dict[str, DecisionRule]:
    """Load clinical decision rule entities.

    When external_rules (e.g. from OpenEM) are provided, converts all rules.
    Otherwise falls back to the bundled set. An optional rng is accepted for
    deterministic shuffling or subsetting in downstream callers but does not
    affect the returned data — decision rules are reference entities.

    Args:
        rng: Optional seeded Random instance (reserved for future sampling).
        external_rules: Optional dict of rule_id -> rule data from an
            external source such as OpenEM.

    Returns:
        Dict of rule_id -> DecisionRule.
    """
    now = datetime.now(timezone.utc)
    result: dict[str, DecisionRule] = {}

    source = external_rules if external_rules is not None else _BUNDLED_RULES

    for rid, data in source.items():
        rule = DecisionRule(
            id=f"DR-{rid}",
            entity_type=EntityType.DECISION_RULE,
            created_at=now,
            updated_at=now,
            rule_id=data.get("rule_id", rid),
            name=data.get("name", ""),
            full_name=data.get("full_name", ""),
            category=data.get("category", ""),
            description=data.get("description", ""),
            variables=tuple(data.get("variables", ())),
            score_ranges=tuple(data.get("score_ranges", ())),
            condition_refs=tuple(data.get("condition_refs", ())),
            evidence_level=data.get("evidence_level", ""),
            url=data.get("url", ""),
        )
        result[rid] = rule

    return result
