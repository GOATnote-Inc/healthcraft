# Task Expansion Roadmap

Full Level I Trauma Center ED complexity requires capabilities beyond isolated
clinical scenarios. This document catalogs what the current 195-task inventory
covers, identifies gaps, and defines expansion phases to close them.

## Current Coverage (195 tasks, v1.0)

### What's Already Tested

| Capability | Tasks | Examples |
|-----------|-------|---------|
| Lethal mimics / confusion pairs | ~40 | CR-001 (STEMI vs dissection), CR-025 (AAA vs renal colic) |
| Protocol-driven workflows | ~30 | MW-020 (ACS pathway), MSW-001 (sepsis bundle) |
| Multi-patient triage | 4 | IR-025 (5 pediatric MCI), SCJ-022 (23-pt MCI), TR-008 (12-pt MCI drill) |
| Boarding / capacity crisis | 2 | TR-004 (140% capacity), TR-013 (boarding hold deterioration) |
| Shift handoff | 1 | TR-007 (15-min shift change, 14 active patients, 6 critical pending) |
| Cascading simultaneous crises | 2 | TR-001 (4 simultaneous crises, solo attending), TR-003 (dual codes) |
| EMTALA / regulatory | ~8 | IR-020 (patient dumping), MSW-001 (insurance vs emergency) |
| Decision rule override | ~5 | SCJ-001 (Ottawa SAH paradox), CR decision rule tasks |
| Ethical judgment | ~6 | SCJ-015 (impaired colleague), SCJ-022 (expectant triage) |
| Social determinants | ~4 | CC-020 (SDOH-driven COPD), communication tasks |
| Antibiotic stewardship | 2 | TR-015 (de-escalation timing), sepsis tasks |
| Trauma activation | ~3 | TR-001 (MVC component), TR-008, SCJ-022 |

### What's Not Yet Tested

These are capabilities a Level I Trauma Center ED demands that the current
task inventory does not exercise.

## Expansion Phase 1: Dynamic World State (Priority: High)

**Gap:** Current tasks present a frozen world state. Real EDs have patients
whose vitals change, labs that return mid-encounter, imaging that completes
asynchronously, and clinical status that evolves during the agent's interaction.

**Architecture support:** The temporal spine and stateful mutations already
enable this. Tasks need `state_events` that fire during the trajectory.

### Proposed Tasks (15-20 new)

**P1-DYN-001: Evolving Sepsis**
Patient arrives with SIRS criteria but stable. During the agent's workup
(after ~5 tool calls), vitals deteriorate: BP drops to 78/40, lactate returns
at 6.2. Agent must recognize the transition from SIRS to septic shock and
escalate from floor admission to ICU + vasopressors. Tests: real-time
clinical reassessment, not just initial pattern recognition.

**P1-DYN-002: Troponin Trend Inflection**
Serial troponins ordered. First negative. After agent continues workup,
second troponin returns elevated (0.04 → 0.38). Agent must recognize the
delta, re-evaluate disposition, and activate cardiology. Tests: dynamic
data integration, not static snapshot interpretation.

**P1-DYN-003: Airway Deterioration**
Patient with angioedema, initially managing own airway. Stridor worsens
during agent interaction. Agent must recognize declining airway exam and
pivot from observation to intubation preparation before complete obstruction.
Tests: time-critical escalation from evolving physical exam.

**P1-DYN-004: Boarding Patient Crash**
Patient boarding 6 hours for ICU bed. During agent's shift management,
patient's monitor alarms: new-onset atrial fibrillation with RVR (HR 168).
Agent must interrupt current task, reassess the boarder, and manage the
acute rhythm change. Tests: interruption handling and clinical re-prioritization.

**P1-DYN-005: Lab Critical Value Callback**
Agent is mid-workup on Patient A when the lab calls with a critical potassium
(7.1) on Patient B (a boarding patient the agent inherited at shift change).
Agent must interrupt, address the hyperkalemia emergency (calcium gluconate,
insulin/dextrose, kayexalate, cardiac monitoring), then resume Patient A
without losing context. Tests: context switching under clinical pressure.

**Implementation:** Add `state_events` field to task YAML:
```yaml
state_events:
  - trigger: tool_call_count >= 5
    action: update_vitals
    patient_id: PAT-042
    new_vitals: {blood_pressure: "78/40", heart_rate: 128, lactate: 6.2}
    notification: "Nurse pages: Patient in Bed 7 is looking worse."
  - trigger: tool_call_count >= 8
    action: return_lab
    result: {test: troponin_i, value: 0.38, critical: true}
```

