# HEALTHCRAFT Entity Mapping

## Overview

HEALTHCRAFT defines 14 entity types that map to Corecraft's entity types,
adapted for emergency medicine. Each entity type is implemented as a frozen
dataclass with a deterministic generator function that accepts `random.Random`.

See [`CORECRAFT_ATTRIBUTION.md`](CORECRAFT_ATTRIBUTION.md) for the rationale
behind each mapping.

## Entity Types

| # | HEALTHCRAFT Entity | Corecraft Entity | Count | FHIR R4 Resource | Source Module |
|---|-------------------|-----------------|-------|-------------------|---------------|
| 1 | Patients | Customers | 500+ | Patient | `entities/patients.py` |
| 2 | Encounters | Orders | 1,200+ | Encounter | `entities/encounters.py` |
| 3 | Clinical Knowledge | Products | 370 | Condition (library) | `entities/clinical_knowledge.py` |
| 4 | Treatment Plans | Builds | 800+ | CarePlan | `entities/treatment_plans.py` |
| 5 | Clinical Tasks | Support Tickets | 2,000+ | Task | `entities/clinical_tasks.py` |
| 6 | Time Constraints | SLAs | 200+ | n/a (custom) | `entities/time_constraints.py` |
| 7 | Transfer Records | Shipping Records | 300+ | n/a (custom) | `entities/transfer_records.py` |
| 8 | Clinical Decision Rules | Compatibility Rules | 150+ | n/a (custom) | `entities/decision_rules.py` |
| 9 | Protocols & Guidelines | Warranty Policies | 100+ | PlanDefinition | `entities/protocols.py` |
| 10 | Insurance & Coverage | Loyalty Tiers | 50+ | Coverage | `entities/insurance.py` |
| 11 | Reference Materials | Knowledgebase Articles | 500+ | DocumentReference | `entities/reference_materials.py` |
| 12 | Resource Availability | Promotions | 100+ | n/a (custom) | `entities/resources.py` |
| 13 | Supplies & Medications | Inventory | 400+ | Medication, SupplyDelivery | `entities/supplies.py` |
| 14 | Regulatory & Legal | Company Policies | 80+ | n/a (custom) | `entities/regulatory.py` |

## Detailed Entity Descriptions

### 1. Patients

**Corecraft equivalent:** Customers

Primary actors in the emergency department. Each patient has demographics,
medical history, allergies, medications, and insurance information.

- **FHIR R4 Resource:** Patient
- **Key fields:** patient_id, name, dob, sex, allergies, medications, pmh,
  insurance_id, emergency_contact
- **OpenEM integration:** Presentations derived from OpenEM condition metadata
- **Determinism:** Generated from seed with realistic demographic distributions

### 2. Encounters

**Corecraft equivalent:** Orders

ED visits with arrival timestamp, ESI triage level (1-5), chief complaint,
disposition, and a timeline of events.

- **FHIR R4 Resource:** Encounter
- **Key fields:** encounter_id, patient_id, arrival_time, esi_level,
  chief_complaint, disposition, assigned_bed, attending_physician
- **Temporal spine:** Each encounter has an ordered timeline of events
- **Entity references:** Links to patient_id, clinical_task_ids, time_constraint_ids

### 3. Clinical Knowledge

**Corecraft equivalent:** Products

The condition knowledge base, powered by OpenEM. Contains 370 emergency medicine
conditions with structured metadata including confusion pairs, decision rules,
time-to-harm estimates, and FHIR condition resources.

- **FHIR R4 Resource:** Condition (library/reference)
- **Key fields:** condition_id, name, category, icd10, presentations,
  confusion_pairs, decision_rules, time_to_harm
- **OpenEM integration:** Direct mapping via `load_condition_map()`
- **Count:** 370 (185 base + 185 expansion)

### 4. Treatment Plans

**Corecraft equivalent:** Builds

Multi-step clinical pathways with dependencies between steps. A treatment plan
for sepsis, for example, includes fluid resuscitation, blood cultures, lactate,
antibiotics, and reassessment -- each with ordering constraints.

- **FHIR R4 Resource:** CarePlan
- **Key fields:** plan_id, encounter_id, condition_id, steps (ordered),
  dependencies, status, created_at
- **Entity references:** Links to encounter_id, condition_id, clinical_task_ids

### 5. Clinical Tasks

**Corecraft equivalent:** Support Tickets

Action items with status tracking: lab orders, imaging orders, consult requests,
medication orders, procedure orders, and nursing tasks.

- **FHIR R4 Resource:** Task
- **Key fields:** task_id, encounter_id, task_type, status (ordered, in_progress,
  completed, cancelled), priority, ordered_by, ordered_at, result
- **Status transitions:** ordered -> in_progress -> completed | cancelled
- **Entity references:** Links to encounter_id, plan_id

### 6. Time Constraints

**Corecraft equivalent:** SLAs

Clinical time targets with deadlines and escalation rules. Examples:
door-to-ECG (10 min), door-to-balloon (90 min), sepsis bundle (3 hr),
stroke CT (25 min).

