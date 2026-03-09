-- HEALTHCRAFT World State Schema
-- PostgreSQL 16 with FHIR R4-compatible columns
-- All clinical content is synthetic.
-- Covers all 14 entity types from the Corecraft entity graph.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ---------------------------------------------------------------------------
-- patients: FHIR Patient resources
-- ---------------------------------------------------------------------------
CREATE TABLE patients (
    patient_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    mrn             VARCHAR(20) UNIQUE NOT NULL,
    resource_type   VARCHAR(50) NOT NULL DEFAULT 'Patient',
    version_id      INTEGER NOT NULL DEFAULT 1,
    last_updated    TIMESTAMPTZ NOT NULL DEFAULT now(),
    name            JSONB NOT NULL,          -- {given: [...], family: "..."}
    dob             DATE NOT NULL,
    sex             VARCHAR(10) NOT NULL,    -- male | female | other
    allergies       JSONB NOT NULL DEFAULT '[]',
    medications     JSONB NOT NULL DEFAULT '[]',
    medical_history JSONB NOT NULL DEFAULT '[]',
    insurance_id    UUID,
    emergency_contact JSONB,
    advance_directives VARCHAR(50),
    resource        JSONB NOT NULL           -- full FHIR Patient resource
);

CREATE INDEX idx_patients_mrn ON patients (mrn);
CREATE INDEX idx_patients_name ON patients USING gin (name);

-- ---------------------------------------------------------------------------
-- encounters: FHIR Encounter resources (ED visits)
-- ---------------------------------------------------------------------------
CREATE TABLE encounters (
    encounter_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    patient_id      UUID NOT NULL REFERENCES patients(patient_id),
    resource_type   VARCHAR(50) NOT NULL DEFAULT 'Encounter',
    version_id      INTEGER NOT NULL DEFAULT 1,
    last_updated    TIMESTAMPTZ NOT NULL DEFAULT now(),
    arrival_time    TIMESTAMPTZ NOT NULL,
    esi_level       INTEGER CHECK (esi_level BETWEEN 1 AND 5),
    chief_complaint TEXT NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
                    -- active | discharged | admitted | transferred
    disposition     VARCHAR(50),
    assigned_bed    VARCHAR(20),
    attending       VARCHAR(100),
    timeline        JSONB NOT NULL DEFAULT '[]',  -- ordered list of events
    resource        JSONB NOT NULL                -- full FHIR Encounter resource
);

CREATE INDEX idx_encounters_patient ON encounters (patient_id);
CREATE INDEX idx_encounters_status ON encounters (status);
CREATE INDEX idx_encounters_arrival ON encounters (arrival_time);
CREATE INDEX idx_encounters_esi ON encounters (esi_level);

-- ---------------------------------------------------------------------------
-- clinical_tasks: FHIR Task resources (orders, consults, results)
-- ---------------------------------------------------------------------------
CREATE TABLE clinical_tasks (
    task_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    encounter_id    UUID NOT NULL REFERENCES encounters(encounter_id),
    resource_type   VARCHAR(50) NOT NULL DEFAULT 'Task',
    version_id      INTEGER NOT NULL DEFAULT 1,
    last_updated    TIMESTAMPTZ NOT NULL DEFAULT now(),
    task_type       VARCHAR(50) NOT NULL,
                    -- lab | imaging | medication | consult | procedure | nursing
    status          VARCHAR(20) NOT NULL DEFAULT 'ordered',
                    -- ordered | in_progress | completed | cancelled
    priority        VARCHAR(20) NOT NULL DEFAULT 'routine',
                    -- routine | urgent | stat
    ordered_by      VARCHAR(100),
    ordered_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    result          JSONB,
    notes           TEXT,
    resource        JSONB NOT NULL               -- full FHIR Task resource
);

CREATE INDEX idx_tasks_encounter ON clinical_tasks (encounter_id);
CREATE INDEX idx_tasks_status ON clinical_tasks (status);
CREATE INDEX idx_tasks_type ON clinical_tasks (task_type);
CREATE INDEX idx_tasks_priority ON clinical_tasks (priority);

-- ---------------------------------------------------------------------------
-- clinical_knowledge: Condition definitions and clinical guidelines
-- ---------------------------------------------------------------------------
CREATE TABLE clinical_knowledge (
    knowledge_id    VARCHAR(100) PRIMARY KEY,
    condition_name  VARCHAR(200) NOT NULL,
    category        VARCHAR(100),
    icd10_codes     JSONB NOT NULL DEFAULT '[]',
    description     TEXT,
    key_findings    JSONB NOT NULL DEFAULT '[]',
    differential    JSONB NOT NULL DEFAULT '[]',
    workup          JSONB NOT NULL DEFAULT '[]',
    treatment       JSONB NOT NULL DEFAULT '[]',
    disposition_criteria JSONB NOT NULL DEFAULT '{}',
    resource        JSONB NOT NULL
);

CREATE INDEX idx_knowledge_category ON clinical_knowledge (category);

