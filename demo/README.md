# Demo FHIR R4 Bundles

This directory holds **synthetic** FHIR R4 transaction bundles used to
demonstrate the ED Decision Rules MCP server end-to-end against
Prompt Opinion's FHIR-context-aware Patient Data import.

All patients in this directory are fictional. No real PHI is present.

## `chest_pain_bundle.json`

A 65-year-old male, "John Doe", presenting to the ED with acute substernal
chest pain. Twelve FHIR R4 resources: Patient, Encounter, four Observations
(troponin elevated, ECG abnormal, heart rate, blood pressure), four
Conditions (CAD, hypertension, type 2 diabetes, hyperlipidemia), and two
MedicationRequests (atorvastatin, aspirin).

This bundle is constructed so the HEART Score variable extractor can read
all five inputs from the FHIR context:

| HEART variable | FHIR resource |
|---|---|
| History | Encounter.reasonCode → SNOMED 29857009 "Chest pain" |
| ECG | Observation Loinc 11524-6 with interpretation `Abnormal` |
| Age | Patient.birthDate (1960-04-15 → age 65 at the demo's effective date) |
| Risk factors | 4× Condition resources for CAD/HTN/T2DM/HLD (>=3 risk factors + history of atherosclerotic disease = 2) |
| Troponin | Observation Loinc 10839-9, value 0.12 ng/mL, ref-range high 0.04 (1-3× ULN) |

Expected HEART Score: **8/10 high risk → Admit for early invasive strategy; 65% MACE risk.**

## Upload

In Prompt Opinion: **Sidebar → Patient Data → Import → "Upload a FHIR Bundle"
widget → select `chest_pain_bundle.json` → Import.** The bundle uses POST
semantics with `urn:uuid:` cross-references — the canonical FHIR transaction-
bundle pattern that works on FHIR servers that don't support PUT updateCreate.

## Regenerate UUIDs (if needed)

If you need a fresh set of UUIDs for a clean import:

```python
import json, uuid
with open('demo/chest_pain_bundle.json') as f:
    bundle = json.load(f)
for entry in bundle['entry']:
    entry['fullUrl'] = f"urn:uuid:{uuid.uuid4()}"
with open('demo/chest_pain_bundle.json', 'w') as f:
    json.dump(bundle, f, indent=2)
```
