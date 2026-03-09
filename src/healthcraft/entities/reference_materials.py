"""Reference material entity for the HEALTHCRAFT simulation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from healthcraft.entities.base import Entity, EntityType


@dataclass(frozen=True)
class ReferenceMaterial(Entity):
    """Immutable reference material entity for drug monographs, procedure guides,
    dosing references, and clinical guidelines.

    Extends Entity with structured reference content used by the MCP
    searchReferenceMaterials and getReferenceArticle tools.
    """

    ref_id: str = ""
    title: str = ""
    material_type: str = (
        ""  # drug_monograph, procedure_guide, dosing_reference, clinical_guideline, calculator
    )
    category: str = ""
    content: str = ""
    keywords: tuple[str, ...] = ()
    condition_refs: tuple[str, ...] = ()
    drug_name: str = ""
    last_reviewed: str = ""
    source: str = ""


# --- Bundled reference materials (common ED references) ---

_BUNDLED_REFERENCES: dict[str, dict[str, Any]] = {
    "REF-DRUG-001": {
        "ref_id": "REF-DRUG-001",
        "title": "Alteplase (tPA) - Drug Monograph",
        "material_type": "drug_monograph",
        "category": "thrombolytics",
        "drug_name": "alteplase",
        "keywords": ("alteplase", "tPA", "thrombolytic", "fibrinolytic", "stroke", "STEMI", "PE"),
        "condition_refs": ("STROKE_ISCHEMIC", "STEMI", "PULMONARY_EMBOLISM"),
        "last_reviewed": "2025-11-15",
        "source": "Mercy Point Pharmacy",
        "content": (
            "Alteplase (Activase) is a recombinant tissue plasminogen activator indicated for "
            "acute ischemic stroke, acute myocardial infarction, and massive pulmonary embolism. "
            "For acute ischemic stroke, administer 0.9 mg/kg IV (max 90 mg) with 10% as bolus "
            "over 1 minute and the remainder infused over 60 minutes. Must be given within 4.5 "
            "hours of symptom onset (3 hours per FDA label; 4.5 hours per AHA/ASA guidelines "
            "with additional exclusion criteria).\n\n"
            "Absolute contraindications include active internal bleeding, recent intracranial "
            "surgery or serious head trauma within 3 months, intracranial neoplasm, AVM or "
            "aneurysm, known bleeding diathesis, and severe uncontrolled hypertension. For "
            "stroke, additional contraindications include blood glucose < 50 mg/dL, platelet "
            "count < 100,000, INR > 1.7, and extensive early ischemic changes on CT.\n\n"
            "Monitor for angioedema (1-5%), intracranial hemorrhage (6.4% in stroke trials), "
            "and systemic bleeding. Hold all antithrombotics for 24 hours post-administration. "
            "Obtain repeat CT head at 24 hours before starting anticoagulation. Cryoprecipitate "
            "and tranexamic acid are reversal agents for life-threatening bleeding."
        ),
    },
    "REF-DRUG-002": {
        "ref_id": "REF-DRUG-002",
        "title": "Ketamine - Drug Monograph",
        "material_type": "drug_monograph",
        "category": "anesthetics",
        "drug_name": "ketamine",
        "keywords": ("ketamine", "dissociative", "sedation", "RSI", "analgesia", "intubation"),
        "condition_refs": ("FRACTURE", "STATUS_ASTHMATICUS"),
        "last_reviewed": "2025-09-20",
        "source": "Mercy Point Pharmacy",
        "content": (
            "Ketamine is a dissociative anesthetic with analgesic properties used in the ED "
            "for procedural sedation, rapid sequence intubation, and pain management. For "
            "procedural sedation, administer 1-2 mg/kg IV over 1-2 minutes (onset 30-60 "
            "seconds, duration 10-20 minutes) or 4-5 mg/kg IM (onset 3-5 minutes, duration "
            "15-30 minutes). For RSI induction, the standard dose is 1.5-2 mg/kg IV push.\n\n"
            "Ketamine maintains airway reflexes, spontaneous respirations, and cardiovascular "
            "stability, making it advantageous in hemodynamically unstable patients and those "
            "with reactive airway disease. It is the preferred induction agent in status "
            "asthmaticus due to its bronchodilatory properties. Sub-dissociative dosing "
            "(0.1-0.3 mg/kg IV) provides effective analgesia as an opioid alternative.\n\n"
            "Emergence reactions occur in 10-30% of adults (less common in children and "
            "with sub-dissociative doses). Pretreatment with midazolam 0.03 mg/kg IV may "
            "reduce emergence phenomena but is not routinely recommended. Contraindications "
            "include age < 3 months, known psychotic disorders, and conditions where elevated "
            "ICP or IOP is a critical concern, though the historical ICP concern has been "
            "largely debunked in current literature."
        ),
    },
    "REF-DRUG-003": {
        "ref_id": "REF-DRUG-003",
        "title": "Rocuronium - Drug Monograph",
        "material_type": "drug_monograph",
        "category": "neuromuscular_blockers",
        "drug_name": "rocuronium",
        "keywords": (
            "rocuronium",
            "paralytic",
            "neuromuscular blocker",
            "RSI",
            "intubation",
            "sugammadex",
        ),
        "condition_refs": (),
        "last_reviewed": "2025-10-01",
        "source": "Mercy Point Pharmacy",
        "content": (
            "Rocuronium is a non-depolarizing neuromuscular blocking agent used for rapid "
            "sequence intubation and facilitation of mechanical ventilation. For RSI, "
            "administer 1.0-1.2 mg/kg IV push (higher dose provides intubating conditions "
            "in 60 seconds comparable to succinylcholine). Standard maintenance dosing is "
            "0.1-0.2 mg/kg IV as needed.\n\n"
            "Duration of action at RSI dose is 40-70 minutes (longer than succinylcholine's "
            "6-10 minutes). This is a critical consideration when the cannot-intubate-"
            "cannot-oxygenate scenario is anticipated. Sugammadex 16 mg/kg IV provides "
            "complete reversal within 3 minutes and should be immediately available whenever "
            "rocuronium is used for RSI.\n\n"
            "Rocuronium has no cardiovascular effects, no histamine release, and no risk of "
            "hyperkalemia, making it preferred over succinylcholine in patients with burns, "
            "crush injuries, prolonged immobility, renal failure, or neuromuscular disease. "
            "Store at 2-8 degrees C; stable at room temperature for 60 days. Monitor with "
            "train-of-four if repeat dosing anticipated."
        ),
    },
    "REF-DRUG-004": {
        "ref_id": "REF-DRUG-004",
        "title": "Tranexamic Acid (TXA) - Drug Monograph",
        "material_type": "drug_monograph",
        "category": "antifibrinolytics",
        "drug_name": "tranexamic acid",
        "keywords": (
            "tranexamic acid",
            "TXA",
            "antifibrinolytic",
            "hemorrhage",
            "trauma",
            "bleeding",
        ),
        "condition_refs": ("HEMORRHAGE_MASSIVE", "TRAUMA_BLUNT"),
        "last_reviewed": "2025-12-01",
        "source": "Mercy Point Pharmacy",
        "content": (
            "Tranexamic acid (TXA) is a synthetic lysine analog that inhibits fibrinolysis "
            "by blocking plasminogen binding to fibrin. In trauma with significant hemorrhage, "
            "administer 1 g IV over 10 minutes within 3 hours of injury, followed by 1 g IV "
            "infused over 8 hours (CRASH-2 protocol). Do NOT administer bolus faster than "
            "10 minutes due to risk of hypotension.\n\n"
            "The CRASH-2 trial demonstrated a significant reduction in death due to bleeding "
            "(4.9% vs 5.7%, p=0.0077) when administered within 3 hours. Benefit is greatest "
            "when given within 1 hour of injury. Administration after 3 hours is associated "
            "with increased mortality and is contraindicated. The WOMAN trial supports use in "
            "postpartum hemorrhage (1 g IV, repeat once if bleeding continues after 30 min).\n\n"
            "Off-label ED uses include epistaxis (topical 500 mg in 5 mL soaked pledget) and "
            "heavy menstrual bleeding (1.3 g PO TID for up to 5 days). Contraindications "
            "include active thromboembolic disease, DIC with predominant thrombosis, and "
            "hypersensitivity. Use with caution in renal impairment (dose adjust for CrCl "
            "< 30 mL/min). Seizure risk increases at high doses or with renal dysfunction."
        ),
    },
    "REF-DRUG-005": {
        "ref_id": "REF-DRUG-005",
        "title": "Nitroglycerin - Drug Monograph",
        "material_type": "drug_monograph",
        "category": "antianginals",
        "drug_name": "nitroglycerin",
        "keywords": (
            "nitroglycerin",
            "NTG",
            "nitro",
            "chest pain",
            "ACS",
            "hypertensive emergency",
            "CHF",
        ),
        "condition_refs": ("STEMI", "ACS_NSTEMI", "CHF_ACUTE"),
        "last_reviewed": "2025-08-10",
        "source": "Mercy Point Pharmacy",
        "content": (
            "Nitroglycerin is a nitrate vasodilator used for acute coronary syndromes, "
            "acute decompensated heart failure, and hypertensive emergencies with pulmonary "
            "edema. Sublingual: 0.4 mg every 5 minutes x3 doses. IV infusion: start at "
            "5-10 mcg/min, titrate by 5-10 mcg/min every 3-5 minutes to symptom relief or "
            "SBP < 100 mmHg (max 200 mcg/min in most protocols).\n\n"
            "Critical contraindications: SBP < 90 mmHg, recent PDE5 inhibitor use (sildenafil "
            "within 24 hours, tadalafil within 48 hours), known right ventricular infarction, "
            "severe aortic stenosis, and hypertrophic obstructive cardiomyopathy. The right "
            "ventricular infarction contraindication is particularly important in inferior "
            "STEMI -- obtain right-sided ECG (V4R) before administering nitroglycerin.\n\n"
            "For acute pulmonary edema, high-dose IV nitroglycerin (bolus 400 mcg then "
            "infusion at 100+ mcg/min) has evidence supporting improved outcomes compared "
            "to traditional low-dose titration. Monitor blood pressure continuously during "
            "IV infusion. Tolerance develops with continuous use > 24 hours. Use non-PVC "
            "tubing for IV administration (drug adsorbs to PVC)."
        ),
    },
    "REF-PROC-001": {
        "ref_id": "REF-PROC-001",
        "title": "Rapid Sequence Intubation (RSI) - Procedure Guide",
        "material_type": "procedure_guide",
        "category": "procedures",
        "drug_name": "",
        "keywords": ("RSI", "intubation", "airway", "rapid sequence", "paralytic", "induction"),
        "condition_refs": ("RESPIRATORY_FAILURE", "PNEUMOTHORAX_TENSION", "STATUS_EPILEPTICUS"),
        "last_reviewed": "2025-10-15",
        "source": "Mercy Point Emergency Medicine",
        "content": (
            "Rapid sequence intubation is the near-simultaneous administration of an "
            "induction agent and neuromuscular blocker to facilitate endotracheal intubation "
            "while minimizing aspiration risk. The 7 P's framework: Preparation, "
            "Preoxygenation, Pretreatment, Paralysis with induction, Placement with proof, "
            "Post-intubation management, and Planning for failure.\n\n"
            "Preparation: Assess airway difficulty (LEMON, 3-3-2 rule), prepare suction, "
            "BVM, two laryngoscope blades, bougie, ETT (7.0-8.0 for adults), video "
            "laryngoscope, supraglottic airway backup, surgical airway kit. Preoxygenation: "
            "100% O2 via NRB or BVM for 3+ minutes (target EtO2 > 85%). Apneic oxygenation "
            "via 15 L/min NC during attempt. Pretreatment (selective): fentanyl 1-3 mcg/kg "
            "for reactive airway, lidocaine 1.5 mg/kg for elevated ICP.\n\n"
            "Induction and paralysis: Etomidate 0.3 mg/kg or ketamine 1.5-2 mg/kg IV push, "
            "immediately followed by succinylcholine 1.5 mg/kg or rocuronium 1.2 mg/kg IV "
            "push. Wait 45-60 seconds for full paralysis. Confirmation: direct visualization "
            "of cords, EtCO2 waveform (MANDATORY), bilateral breath sounds, chest rise, "
            "CXR. Post-intubation: sedation (propofol, midazolam, or ketamine infusion), "
            "analgesia (fentanyl), ventilator settings (TV 6-8 mL/kg IBW, RR 14-16, "
            "PEEP 5, FiO2 titrate to SpO2 94-98%)."
        ),
    },
    "REF-PROC-002": {
        "ref_id": "REF-PROC-002",
        "title": "Chest Tube Insertion (Tube Thoracostomy) - Procedure Guide",
        "material_type": "procedure_guide",
        "category": "procedures",
        "drug_name": "",
        "keywords": ("chest tube", "tube thoracostomy", "pneumothorax", "hemothorax", "pleural"),
        "condition_refs": ("PNEUMOTHORAX_TENSION", "HEMOTHORAX", "PLEURAL_EFFUSION"),
        "last_reviewed": "2025-07-22",
        "source": "Mercy Point Emergency Medicine",
        "content": (
            "Tube thoracostomy is indicated for pneumothorax (traumatic, tension, or large "
            "spontaneous), hemothorax, large pleural effusion with respiratory compromise, "
            "and empyema. Standard site: 4th or 5th intercostal space at the anterior "
            "axillary line (safe triangle). Use 28-32 Fr for hemothorax/trauma, 20-24 Fr "
            "for pneumothorax, 28 Fr for empyema.\n\n"
            "Technique: Position patient supine with arm abducted to 90 degrees and "
            "externally rotated. Prep and drape. Local anesthesia with 1% lidocaine "
            "(10-20 mL) -- infiltrate skin, subcutaneous tissue, intercostal muscles, and "
            "parietal pleura along the superior border of the rib (avoid neurovascular "
            "bundle at inferior border). Make 3-4 cm transverse incision. Blunt dissect "
            "through intercostal muscles with Kelly clamp. Puncture parietal pleura and "
            "sweep finger to confirm intrapleural position and absence of adhesions.\n\n"
            "Insert tube directed posteriorly and superiorly for pneumothorax, posteriorly "
            "and inferiorly for effusion/hemothorax. Secure with 0-silk suture (horizontal "
            "mattress and ties). Connect to underwater seal or Pleur-evac at -20 cmH2O. "
            "Confirm placement with CXR. Document time, tube size, output character and "
            "volume, and patient tolerance. Complications: intercostal artery injury, "
            "lung parenchymal injury, subcutaneous placement, diaphragm injury."
        ),
    },
    "REF-PROC-003": {
        "ref_id": "REF-PROC-003",
        "title": "Central Venous Catheter Placement - Procedure Guide",
        "material_type": "procedure_guide",
        "category": "procedures",
        "drug_name": "",
        "keywords": (
            "central line",
            "central venous catheter",
            "CVC",
            "IJ",
            "subclavian",
            "femoral",
        ),
        "condition_refs": ("SEPSIS", "HEMORRHAGE_MASSIVE"),
        "last_reviewed": "2025-11-01",
        "source": "Mercy Point Emergency Medicine",
        "content": (
            "Central venous catheter placement provides reliable large-bore access for "
            "vasopressor administration, volume resuscitation, CVP monitoring, and "
            "transvenous pacing. Sites: internal jugular (preferred -- lowest infection "
            "rate with ultrasound guidance), subclavian (lowest catheter-related infection "
            "but pneumothorax risk), femoral (fastest in emergencies but highest infection "
            "rate). Use real-time ultrasound guidance for all IJ and femoral placements.\n\n"
            "Seldinger technique: Position patient (Trendelenburg for IJ/subclavian), prep "
            "with chlorhexidine, full sterile barrier precautions (cap, mask, gown, sterile "
            "gloves, full drape). Identify vessel with ultrasound. Access vein with "
            "introducer needle under real-time guidance. Confirm venous blood (dark, "
            "non-pulsatile). Advance J-wire through needle (NEVER force the wire). Remove "
            "needle, nick skin, advance dilator over wire, remove dilator, thread catheter "
            "over wire. Remove wire (ALWAYS account for the wire). Aspirate and flush all "
            "ports. Secure with suture and sterile dressing.\n\n"
            "Post-procedure: Confirm placement with CXR (tip at cavoatrial junction). "
            "Document indication, site, number of attempts, wire visualization, "
            "complications, and CXR result. Complications: arterial puncture (withdraw and "
            "hold pressure), pneumothorax (subclavian), air embolism (position in "
            "Trendelenburg), arrhythmia (withdraw wire/catheter), infection."
        ),
    },
    "REF-PROC-004": {
        "ref_id": "REF-PROC-004",
        "title": "Lumbar Puncture - Procedure Guide",
        "material_type": "procedure_guide",
        "category": "procedures",
        "drug_name": "",
        "keywords": ("lumbar puncture", "LP", "spinal tap", "CSF", "meningitis", "SAH"),
        "condition_refs": ("MENINGITIS_BACTERIAL", "SAH"),
        "last_reviewed": "2025-06-30",
        "source": "Mercy Point Emergency Medicine",
        "content": (
            "Lumbar puncture is indicated when meningitis, encephalitis, or subarachnoid "
            "hemorrhage is suspected and CT head is non-diagnostic. CT head before LP is "
            "required when: focal neurological deficit, papilledema, altered mental status, "
            "immunocompromised state, age > 60, or history of CNS disease. Do NOT delay "
            "antibiotics for LP if bacterial meningitis is suspected -- obtain blood cultures "
            "and start empiric therapy immediately.\n\n"
            "Technique: Lateral decubitus position (fetal position) or seated with forward "
            "flexion. Identify L3-L4 or L4-L5 interspace (iliac crest landmark = L4 spinous "
            "process). Prep with chlorhexidine, sterile drape. Local anesthesia with 1% "
            "lidocaine (skin wheal, then deeper infiltration). Insert 20-22 gauge spinal "
            "needle with stylet, bevel oriented sagittally, aiming toward umbilicus. Advance "
            "slowly; a 'pop' is felt at the ligamentum flavum and again at the dura. Remove "
            "stylet, observe for CSF flow. Measure opening pressure with manometer.\n\n"
            "Collect 1-2 mL per tube: Tube 1 (cell count and differential), Tube 2 "
            "(protein and glucose), Tube 3 (gram stain, culture, sensitivity), Tube 4 "
            "(cell count -- compare with Tube 1 for traumatic tap). For SAH evaluation, "
            "send Tube 4 for xanthochromia. Normal values: WBC < 5, protein 15-45 mg/dL, "
            "glucose > 40 mg/dL (or CSF:serum ratio > 0.6), opening pressure 6-20 cmH2O. "
            "Post-procedure headache occurs in 10-30%; use atraumatic needle to reduce risk."
        ),
    },
    "REF-DOSE-001": {
        "ref_id": "REF-DOSE-001",
        "title": "Pediatric Emergency Drug Dosing Reference",
        "material_type": "dosing_reference",
        "category": "pediatrics",
        "drug_name": "",
        "keywords": (
            "pediatric",
            "dosing",
            "weight-based",
            "Broselow",
            "children",
            "resuscitation",
        ),
        "condition_refs": (),
        "last_reviewed": "2025-12-15",
        "source": "Mercy Point Pharmacy",
        "content": (
            "All pediatric emergency medications are dosed by weight (kg). If weight "
            "unknown, use Broselow tape or age-based estimation: weight (kg) = (age x 2) + "
            "8 for ages 1-10 years. ALWAYS weigh the child when feasible. Key resuscitation "
            "doses: Epinephrine 0.01 mg/kg IV/IO (0.1 mL/kg of 1:10,000) every 3-5 min; "
            "Epinephrine 0.01 mg/kg IM (0.01 mL/kg of 1:1,000) for anaphylaxis (max "
            "0.3 mg if < 30 kg, 0.5 mg if > 30 kg). Amiodarone 5 mg/kg IV/IO for "
            "pulseless VT/VF (max 300 mg first dose).\n\n"
            "Airway medications: Succinylcholine 2 mg/kg IV (neonates/infants), 1.5 mg/kg "
            "IV (children > 1 year). Rocuronium 1 mg/kg IV for RSI. Etomidate 0.3 mg/kg "
            "IV (age > 10 years). Ketamine 1-2 mg/kg IV for induction, 0.5-1 mg/kg for "
            "procedural sedation. Midazolam 0.1 mg/kg IV (max 5 mg) for seizures. "
            "Atropine 0.02 mg/kg IV (min 0.1 mg, max 0.5 mg child / 1 mg adolescent) -- "
            "use for bradycardia after ensuring adequate oxygenation and ventilation.\n\n"
            "Fluid resuscitation: 20 mL/kg NS or LR bolus, reassess, repeat up to 60 mL/kg. "
            "Dextrose: D10W 5 mL/kg for neonates, D25W 2-4 mL/kg for infants/children. "
            "Blood products: 10 mL/kg pRBC for hemorrhage. Defibrillation: 2 J/kg first "
            "shock, 4 J/kg subsequent. Cardioversion: 0.5-1 J/kg, may increase to 2 J/kg. "
            "ETT size: (age/4) + 3.5 for cuffed tubes. Always have one size larger and "
            "smaller available."
        ),
    },
    "REF-DOSE-002": {
        "ref_id": "REF-DOSE-002",
        "title": "Antibiotic Dosing in Renal Impairment",
        "material_type": "dosing_reference",
        "category": "antibiotics",
        "drug_name": "",
        "keywords": ("antibiotics", "renal", "dosing", "CrCl", "dialysis", "GFR", "adjustment"),
        "condition_refs": ("SEPSIS",),
        "last_reviewed": "2025-09-01",
        "source": "Mercy Point Pharmacy",
        "content": (
            "Renal dose adjustment is critical for aminoglycosides, vancomycin, and many "
            "beta-lactams. Calculate CrCl using Cockcroft-Gault: CrCl = [(140 - age) x "
            "weight (kg)] / (72 x serum Cr) x 0.85 if female. Use actual body weight "
            "unless obese (BMI > 30), then use adjusted body weight. First dose of "
            "antibiotics in sepsis should NOT be adjusted -- give full loading dose "
            "regardless of renal function to achieve therapeutic levels rapidly.\n\n"
            "Common adjustments (CrCl in mL/min): Vancomycin -- load 25-30 mg/kg IV "
            "regardless of renal function, then dose per levels (trough 15-20 for serious "
            "infections, AUC/MIC-guided preferred). Gentamicin -- extend interval: q8h "
            "if CrCl > 80, q12h if 40-80, q24h if 20-40, per levels if < 20. "
            "Piperacillin-tazobactam -- 3.375g q6h if CrCl > 40, 2.25g q6h if 20-40, "
            "2.25g q8h if < 20. Cefepime -- 2g q8h if CrCl > 60, 2g q12h if 30-60, "
            "1g q12h if 11-30, 1g q24h if < 11.\n\n"
            "Hemodialysis considerations: Many antibiotics are dialyzable and require "
            "post-HD supplemental dosing. Vancomycin: re-dose per level after HD. "
            "Cefepime: give supplemental dose after each HD session. Meropenem: give "
            "dose after HD. Fluoroquinolones (levofloxacin, moxifloxacin) and "
            "metronidazole require minimal renal adjustment. Daptomycin: q48h if CrCl "
            "< 30. Always consult pharmacy for complex renal dosing scenarios."
        ),
    },
    "REF-DOSE-003": {
        "ref_id": "REF-DOSE-003",
        "title": "Weight-Based Heparin Protocol",
        "material_type": "dosing_reference",
        "category": "anticoagulants",
        "drug_name": "heparin",
        "keywords": ("heparin", "anticoagulation", "PTT", "weight-based", "DVT", "PE", "ACS"),
        "condition_refs": ("PULMONARY_EMBOLISM", "ACS_NSTEMI", "DVT"),
        "last_reviewed": "2025-10-20",
        "source": "Mercy Point Pharmacy",
        "content": (
            "Weight-based heparin dosing for venous thromboembolism (DVT/PE): Bolus 80 "
            "units/kg IV, then infusion at 18 units/kg/hr. For acute coronary syndromes: "
            "Bolus 60 units/kg IV (max 4,000 units), then infusion at 12 units/kg/hr "
            "(max 1,000 units/hr). Use actual body weight up to 150 kg; for patients "
            "> 150 kg, use 150 kg as dosing weight and consult pharmacy.\n\n"
            "Monitoring: Check aPTT 6 hours after initiation and 6 hours after every dose "
            "change. Target aPTT: 60-80 seconds (1.5-2.5x control) for most indications. "
            "Adjustment nomogram: aPTT < 35 sec -- bolus 80 u/kg, increase rate by 4 "
            "u/kg/hr; aPTT 35-45 -- bolus 40 u/kg, increase by 2 u/kg/hr; aPTT 46-70 -- "
            "no change; aPTT 71-90 -- decrease by 2 u/kg/hr; aPTT > 90 -- hold 1 hour, "
            "decrease by 3 u/kg/hr. Recheck aPTT 6 hours after any change.\n\n"
            "Critical safety considerations: Monitor platelets at baseline and q2-3 days "
            "(HIT risk). If platelet count drops > 50% or below 150,000, send HIT panel "
            "and consider switching to argatroban. Protamine reversal: 1 mg per 100 units "
            "heparin given in last 2-3 hours (max 50 mg slow IV push). Contraindications: "
            "active bleeding, HIT history, severe thrombocytopenia. Hold for invasive "
            "procedures -- aPTT normalizes within 1-2 hours of stopping infusion."
        ),
    },
    "REF-GUIDE-001": {
        "ref_id": "REF-GUIDE-001",
        "title": "Sepsis Management - Surviving Sepsis Campaign Bundle",
        "material_type": "clinical_guideline",
        "category": "infectious",
        "drug_name": "",
        "keywords": (
            "sepsis",
            "septic shock",
            "surviving sepsis",
            "SSC",
            "bundle",
            "qSOFA",
            "lactate",
        ),
        "condition_refs": ("SEPSIS",),
        "last_reviewed": "2025-11-30",
        "source": "ACEP Guidelines",
        "content": (
            "The Surviving Sepsis Campaign (2021 update) Hour-1 Bundle requires the "
            "following to be initiated within 1 hour of sepsis recognition: (1) Measure "
            "lactate level, re-measure if initial lactate > 2 mmol/L; (2) Obtain blood "
            "cultures before antibiotics (do not delay antibiotics if cultures cannot be "
            "obtained promptly); (3) Administer broad-spectrum antibiotics; (4) Begin "
            "rapid administration of 30 mL/kg crystalloid for hypotension or lactate "
            ">= 4 mmol/L; (5) Apply vasopressors if hypotensive during or after fluid "
            "resuscitation to maintain MAP >= 65 mmHg.\n\n"
            "Screening: Use qSOFA (>= 2 of: RR >= 22, altered mentation, SBP <= 100) "
            "as bedside screen; SOFA score for organ dysfunction quantification. Septic "
            "shock = sepsis + vasopressor requirement + lactate > 2 despite adequate "
            "resuscitation. Antibiotic selection: target likely source. Empiric regimens: "
            "unknown source -- vancomycin + piperacillin-tazobactam or meropenem; "
            "urinary -- ceftriaxone or fluoroquinolone; pneumonia -- ceftriaxone + "
            "azithromycin; abdominal -- piperacillin-tazobactam or meropenem + "
            "metronidazole; skin/soft tissue -- vancomycin + piperacillin-tazobactam.\n\n"
            "Reassessment: Dynamic measures (passive leg raise, pulse pressure variation) "
            "preferred over CVP to guide further fluids after initial resuscitation. "
            "Norepinephrine is first-line vasopressor. Add vasopressin 0.03 units/min as "
            "second agent if needed. Consider hydrocortisone 200 mg/day IV if vasopressor "
            "requirements are escalating despite adequate resuscitation. Target lactate "
            "clearance >= 20% per 2 hours."
        ),
    },
    "REF-GUIDE-002": {
        "ref_id": "REF-GUIDE-002",
        "title": "Acute Stroke Pathway - Emergency Department Protocol",
        "material_type": "clinical_guideline",
        "category": "neurological",
        "drug_name": "",
        "keywords": (
            "stroke",
            "tPA",
            "thrombectomy",
            "NIHSS",
            "stroke alert",
            "LVO",
            "last known well",
        ),
        "condition_refs": ("STROKE_ISCHEMIC", "STROKE_HEMORRHAGIC"),
        "last_reviewed": "2025-08-25",
        "source": "ACEP Guidelines",
        "content": (
            "Stroke Alert Activation: Any patient with acute focal neurological deficit "
            "and last known well (LKW) within 24 hours. Immediate actions upon arrival: "
            "ABCs, establish IV access, point-of-care glucose (treat hypoglycemia first), "
            "NIHSS assessment, non-contrast CT head STAT (door-to-CT target < 25 minutes). "
            "Do not lower blood pressure unless > 220/120 (or > 185/110 if tPA candidate). "
            "Nothing by mouth.\n\n"
            "tPA Criteria: Age >= 18, clinical diagnosis of ischemic stroke with measurable "
            "deficit, symptom onset (or LKW) within 4.5 hours. CT must exclude hemorrhage. "
            "Major exclusion criteria: ICH on CT, prior ICH, intracranial surgery/trauma "
            "within 3 months, active bleeding, platelet count < 100,000, INR > 1.7, "
            "aPTT > 40, glucose < 50. Additional 3-4.5 hour exclusions: age > 80, oral "
            "anticoagulant use, NIHSS > 25, history of both stroke and diabetes. "
            "Door-to-needle target: < 60 minutes (ideal < 45 minutes).\n\n"
            "Large Vessel Occlusion (LVO) screening: Consider thrombectomy for NIHSS >= 6, "
            "LVO confirmed on CTA, within 24 hours with favorable perfusion imaging. "
            "Contact neuro-interventional team early if LVO suspected. CTA head/neck should "
            "be obtained concurrently with non-contrast CT and should NOT delay tPA "
            "administration. For hemorrhagic stroke: reverse anticoagulation, lower SBP to "
            "< 140 mmHg, neurosurgery consult, ICU admission. Serial neuro checks q15 min "
            "for first 2 hours, q30 min for next 6 hours."
        ),
    },
    "REF-GUIDE-003": {
        "ref_id": "REF-GUIDE-003",
        "title": "Chest Pain Evaluation - Emergency Department Protocol",
        "material_type": "clinical_guideline",
        "category": "cardiovascular",
        "drug_name": "",
        "keywords": ("chest pain", "ACS", "STEMI", "NSTEMI", "HEART score", "troponin", "ECG"),
        "condition_refs": ("STEMI", "ACS_NSTEMI", "AORTIC_DISSECTION", "PULMONARY_EMBOLISM"),
        "last_reviewed": "2025-10-10",
        "source": "ACEP Guidelines",
        "content": (
            "All chest pain patients require ECG within 10 minutes of arrival. Immediate "
            "assessment: vital signs, oxygen saturation, IV access, cardiac monitor. "
            "STEMI on ECG: activate cath lab immediately (door-to-balloon target < 90 "
            "minutes), aspirin 325 mg, heparin bolus, P2Y12 inhibitor per cardiology, "
            "nitroglycerin (if no contraindication). Do NOT delay cath lab activation for "
            "troponin results in clear STEMI.\n\n"
            "Risk stratification for non-STEMI chest pain: Use HEART score (History, ECG, "
            "Age, Risk factors, Troponin). Score 0-3: low risk, consider discharge with "
            "outpatient follow-up after negative serial troponins. Score 4-6: moderate risk, "
            "admit for observation, serial troponins, possible stress test. Score 7-10: "
            "high risk, admit, cardiology consult, likely catheterization. High-sensitivity "
            "troponin protocols: 0/1-hour or 0/3-hour rule-out algorithms per institutional "
            "protocol. A single undetectable hs-troponin with low HEART score (0-3) and "
            "non-ischemic ECG has NPV > 99%.\n\n"
            "Critical must-not-miss diagnoses in chest pain: STEMI, NSTEMI/unstable angina, "
            "aortic dissection, pulmonary embolism, tension pneumothorax, cardiac tamponade, "
            "esophageal rupture (Boerhaave). Red flags for aortic dissection: tearing pain "
            "radiating to back, blood pressure differential between arms > 20 mmHg, "
            "widened mediastinum on CXR, new aortic regurgitation murmur. If dissection is "
            "suspected, obtain CTA chest/abdomen/pelvis and AVOID anticoagulation until "
            "dissection is excluded."
        ),
    },
}


def load_reference_materials() -> dict[str, ReferenceMaterial]:
    """Load bundled reference material entities.

    Returns:
        Dict of ref_id -> ReferenceMaterial.
    """
    now = datetime.now(timezone.utc)
    result: dict[str, ReferenceMaterial] = {}

    for ref_id, data in _BUNDLED_REFERENCES.items():
        rm = ReferenceMaterial(
            id=f"RM-{ref_id}",
            entity_type=EntityType.REFERENCE_MATERIAL,
            created_at=now,
            updated_at=now,
            ref_id=data.get("ref_id", ref_id),
            title=data.get("title", ""),
            material_type=data.get("material_type", ""),
            category=data.get("category", ""),
            content=data.get("content", ""),
            keywords=tuple(data.get("keywords", ())),
            condition_refs=tuple(data.get("condition_refs", ())),
            drug_name=data.get("drug_name", ""),
            last_reviewed=data.get("last_reviewed", ""),
            source=data.get("source", ""),
        )
        result[ref_id] = rm

    return result
