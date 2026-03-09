# HEALTHCRAFT Tool Mapping

## Overview

HEALTHCRAFT exposes 24 MCP tools via FastMCP. 23 map directly to Corecraft
tools; 1 (`runDecisionRule`) is new. All tools validate inputs, log to the
audit trail, and interact with the world state through a state manager.

See [`CORECRAFT_ATTRIBUTION.md`](CORECRAFT_ATTRIBUTION.md) for the mapping
rationale.

## Tool Reference

### Search Tools (6)

#### 1. searchEncounters

**Corecraft:** searchOrders

Search ED encounters by patient, date range, ESI level, chief complaint,
disposition, or status.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| patient_id | string | No | Filter by patient |
| date_from | datetime | No | Start of date range |
| date_to | datetime | No | End of date range |
| esi_level | integer (1-5) | No | ESI triage level |
| chief_complaint | string | No | Keyword search on chief complaint |
| status | string | No | active, discharged, admitted, transferred |
| limit | integer | No | Max results (default 20) |

**Returns:** List of encounter summaries with encounter_id, patient_id,
arrival_time, esi_level, chief_complaint, status.

---

#### 2. searchClinicalKnowledge

**Corecraft:** searchProducts

Search the clinical knowledge base (OpenEM conditions) by name, category,
ICD-10 code, or keyword.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| query | string | No | Free-text search |
| category | string | No | OpenEM category (e.g., "cardiovascular") |
| icd10 | string | No | ICD-10 code prefix |
| has_confusion_pairs | boolean | No | Filter for conditions with confusion pairs |
| limit | integer | No | Max results (default 20) |

**Returns:** List of condition summaries with condition_id, name, category,
icd10, time_to_harm.

---

#### 3. searchPatients

**Corecraft:** searchCustomers

Search patients by name, date of birth, MRN, or demographics.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| name | string | No | Patient name (partial match) |
| dob | date | No | Date of birth |
| mrn | string | No | Medical record number |
| sex | string | No | male, female, other |
| limit | integer | No | Max results (default 20) |

**Returns:** List of patient summaries with patient_id, name, dob, sex, mrn.

---

#### 4. searchReferenceMaterials

**Corecraft:** searchKnowledgebase

Search clinical reference materials by keyword, category, or topic.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| query | string | Yes | Search query |
| category | string | No | drug_monograph, procedure_guide, dosing, guideline, toxicology |
| limit | integer | No | Max results (default 10) |

**Returns:** List of reference summaries with reference_id, title, category,
relevance_score.

---

#### 5. searchAvailableResources

**Corecraft:** searchPromotions

Search current resource availability by type.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| resource_type | string | Yes | bed, or_slot, blood_product, specialist, imaging |
| department | string | No | Filter by department |
| urgency | string | No | routine, urgent, emergent |

**Returns:** List of available resources with resource_id, resource_type,
available_count, constraints.

---

#### 6. checkResourceAvailability

**Corecraft:** checkInventory

Check real-time availability of a specific resource (bed, OR, blood product,
specialist, imaging modality).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| resource_type | string | Yes | Type of resource |
| resource_id | string | No | Specific resource ID |
| quantity | integer | No | Quantity needed (default 1) |

**Returns:** Availability status with available_count, estimated_wait,
alternatives.

---

### Read Tools (7)

#### 7. getEncounterDetails

**Corecraft:** getOrderDetails

Get full encounter details including timeline, orders, results, and disposition.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| encounter_id | string | Yes | Encounter ID |
| include_timeline | boolean | No | Include event timeline (default true) |
| include_tasks | boolean | No | Include associated tasks (default true) |

**Returns:** Complete encounter with patient reference, timeline, tasks,
time constraints, disposition.

---

#### 8. getConditionDetails

**Corecraft:** getProductDetails

Get detailed clinical knowledge for a condition, including presentations,
confusion pairs, decision rules, and treatment guidelines.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| condition_id | string | Yes | OpenEM condition ID |
| include_confusion_pairs | boolean | No | Include look-alike conditions (default true) |
| include_decision_rules | boolean | No | Include applicable decision rules (default true) |

**Returns:** Full condition data with presentations, confusion pairs, decision
rules, time_to_harm, FHIR Condition resource.

---

#### 9. getPatientHistory

**Corecraft:** getCustomerHistory

