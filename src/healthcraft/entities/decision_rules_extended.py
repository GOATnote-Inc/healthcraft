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
    # ----------------------------------------------------------------
    # Pneumonia severity (alternative to CURB-65 with more variables)
    # ----------------------------------------------------------------
    "RULE-PSI-001": {
        "rule_id": "RULE-PSI-001",
        "name": "PSI / PORT Score",
        "full_name": "Pneumonia Severity Index (Pneumonia Outcomes Research Team)",
        "category": "pulmonary",
        "description": (
            "Stratifies CAP mortality risk into 5 classes by additive points "
            "(simplified scoring; detailed sub-scoring per MDCalc)."
        ),
        "variables": (
            {"name": "Age (points)", "min_value": 0, "max_value": 100},
            {"name": "Nursing home resident", "min_value": 0, "max_value": 10},
            {"name": "Comorbidity score", "min_value": 0, "max_value": 30},
            {"name": "Vital sign abnormalities", "min_value": 0, "max_value": 30},
            {"name": "Lab abnormalities", "min_value": 0, "max_value": 50},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 70,
                "risk_level": "low",
                "recommendation": "Class I-II; outpatient management acceptable.",
            },
            {
                "min_score": 71,
                "max_score": 90,
                "risk_level": "moderate",
                "recommendation": "Class III; brief observation or admit.",
            },
            {
                "min_score": 91,
                "max_score": 220,
                "risk_level": "high",
                "recommendation": "Class IV-V; admit, consider ICU.",
            },
        ),
        "condition_refs": ("PNEUMONIA",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/33/psi-port-score-pneumonia-severity-index-cap",
    },
    "RULE-CRB-65-001": {
        "rule_id": "RULE-CRB-65-001",
        "name": "CRB-65",
        "full_name": "CRB-65 Score for Pneumonia (no labs needed)",
        "category": "pulmonary",
        "description": "Simplified CURB-65 without urea; usable in primary-care/triage.",
        "variables": tuple(
            {"name": name, "min_value": 0, "max_value": 1}
            for name in (
                "Confusion",
                "Respiratory rate >= 30",
                "BP (SBP < 90 or DBP <= 60)",
                "Age >= 65",
            )
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 0,
                "risk_level": "low",
                "recommendation": "<1.2% mortality; outpatient.",
            },
            {
                "min_score": 1,
                "max_score": 2,
                "risk_level": "moderate",
                "recommendation": "8.2% mortality; admit for short stay.",
            },
            {
                "min_score": 3,
                "max_score": 4,
                "risk_level": "high",
                "recommendation": ">=31% mortality; ICU consideration.",
            },
        ),
        "condition_refs": ("PNEUMONIA",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/324/crb-65-score-pneumonia-severity",
    },
    # ----------------------------------------------------------------
    # Sepsis severity (organ dysfunction)
    # ----------------------------------------------------------------
    "RULE-SOFA-001": {
        "rule_id": "RULE-SOFA-001",
        "name": "SOFA",
        "full_name": "Sequential Organ Failure Assessment",
        "category": "infectious",
        "description": (
            "Six-organ-system score (resp/coag/liver/cardio/CNS/renal) 0-4 each. "
            "Total 0-24; >=2 from baseline = sepsis (Sepsis-3 definition)."
        ),
        "variables": tuple(
            {"name": name, "min_value": 0, "max_value": 4}
            for name in (
                "Respiratory (PaO2/FiO2)",
                "Coagulation (platelets)",
                "Liver (bilirubin)",
                "Cardiovascular (MAP/pressors)",
                "CNS (GCS)",
                "Renal (creatinine/UOP)",
            )
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 6,
                "risk_level": "low",
                "recommendation": "<10% in-hospital mortality.",
            },
            {
                "min_score": 7,
                "max_score": 9,
                "risk_level": "moderate",
                "recommendation": "15-20% in-hospital mortality; ICU consideration.",
            },
            {
                "min_score": 10,
                "max_score": 24,
                "risk_level": "high",
                "recommendation": ">40% in-hospital mortality; ICU.",
            },
        ),
        "condition_refs": ("SEPSIS",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/691/sequential-organ-failure-assessment-sofa-score",
    },
    "RULE-MEDS-001": {
        "rule_id": "RULE-MEDS-001",
        "name": "MEDS Score",
        "full_name": "Mortality in Emergency Department Sepsis Score",
        "category": "infectious",
        "description": "ED-specific 28-day mortality for suspected sepsis.",
        "variables": (
            {"name": "Terminal illness (<30d expected)", "min_value": 0, "max_value": 6},
            {"name": "Tachypnea or hypoxia", "min_value": 0, "max_value": 3},
            {"name": "Septic shock", "min_value": 0, "max_value": 3},
            {"name": "Platelets < 150K", "min_value": 0, "max_value": 3},
            {"name": "Bands > 5%", "min_value": 0, "max_value": 3},
            {"name": "Age > 65", "min_value": 0, "max_value": 3},
            {"name": "Lower respiratory infection", "min_value": 0, "max_value": 2},
            {"name": "Nursing home resident", "min_value": 0, "max_value": 2},
            {"name": "Altered mental status", "min_value": 0, "max_value": 2},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 4,
                "risk_level": "low",
                "recommendation": "1.1% mortality; standard care.",
            },
            {
                "min_score": 5,
                "max_score": 7,
                "risk_level": "moderate",
                "recommendation": "9.0% mortality; admit.",
            },
            {
                "min_score": 8,
                "max_score": 12,
                "risk_level": "high",
                "recommendation": "21% mortality; ICU consideration.",
            },
            {
                "min_score": 13,
                "max_score": 27,
                "risk_level": "very_high",
                "recommendation": "50%+ mortality; aggressive ICU resuscitation.",
            },
        ),
        "condition_refs": ("SEPSIS",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1872/meds-score-mortality-emergency-department-sepsis",
    },
    "RULE-SIRS-001": {
        "rule_id": "RULE-SIRS-001",
        "name": "SIRS Criteria",
        "full_name": "Systemic Inflammatory Response Syndrome Criteria",
        "category": "infectious",
        "description": (
            "4 criteria; >=2 = SIRS. Pre-Sepsis-3 sepsis screen, still used in many EDs."
        ),
        "variables": tuple(
            {"name": name, "min_value": 0, "max_value": 1}
            for name in (
                "Temp > 38C or < 36C",
                "Heart rate > 90",
                "Respiratory rate > 20 or PaCO2 < 32",
                "WBC > 12K, < 4K, or > 10% bands",
            )
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 1,
                "risk_level": "low",
                "recommendation": "SIRS not met; standard workup.",
            },
            {
                "min_score": 2,
                "max_score": 4,
                "risk_level": "high",
                "recommendation": "SIRS met; if infection suspected, evaluate for sepsis.",
            },
        ),
        "condition_refs": ("SEPSIS",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1096/sirs-sepsis-septic-shock-criteria",
    },
    # ----------------------------------------------------------------
    # Pediatrics
    # ----------------------------------------------------------------
    "RULE-PED-GCS-001": {
        "rule_id": "RULE-PED-GCS-001",
        "name": "Pediatric Glasgow Coma Scale",
        "full_name": "Pediatric Glasgow Coma Scale (children < 5 years)",
        "category": "trauma",
        "description": "Age-modified GCS for non-verbal children; total 3-15.",
        "variables": (
            {"name": "Eye opening (peds)", "min_value": 1, "max_value": 4},
            {"name": "Verbal response (peds)", "min_value": 1, "max_value": 5},
            {"name": "Motor response (peds)", "min_value": 1, "max_value": 6},
        ),
        "score_ranges": (
            {
                "min_score": 3,
                "max_score": 8,
                "risk_level": "high",
                "recommendation": "Severe pediatric TBI; intubate, neurosurg consult.",
            },
            {
                "min_score": 9,
                "max_score": 12,
                "risk_level": "moderate",
                "recommendation": "Moderate; CT and admit.",
            },
            {
                "min_score": 13,
                "max_score": 15,
                "risk_level": "low",
                "recommendation": "Mild; observe with reassessment.",
            },
        ),
        "condition_refs": ("PEDIATRIC_TBI",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/30/glasgow-coma-scale-pediatric-pgcs",
    },
    "RULE-APGAR-001": {
        "rule_id": "RULE-APGAR-001",
        "name": "APGAR",
        "full_name": "APGAR Score (Newborn)",
        "category": "obstetric",
        "description": "Newborn assessment at 1 and 5 minutes; total 0-10.",
        "variables": tuple(
            {"name": name, "min_value": 0, "max_value": 2}
            for name in (
                "Appearance (color)",
                "Pulse",
                "Grimace (reflex)",
                "Activity (muscle tone)",
                "Respiration",
            )
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 3,
                "risk_level": "high",
                "recommendation": "Severely depressed; immediate resuscitation.",
            },
            {
                "min_score": 4,
                "max_score": 6,
                "risk_level": "moderate",
                "recommendation": "Moderately depressed; supportive care + reassess.",
            },
            {
                "min_score": 7,
                "max_score": 10,
                "risk_level": "low",
                "recommendation": "Reassuring; routine newborn care.",
            },
        ),
        "condition_refs": ("NEWBORN",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/23/apgar-score",
    },
    # ----------------------------------------------------------------
    # VTE prophylaxis risk
    # ----------------------------------------------------------------
    "RULE-PADUA-001": {
        "rule_id": "RULE-PADUA-001",
        "name": "Padua Prediction Score",
        "full_name": "Padua Prediction Score for VTE in Hospitalized Patients",
        "category": "hematologic",
        "description": "VTE risk in medical inpatients; >=4 = high risk, prophylaxis indicated.",
        "variables": (
            {"name": "Active cancer", "min_value": 0, "max_value": 3},
            {"name": "Previous VTE", "min_value": 0, "max_value": 3},
            {"name": "Reduced mobility", "min_value": 0, "max_value": 3},
            {"name": "Known thrombophilia", "min_value": 0, "max_value": 3},
            {"name": "Recent trauma/surgery", "min_value": 0, "max_value": 2},
            {"name": "Age >= 70", "min_value": 0, "max_value": 1},
            {"name": "Heart or respiratory failure", "min_value": 0, "max_value": 1},
            {"name": "Acute MI or stroke", "min_value": 0, "max_value": 1},
            {"name": "Acute infection or rheumatologic disorder", "min_value": 0, "max_value": 1},
            {"name": "BMI >= 30", "min_value": 0, "max_value": 1},
            {"name": "Hormonal therapy", "min_value": 0, "max_value": 1},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 3,
                "risk_level": "low",
                "recommendation": "0.3% VTE; mechanical prophylaxis only.",
            },
            {
                "min_score": 4,
                "max_score": 20,
                "risk_level": "high",
                "recommendation": "11% VTE; pharmacologic prophylaxis indicated.",
            },
        ),
        "condition_refs": ("VTE",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1873/padua-prediction-score-risk-vte",
    },
    "RULE-CAPRINI-001": {
        "rule_id": "RULE-CAPRINI-001",
        "name": "Caprini Score",
        "full_name": "Caprini Score for Surgical VTE Risk",
        "category": "hematologic",
        "description": (
            "Comprehensive VTE risk for surgical patients; categorized 0-1 / 2 / 3-4 / >=5."
        ),
        "variables": (
            {"name": "Risk-1 factors (1 pt each)", "min_value": 0, "max_value": 10},
            {"name": "Risk-2 factors (2 pts each)", "min_value": 0, "max_value": 8},
            {"name": "Risk-3 factors (3 pts each)", "min_value": 0, "max_value": 6},
            {"name": "Risk-5 factors (5 pts each)", "min_value": 0, "max_value": 10},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 1,
                "risk_level": "low",
                "recommendation": "Very low risk; ambulation only.",
            },
            {
                "min_score": 2,
                "max_score": 2,
                "risk_level": "moderate",
                "recommendation": "Low risk; mechanical prophylaxis.",
            },
            {
                "min_score": 3,
                "max_score": 4,
                "risk_level": "high",
                "recommendation": "Moderate risk; LMWH or heparin.",
            },
            {
                "min_score": 5,
                "max_score": 34,
                "risk_level": "very_high",
                "recommendation": "High risk; LMWH + mechanical, consider extended.",
            },
        ),
        "condition_refs": ("VTE",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/3970/caprini-score-venous-thromboembolism-2005",
    },
    # ----------------------------------------------------------------
    # Anticoag risk (legacy / alternatives)
    # ----------------------------------------------------------------
    "RULE-CHADS2-001": {
        "rule_id": "RULE-CHADS2-001",
        "name": "CHADS2",
        "full_name": "CHADS2 Score for Atrial Fibrillation Stroke Risk",
        "category": "cardiac",
        "description": "Legacy precursor to CHA2DS2-VASc; still cited in some guidelines.",
        "variables": (
            {"name": "Congestive heart failure", "min_value": 0, "max_value": 1},
            {"name": "Hypertension", "min_value": 0, "max_value": 1},
            {"name": "Age >= 75", "min_value": 0, "max_value": 1},
            {"name": "Diabetes", "min_value": 0, "max_value": 1},
            {"name": "Stroke/TIA history", "min_value": 0, "max_value": 2},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 0,
                "risk_level": "low",
                "recommendation": "1.9%/yr stroke; no anticoagulation routinely.",
            },
            {
                "min_score": 1,
                "max_score": 2,
                "risk_level": "moderate",
                "recommendation": "2.8-4.0%/yr; consider anticoagulation.",
            },
            {
                "min_score": 3,
                "max_score": 6,
                "risk_level": "high",
                "recommendation": ">=5.9%/yr; anticoagulation indicated.",
            },
        ),
        "condition_refs": ("AFIB",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/40/chads2-score-atrial-fibrillation-stroke-risk",
    },
    "RULE-HEMORR2HAGES-001": {
        "rule_id": "RULE-HEMORR2HAGES-001",
        "name": "HEMORR2HAGES",
        "full_name": "HEMORR2HAGES Bleeding Risk on Anticoagulation",
        "category": "hematologic",
        "description": "Annual major-bleed risk for AFib patients on warfarin.",
        "variables": (
            {"name": "Hepatic/Renal disease", "min_value": 0, "max_value": 1},
            {"name": "Ethanol abuse", "min_value": 0, "max_value": 1},
            {"name": "Malignancy", "min_value": 0, "max_value": 1},
            {"name": "Older (>75)", "min_value": 0, "max_value": 1},
            {"name": "Reduced platelets/function", "min_value": 0, "max_value": 1},
            {"name": "Rebleed history", "min_value": 0, "max_value": 2},
            {"name": "Hypertension uncontrolled", "min_value": 0, "max_value": 1},
            {"name": "Anemia", "min_value": 0, "max_value": 1},
            {"name": "Genetic factors (CYP2C9)", "min_value": 0, "max_value": 1},
            {"name": "Excessive fall risk", "min_value": 0, "max_value": 1},
            {"name": "Stroke history", "min_value": 0, "max_value": 1},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 1,
                "risk_level": "low",
                "recommendation": "<=1.9 bleeds/100 patient-yr.",
            },
            {
                "min_score": 2,
                "max_score": 3,
                "risk_level": "moderate",
                "recommendation": "2.5-5.3 bleeds/100 patient-yr.",
            },
            {
                "min_score": 4,
                "max_score": 12,
                "risk_level": "high",
                "recommendation": ">=8.4 bleeds/100 patient-yr; reconsider anticoag.",
            },
        ),
        "condition_refs": ("AFIB",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/802/hemorr2hages-score-major-bleeding-risk",
    },
    "RULE-ATRIA-BLEED-001": {
        "rule_id": "RULE-ATRIA-BLEED-001",
        "name": "ATRIA Bleeding Risk",
        "full_name": "ATRIA Bleeding Risk Score",
        "category": "hematologic",
        "description": "Major-bleed risk on warfarin in AFib patients; alternative to HAS-BLED.",
        "variables": (
            {"name": "Anemia", "min_value": 0, "max_value": 3},
            {"name": "Severe renal disease", "min_value": 0, "max_value": 3},
            {"name": "Age >= 75", "min_value": 0, "max_value": 2},
            {"name": "Prior bleeding", "min_value": 0, "max_value": 1},
            {"name": "Hypertension", "min_value": 0, "max_value": 1},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 3,
                "risk_level": "low",
                "recommendation": "0.8%/yr major bleeding.",
            },
            {
                "min_score": 4,
                "max_score": 4,
                "risk_level": "moderate",
                "recommendation": "2.6%/yr major bleeding.",
            },
            {
                "min_score": 5,
                "max_score": 10,
                "risk_level": "high",
                "recommendation": ">=5.8%/yr major bleeding.",
            },
        ),
        "condition_refs": ("AFIB",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/3938/atria-bleeding-risk-score",
    },
    # ----------------------------------------------------------------
    # Syncope (alternatives to SF Syncope)
    # ----------------------------------------------------------------
    "RULE-OESIL-001": {
        "rule_id": "RULE-OESIL-001",
        "name": "OESIL",
        "full_name": "OESIL Score for Syncope",
        "category": "cardiac",
        "description": "1-year mortality after ED syncope; >=2 = high.",
        "variables": tuple(
            {"name": name, "min_value": 0, "max_value": 1}
            for name in (
                "Age > 65",
                "Cardiovascular disease history",
                "Syncope without prodrome",
                "Abnormal ECG",
            )
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 1,
                "risk_level": "low",
                "recommendation": "<=0.6% 1-yr mortality.",
            },
            {
                "min_score": 2,
                "max_score": 4,
                "risk_level": "high",
                "recommendation": ">=14% 1-yr mortality; admit.",
            },
        ),
        "condition_refs": ("SYNCOPE",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1856/oesil-risk-score-syncope",
    },
    # ----------------------------------------------------------------
    # General ED severity
    # ----------------------------------------------------------------
    "RULE-REMS-001": {
        "rule_id": "RULE-REMS-001",
        "name": "REMS",
        "full_name": "Rapid Emergency Medicine Score",
        "category": "general",
        "description": "ED in-hospital mortality predictor across non-trauma presentations.",
        "variables": (
            {"name": "Age points", "min_value": 0, "max_value": 6},
            {"name": "Mean arterial pressure points", "min_value": 0, "max_value": 4},
            {"name": "Heart rate points", "min_value": 0, "max_value": 4},
            {"name": "Respiratory rate points", "min_value": 0, "max_value": 4},
            {"name": "Oxygen saturation points", "min_value": 0, "max_value": 4},
            {"name": "GCS points", "min_value": 0, "max_value": 4},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 5,
                "risk_level": "low",
                "recommendation": "<5% mortality.",
            },
            {
                "min_score": 6,
                "max_score": 9,
                "risk_level": "moderate",
                "recommendation": "5-15% mortality.",
            },
            {
                "min_score": 10,
                "max_score": 26,
                "risk_level": "high",
                "recommendation": ">=15% mortality; admit.",
            },
        ),
        "condition_refs": (),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1862/rapid-emergency-medicine-score-rems",
    },
    # ----------------------------------------------------------------
    # ACS — additional / mortality
    # ----------------------------------------------------------------
    "RULE-GRACE-001": {
        "rule_id": "RULE-GRACE-001",
        "name": "GRACE Score",
        "full_name": "GRACE ACS Risk Score (in-hospital mortality, additive form)",
        "category": "cardiac",
        "description": (
            "Predicts in-hospital mortality in ACS using additive points by tier "
            "(simplified additive form; full GRACE uses logistic-regression "
            "coefficients). Variable values are pre-computed point contributions."
        ),
        "variables": (
            {"name": "Age points", "min_value": 0, "max_value": 100},
            {"name": "Heart rate points", "min_value": 0, "max_value": 46},
            {"name": "Systolic BP points", "min_value": 0, "max_value": 58},
            {"name": "Creatinine points", "min_value": 1, "max_value": 28},
            {"name": "Killip class points", "min_value": 0, "max_value": 59},
            {"name": "Cardiac arrest at admission", "min_value": 0, "max_value": 39},
            {"name": "ST-segment deviation", "min_value": 0, "max_value": 28},
            {"name": "Elevated cardiac enzymes", "min_value": 0, "max_value": 14},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 108,
                "risk_level": "low",
                "recommendation": "<=1% in-hospital mortality; conservative pathway.",
            },
            {
                "min_score": 109,
                "max_score": 140,
                "risk_level": "moderate",
                "recommendation": "1-3% mortality; early invasive strategy.",
            },
            {
                "min_score": 141,
                "max_score": 372,
                "risk_level": "high",
                "recommendation": ">3% mortality; aggressive intervention indicated.",
            },
        ),
        "condition_refs": ("ACS",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1099/grace-acs-risk-mortality-calculator",
    },
    # ----------------------------------------------------------------
    # Stroke severity
    # ----------------------------------------------------------------
    "RULE-NIHSS-001": {
        "rule_id": "RULE-NIHSS-001",
        "name": "NIHSS",
        "full_name": "NIH Stroke Scale",
        "category": "neuro",
        "description": (
            "Stroke-severity instrument; 11 items (0-3 or 0-4 each). "
            "Total 0-42; thresholds drive tPA decision-making."
        ),
        "variables": (
            {"name": "Level of consciousness", "min_value": 0, "max_value": 3},
            {"name": "LOC questions", "min_value": 0, "max_value": 2},
            {"name": "LOC commands", "min_value": 0, "max_value": 2},
            {"name": "Best gaze", "min_value": 0, "max_value": 2},
            {"name": "Visual fields", "min_value": 0, "max_value": 3},
            {"name": "Facial palsy", "min_value": 0, "max_value": 3},
            {"name": "Motor arm", "min_value": 0, "max_value": 4},
            {"name": "Motor leg", "min_value": 0, "max_value": 4},
            {"name": "Limb ataxia", "min_value": 0, "max_value": 2},
            {"name": "Sensory", "min_value": 0, "max_value": 2},
            {"name": "Best language", "min_value": 0, "max_value": 3},
            {"name": "Dysarthria", "min_value": 0, "max_value": 2},
            {"name": "Extinction/inattention", "min_value": 0, "max_value": 2},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 4,
                "risk_level": "low",
                "recommendation": "Minor stroke; tPA may not be indicated.",
            },
            {
                "min_score": 5,
                "max_score": 15,
                "risk_level": "moderate",
                "recommendation": "Moderate stroke; consider tPA + admit.",
            },
            {
                "min_score": 16,
                "max_score": 20,
                "risk_level": "high",
                "recommendation": "Moderate-severe stroke; tPA + neurology consult.",
            },
            {
                "min_score": 21,
                "max_score": 42,
                "risk_level": "very_high",
                "recommendation": "Severe stroke; high tPA-bleed risk; ICU.",
            },
        ),
        "condition_refs": ("STROKE",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/715/nih-stroke-scale-score-nihss",
    },
    # ----------------------------------------------------------------
    # Full PESI (additive points form)
    # ----------------------------------------------------------------
    "RULE-PESI-FULL-001": {
        "rule_id": "RULE-PESI-FULL-001",
        "name": "PESI",
        "full_name": "Pulmonary Embolism Severity Index (full)",
        "category": "pulmonary",
        "description": (
            "30-day mortality after PE; 5 risk classes by additive points. "
            "Each variable is a pre-computed point contribution per the "
            "MDCalc lookup table."
        ),
        "variables": (
            {"name": "Age (years as points)", "min_value": 0, "max_value": 120},
            {"name": "Male sex", "min_value": 0, "max_value": 10},
            {"name": "Cancer history", "min_value": 0, "max_value": 30},
            {"name": "Heart failure", "min_value": 0, "max_value": 10},
            {"name": "Chronic lung disease", "min_value": 0, "max_value": 10},
            {"name": "Heart rate >= 110", "min_value": 0, "max_value": 20},
            {"name": "Systolic BP < 100", "min_value": 0, "max_value": 30},
            {"name": "Respiratory rate >= 30", "min_value": 0, "max_value": 20},
            {"name": "Temperature < 36C", "min_value": 0, "max_value": 20},
            {"name": "Altered mental status", "min_value": 0, "max_value": 60},
            {"name": "SpO2 < 90%", "min_value": 0, "max_value": 20},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 65,
                "risk_level": "low",
                "recommendation": "Class I; <=1.6% 30-day mortality; outpatient possible.",
            },
            {
                "min_score": 66,
                "max_score": 85,
                "risk_level": "moderate",
                "recommendation": "Class II; 3.5% mortality; brief observation.",
            },
            {
                "min_score": 86,
                "max_score": 105,
                "risk_level": "high",
                "recommendation": "Class III; 7.1% mortality; admit.",
            },
            {
                "min_score": 106,
                "max_score": 125,
                "risk_level": "very_high",
                "recommendation": "Class IV; 11.4% mortality; ICU consideration.",
            },
            {
                "min_score": 126,
                "max_score": 350,
                "risk_level": "extreme",
                "recommendation": "Class V; 24.5% mortality; ICU + thrombolysis.",
            },
        ),
        "condition_refs": ("PE",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1304/pulmonary-embolism-severity-index-pesi",
    },
    # ----------------------------------------------------------------
    # Syncope (alternatives, additional)
    # ----------------------------------------------------------------
    "RULE-ROSE-001": {
        "rule_id": "RULE-ROSE-001",
        "name": "ROSE Rule",
        "full_name": "Risk Stratification of Syncope in the Emergency Department",
        "category": "cardiac",
        "description": (
            "1-month adverse outcome risk in ED syncope; any positive "
            "criterion = high-risk (admit)."
        ),
        "variables": tuple(
            {"name": name, "min_value": 0, "max_value": 1}
            for name in (
                "BNP >= 300 pg/mL",
                "Bradycardia <= 50",
                "Rectal exam fecal occult positive",
                "Hemoglobin <= 9 g/dL",
                "Chest pain with syncope",
                "ECG with Q wave (not lead III)",
                "Saturation <= 94% on room air",
            )
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 0,
                "risk_level": "low",
                "recommendation": "Low risk; consider outpatient.",
            },
            {
                "min_score": 1,
                "max_score": 7,
                "risk_level": "high",
                "recommendation": "High risk; admit for monitoring/workup.",
            },
        ),
        "condition_refs": ("SYNCOPE",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/2008/rose-rule-syncope",
    },
    "RULE-EGSYS-001": {
        "rule_id": "RULE-EGSYS-001",
        "name": "EGSYS",
        "full_name": "EGSYS Score for Syncope",
        "category": "cardiac",
        "description": (
            "Likelihood of cardiac syncope; >=3 = cardiac syncope likely. "
            "Some variables contribute negative points."
        ),
        "variables": (
            {"name": "Abnormal ECG and/or heart disease", "min_value": 0, "max_value": 3},
            {"name": "Palpitations preceding syncope", "min_value": 0, "max_value": 4},
            {"name": "Syncope during effort", "min_value": 0, "max_value": 3},
            {"name": "Syncope while supine", "min_value": 0, "max_value": 2},
            {"name": "Autonomic prodrome", "min_value": -1, "max_value": 0},
            {"name": "Predisposing/precipitating factors", "min_value": -1, "max_value": 0},
        ),
        "score_ranges": (
            {
                "min_score": -2,
                "max_score": 2,
                "risk_level": "low",
                "recommendation": "Cardiac syncope unlikely; outpatient cardiology.",
            },
            {
                "min_score": 3,
                "max_score": 12,
                "risk_level": "high",
                "recommendation": "Cardiac syncope likely (95% sens); admit / monitor.",
            },
        ),
        "condition_refs": ("SYNCOPE",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/3922/egsys-score-syncope",
    },
    # ----------------------------------------------------------------
    # Intracranial hemorrhage prognosis
    # ----------------------------------------------------------------
    "RULE-ICH-SCORE-001": {
        "rule_id": "RULE-ICH-SCORE-001",
        "name": "ICH Score",
        "full_name": "Intracerebral Hemorrhage Score (30-day mortality)",
        "category": "neuro",
        "description": "30-day mortality after spontaneous ICH; 0 = ~0%, 6 = 100%.",
        "variables": (
            {"name": "GCS points (3-4=2; 5-12=1; 13-15=0)", "min_value": 0, "max_value": 2},
            {"name": "Age >= 80", "min_value": 0, "max_value": 1},
            {"name": "Infratentorial origin", "min_value": 0, "max_value": 1},
            {"name": "ICH volume >= 30 mL", "min_value": 0, "max_value": 1},
            {"name": "Intraventricular hemorrhage", "min_value": 0, "max_value": 1},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 1,
                "risk_level": "low",
                "recommendation": "0-13% 30-day mortality.",
            },
            {
                "min_score": 2,
                "max_score": 3,
                "risk_level": "moderate",
                "recommendation": "26-72% 30-day mortality; ICU.",
            },
            {
                "min_score": 4,
                "max_score": 6,
                "risk_level": "high",
                "recommendation": "97-100% 30-day mortality; goals-of-care discussion.",
            },
        ),
        "condition_refs": ("ICH",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1334/ich-score",
    },
    # ----------------------------------------------------------------
    # Pancreatitis severity
    # ----------------------------------------------------------------
    "RULE-BISAP-001": {
        "rule_id": "RULE-BISAP-001",
        "name": "BISAP",
        "full_name": "Bedside Index for Severity in Acute Pancreatitis",
        "category": "gi",
        "description": "5-criterion mortality score for acute pancreatitis; >=3 high risk.",
        "variables": tuple(
            {"name": name, "min_value": 0, "max_value": 1}
            for name in (
                "BUN > 25 mg/dL",
                "Impaired mental status",
                "SIRS >= 2",
                "Age > 60",
                "Pleural effusion",
            )
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 2,
                "risk_level": "low",
                "recommendation": "<=1.9% mortality.",
            },
            {
                "min_score": 3,
                "max_score": 5,
                "risk_level": "high",
                "recommendation": ">=5.3% mortality; ICU consideration.",
            },
        ),
        "condition_refs": ("PANCREATITIS",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1956/bisap-score-pancreatitis-mortality",
    },
    "RULE-GLASGOW-IMRIE-001": {
        "rule_id": "RULE-GLASGOW-IMRIE-001",
        "name": "Glasgow-Imrie",
        "full_name": "Glasgow-Imrie Score for Pancreatitis",
        "category": "gi",
        "description": "Severity of acute pancreatitis at 48h; >=3 = severe.",
        "variables": tuple(
            {"name": name, "min_value": 0, "max_value": 1}
            for name in (
                "PaO2 < 60 mmHg",
                "Age > 55",
                "WBC > 15K",
                "Calcium < 8 mg/dL",
                "BUN > 45 mg/dL",
                "LDH > 600 U/L",
                "Albumin < 3.2 g/dL",
                "Glucose > 180 mg/dL",
            )
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 2,
                "risk_level": "low",
                "recommendation": "Mild pancreatitis; ward admission.",
            },
            {
                "min_score": 3,
                "max_score": 8,
                "risk_level": "high",
                "recommendation": "Severe pancreatitis; ICU consideration.",
            },
        ),
        "condition_refs": ("PANCREATITIS",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1957/glasgow-imrie-criteria-severity-acute-pancreatitis",
    },
    # ----------------------------------------------------------------
    # Heparin-induced thrombocytopenia
    # ----------------------------------------------------------------
    "RULE-4TS-001": {
        "rule_id": "RULE-4TS-001",
        "name": "4Ts Score",
        "full_name": "4Ts Score for Heparin-Induced Thrombocytopenia",
        "category": "hematologic",
        "description": "Pretest probability of HIT; >=6 = high probability.",
        "variables": (
            {"name": "Thrombocytopenia magnitude", "min_value": 0, "max_value": 2},
            {"name": "Timing of platelet count fall", "min_value": 0, "max_value": 2},
            {"name": "Thrombosis or other sequelae", "min_value": 0, "max_value": 2},
            {"name": "Other causes of thrombocytopenia", "min_value": 0, "max_value": 2},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 3,
                "risk_level": "low",
                "recommendation": "<=5% HIT probability; alternative diagnosis.",
            },
            {
                "min_score": 4,
                "max_score": 5,
                "risk_level": "moderate",
                "recommendation": "~14% HIT probability; send anti-PF4 antibody.",
            },
            {
                "min_score": 6,
                "max_score": 8,
                "risk_level": "high",
                "recommendation": "~64% HIT probability; stop heparin, alternative anticoag.",
            },
        ),
        "condition_refs": ("HIT",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1787/4ts-score-heparin-induced-thrombocytopenia",
    },
    # ----------------------------------------------------------------
    # Acute MI severity
    # ----------------------------------------------------------------
    "RULE-KILLIP-001": {
        "rule_id": "RULE-KILLIP-001",
        "name": "Killip Class",
        "full_name": "Killip Classification for Acute MI",
        "category": "cardiac",
        "description": "Hemodynamic severity at MI presentation; Class I-IV by exam.",
        "variables": (
            {
                "name": "Killip class number (I=0, II=1, III=2, IV=3)",
                "min_value": 0,
                "max_value": 3,
            },
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 0,
                "risk_level": "low",
                "recommendation": "Class I; no signs of CHF; 6% 30-day mortality.",
            },
            {
                "min_score": 1,
                "max_score": 1,
                "risk_level": "moderate",
                "recommendation": "Class II; rales/S3; 17% 30-day mortality.",
            },
            {
                "min_score": 2,
                "max_score": 2,
                "risk_level": "high",
                "recommendation": "Class III; pulmonary edema; 38% 30-day mortality.",
            },
            {
                "min_score": 3,
                "max_score": 3,
                "risk_level": "very_high",
                "recommendation": "Class IV; cardiogenic shock; 81% 30-day mortality.",
            },
        ),
        "condition_refs": ("ACS",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1141/killip-classification-heart-failure",
    },
    # ----------------------------------------------------------------
    # Febrile neutropenia risk
    # ----------------------------------------------------------------
    "RULE-MASCC-001": {
        "rule_id": "RULE-MASCC-001",
        "name": "MASCC",
        "full_name": "Multinational Association for Supportive Care in Cancer Risk Index",
        "category": "infectious",
        "description": "Low-risk febrile neutropenia (>=21 = low risk for outpatient mgmt).",
        "variables": (
            {
                "name": "Burden of illness (no/mild=5; moderate=3; severe=0)",
                "min_value": 0,
                "max_value": 5,
            },
            {"name": "No hypotension", "min_value": 0, "max_value": 5},
            {"name": "No COPD", "min_value": 0, "max_value": 4},
            {"name": "Solid tumor or no prior fungal", "min_value": 0, "max_value": 4},
            {"name": "No dehydration requiring IV fluids", "min_value": 0, "max_value": 3},
            {"name": "Outpatient at fever onset", "min_value": 0, "max_value": 3},
            {"name": "Age < 60", "min_value": 0, "max_value": 2},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 20,
                "risk_level": "high",
                "recommendation": "High risk; admit, IV antibiotics.",
            },
            {
                "min_score": 21,
                "max_score": 26,
                "risk_level": "low",
                "recommendation": "Low risk; consider outpatient oral antibiotics.",
            },
        ),
        "condition_refs": ("FEBRILE_NEUTROPENIA",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/3917/mascc-risk-index-febrile-neutropenia",
    },
    # ----------------------------------------------------------------
    # Chest pain (primary care / triage rule-out)
    # ----------------------------------------------------------------
    "RULE-MARBURG-001": {
        "rule_id": "RULE-MARBURG-001",
        "name": "Marburg Heart Score",
        "full_name": "Marburg Heart Score for Chest Pain in Primary Care",
        "category": "cardiac",
        "description": "Chest pain CAD likelihood in outpatient/triage; >=3 = high probability.",
        "variables": tuple(
            {"name": name, "min_value": 0, "max_value": 1}
            for name in (
                "Female age >=65 OR male age >=55",
                "Known CAD/cerebrovascular disease/PAD",
                "Pain worse with exercise",
                "Pain not reproducible by palpation",
                "Patient assumes heart-related",
            )
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 2,
                "risk_level": "low",
                "recommendation": "<=1% CAD probability; outpatient evaluation.",
            },
            {
                "min_score": 3,
                "max_score": 5,
                "risk_level": "high",
                "recommendation": ">=23% CAD probability; expedited cardiology referral.",
            },
        ),
        "condition_refs": ("ACS",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/3915/marburg-heart-score-mhs",
    },
    "RULE-INTERCHEST-001": {
        "rule_id": "RULE-INTERCHEST-001",
        "name": "INTERCHEST",
        "full_name": "INTERCHEST Score for Chest Pain in Primary Care",
        "category": "cardiac",
        "description": "Likelihood of CAD-related chest pain in primary-care chest pain.",
        "variables": (
            {"name": "Age (M >=55 / F >=65)", "min_value": 0, "max_value": 1},
            {"name": "Known CAD", "min_value": 0, "max_value": 1},
            {"name": "Pain worse with exercise", "min_value": 0, "max_value": 1},
            {"name": "Pain not reproducible by palpation", "min_value": 0, "max_value": 1},
            {"name": "Patient assumes heart-related", "min_value": 0, "max_value": 1},
            {"name": "Pressure-like chest discomfort", "min_value": 0, "max_value": 1},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 1,
                "risk_level": "low",
                "recommendation": "<=2% CAD probability.",
            },
            {
                "min_score": 2,
                "max_score": 3,
                "risk_level": "moderate",
                "recommendation": "5-10% CAD probability; outpatient stress.",
            },
            {
                "min_score": 4,
                "max_score": 6,
                "risk_level": "high",
                "recommendation": ">=43% CAD probability; expedited workup.",
            },
        ),
        "condition_refs": ("ACS",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/10148/interchest-clinical-prediction-rule-chest-pain-primary-care",
    },
    # ----------------------------------------------------------------
    # MELD-Na (regression scoring strategy demonstration)
    # ----------------------------------------------------------------
    "RULE-MELD-NA-001": {
        "rule_id": "RULE-MELD-NA-001",
        "name": "MELD-Na",
        "full_name": "MELD-Na Score for End-Stage Liver Disease",
        "category": "gi",
        "description": (
            "Regression-based 90-day mortality predictor in cirrhosis; uses "
            "natural-log transforms of creatinine/bilirubin/INR plus a Na "
            "correction. Computed by the ``meld_na`` scoring strategy, not "
            "additive sum."
        ),
        "scorer": "meld_na",
        "variables": (
            {"name": "Creatinine (mg/dL)", "min_value": 0.0, "max_value": 4.0},
            {"name": "Bilirubin (mg/dL)", "min_value": 0.0, "max_value": 50.0},
            {"name": "INR", "min_value": 0.5, "max_value": 10.0},
            {"name": "Sodium (mmol/L)", "min_value": 100.0, "max_value": 150.0},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 9,
                "risk_level": "low",
                "recommendation": "<=2% 90-day mortality.",
            },
            {
                "min_score": 10,
                "max_score": 19,
                "risk_level": "moderate",
                "recommendation": "6-9% 90-day mortality.",
            },
            {
                "min_score": 20,
                "max_score": 29,
                "risk_level": "high",
                "recommendation": "20-30% 90-day mortality.",
            },
            {
                "min_score": 30,
                "max_score": 39,
                "risk_level": "very_high",
                "recommendation": "53-67% 90-day mortality; transplant evaluation.",
            },
            {
                "min_score": 40,
                "max_score": 99,
                "risk_level": "extreme",
                "recommendation": ">71% 90-day mortality; urgent transplant evaluation.",
            },
        ),
        "condition_refs": ("CIRRHOSIS",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/78/meld-score-original-pre-2016-model-end-stage-liver-disease",
    },
    # ----------------------------------------------------------------
    # Blunt thoracic trauma (chest CT decision)
    # ----------------------------------------------------------------
    "RULE-NEXUS-CHEST-001": {
        "rule_id": "RULE-NEXUS-CHEST-001",
        "name": "NEXUS Chest Decision Instrument",
        "full_name": "NEXUS Chest Decision Instrument for Blunt Thoracic Trauma",
        "category": "trauma",
        "description": (
            "7 binary criteria; >=1 positive = imaging indicated. "
            "98.8% sensitivity for thoracic injury."
        ),
        "variables": tuple(
            {"name": name, "min_value": 0, "max_value": 1}
            for name in (
                "Age > 60",
                "Rapid deceleration mechanism",
                "Chest pain",
                "Intoxication",
                "Altered mental status",
                "Distracting injury",
                "Tenderness to chest wall palpation",
            )
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 0,
                "risk_level": "low",
                "recommendation": "All criteria absent; chest imaging not indicated.",
            },
            {
                "min_score": 1,
                "max_score": 7,
                "risk_level": "high",
                "recommendation": ">=1 criterion positive; chest CT or CXR indicated.",
            },
        ),
        "condition_refs": ("THORACIC_TRAUMA",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/3009/nexus-chest-decision-instrument-blunt-chest-trauma",
    },
    # ----------------------------------------------------------------
    # Pneumonia severity (Japanese alternative to CURB-65)
    # ----------------------------------------------------------------
    "RULE-A-DROP-001": {
        "rule_id": "RULE-A-DROP-001",
        "name": "A-DROP",
        "full_name": "A-DROP Score for Community-Acquired Pneumonia",
        "category": "pulmonary",
        "description": (
            "Japanese Respiratory Society modification of CURB-65; 5 binary "
            "criteria, 30-day mortality risk by count."
        ),
        "variables": tuple(
            {"name": name, "min_value": 0, "max_value": 1}
            for name in (
                "Age (M >= 70 / F >= 75)",
                "Dehydration (BUN >= 21 mg/dL)",
                "Respiratory failure (SpO2 <= 90%)",
                "Orientation disturbance",
                "Low blood pressure (SBP <= 90)",
            )
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 0,
                "risk_level": "low",
                "recommendation": "Mild; outpatient management.",
            },
            {
                "min_score": 1,
                "max_score": 2,
                "risk_level": "moderate",
                "recommendation": "Moderate; admit ward.",
            },
            {
                "min_score": 3,
                "max_score": 4,
                "risk_level": "high",
                "recommendation": "Severe; ICU consideration.",
            },
            {
                "min_score": 5,
                "max_score": 5,
                "risk_level": "very_high",
                "recommendation": "Extremely severe; ICU.",
            },
        ),
        "condition_refs": ("PNEUMONIA",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/10169/a-drop-score-community-acquired-pneumonia",
    },
    # ----------------------------------------------------------------
    # PE intermediate-risk subgrouping
    # ----------------------------------------------------------------
    "RULE-BOVA-001": {
        "rule_id": "RULE-BOVA-001",
        "name": "Bova Score",
        "full_name": "Bova Score for PE Complications in Hemodynamically Stable Patients",
        "category": "pulmonary",
        "description": (
            "Subgrades intermediate-risk PE (sPESI >=1, hemodynamically stable) "
            "into stages I-III by 30-day complications/mortality."
        ),
        "variables": (
            {"name": "Heart rate >= 110", "min_value": 0, "max_value": 1},
            {"name": "Systolic BP 90-100", "min_value": 0, "max_value": 2},
            {"name": "Elevated cardiac troponin", "min_value": 0, "max_value": 2},
            {"name": "RV dysfunction on imaging", "min_value": 0, "max_value": 2},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 2,
                "risk_level": "low",
                "recommendation": "Stage I; 4.4% 30-day complications.",
            },
            {
                "min_score": 3,
                "max_score": 4,
                "risk_level": "moderate",
                "recommendation": "Stage II; 18% 30-day complications.",
            },
            {
                "min_score": 5,
                "max_score": 7,
                "risk_level": "high",
                "recommendation": "Stage III; 42% 30-day complications; ICU.",
            },
        ),
        "condition_refs": ("PE",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/4044/bova-score-pulmonary-embolism-complications",
    },
    # ----------------------------------------------------------------
    # Chest pain triage without troponin (HEART without the T)
    # ----------------------------------------------------------------
    "RULE-HEAR-001": {
        "rule_id": "RULE-HEAR-001",
        "name": "HEAR Score",
        "full_name": "HEAR Score for Chest Pain (HEART without troponin)",
        "category": "cardiac",
        "description": (
            "Pre-troponin chest-pain triage; 0-1 = MACE rule-out (~99% NPV) without lab testing."
        ),
        "variables": (
            {"name": "History suspicious", "min_value": 0, "max_value": 2},
            {"name": "ECG findings", "min_value": 0, "max_value": 2},
            {"name": "Age tier", "min_value": 0, "max_value": 2},
            {"name": "Risk factors", "min_value": 0, "max_value": 2},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 1,
                "risk_level": "low",
                "recommendation": "<2% 30-day MACE; no troponin needed in selected cohorts.",
            },
            {
                "min_score": 2,
                "max_score": 4,
                "risk_level": "moderate",
                "recommendation": "Equivocal; obtain troponin and apply HEART.",
            },
            {
                "min_score": 5,
                "max_score": 8,
                "risk_level": "high",
                "recommendation": "High-risk; obtain troponin and admit/observe.",
            },
        ),
        "condition_refs": ("ACS",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/10153/hear-score-major-cardiac-events",
    },
    # ----------------------------------------------------------------
    # Depression screen
    # ----------------------------------------------------------------
    "RULE-PHQ9-001": {
        "rule_id": "RULE-PHQ9-001",
        "name": "PHQ-9",
        "full_name": "Patient Health Questionnaire-9 for Depression Severity",
        "category": "psychiatric",
        "description": (
            "9 items, 0-3 each (frequency over past 2 weeks); total 0-27. "
            "Score 5 = mild, 10 = moderate, 15 = moderately severe, 20+ = severe."
        ),
        "variables": tuple(
            {"name": f"PHQ-9 item {i}", "min_value": 0, "max_value": 3} for i in range(1, 10)
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 4,
                "risk_level": "low",
                "recommendation": "No-minimal depression.",
            },
            {
                "min_score": 5,
                "max_score": 9,
                "risk_level": "moderate",
                "recommendation": "Mild; PCP follow-up.",
            },
            {
                "min_score": 10,
                "max_score": 14,
                "risk_level": "high",
                "recommendation": "Moderate; treatment consideration.",
            },
            {
                "min_score": 15,
                "max_score": 19,
                "risk_level": "very_high",
                "recommendation": "Moderately severe; active treatment indicated.",
            },
            {
                "min_score": 20,
                "max_score": 27,
                "risk_level": "extreme",
                "recommendation": "Severe; immediate treatment, consider hospitalization.",
            },
        ),
        "condition_refs": ("DEPRESSION",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1725/phq-9-patient-health-questionnaire-9",
    },
    # ----------------------------------------------------------------
    # Pediatric Appendicitis
    # ----------------------------------------------------------------
    "RULE-PAS-001": {
        "rule_id": "RULE-PAS-001",
        "name": "Pediatric Appendicitis Score (PAS)",
        "full_name": "Pediatric Appendicitis Score",
        "category": "gi",
        "description": "Pediatric appendicitis likelihood; 0-3 unlikely, 7-10 likely.",
        "variables": (
            {"name": "Cough/percussion/hopping tenderness", "min_value": 0, "max_value": 2},
            {"name": "Anorexia", "min_value": 0, "max_value": 1},
            {"name": "Pyrexia (>= 38C)", "min_value": 0, "max_value": 1},
            {"name": "Nausea/emesis", "min_value": 0, "max_value": 1},
            {"name": "RLQ tenderness", "min_value": 0, "max_value": 2},
            {"name": "Leukocytosis (WBC > 10K)", "min_value": 0, "max_value": 1},
            {"name": "Polymorphonuclear neutrophilia (>75%)", "min_value": 0, "max_value": 1},
            {"name": "Migration of pain to RLQ", "min_value": 0, "max_value": 1},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 3,
                "risk_level": "low",
                "recommendation": "Unlikely appendicitis; observation/discharge.",
            },
            {
                "min_score": 4,
                "max_score": 6,
                "risk_level": "moderate",
                "recommendation": "Equivocal; imaging or surgical consult.",
            },
            {
                "min_score": 7,
                "max_score": 10,
                "risk_level": "high",
                "recommendation": "Likely appendicitis; surgical evaluation.",
            },
        ),
        "condition_refs": ("APPENDICITIS_PEDS",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/2059/pediatric-appendicitis-score-pas",
    },
    # ----------------------------------------------------------------
    # Revised Geneva Score (PE; alternative to Wells)
    # ----------------------------------------------------------------
    "RULE-GENEVA-REV-001": {
        "rule_id": "RULE-GENEVA-REV-001",
        "name": "Geneva Score (Revised)",
        "full_name": "Revised Geneva Score for Pulmonary Embolism",
        "category": "pulmonary",
        "description": (
            "Pretest probability of PE; alternative to Wells. Fully objective "
            "(no clinical-gestalt component)."
        ),
        "variables": (
            {"name": "Age > 65", "min_value": 0, "max_value": 1},
            {"name": "Previous DVT or PE", "min_value": 0, "max_value": 3},
            {"name": "Surgery or fracture in past month", "min_value": 0, "max_value": 2},
            {"name": "Active malignancy", "min_value": 0, "max_value": 2},
            {"name": "Unilateral lower limb pain", "min_value": 0, "max_value": 3},
            {"name": "Hemoptysis", "min_value": 0, "max_value": 2},
            {"name": "Heart rate 75-94", "min_value": 0, "max_value": 3},
            {"name": "Heart rate >= 95", "min_value": 0, "max_value": 5},
            {
                "name": "Pain on lower limb deep palpation and unilateral edema",
                "min_value": 0,
                "max_value": 4,
            },
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 3,
                "risk_level": "low",
                "recommendation": "8% PE prevalence; D-dimer; if negative, PE excluded.",
            },
            {
                "min_score": 4,
                "max_score": 10,
                "risk_level": "moderate",
                "recommendation": "29% PE prevalence; D-dimer; if positive, CTPA.",
            },
            {
                "min_score": 11,
                "max_score": 25,
                "risk_level": "high",
                "recommendation": "74% PE prevalence; CTPA indicated.",
            },
        ),
        "condition_refs": ("PE",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1750/geneva-score-revised-pulmonary-embolism",
    },
    # ----------------------------------------------------------------
    # CART Score (cardiac arrest risk on wards)
    # ----------------------------------------------------------------
    "RULE-CART-001": {
        "rule_id": "RULE-CART-001",
        "name": "CART Score",
        "full_name": "Cardiac Arrest Risk Triage Score",
        "category": "general",
        "description": (
            "Predicts in-hospital cardiac arrest from RR/HR/DBP/Age points. "
            "Scores >=20 = high risk, ICU consideration."
        ),
        "variables": (
            {"name": "Respiratory rate points", "min_value": 0, "max_value": 22},
            {"name": "Heart rate points", "min_value": 0, "max_value": 13},
            {"name": "Diastolic BP points", "min_value": 0, "max_value": 23},
            {"name": "Age points", "min_value": 0, "max_value": 9},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 9,
                "risk_level": "low",
                "recommendation": "Low; routine ward.",
            },
            {
                "min_score": 10,
                "max_score": 19,
                "risk_level": "moderate",
                "recommendation": "Moderate; intensify monitoring.",
            },
            {
                "min_score": 20,
                "max_score": 67,
                "risk_level": "high",
                "recommendation": "High; rapid response / ICU consideration.",
            },
        ),
        "condition_refs": (),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/4055/cart-cardiac-arrest-risk-triage-score",
    },
    # ----------------------------------------------------------------
    # Pediatric early warning
    # ----------------------------------------------------------------
    "RULE-PEWS-001": {
        "rule_id": "RULE-PEWS-001",
        "name": "PEWS",
        "full_name": "Pediatric Early Warning Score",
        "category": "general",
        "description": "Pediatric clinical-deterioration screen; 3 sub-scores 0-3 each.",
        "variables": (
            {"name": "Behavior", "min_value": 0, "max_value": 3},
            {"name": "Cardiovascular", "min_value": 0, "max_value": 3},
            {"name": "Respiratory", "min_value": 0, "max_value": 3},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 2,
                "risk_level": "low",
                "recommendation": "Routine pediatric ward observation.",
            },
            {
                "min_score": 3,
                "max_score": 4,
                "risk_level": "moderate",
                "recommendation": "Increase monitoring; nursing reassessment.",
            },
            {
                "min_score": 5,
                "max_score": 9,
                "risk_level": "high",
                "recommendation": "Urgent senior review; consider pediatric ICU.",
            },
        ),
        "condition_refs": (),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/2070/brighton-pediatric-early-warning-score-pews",
    },
    # ----------------------------------------------------------------
    # Frailty (peri-procedural / surgical risk)
    # ----------------------------------------------------------------
    "RULE-MFI5-001": {
        "rule_id": "RULE-MFI5-001",
        "name": "mFI-5",
        "full_name": "Modified Frailty Index (5-item)",
        "category": "general",
        "description": (
            "5 binary comorbidities; >=2 predicts post-op morbidity, mortality, "
            "and prolonged length of stay."
        ),
        "variables": tuple(
            {"name": name, "min_value": 0, "max_value": 1}
            for name in (
                "Functional dependence",
                "Diabetes mellitus",
                "COPD or pneumonia",
                "Congestive heart failure",
                "Hypertension requiring medication",
            )
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 1,
                "risk_level": "low",
                "recommendation": "Robust; standard surgical/procedural pathway.",
            },
            {
                "min_score": 2,
                "max_score": 3,
                "risk_level": "moderate",
                "recommendation": "Pre-frail; optimize comorbidities, geriatric input.",
            },
            {
                "min_score": 4,
                "max_score": 5,
                "risk_level": "high",
                "recommendation": "Frail; high post-op risk; shared decision-making.",
            },
        ),
        "condition_refs": (),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/10043/modified-frailty-index-mfi-5",
    },
    # ----------------------------------------------------------------
    # Alcohol/substance screens
    # ----------------------------------------------------------------
    "RULE-CAGE-001": {
        "rule_id": "RULE-CAGE-001",
        "name": "CAGE",
        "full_name": "CAGE Questionnaire for Alcohol Use Disorder",
        "category": "psychiatric",
        "description": "4 yes/no questions; >=2 = clinically significant alcohol use disorder.",
        "variables": tuple(
            {"name": name, "min_value": 0, "max_value": 1}
            for name in (
                "Cut down (felt need to)",
                "Annoyed by criticism",
                "Guilty about drinking",
                "Eye-opener (morning drink)",
            )
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 1,
                "risk_level": "low",
                "recommendation": "Negative; routine screening.",
            },
            {
                "min_score": 2,
                "max_score": 4,
                "risk_level": "high",
                "recommendation": "Positive; full alcohol-use evaluation.",
            },
        ),
        "condition_refs": ("ALCOHOL_USE_DISORDER",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/3198/cage-questions-alcohol-use",
    },
    "RULE-AUDIT-C-001": {
        "rule_id": "RULE-AUDIT-C-001",
        "name": "AUDIT-C",
        "full_name": "Alcohol Use Disorders Identification Test - Consumption",
        "category": "psychiatric",
        "description": (
            "3 items, 0-4 each; cutoffs M >=4 / F >=3 = positive screen for hazardous drinking."
        ),
        "variables": (
            {"name": "Frequency of drinking", "min_value": 0, "max_value": 4},
            {"name": "Drinks per typical drinking day", "min_value": 0, "max_value": 4},
            {"name": "Frequency of >=6 drinks on one occasion", "min_value": 0, "max_value": 4},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 2,
                "risk_level": "low",
                "recommendation": "Negative; routine screening.",
            },
            {
                "min_score": 3,
                "max_score": 4,
                "risk_level": "moderate",
                "recommendation": "Positive in women; possible hazardous drinking.",
            },
            {
                "min_score": 5,
                "max_score": 12,
                "risk_level": "high",
                "recommendation": (
                    "Positive; high probability of alcohol use disorder; brief intervention."
                ),
            },
        ),
        "condition_refs": ("ALCOHOL_USE_DISORDER",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1990/audit-c-alcohol-use",
    },
    # ----------------------------------------------------------------
    # Sleep apnea screen (used in pre-op / ED triage of OSA)
    # ----------------------------------------------------------------
    "RULE-STOP-BANG-001": {
        "rule_id": "RULE-STOP-BANG-001",
        "name": "STOP-BANG",
        "full_name": "STOP-BANG Score for Obstructive Sleep Apnea",
        "category": "pulmonary",
        "description": "8 yes/no items; >=3 high probability of OSA.",
        "variables": tuple(
            {"name": name, "min_value": 0, "max_value": 1}
            for name in (
                "Snoring loudly",
                "Tired/fatigued daily",
                "Observed apnea",
                "Pressure (high BP)",
                "BMI > 35",
                "Age > 50",
                "Neck circumference > 40 cm",
                "Gender male",
            )
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 2,
                "risk_level": "low",
                "recommendation": "Low probability OSA.",
            },
            {
                "min_score": 3,
                "max_score": 4,
                "risk_level": "moderate",
                "recommendation": "Intermediate probability; consider sleep study.",
            },
            {
                "min_score": 5,
                "max_score": 8,
                "risk_level": "high",
                "recommendation": "High probability OSA; sleep study indicated.",
            },
        ),
        "condition_refs": ("OSA",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/3992/stop-bang-score-obstructive-sleep-apnea",
    },
    # ----------------------------------------------------------------
    # Readmission risk
    # ----------------------------------------------------------------
    "RULE-LACE-001": {
        "rule_id": "RULE-LACE-001",
        "name": "LACE Score",
        "full_name": "LACE Index for Readmission",
        "category": "general",
        "description": (
            "30-day readmission/death prediction based on Length, Acuity, Comorbidities, ED visits."
        ),
        "variables": (
            {"name": "Length of stay points", "min_value": 0, "max_value": 7},
            {"name": "Acuity of admission (emergent)", "min_value": 0, "max_value": 3},
            {"name": "Charlson comorbidity points", "min_value": 0, "max_value": 5},
            {"name": "ED visits in past 6 months points", "min_value": 0, "max_value": 4},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 4,
                "risk_level": "low",
                "recommendation": "Low (<5%) 30-day readmission/death.",
            },
            {
                "min_score": 5,
                "max_score": 9,
                "risk_level": "moderate",
                "recommendation": "Moderate (8-12%); transitions-of-care follow-up.",
            },
            {
                "min_score": 10,
                "max_score": 19,
                "risk_level": "high",
                "recommendation": "High (>=15%); intensive discharge planning.",
            },
        ),
        "condition_refs": (),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/3805/lace-index-readmission",
    },
    "RULE-HOSPITAL-001": {
        "rule_id": "RULE-HOSPITAL-001",
        "name": "HOSPITAL Score",
        "full_name": "HOSPITAL Score for Readmissions",
        "category": "general",
        "description": "30-day potentially avoidable readmission risk.",
        "variables": (
            {"name": "Hemoglobin < 12 g/dL at discharge", "min_value": 0, "max_value": 1},
            {"name": "Discharge from oncology service", "min_value": 0, "max_value": 2},
            {"name": "Sodium < 135 at discharge", "min_value": 0, "max_value": 1},
            {"name": "Procedure during hospitalization", "min_value": 0, "max_value": 1},
            {"name": "Index admission type (urgent)", "min_value": 0, "max_value": 1},
            {"name": ">=1 admission in past year", "min_value": 0, "max_value": 5},
            {"name": "Length of stay >= 5 days", "min_value": 0, "max_value": 2},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 4,
                "risk_level": "low",
                "recommendation": "<6% 30-day potentially-avoidable readmission.",
            },
            {
                "min_score": 5,
                "max_score": 6,
                "risk_level": "moderate",
                "recommendation": "9-13% readmission; standard transitions.",
            },
            {
                "min_score": 7,
                "max_score": 13,
                "risk_level": "high",
                "recommendation": ">=18% readmission; intensive transitions.",
            },
        ),
        "condition_refs": (),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/3978/hospital-score-readmissions",
    },
    # ----------------------------------------------------------------
    # ACS in-hospital bleeding risk
    # ----------------------------------------------------------------
    "RULE-CRUSADE-001": {
        "rule_id": "RULE-CRUSADE-001",
        "name": "CRUSADE Score",
        "full_name": "CRUSADE Score for Major Bleeding in NSTEMI",
        "category": "cardiac",
        "description": (
            "In-hospital major-bleeding risk in NSTEMI patients receiving anticoagulation."
        ),
        "variables": (
            {"name": "Baseline hematocrit points", "min_value": 0, "max_value": 9},
            {"name": "Creatinine clearance points", "min_value": 0, "max_value": 39},
            {"name": "Heart rate points", "min_value": 0, "max_value": 11},
            {"name": "Female sex", "min_value": 0, "max_value": 8},
            {"name": "Signs of CHF at presentation", "min_value": 0, "max_value": 7},
            {"name": "Prior vascular disease", "min_value": 0, "max_value": 6},
            {"name": "Diabetes", "min_value": 0, "max_value": 6},
            {"name": "Systolic BP points", "min_value": 0, "max_value": 10},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 20,
                "risk_level": "low",
                "recommendation": "Very low bleeding risk (3.1%).",
            },
            {
                "min_score": 21,
                "max_score": 30,
                "risk_level": "moderate",
                "recommendation": "Low (5.5%); standard anticoagulation.",
            },
            {
                "min_score": 31,
                "max_score": 40,
                "risk_level": "high",
                "recommendation": "Moderate (8.6%); careful anticoag selection.",
            },
            {
                "min_score": 41,
                "max_score": 50,
                "risk_level": "very_high",
                "recommendation": "High (11.9%); minimize anticoagulation.",
            },
            {
                "min_score": 51,
                "max_score": 96,
                "risk_level": "extreme",
                "recommendation": "Very high (19.5%); reconsider invasive strategy.",
            },
        ),
        "condition_refs": ("ACS",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/1873/crusade-score-post-mi-bleeding-risk",
    },
    # ----------------------------------------------------------------
    # Geriatric depression
    # ----------------------------------------------------------------
    "RULE-GDS15-001": {
        "rule_id": "RULE-GDS15-001",
        "name": "GDS-15",
        "full_name": "Geriatric Depression Scale (15-item)",
        "category": "psychiatric",
        "description": "Depression screen in older adults; >=5 = depression possible.",
        "variables": tuple(
            {"name": f"GDS item {i}", "min_value": 0, "max_value": 1} for i in range(1, 16)
        ),
        "score_ranges": (
            {"min_score": 0, "max_score": 4, "risk_level": "low", "recommendation": "Normal."},
            {
                "min_score": 5,
                "max_score": 9,
                "risk_level": "moderate",
                "recommendation": "Suggestive of depression; further evaluation.",
            },
            {
                "min_score": 10,
                "max_score": 15,
                "risk_level": "high",
                "recommendation": "Indicative of depression; treatment indicated.",
            },
        ),
        "condition_refs": ("DEPRESSION",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/3322/geriatric-depression-scale-gds15",
    },
    # ----------------------------------------------------------------
    # Adult malnutrition
    # ----------------------------------------------------------------
    "RULE-MUST-001": {
        "rule_id": "RULE-MUST-001",
        "name": "MUST",
        "full_name": "Malnutrition Universal Screening Tool",
        "category": "general",
        "description": "Adult inpatient malnutrition screen; 5-step tool by BAPEN.",
        "variables": (
            {"name": "BMI score", "min_value": 0, "max_value": 2},
            {"name": "Weight loss score", "min_value": 0, "max_value": 2},
            {"name": "Acute disease effect score", "min_value": 0, "max_value": 2},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 0,
                "risk_level": "low",
                "recommendation": "Routine clinical care; repeat screening per setting.",
            },
            {
                "min_score": 1,
                "max_score": 1,
                "risk_level": "moderate",
                "recommendation": "Document dietary intake; observe; repeat screening.",
            },
            {
                "min_score": 2,
                "max_score": 6,
                "risk_level": "high",
                "recommendation": "Refer to dietitian; nutrition support plan.",
            },
        ),
        "condition_refs": ("MALNUTRITION",),
        "evidence_level": "validated",
        "url": "https://www.bapen.org.uk/screening-and-must/must",
    },
    # ----------------------------------------------------------------
    # COPD exacerbation mortality
    # ----------------------------------------------------------------
    "RULE-DECAF-001": {
        "rule_id": "RULE-DECAF-001",
        "name": "DECAF",
        "full_name": "DECAF Score for AECOPD Mortality",
        "category": "pulmonary",
        "description": "In-hospital mortality after AECOPD; 0-6 total points.",
        "variables": (
            {"name": "Dyspnea points", "min_value": 0, "max_value": 2},
            {"name": "Eosinopenia", "min_value": 0, "max_value": 1},
            {"name": "Consolidation", "min_value": 0, "max_value": 1},
            {"name": "Acidemia (pH < 7.30)", "min_value": 0, "max_value": 1},
            {"name": "Atrial fibrillation", "min_value": 0, "max_value": 1},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 1,
                "risk_level": "low",
                "recommendation": "Low (1-2%) in-hospital mortality.",
            },
            {
                "min_score": 2,
                "max_score": 2,
                "risk_level": "moderate",
                "recommendation": "Intermediate (8.4%); admit ward.",
            },
            {
                "min_score": 3,
                "max_score": 6,
                "risk_level": "high",
                "recommendation": "High (>=24%); ICU consideration.",
            },
        ),
        "condition_refs": ("COPD",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/3804/decaf-score-acute-exacerbation-copd",
    },
    # ----------------------------------------------------------------
    # HFNC failure prediction
    # ----------------------------------------------------------------
    "RULE-HACOR-001": {
        "rule_id": "RULE-HACOR-001",
        "name": "HACOR",
        "full_name": "HACOR Score for HFNC/NIV Failure",
        "category": "pulmonary",
        "description": "Likelihood of NIV/HFNC failure at 1h; >5 = high failure rate.",
        "variables": (
            {"name": "Heart rate points", "min_value": 0, "max_value": 1},
            {"name": "Acidosis points", "min_value": 0, "max_value": 4},
            {"name": "Consciousness points", "min_value": 0, "max_value": 4},
            {"name": "Oxygenation points", "min_value": 0, "max_value": 4},
            {"name": "Respiratory rate points", "min_value": 0, "max_value": 2},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 5,
                "risk_level": "low",
                "recommendation": "Low NIV failure (<20%).",
            },
            {
                "min_score": 6,
                "max_score": 10,
                "risk_level": "moderate",
                "recommendation": "Moderate NIV failure (~46%); intensive monitoring.",
            },
            {
                "min_score": 11,
                "max_score": 15,
                "risk_level": "high",
                "recommendation": "High NIV failure (~67%); intubation likely.",
            },
        ),
        "condition_refs": ("RESPIRATORY_FAILURE",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/10112/hacor-score-niv-failure",
    },
    # ----------------------------------------------------------------
    # Manchester ACS rule (MACS)
    # ----------------------------------------------------------------
    "RULE-MACS-001": {
        "rule_id": "RULE-MACS-001",
        "name": "MACS",
        "full_name": "Manchester Acute Coronary Syndromes Decision Rule",
        "category": "cardiac",
        "description": (
            "Pretest probability of ACS in chest-pain patients using H-FABP and clinical signs."
        ),
        "variables": (
            {
                "name": "Heart-type fatty acid binding protein elevated",
                "min_value": 0,
                "max_value": 4,
            },
            {"name": "ECG ischemia", "min_value": 0, "max_value": 2},
            {"name": "Worsening angina", "min_value": 0, "max_value": 1},
            {"name": "Sweating observed", "min_value": 0, "max_value": 2},
            {"name": "Vomiting with pain", "min_value": 0, "max_value": 1},
            {"name": "Systolic BP < 100", "min_value": 0, "max_value": 3},
            {"name": "Pain in right arm/shoulder", "min_value": 0, "max_value": 1},
            {"name": "Hypoperfusion (cool skin)", "min_value": 0, "max_value": 1},
        ),
        "score_ranges": (
            {
                "min_score": 0,
                "max_score": 1,
                "risk_level": "low",
                "recommendation": "Very low ACS (<=2%); discharge possible.",
            },
            {
                "min_score": 2,
                "max_score": 5,
                "risk_level": "moderate",
                "recommendation": "5-30% ACS; serial troponin.",
            },
            {
                "min_score": 6,
                "max_score": 15,
                "risk_level": "high",
                "recommendation": ">=30% ACS; aggressive workup.",
            },
        ),
        "condition_refs": ("ACS",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/4044/macs-rule-acute-coronary-syndromes",
    },
    # ----------------------------------------------------------------
    # Tokyo Guidelines (categorical scoring strategy demonstration)
    # ----------------------------------------------------------------
    "RULE-TOKYO-CHOL-001": {
        "rule_id": "RULE-TOKYO-CHOL-001",
        "name": "Tokyo Guidelines (Cholangitis Severity)",
        "full_name": "Tokyo Guidelines TG18 Severity Grading for Acute Cholangitis",
        "category": "gi",
        "description": (
            "Categorical decision tree: any organ dysfunction (Grade III "
            "criterion) -> severe; else 2+ Grade II criteria -> moderate; "
            "else mild. Computed by the ``tokyo_cholangitis`` strategy."
        ),
        "scorer": "tokyo_cholangitis",
        "variables": (
            {
                "name": "Cardiovascular dysfunction (pressors required)",
                "min_value": 0,
                "max_value": 1,
            },
            {"name": "Neurologic dysfunction (consciousness)", "min_value": 0, "max_value": 1},
            {"name": "Respiratory dysfunction (PaO2/FiO2 < 300)", "min_value": 0, "max_value": 1},
            {"name": "Renal dysfunction (Cr > 2 or oliguria)", "min_value": 0, "max_value": 1},
            {"name": "Hepatic dysfunction (PT-INR > 1.5)", "min_value": 0, "max_value": 1},
            {"name": "Hematologic dysfunction (platelets < 100K)", "min_value": 0, "max_value": 1},
            {"name": "WBC < 4 or > 12", "min_value": 0, "max_value": 1},
            {"name": "Fever >= 39C", "min_value": 0, "max_value": 1},
            {"name": "Age >= 75", "min_value": 0, "max_value": 1},
            {"name": "Total bilirubin >= 5", "min_value": 0, "max_value": 1},
            {"name": "Albumin < 0.7 x lower limit normal", "min_value": 0, "max_value": 1},
        ),
        "score_ranges": (
            {
                "min_score": 1,
                "max_score": 1,
                "risk_level": "low",
                "recommendation": "Grade I (mild); medical management.",
            },
            {
                "min_score": 2,
                "max_score": 2,
                "risk_level": "moderate",
                "recommendation": "Grade II (moderate); urgent biliary drainage.",
            },
            {
                "min_score": 3,
                "max_score": 3,
                "risk_level": "high",
                "recommendation": "Grade III (severe); ICU + emergent biliary drainage.",
            },
        ),
        "condition_refs": ("CHOLANGITIS",),
        "evidence_level": "validated",
        "url": "https://www.mdcalc.com/calc/10231/tokyo-guidelines-acute-cholangitis-2018",
    },
}
