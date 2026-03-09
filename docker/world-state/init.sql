-- HEALTHCRAFT World State Schema
-- PostgreSQL 16 with FHIR R4-compatible columns
-- All clinical content is synthetic.

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