-- ---------------------------------------------------------------------------
-- protocols: Clinical protocols and bundles
-- ---------------------------------------------------------------------------
CREATE TABLE protocols (
    protocol_id     VARCHAR(100) PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    category        VARCHAR(100),
    description     TEXT,
    steps           JSONB NOT NULL DEFAULT '[]',
    time_targets    JSONB NOT NULL DEFAULT '{}',
    activation_criteria JSONB NOT NULL DEFAULT '{}',
    resource        JSONB NOT NULL
);

CREATE INDEX idx_protocols_category ON protocols (category);

-- ---------------------------------------------------------------------------
-- decision_rules: Clinical decision rules and scoring tools
-- ---------------------------------------------------------------------------
CREATE TABLE decision_rules (
    rule_id         VARCHAR(100) PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    category        VARCHAR(100),
    description     TEXT,
    variables       JSONB NOT NULL DEFAULT '[]',
    scoring         JSONB NOT NULL DEFAULT '{}',
    interpretation  JSONB NOT NULL DEFAULT '{}',
    resource        JSONB NOT NULL
);

CREATE INDEX idx_rules_category ON decision_rules (category);

-- ---------------------------------------------------------------------------
-- treatment_plans: Per-encounter treatment plans
-- ---------------------------------------------------------------------------
CREATE TABLE treatment_plans (
    plan_id         VARCHAR(100) PRIMARY KEY,
    encounter_id    UUID NOT NULL REFERENCES encounters(encounter_id),
    patient_id      UUID NOT NULL REFERENCES patients(patient_id),
    condition_ref   VARCHAR(200),
    medications     JSONB NOT NULL DEFAULT '[]',
    procedures      JSONB NOT NULL DEFAULT '[]',
    monitoring      JSONB NOT NULL DEFAULT '[]',
    disposition_plan VARCHAR(100),
    notes           TEXT,
    resource        JSONB NOT NULL
);

CREATE INDEX idx_plans_encounter ON treatment_plans (encounter_id);
CREATE INDEX idx_plans_patient ON treatment_plans (patient_id);

-- ---------------------------------------------------------------------------
-- supplies: Medications and supplies inventory
-- ---------------------------------------------------------------------------
CREATE TABLE supplies (
    supply_id       VARCHAR(100) PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    category        VARCHAR(100),
    quantity         INTEGER NOT NULL DEFAULT 0,
    unit            VARCHAR(50),
    on_shortage     BOOLEAN NOT NULL DEFAULT false,
    formulary       BOOLEAN NOT NULL DEFAULT true,
    contraindications JSONB NOT NULL DEFAULT '[]',
    resource        JSONB NOT NULL
);

CREATE INDEX idx_supplies_category ON supplies (category);
CREATE INDEX idx_supplies_shortage ON supplies (on_shortage) WHERE on_shortage = true;

-- ---------------------------------------------------------------------------
-- insurance: Patient insurance records
-- ---------------------------------------------------------------------------
CREATE TABLE insurance (
    insurance_id    VARCHAR(100) PRIMARY KEY,
    patient_id      UUID NOT NULL REFERENCES patients(patient_id),
    plan_name       VARCHAR(200),
    plan_type       VARCHAR(50),     -- hmo | ppo | medicare | medicaid | uninsured
    group_number    VARCHAR(100),
    member_id       VARCHAR(100),
    effective_date  DATE,
    expiration_date DATE,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    coverage        JSONB NOT NULL DEFAULT '{}',
    resource        JSONB NOT NULL
);

CREATE INDEX idx_insurance_patient ON insurance (patient_id);
CREATE INDEX idx_insurance_active ON insurance (is_active);

-- ---------------------------------------------------------------------------
-- resources: ED resources (beds, equipment, rooms)
-- ---------------------------------------------------------------------------
CREATE TABLE resources (
    resource_id     VARCHAR(100) PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    resource_type   VARCHAR(100) NOT NULL,  -- bed | equipment | room | vehicle
    location        VARCHAR(100),
    status          VARCHAR(50) NOT NULL DEFAULT 'available',
                    -- available | occupied | maintenance | reserved
    capacity        INTEGER DEFAULT 1,
    attributes      JSONB NOT NULL DEFAULT '{}',
    resource        JSONB NOT NULL
);

CREATE INDEX idx_resources_type ON resources (resource_type);
CREATE INDEX idx_resources_status ON resources (status);

-- ---------------------------------------------------------------------------
-- transfers: Inter-facility transfer records
-- ---------------------------------------------------------------------------
CREATE TABLE transfers (
    transfer_id     VARCHAR(100) PRIMARY KEY,
    encounter_id    UUID NOT NULL REFERENCES encounters(encounter_id),
    patient_id      UUID NOT NULL REFERENCES patients(patient_id),
    destination     VARCHAR(200) NOT NULL,
    reason          TEXT,
    status          VARCHAR(50) NOT NULL DEFAULT 'pending',
                    -- pending | accepted | in_transit | completed | cancelled
    transport_mode  VARCHAR(50),     -- ground | air | critical_care
    estimated_time  INTEGER,         -- minutes
    departed_at     TIMESTAMPTZ,
    arrived_at      TIMESTAMPTZ,
    emtala_compliant BOOLEAN NOT NULL DEFAULT true,
    resource        JSONB NOT NULL
);