MCP server intercepts triggers and injects state changes + notifications into
the conversation. Agent sees them as system messages.

## Expansion Phase 2: Interruption and Context Recovery (Priority: High)

**Gap:** Real ED physicians are interrupted every 3-5 minutes. No current task
tests the ability to suspend a clinical thread, handle an interruption, and
resume without losing safety-critical context.

### Proposed Tasks (10-15 new)

**P2-INT-001: Trauma During Sepsis Workup**
Agent is managing septic shock (antibiotics ordered, fluids running, awaiting
lactate clearance). Trauma activation fires: MVC with GCS 8 en route, ETA
3 minutes. Agent must: delegate sepsis monitoring (verbal order to nurse),
prepare for trauma (activate team, verify blood availability, clear resus
bay), then manage the trauma arrival — all while ensuring the sepsis patient's
antibiotics aren't delayed and reassessment happens on schedule.

**P2-INT-002: Family Escalation During Resuscitation**
Agent is running a code (cardiac arrest). Patient's family arrives, demands
information, becomes aggressive when no one will stop to talk. Social worker
is unavailable. Agent must: continue directing the code, delegate family
communication to available staff, and document the encounter — without
compromising code quality or violating family's right to information.

**P2-INT-003: Phone Interruption Cascade**
Agent is doing a focused assessment. Three phone calls arrive in sequence:
(1) admitting wants to reject a patient the agent accepted, (2) EMS is
bringing a stroke alert in 8 minutes, (3) radiology calls with an incidental
finding on a discharged patient from yesterday. Agent must triage the calls
by urgency, act on the stroke alert immediately, defer the admitting dispute,
and document the incidental finding for follow-up.

**Implementation:** Inject interruption events as system messages mid-trajectory.
The agent must respond to the interruption and resume the primary task. Criteria
evaluate both the interruption response AND the primary task completion.

## Expansion Phase 3: Sustained Workload Management (Priority: Medium)

**Gap:** The hardest part of ED medicine isn't any single case — it's managing
15-25 patients simultaneously across a shift. Current tasks are episodic.
No task tests sustained cognitive load across multiple concurrent patients
with competing timelines.

### Proposed Tasks (5-10 new, Level 5)

**P3-WL-001: The Full Board**
Agent inherits a shift with 22 active patients:
- 3 boarding (ICU, telemetry, psych — none with beds available)
- 5 in active workup (labs pending, imaging pending)
- 4 ready for disposition (2 discharges, 1 admission, 1 transfer)
- 6 waiting to be seen (ESI 3-4, longest wait 2.5 hours)
- 2 in resuscitation (trauma post-stabilization, STEMI post-cath)
- 2 behavioral health holds (one calm, one agitated)

Over the task, 3 new patients arrive (ESI 2, ESI 3, ESI 4). Agent must
prioritize, delegate, disposition, and manage all patients without any
falling through cracks. Tests: prioritization, delegation, throughput
management, safety across a full panel.

**P3-WL-002: Night Shift Solo**
Solo attending, 2200-0600. Census starts at 8. Over the shift:
- Ambulance arrival pattern: 2 in first hour, 1/hr baseline, surge of 4
  between 0200-0300
- One nurse calls in sick at 2300 (staff shortage)
- Boarding patient decompensates at 0100
- Lab system goes down 0300-0330 (must manage without labs)
- Shift handoff at 0600 with 12 active patients

Tests: sustained performance under fatigue-analog conditions (increasing
complexity over time), resource degradation, and handoff quality.

**Implementation:** These tasks require extended trajectories (50-100+ tool
calls) and multi-patient world state with independent timelines. The entity
graph already supports this — encounters are independent with their own
temporal spines. New: a shift-level orchestration layer that manages the
patient census and event queue.

## Expansion Phase 4: Team Coordination Failures (Priority: Medium)

**Gap:** Current tasks assume the agent is the sole decision-maker. Real EDs
have residents, nurses, consultants, and specialists who may misunderstand
orders, fail to execute, or provide conflicting recommendations.

### Proposed Tasks (8-12 new)

**P4-TC-001: Consultant Disagreement**
Agent diagnoses appendicitis and requests surgical consult. Surgeon disagrees:
"CT doesn't look that bad, observe overnight." Patient has peritoneal signs.
Agent must: assert clinical judgment, escalate to attending surgeon, document
disagreement, and ensure the patient isn't harmed by delay. Tests: inter-
professional assertiveness and patient advocacy.

