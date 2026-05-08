"""Extended ED decision-rule library.

Bundled in addition to the original 12 in ``decision_rules.py``. Each rule
follows the same ``(variables, score_ranges)`` shape consumed by
``run_decision_rule`` so no extra plumbing is needed — the loader merges
both dicts.

Inclusion criteria: rule appears on every contemporary ED reference
(Tintinalli, Rosen, MDCalc top-10), has additive scoring, and is widely
cited in published validation cohorts. Each entry includes the canonical
URL pointing to MDCalc or the original publication for provenance.

References to validation cohorts and publication years are kept short;
the exhaustive citation lives in MODEL_CARD.md when added.
"""

from __future__ import annotations

from typing import Any

EXTENDED_RULES: dict[str, dict[str, Any]] = {
    # ----------------------------------------------------------------
    # Pulmonary embolism (low-pretest rule-out)
    # ----------------------------------------------------------------
    "RULE-PERC-001": {
        "rule_id": "RULE-PERC-001",
        "name": "PERC Rule",
        "full_name": "Pulmonary Embolism Rule-Out Criteria",
        "category": "pulmonary",
        "description": (
            "Rules out PE without further workup if all 8 criteria absent and "
            "clinical gestalt low (<15%). Score = number of criteria present; "
            "any positive criterion fails the rule."
        ),
        "variables": tuple(
            {"name": name, "min_value": 0, "max_value": 1}
            for name in (
                "Age >= 50",
                "Heart rate >= 100",
                "SpO2 < 95% on room air",
                "Unilateral leg swelling",
                "Hemoptysis",
                "Recent surgery or trauma",
                "Prior DVT or PE",
                "Hormone use (estrogen)",
            )
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 0,
                "risk_level": "low",
                "recommendation": "PERC negative; further PE workup not indicated.",
            },
            {
                "min_score": 1,
                "max_score": 8,
                "risk_level": "high",
                "recommendation": "PERC positive; proceed to D-dimer or CTPA.",
            },
        ),
        "condition_refs": ("PE",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/347/perc-rule-pulmonary-embolism",
    },
    # ----------------------------------------------------------------
    # TIA / stroke risk
    # ----------------------------------------------------------------
    "RULE-ABCD2-001": {
        "rule_id": "RULE-ABCD2-001",
        "name": "ABCD2 Score",
        "full_name": "ABCD2 Score for Transient Ischemic Attack",
        "category": "neuro",
        "description": ("7-day stroke risk after TIA. Score 0-3 low, 4-5 moderate, 6-7 high."),
        "variables": (
            {"name": "Age >= 60", "min_value": 0, "max_value": 1},
            {"name": "Blood pressure >= 140/90", "min_value": 0, "max_value": 1},
            {
                "name": "Clinical features",
                "description": "Unilateral weakness=2, speech disturbance without weakness=1",
                "min_value": 0,
                "max_value": 2,
            },
            {
                "name": "Duration",
                "description": ">=60 min=2; 10-59 min=1; <10 min=0",
                "min_value": 0,
                "max_value": 2,
            },
            {"name": "Diabetes", "min_value": 0, "max_value": 1},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 3,
                "risk_level": "low",
                "recommendation": "1.0% 2-day stroke risk; outpatient workup acceptable.",
            },
            {
                "min_score": 4,
                "max_score": 5,
                "risk_level": "moderate",
                "recommendation": "4.1% 2-day stroke risk; admit or expedited workup.",
            },
            {
                "min_score": 6,
                "max_score": 7,
                "risk_level": "high",
                "recommendation": "8.1% 2-day stroke risk; admit, neurology consult.",
            },
        ),
        "condition_refs": ("TIA", "STROKE"),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/357/abcd2-score-tia",
    },
    # ----------------------------------------------------------------
    # Early warning scores
    # ----------------------------------------------------------------
    "RULE-NEWS2-001": {
        "rule_id": "RULE-NEWS2-001",
        "name": "NEWS2",
        "full_name": "National Early Warning Score 2",
        "category": "general",
        "description": (
            "RCP UK early-warning score for clinical deterioration. "
            "Aggregate score 0-20+; 0-4 low, 5-6 medium, 7+ high."
        ),
        "variables": (
            {"name": "Respiratory rate", "min_value": 0, "max_value": 3},
            {"name": "SpO2 scale 1", "min_value": 0, "max_value": 3},
            {"name": "Supplemental O2", "min_value": 0, "max_value": 2},
            {"name": "Temperature", "min_value": 0, "max_value": 3},
            {"name": "Systolic blood pressure", "min_value": 0, "max_value": 3},
            {"name": "Heart rate", "min_value": 0, "max_value": 3},
            {"name": "Consciousness", "min_value": 0, "max_value": 3},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 4,
                "risk_level": "low",
                "recommendation": "Routine monitoring.",
            },
            {
                "min_score": 5,
                "max_score": 6,
                "risk_level": "moderate",
                "recommendation": "Urgent ward review; increase monitoring frequency.",
            },
            {
                "min_score": 7,
                "max_score": 20,
                "risk_level": "high",
                "recommendation": "Emergency assessment by critical care team.",
            },
        ),
        "condition_refs": (),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/10083/national-early-warning-score-news-2",
    },
    "RULE-MEWS-001": {
        "rule_id": "RULE-MEWS-001",
        "name": "MEWS",
        "full_name": "Modified Early Warning Score",
        "category": "general",
        "description": "Original UK MEWS for ward-level deterioration screen.",
        "variables": (
            {"name": "Systolic blood pressure", "min_value": 0, "max_value": 3},
            {"name": "Heart rate", "min_value": 0, "max_value": 3},
            {"name": "Respiratory rate", "min_value": 0, "max_value": 3},
            {"name": "Temperature", "min_value": 0, "max_value": 2},
            {"name": "AVPU level of consciousness", "min_value": 0, "max_value": 3},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 2,
                "risk_level": "low",
                "recommendation": "Routine ward observation.",
            },
            {
                "min_score": 3,
                "max_score": 4,
                "risk_level": "moderate",
                "recommendation": "Increase observations; nurse-led review.",
            },
            {
                "min_score": 5,
                "max_score": 14,
                "risk_level": "high",
                "recommendation": "Urgent medical review; consider escalation.",
            },
        ),
        "condition_refs": (),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1875/modified-early-warning-score-mews-clinical-deterioration",
    },
    # ----------------------------------------------------------------
    # Syncope
    # ----------------------------------------------------------------
    "RULE-SF-SYNCOPE-001": {
        "rule_id": "RULE-SF-SYNCOPE-001",
        "name": "San Francisco Syncope Rule",
        "full_name": "San Francisco Syncope Rule",
        "category": "cardiac",
        "description": ("CHESS mnemonic: any positive => high 7-day serious-outcome risk."),
        "variables": tuple(
            {"name": name, "min_value": 0, "max_value": 1}
            for name in (
                "CHF history",
                "Hematocrit < 30%",
                "Abnormal ECG",
                "Shortness of breath",
                "Systolic BP < 90",
            )
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 0,
                "risk_level": "low",
                "recommendation": "Low risk; outpatient evaluation acceptable.",
            },
            {
                "min_score": 1,
                "max_score": 5,
                "risk_level": "high",
                "recommendation": "Admit for monitoring and workup.",
            },
        ),
        "condition_refs": ("SYNCOPE",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/93/san-francisco-syncope-rule",
    },
    # ----------------------------------------------------------------
    # STEMI in LBBB
    # ----------------------------------------------------------------
    "RULE-SGARBOSSA-001": {
        "rule_id": "RULE-SGARBOSSA-001",
        "name": "Sgarbossa Criteria",
        "full_name": "Sgarbossa Criteria for STEMI in LBBB",
        "category": "cardiac",
        "description": (
            "ECG criteria for diagnosing STEMI in the presence of left bundle "
            "branch block. Score >=3 specific for STEMI."
        ),
        "variables": (
            {"name": "Concordant ST elevation >= 1 mm", "min_value": 0, "max_value": 5},
            {"name": "Concordant ST depression >= 1 mm in V1-V3", "min_value": 0, "max_value": 3},
            {"name": "Discordant ST elevation >= 5 mm", "min_value": 0, "max_value": 2},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 2,
                "risk_level": "low",
                "recommendation": "Sgarbossa not met; consider modified criteria.",
            },
            {
                "min_score": 3,
                "max_score": 10,
                "risk_level": "high",
                "recommendation": "STEMI in LBBB; activate cath lab.",
            },
        ),
        "condition_refs": ("STEMI",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1855/sgarbossa-criteria-mi-left-bundle-branch-block",
    },
    "RULE-SMITH-SGARBOSSA-001": {
        "rule_id": "RULE-SMITH-SGARBOSSA-001",
        "name": "Smith-Modified Sgarbossa",
        "full_name": "Smith-Modified Sgarbossa Criteria",
        "category": "cardiac",
        "description": (
            "Replaces 5mm absolute discordant ST elevation with proportionality "
            "(>=25%); higher sensitivity than original Sgarbossa."
        ),
        "variables": (
            {"name": "Concordant ST elevation >= 1 mm", "min_value": 0, "max_value": 1},
            {"name": "Concordant ST depression >= 1 mm in V1-V3", "min_value": 0, "max_value": 1},
            {
                "name": "Discordant ST elevation >= 25% of S-wave",
                "min_value": 0,
                "max_value": 1,
            },
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 0,
                "risk_level": "low",
                "recommendation": "STEMI not supported by ECG criteria.",
            },
            {
                "min_score": 1,
                "max_score": 3,
                "risk_level": "high",
                "recommendation": "STEMI in LBBB by modified criteria; activate cath lab.",
            },
        ),
        "condition_refs": ("STEMI",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/3215/sgarbossa-criteria-mi-lbbb-modified-smith",
    },
    # ----------------------------------------------------------------
    # Pharyngitis
    # ----------------------------------------------------------------
    "RULE-CENTOR-001": {
        "rule_id": "RULE-CENTOR-001",
        "name": "Centor Score",
        "full_name": "Modified Centor Score for Strep Pharyngitis",
        "category": "infectious",
        "description": (
            "Likelihood of group-A strep; guides rapid antigen test vs empiric treatment."
        ),
        "variables": (
            {"name": "Tonsillar exudate", "min_value": 0, "max_value": 1},
            {"name": "Tender anterior cervical adenopathy", "min_value": 0, "max_value": 1},
            {"name": "Fever > 38C", "min_value": 0, "max_value": 1},
            {"name": "Cough absent", "min_value": 0, "max_value": 1},
            {
                "name": "Age modifier",
                "description": "<15=+1, 15-44=0, >=45=-1",
                "min_value": -1,
                "max_value": 1,
            },
        ),
        "score_ranges": (
            {
                "min_score": -1,
                "max_score": 0,
                "risk_level": "low",
                "recommendation": "<2.5% strep; no testing needed.",
            },
            {
                "min_score": 1,
                "max_score": 2,
                "risk_level": "moderate",
                "recommendation": "Rapid antigen test; treat if positive.",
            },
            {
                "min_score": 3,
                "max_score": 5,
                "risk_level": "high",
                "recommendation": ">=28% strep; consider empiric treatment.",
            },
        ),
        "condition_refs": ("PHARYNGITIS",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/104/centor-score-modified-mclsaac-strep-pharyngitis",
    },
    # ----------------------------------------------------------------
    # ACS risk (alternative to HEART)
    # ----------------------------------------------------------------
    "RULE-TIMI-UA-001": {
        "rule_id": "RULE-TIMI-UA-001",
        "name": "TIMI Risk Score for UA/NSTEMI",
        "full_name": "TIMI Risk Score for Unstable Angina/Non-ST Elevation MI",
        "category": "cardiac",
        "description": "Predicts 14-day mortality and ischemic events.",
        "variables": tuple(
            {"name": name, "min_value": 0, "max_value": 1}
            for name in (
                "Age >= 65",
                ">=3 CAD risk factors",
                "Known CAD (>=50% stenosis)",
                "Aspirin use in past 7 days",
                "Severe angina (>=2 episodes in 24h)",
                "ST changes >= 0.5 mm",
                "Positive cardiac marker",
            )
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 2,
                "risk_level": "low",
                "recommendation": "<= 8.3% risk; conservative pathway.",
            },
            {
                "min_score": 3,
                "max_score": 4,
                "risk_level": "moderate",
                "recommendation": "13-19.9% risk; early invasive strategy.",
            },
            {
                "min_score": 5,
                "max_score": 7,
                "risk_level": "high",
                "recommendation": ">= 26% risk; aggressive intervention indicated.",
            },
        ),
        "condition_refs": ("ACS", "UNSTABLE_ANGINA"),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/111/timi-risk-score-ua-nstemi",
    },
    # ----------------------------------------------------------------
    # GI bleeding
    # ----------------------------------------------------------------
    "RULE-GLASGOW-BLATCHFORD-001": {
        "rule_id": "RULE-GLASGOW-BLATCHFORD-001",
        "name": "Glasgow-Blatchford Bleeding Score",
        "full_name": "Glasgow-Blatchford Score for UGI Bleeding",
        "category": "gi",
        "description": "Stratifies UGI bleed need for medical intervention; score 0 may discharge.",
        "variables": (
            {"name": "BUN", "description": "0..6 by tier", "min_value": 0, "max_value": 6},
            {
                "name": "Hemoglobin",
                "description": "0..6 by tier and sex",
                "min_value": 0,
                "max_value": 6,
            },
            {"name": "Systolic blood pressure", "min_value": 0, "max_value": 3},
            {"name": "Pulse >= 100", "min_value": 0, "max_value": 1},
            {"name": "Melena present", "min_value": 0, "max_value": 1},
            {"name": "Syncope", "min_value": 0, "max_value": 2},
            {"name": "Hepatic disease", "min_value": 0, "max_value": 2},
            {"name": "Cardiac failure", "min_value": 0, "max_value": 2},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 0,
                "risk_level": "low",
                "recommendation": "Outpatient management possible.",
            },
            {
                "min_score": 1,
                "max_score": 5,
                "risk_level": "moderate",
                "recommendation": "Admit; early endoscopy.",
            },
            {
                "min_score": 6,
                "max_score": 23,
                "risk_level": "high",
                "recommendation": "High risk; urgent endoscopy and intervention.",
            },
        ),
        "condition_refs": ("UGI_BLEED",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/518/glasgow-blatchford-bleeding-score-gbs",
    },
    "RULE-AIMS65-001": {
        "rule_id": "RULE-AIMS65-001",
        "name": "AIMS65",
        "full_name": "AIMS65 Score for UGI Bleed Mortality",
        "category": "gi",
        "description": "Inpatient mortality risk after UGI bleed.",
        "variables": tuple(
            {"name": name, "min_value": 0, "max_value": 1}
            for name in (
                "Albumin < 3.0",
                "INR > 1.5",
                "Altered mental status",
                "Systolic BP <= 90",
                "Age > 65",
            )
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 1,
                "risk_level": "low",
                "recommendation": "<= 2.4% mortality.",
            },
            {
                "min_score": 2,
                "max_score": 3,
                "risk_level": "moderate",
                "recommendation": "5.4-9.8% mortality; admit ICU consideration.",
            },
            {
                "min_score": 4,
                "max_score": 5,
                "risk_level": "high",
                "recommendation": ">= 16.5% mortality; ICU.",
            },
        ),
        "condition_refs": ("UGI_BLEED",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/2275/aims65-score-upper-gi-bleeding-mortality",
    },
    "RULE-ROCKALL-001": {
        "rule_id": "RULE-ROCKALL-001",
        "name": "Rockall Score",
        "full_name": "Rockall Score for UGI Bleed Mortality",
        "category": "gi",
        "description": "Pre- and post-endoscopy mortality prediction for UGI bleed.",
        "variables": (
            {
                "name": "Age",
                "description": "<60=0; 60-79=1; >=80=2",
                "min_value": 0,
                "max_value": 2,
            },
            {
                "name": "Shock",
                "description": "tachycardia=1, hypotension=2",
                "min_value": 0,
                "max_value": 2,
            },
            {"name": "Comorbidity", "min_value": 0, "max_value": 3},
            {"name": "Diagnosis", "min_value": 0, "max_value": 2},
            {"name": "Stigmata of recent hemorrhage", "min_value": 0, "max_value": 2},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 2,
                "risk_level": "low",
                "recommendation": "<= 5% mortality; consider outpatient.",
            },
            {
                "min_score": 3,
                "max_score": 4,
                "risk_level": "moderate",
                "recommendation": "11% mortality; admit.",
            },
            {
                "min_score": 5,
                "max_score": 11,
                "risk_level": "high",
                "recommendation": ">= 25% mortality; ICU/intervention.",
            },
        ),
        "condition_refs": ("UGI_BLEED",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1841/rockall-score-upper-gi-bleeding-complete",
    },
    # ----------------------------------------------------------------
    # Anticoagulation risk
    # ----------------------------------------------------------------
    "RULE-HAS-BLED-001": {
        "rule_id": "RULE-HAS-BLED-001",
        "name": "HAS-BLED Score",
        "full_name": "HAS-BLED Score for Major Bleeding Risk",
        "category": "hematologic",
        "description": "1-year major-bleeding risk on anticoagulation.",
        "variables": tuple(
            {"name": name, "min_value": 0, "max_value": 1}
            for name in (
                "Hypertension uncontrolled",
                "Abnormal renal function",
                "Abnormal liver function",
                "Stroke history",
                "Bleeding history",
                "Labile INR",
                "Elderly (>65)",
                "Drugs (antiplatelet/NSAID)",
                "Alcohol >= 8 drinks/week",
            )
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 1,
                "risk_level": "low",
                "recommendation": "<= 1.5% major bleeding/yr.",
            },
            {
                "min_score": 2,
                "max_score": 3,
                "risk_level": "moderate",
                "recommendation": "1.9-3.7% major bleeding/yr.",
            },
            {
                "min_score": 4,
                "max_score": 9,
                "risk_level": "high",
                "recommendation": ">= 8.7% bleeding/yr; reconsider anticoagulation strategy.",
            },
        ),
        "condition_refs": ("AFIB",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/807/has-bled-score-major-bleeding-risk",
    },
    "RULE-CHA2DS2-VASC-001": {
        "rule_id": "RULE-CHA2DS2-VASC-001",
        "name": "CHA2DS2-VASc",
        "full_name": "CHA2DS2-VASc Score for AFib Stroke Risk",
        "category": "cardiac",
        "description": "Annual ischemic-stroke risk in non-valvular atrial fibrillation.",
        "variables": (
            {"name": "Congestive heart failure", "min_value": 0, "max_value": 1},
            {"name": "Hypertension", "min_value": 0, "max_value": 1},
            {"name": "Age >= 75", "min_value": 0, "max_value": 2},
            {"name": "Diabetes", "min_value": 0, "max_value": 1},
            {"name": "Stroke/TIA history", "min_value": 0, "max_value": 2},
            {"name": "Vascular disease", "min_value": 0, "max_value": 1},
            {"name": "Age 65-74", "min_value": 0, "max_value": 1},
            {"name": "Sex (female)", "min_value": 0, "max_value": 1},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 1,
                "risk_level": "low",
                "recommendation": "Anticoagulation not generally indicated.",
            },
            {
                "min_score": 2,
                "max_score": 3,
                "risk_level": "moderate",
                "recommendation": "Consider anticoagulation.",
            },
            {
                "min_score": 4,
                "max_score": 10,
                "risk_level": "high",
                "recommendation": "Anticoagulation strongly indicated; balance against HAS-BLED.",
            },
        ),
        "condition_refs": ("AFIB",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/801/cha2ds2-vasc-score-atrial-fibrillation-stroke-risk",
    },
    # ----------------------------------------------------------------
    # Trauma / consciousness
    # ----------------------------------------------------------------
    "RULE-GCS-001": {
        "rule_id": "RULE-GCS-001",
        "name": "Glasgow Coma Scale",
        "full_name": "Glasgow Coma Scale (Adult)",
        "category": "trauma",
        "description": "Level-of-consciousness assessment; total 3-15.",
        "variables": (
            {"name": "Eye opening response", "min_value": 1, "max_value": 4},
            {"name": "Verbal response", "min_value": 1, "max_value": 5},
            {"name": "Motor response", "min_value": 1, "max_value": 6},
        ),
        "score_ranges": (
            {
                "min_score": 3,
                "max_score": 8,
                "risk_level": "high",
                "recommendation": "Severe TBI; consider intubation.",
            },
            {
                "min_score": 9,
                "max_score": 12,
                "risk_level": "moderate",
                "recommendation": "Moderate TBI; close monitoring + neuro-imaging.",
            },
            {
                "min_score": 13,
                "max_score": 15,
                "risk_level": "low",
                "recommendation": "Mild TBI; monitor for deterioration.",
            },
        ),
        "condition_refs": ("TBI",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/64/glasgow-coma-scale-score",
    },
    # ----------------------------------------------------------------
    # PE severity (after diagnosis)
    # ----------------------------------------------------------------
    "RULE-SPESI-001": {
        "rule_id": "RULE-SPESI-001",
        "name": "sPESI",
        "full_name": "Simplified Pulmonary Embolism Severity Index",
        "category": "pulmonary",
        "description": (
            "30-day mortality risk after acute PE; 0 = low risk for outpatient management."
        ),
        "variables": tuple(
            {"name": name, "min_value": 0, "max_value": 1}
            for name in (
                "Age > 80",
                "History of cancer",
                "Chronic cardiopulmonary disease",
                "Heart rate >= 110",
                "Systolic BP < 100",
                "SpO2 < 90%",
            )
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 0,
                "risk_level": "low",
                "recommendation": "1.0% 30-day mortality; outpatient mgmt acceptable.",
            },
            {
                "min_score": 1,
                "max_score": 6,
                "risk_level": "high",
                "recommendation": (
                    "10.9% 30-day mortality; admit and consider thrombolysis "
                    "if hemodynamically unstable."
                ),
            },
        ),
        "condition_refs": ("PE",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1247/simplified-pesi-pulmonary-embolism-severity-index",
    },
    # ----------------------------------------------------------------
    # Alcohol withdrawal
    # ----------------------------------------------------------------
    "RULE-CIWA-AR-001": {
        "rule_id": "RULE-CIWA-AR-001",
        "name": "CIWA-Ar",
        "full_name": "Clinical Institute Withdrawal Assessment for Alcohol, Revised",
        "category": "toxicology",
        "description": "Severity of alcohol withdrawal; guides benzodiazepine dosing.",
        "variables": tuple(
            {"name": name, "min_value": 0, "max_value": 7}
            for name in (
                "Nausea/vomiting",
                "Tremor",
                "Paroxysmal sweats",
                "Anxiety",
                "Agitation",
                "Tactile disturbances",
                "Auditory disturbances",
                "Visual disturbances",
                "Headache",
                "Orientation/clouded sensorium",
            )
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 8,
                "risk_level": "low",
                "recommendation": "Mild; q4-8h reassess; may not require pharmacotherapy.",
            },
            {
                "min_score": 9,
                "max_score": 15,
                "risk_level": "moderate",
                "recommendation": "Moderate; symptom-triggered benzodiazepine therapy.",
            },
            {
                "min_score": 16,
                "max_score": 70,
                "risk_level": "high",
                "recommendation": "Severe; aggressive benzodiazepine, monitored bed.",
            },
        ),
        "condition_refs": ("ALCOHOL_WITHDRAWAL",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1736/ciwa-ar-alcohol-withdrawal",
    },
    # ----------------------------------------------------------------
    # COPD severity (ED disposition)
    # ----------------------------------------------------------------
    "RULE-BAP65-001": {
        "rule_id": "RULE-BAP65-001",
        "name": "BAP-65",
        "full_name": "BAP-65 Score for AECOPD",
        "category": "pulmonary",
        "description": "In-hospital mortality risk for acute exacerbation of COPD.",
        "variables": (
            {"name": "BUN >= 25 mg/dL", "min_value": 0, "max_value": 1},
            {"name": "Altered mental status", "min_value": 0, "max_value": 1},
            {"name": "Pulse >= 109", "min_value": 0, "max_value": 1},
            {"name": "Age >= 65", "min_value": 0, "max_value": 1},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 0,
                "risk_level": "low",
                "recommendation": "Class I; <0.3% mortality; consider outpatient.",
            },
            {
                "min_score": 1,
                "max_score": 2,
                "risk_level": "moderate",
                "recommendation": "Class II-III; admit ward.",
            },
            {
                "min_score": 3,
                "max_score": 4,
                "risk_level": "high",
                "recommendation": "Class IV-V; ICU consideration.",
            },
        ),
        "condition_refs": ("COPD",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/2129/bap-65-score-acute-exacerbation-copd",
    },
}