- **FHIR R4 Resource:** n/a (custom schema)
- **Key fields:** constraint_id, encounter_id, constraint_type, target_minutes,
  deadline, status (pending, met, breached), escalation_path
- **Temporal spine:** Constraints have start time and deadline; breached
  constraints trigger escalation events

### 7. Transfer Records

**Corecraft equivalent:** Shipping Records

Inter-facility transfers, EMS arrivals, and EMTALA-mandated transfers. Include
accepting facility, transport mode, clinical handoff documentation.

- **FHIR R4 Resource:** n/a (custom schema)
- **Key fields:** transfer_id, patient_id, encounter_id, direction (inbound,
  outbound), transport_mode, accepting_facility, emtala_compliant, handoff_note
- **Regulatory link:** EMTALA compliance fields

### 8. Clinical Decision Rules

**Corecraft equivalent:** Compatibility Rules

Validated clinical prediction rules with parameters, thresholds, and
recommended actions. Examples: HEART Score, Wells Criteria for PE, Ottawa
Ankle Rules, PECARN, Canadian C-Spine Rule.

- **FHIR R4 Resource:** n/a (custom schema)
- **Key fields:** rule_id, name, condition_ids, parameters (with types and
  ranges), thresholds, risk_categories, recommended_actions
- **OpenEM integration:** 45 decision rules from OpenEM metadata

### 9. Protocols & Guidelines

**Corecraft equivalent:** Warranty Policies

Standard clinical protocols and institutional guidelines: sepsis bundle,
stroke alert pathway, massive transfusion protocol (MTP), difficult airway
algorithm, cardiac arrest algorithm.

- **FHIR R4 Resource:** PlanDefinition
- **Key fields:** protocol_id, name, category, version, steps, triggers,
  contraindications, override_criteria
- **Entity references:** Links to condition_ids, decision_rule_ids

### 10. Insurance & Coverage

**Corecraft equivalent:** Loyalty Tiers

Insurance coverage information including plan type, authorization requirements,
formulary restrictions, and network status.

- **FHIR R4 Resource:** Coverage
- **Key fields:** coverage_id, patient_id, plan_type (commercial, medicare,
  medicaid, va, self_pay, uninsured), plan_name, authorization_required,
  formulary_tier, network_status
- **Task interaction:** Some clinical orders require prior authorization

### 11. Reference Materials

**Corecraft equivalent:** Knowledgebase Articles

Clinical reference documents: drug monographs, procedure guides, dosing
calculators, clinical practice guidelines, toxicology references.

- **FHIR R4 Resource:** DocumentReference
- **Key fields:** reference_id, title, category, content, keywords,
  last_reviewed, source
- **Search:** Full-text searchable via `searchReferenceMaterials` tool

### 12. Resource Availability

**Corecraft equivalent:** Promotions

Real-time availability of ED resources: bed census, OR availability, blood
bank inventory, specialist on-call status, EMS diversion status.

- **FHIR R4 Resource:** n/a (custom schema)
- **Key fields:** resource_id, resource_type (bed, or_slot, blood_product,
  specialist, imaging), available_count, total_count, constraints, updated_at
- **Temporal spine:** Availability changes over time (shift changes, admissions)

### 13. Supplies & Medications

**Corecraft equivalent:** Inventory

Formulary with stock levels, shortages, substitution rules, and
contraindications. Includes controlled substance tracking.

- **FHIR R4 Resource:** Medication, SupplyDelivery
- **Key fields:** item_id, name, category, stock_level, unit, shortage_status,
  substitutions, contraindications, controlled_schedule
- **Safety interaction:** Medication orders validated against patient allergies

### 14. Regulatory & Legal

**Corecraft equivalent:** Company Policies

Legal and regulatory constraints: EMTALA requirements, informed consent rules,
AMA (against medical advice) documentation, mandatory reporting obligations,
psychiatric hold criteria, organ donation protocols.

- **FHIR R4 Resource:** n/a (custom schema)
- **Key fields:** regulation_id, name, category, jurisdiction, requirements,
  documentation_template, penalties, exceptions
- **Task interaction:** Regulatory requirements can block or mandate actions

## Entity Relationships

```
Patients ----< Encounters ----< Clinical Tasks
    |              |                  |
    |              +----< Time Constraints
    |              |
    |              +----< Treatment Plans ----< Clinical Tasks
    |              |
    |              +----< Transfer Records
    |
    +---- Insurance & Coverage

Clinical Knowledge ----< Clinical Decision Rules
       |
       +----< Protocols & Guidelines

Resource Availability
Supplies & Medications
Reference Materials
Regulatory & Legal
```

Legend: `----<` means one-to-many relationship.

## Determinism Contract

All entity generators follow the same pattern:

```python
def generate_patients(rng: random.Random, count: int, ...) -> list[Patient]:
    """Generate deterministic patient entities.

    Given the same rng state, produces identical output.
    """
    ...
```

Default seed is 42. World state configs can override per entity type.