Get a patient's clinical history including past encounters, conditions,
medications, allergies, and procedures.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| patient_id | string | Yes | Patient ID |
| include_encounters | boolean | No | Include past encounters (default true) |
| include_medications | boolean | No | Include active medications (default true) |
| include_allergies | boolean | No | Include allergies (default true) |

**Returns:** Patient history with demographics, encounters, active medications,
allergies, surgical history, social history.

---

#### 10. getReferenceArticle

**Corecraft:** getKnowledgebaseArticle

Get a specific clinical reference document by ID.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| reference_id | string | Yes | Reference material ID |

**Returns:** Full reference document with content, metadata, last_reviewed date.

---

#### 11. getProtocolDetails

**Corecraft:** getWarrantyPolicy

Get detailed protocol or guideline by ID, including steps, triggers,
contraindications, and override criteria.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| protocol_id | string | Yes | Protocol ID |

**Returns:** Full protocol with steps, triggers, contraindications,
override_criteria, evidence_level.

---

#### 12. getTransferStatus

**Corecraft:** getShippingStatus

Get the status of a patient transfer (inbound or outbound).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| transfer_id | string | Yes | Transfer record ID |

**Returns:** Transfer status with transport mode, ETA/departure, accepting
facility, clinical handoff status, EMTALA compliance.

---

#### 13. getInsuranceCoverage

**Corecraft:** getLoyaltyTier

Get insurance coverage details for a patient, including authorization
requirements and formulary restrictions.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| patient_id | string | Yes | Patient ID |
| service_type | string | No | Filter for specific service type |

**Returns:** Coverage details with plan type, authorization requirements,
formulary tier, network status.

---

### Write Tools (5)

#### 14. createClinicalOrder

**Corecraft:** createTicket

Create a new clinical order (lab, imaging, medication, consult, procedure).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| encounter_id | string | Yes | Associated encounter |
| order_type | string | Yes | lab, imaging, medication, consult, procedure |
| order_details | object | Yes | Type-specific order parameters |
| priority | string | No | routine, urgent, stat (default routine) |
| indication | string | No | Clinical indication |

**Returns:** Created task with task_id, status, estimated_completion.

**Safety validation:** Medication orders checked against patient allergies
and contraindications. Blocked if lethal interaction detected.

---

#### 15. updateTaskStatus

**Corecraft:** updateTicketStatus

Update the status of a clinical task.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| task_id | string | Yes | Task ID |
| new_status | string | Yes | in_progress, completed, cancelled |
| notes | string | No | Status update notes |
| result | object | No | Result data (for completed tasks) |

**Returns:** Updated task with previous_status, new_status, updated_at.

---

#### 16. updateEncounter

**Corecraft:** updateOrder

Update encounter fields (reassign bed, change ESI, update disposition plan).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| encounter_id | string | Yes | Encounter ID |
| updates | object | Yes | Fields to update |

**Returns:** Updated encounter with changed fields highlighted.

---

#### 17. registerPatient

**Corecraft:** createCustomer

Register a new patient in the system (walk-in, unregistered EMS arrival).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| name | string | Yes | Patient name |
| dob | date | Yes | Date of birth |
| sex | string | Yes | male, female, other |
| chief_complaint | string | Yes | Presenting complaint |
| arrival_mode | string | No | walk_in, ems, transfer (default walk_in) |
| insurance | object | No | Insurance information |

**Returns:** Created patient and encounter with patient_id, encounter_id,
assigned_bed.

---

#### 18. updatePatientRecord

**Corecraft:** updateCustomer

Update patient record fields (allergies discovered, history updated, contact
information changed).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| patient_id | string | Yes | Patient ID |
| updates | object | Yes | Fields to update |

**Returns:** Updated patient record with changed fields highlighted.

---

### Execute Tools (4)

#### 19. processDischarge

**Corecraft:** processReturn

Process a patient discharge with required documentation, prescriptions,
follow-up instructions, and safety checks.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| encounter_id | string | Yes | Encounter ID |
| disposition | string | Yes | home, ama, admitted, transferred, deceased |
| discharge_instructions | string | Yes | Patient instructions |
| prescriptions | array | No | Discharge medications |
| follow_up | object | No | Follow-up appointment details |

**Returns:** Discharge summary with warnings for missing safety elements.

**Safety validation:** Blocks discharge if critical results are pending or
time constraints are unmet.

---

#### 20. applyProtocol

**Corecraft:** applyPromotion