**P4-TC-002: Resident Medication Error**
Resident orders 10x the correct dose of a medication (decimal point error).
Pharmacy flags it. Agent must: recognize the error severity, correct the
order, assess patient for harm (was it administered?), report through
institutional channels, and provide educational feedback — without destroying
the resident's confidence or creating a punitive environment.

**P4-TC-003: Nursing Handoff Loss**
During nursing shift change, a critical lab result (positive blood culture)
arrives but is not communicated to the new nurse. Agent discovers it 2 hours
later. Patient is still on empiric antibiotics that don't cover the organism.
Agent must: act on the result, investigate the communication failure, adjust
treatment, and implement a safety measure to prevent recurrence.

**Implementation:** Introduce simulated team member responses via the MCP
server. Tool calls that involve team members (consult requests, nursing
orders) return realistic responses including disagreement, misunderstanding,
or failure to execute. The agent must detect and manage these failures.

## Expansion Phase 5: Inter-Facility and System-Level (Priority: Low)

**Gap:** Level I Trauma Centers are regional resources. They receive transfers,
coordinate mutual aid during MCI, manage surge capacity, and interface with
EMS systems. No current task tests system-level coordination.

### Proposed Tasks (5-8 new)

**P5-IF-001: Incoming Transfer Acceptance**
Community hospital calls: 45-year-old with dissecting aortic aneurysm,
hemodynamically unstable, needs cardiothoracic surgery. Agent's OR is
occupied with an emergent case (estimated 2 more hours). ICU has 1 bed.
Agent must: assess transfer appropriateness, estimate capacity, coordinate
with OR/ICU, decide accept vs redirect to another Level I center, and manage
the logistics — all under EMTALA transfer obligations.

**P5-IF-002: MCI Mutual Aid Coordination**
Major MCI declared. Agent's ED is receiving facility. 3 community hospitals
are diverting patients. EMS command requests capacity status every 15 minutes.
Agent must: manage incoming patient flow, report accurate capacity, coordinate
with in-house teams, and balance accepting patients against overwhelming
own resources.

## Task Count Projection

| Phase | New Tasks | Running Total | Complexity Level |
|-------|-----------|---------------|------------------|
| v1.0 (current) | 195 | 195 | L1-L5 |
| Phase 1: Dynamic State | 15-20 | ~215 | L3-L4 |
| Phase 2: Interruptions | 10-15 | ~230 | L4-L5 |
| Phase 3: Sustained Workload | 5-10 | ~240 | L5 |
| Phase 4: Team Coordination | 8-12 | ~252 | L3-L5 |
| Phase 5: Inter-Facility | 5-8 | ~260 | L4-L5 |

Target: ~260 tasks covering the full operational complexity of a Level I
Trauma Center ED. Current 195 cover focused clinical competencies. Phases 1-5
add the operational, dynamic, and systemic dimensions.

## Implementation Dependencies

| Phase | Requires |
|-------|----------|
| Phase 1 | `state_events` in task YAML + MCP server event injection |
| Phase 2 | System message injection mid-trajectory + multi-thread criteria |
| Phase 3 | Multi-patient world state orchestration + shift-level event queue |
| Phase 4 | Simulated team member response engine in MCP server |
| Phase 5 | Inter-facility entity type + EMS coordination tools |

Phases 1-2 are achievable with modest MCP server extensions. Phases 3-5
require new architectural components.

## Sequencing

Phase 1 (Dynamic State) should ship first — it's the highest-value gap and
the most architecturally straightforward. The `state_events` mechanism also
enables Phases 2-3. Phase 4 (Team Coordination) is independently valuable
and can proceed in parallel once the MCP server supports simulated team
responses.

## Relationship to RL Training

Corecraft Section 5.2 uses 1,000 training tasks + 150 eval tasks. Current
195 tasks serve as the eval set. Phases 1-5 expand the eval set to ~260.
Training tasks (5-10x scale) should be authored separately following the same
expansion dimensions, with procedural generation where possible (Corecraft
Section 3.2).

## Non-Goals

- **Fatigue modeling.** We test sustained workload (Phase 3) but do not model
  cognitive fatigue as a parameter. The agent either manages the workload or
  doesn't.
- **Physical procedures.** HEALTHCRAFT evaluates decision-making, not manual
  dexterity. Intubation is "order intubation + verify success," not a motor
  skill simulation.
- **EMR UI simulation.** Tools abstract away the EHR interface. We don't test
  whether an agent can navigate Epic's 47-click discharge workflow.
- **Training curriculum.** This document covers eval tasks only. Training task
  generation is a separate workstream.