CREATE INDEX idx_transfers_encounter ON transfers (encounter_id);
CREATE INDEX idx_transfers_status ON transfers (status);

-- ---------------------------------------------------------------------------
-- reference_materials: Drug references, guidelines, procedure guides
-- ---------------------------------------------------------------------------
CREATE TABLE reference_materials (
    reference_id    VARCHAR(100) PRIMARY KEY,
    title           VARCHAR(500) NOT NULL,
    category        VARCHAR(100),      -- drug_monograph | procedure_guide | guideline | dosing
    content         TEXT,
    keywords        JSONB NOT NULL DEFAULT '[]',
    source          VARCHAR(200),
    last_reviewed   DATE,
    resource        JSONB NOT NULL
);

CREATE INDEX idx_references_category ON reference_materials (category);

-- ---------------------------------------------------------------------------
-- regulatory: Regulatory and legal requirements
-- ---------------------------------------------------------------------------
CREATE TABLE regulatory (
    regulation_id   VARCHAR(100) PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    category        VARCHAR(100),      -- federal | state | hospital_policy | consent
    description     TEXT,
    requirements    JSONB NOT NULL DEFAULT '[]',
    penalties       JSONB NOT NULL DEFAULT '[]',
    applies_to      JSONB NOT NULL DEFAULT '[]',
    resource        JSONB NOT NULL
);

CREATE INDEX idx_regulatory_category ON regulatory (category);

-- ---------------------------------------------------------------------------
-- staff: ED staff (physicians, nurses, techs)
-- ---------------------------------------------------------------------------
CREATE TABLE staff (
    staff_id        VARCHAR(100) PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    role            VARCHAR(100) NOT NULL,  -- attending | resident | nurse | tech
    specialty       VARCHAR(100),
    is_on_duty      BOOLEAN NOT NULL DEFAULT true,
    current_patients INTEGER NOT NULL DEFAULT 0,
    max_patients    INTEGER NOT NULL DEFAULT 6,
    resource        JSONB NOT NULL
);

CREATE INDEX idx_staff_role ON staff (role);
CREATE INDEX idx_staff_on_duty ON staff (is_on_duty) WHERE is_on_duty = true;

-- ---------------------------------------------------------------------------
-- orders: Clinical orders (linked to encounters and tasks)
-- ---------------------------------------------------------------------------
CREATE TABLE orders (
    order_id        VARCHAR(100) PRIMARY KEY,
    encounter_id    UUID NOT NULL REFERENCES encounters(encounter_id),
    order_type      VARCHAR(50) NOT NULL,
                    -- lab | imaging | medication | procedure | consult
    details         JSONB NOT NULL DEFAULT '{}',
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    ordered_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ordered_by      VARCHAR(100),
    resource        JSONB NOT NULL
);

CREATE INDEX idx_orders_encounter ON orders (encounter_id);
CREATE INDEX idx_orders_type ON orders (order_type);
CREATE INDEX idx_orders_status ON orders (status);

-- ---------------------------------------------------------------------------
-- time_constraints: Clinical time targets (SLA equivalent)
-- ---------------------------------------------------------------------------
CREATE TABLE time_constraints (
    constraint_id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    encounter_id    UUID NOT NULL REFERENCES encounters(encounter_id),
    constraint_type VARCHAR(100) NOT NULL,
                    -- door_to_ecg | door_to_balloon | sepsis_antibiotics
                    -- | sepsis_bundle | stroke_ct | trauma_ct | ...
    target_minutes  INTEGER NOT NULL,
    start_time      TIMESTAMPTZ NOT NULL,
    deadline        TIMESTAMPTZ NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
                    -- pending | met | breached
    met_at          TIMESTAMPTZ,
    escalation_path JSONB,                       -- who to notify on breach
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_constraints_encounter ON time_constraints (encounter_id);
CREATE INDEX idx_constraints_status ON time_constraints (status);
CREATE INDEX idx_constraints_deadline ON time_constraints (deadline);

-- ---------------------------------------------------------------------------
-- audit_log: Append-only log of all MCP tool calls
-- ---------------------------------------------------------------------------
CREATE TABLE audit_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id      UUID NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    tool_name       VARCHAR(100) NOT NULL,
    parameters      JSONB NOT NULL DEFAULT '{}',
    result_summary  JSONB,
    duration_ms     INTEGER,
    error           TEXT
);

CREATE INDEX idx_audit_session ON audit_log (session_id);
CREATE INDEX idx_audit_timestamp ON audit_log (timestamp);
CREATE INDEX idx_audit_tool ON audit_log (tool_name);

-- ---------------------------------------------------------------------------
-- Prevent updates and deletes on audit_log (append-only)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION prevent_audit_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only: % operations are not permitted',
                    TG_OP;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_log_immutable
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();