Activate a clinical protocol for an encounter (sepsis bundle, stroke alert,
MTP, trauma activation).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| encounter_id | string | Yes | Encounter ID |
| protocol_id | string | Yes | Protocol to activate |
| parameters | object | No | Protocol-specific parameters |
| override_reason | string | No | Required if overriding contraindication |

**Returns:** Activated protocol with generated tasks and time constraints.

---

#### 21. processTransfer

**Corecraft:** processExchange

Initiate or complete a patient transfer to another facility or department.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| encounter_id | string | Yes | Encounter ID |
| destination | string | Yes | Receiving facility or department |
| transport_mode | string | Yes | ground_ems, air, private, walk |
| clinical_summary | string | Yes | Transfer handoff summary |
| emtala_certification | boolean | No | EMTALA transfer certification (default false) |

**Returns:** Transfer record with transfer_id, estimated_transport_time,
required_documentation checklist.

---

#### 22. calculateTransferTime

**Corecraft:** calculateShipping

Calculate estimated transport time and resource requirements for a transfer.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| origin | string | Yes | Origin facility |
| destination | string | Yes | Destination facility |
| transport_mode | string | Yes | ground_ems, air, private |
| patient_acuity | string | No | stable, unstable, critical |

**Returns:** Estimated time, required crew, equipment, and cost.

---

### Query Tools (2)

#### 23. validateTreatmentPlan

**Corecraft:** validateBuildCompatibility

Validate a proposed treatment plan for clinical correctness, drug interactions,
allergy conflicts, and protocol compliance.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| encounter_id | string | Yes | Encounter ID |
| plan | object | Yes | Proposed treatment plan |
| check_interactions | boolean | No | Check drug-drug interactions (default true) |
| check_allergies | boolean | No | Check patient allergies (default true) |
| check_protocols | boolean | No | Verify protocol compliance (default true) |

**Returns:** Validation result with warnings, errors, and recommendations.

---

#### 24. runDecisionRule

**Corecraft:** *(new -- no equivalent)*

Execute a validated clinical decision rule with patient-specific parameters.
Returns risk category and recommended actions.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| rule_id | string | Yes | Decision rule ID (e.g., "HEART", "WELLS_PE") |
| encounter_id | string | Yes | Encounter for context |
| parameters | object | Yes | Rule-specific input values |

**Returns:** Calculated score, risk category, recommended actions, evidence
references.

**Examples:**
- HEART Score: age, risk_factors, history, ecg, troponin -> score 0-10, risk low/moderate/high
- Wells PE: clinical_signs, heart_rate, immobilization, prior_dvt_pe, hemoptysis, malignancy, alternative_diagnosis -> score 0-12.5, probability low/moderate/high
- Ottawa Ankle: bone_tenderness_zone, weight_bearing -> xray_indicated (boolean)
- PECARN: age_group, gcs, mental_status, scalp_hematoma, loc, mechanism -> risk very_low/low/moderate

## Tool Categories Summary

| Category | Count | Tools |
|----------|-------|-------|
| Search | 6 | searchEncounters, searchClinicalKnowledge, searchPatients, searchReferenceMaterials, searchAvailableResources, checkResourceAvailability |
| Read | 7 | getEncounterDetails, getConditionDetails, getPatientHistory, getReferenceArticle, getProtocolDetails, getTransferStatus, getInsuranceCoverage |
| Write | 5 | createClinicalOrder, updateTaskStatus, updateEncounter, registerPatient, updatePatientRecord |
| Execute | 4 | processDischarge, applyProtocol, processTransfer, calculateTransferTime |
| Query | 2 | validateTreatmentPlan, runDecisionRule |

## Common Patterns

### Information Gathering

```
searchPatients -> getPatientHistory -> getEncounterDetails -> getConditionDetails
```

### Clinical Workflow

```
getEncounterDetails -> runDecisionRule -> applyProtocol -> createClinicalOrder -> updateTaskStatus
```

### Discharge

```
getEncounterDetails -> validateTreatmentPlan -> processDischarge
```

### Transfer

```
getEncounterDetails -> calculateTransferTime -> getInsuranceCoverage -> processTransfer
```

## Audit Contract

Every tool call is logged to the `audit_log` table with:
- session_id, timestamp, tool_name, parameters, result_summary, duration_ms, error

The rubric evaluator uses the audit log as ground truth for scoring.
