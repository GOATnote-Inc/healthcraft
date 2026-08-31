# Pre-Deployment Checklist — Clinical Use With Real PHI

**Version:** v0.1.1
**Audience:** Organizations evaluating this MCP server for clinical deployment

**This is a gating checklist.** Each item is necessary; the order is approximate. The v0.1 reference deployment at `https://mcp.thegoatnote.com/mcp` does **not** satisfy these items and is research/demo only. To use this software with real PHI, your organization must independently complete every item below.

This document complements `docs/COMPLIANCE.md` (control mapping) and `docs/SECURITY_REVIEW_v0.1.1.md` (per-finding security review).

---

## Phase 0 — Determine applicability

- [ ] **Are you a HIPAA Covered Entity** (provider, plan, clearinghouse)? If yes, every item below applies. If no, only items marked "BA-only" apply if you are a Business Associate; if neither, HIPAA does not apply, but state laws (CCPA, CTDPA, GDPR-equivalents) may.
- [ ] **Will any real patient data flow through this server?** If no, you can deploy without a BAA chain but you must still document that PHI is excluded and enforce that exclusion technically.
- [ ] **What is the use case classification?** Decision-support advisory (CDS) is generally not an FDA medical device under §3060 of the 21st Century Cures Act, provided the four CDS carve-out criteria are met. See `MODEL_CARD.md` §2 for the analysis. Other use cases (autonomous triage, diagnostic conclusion delivery, etc.) require regulatory review.

## Phase 1 — Legal and contractual

- [ ] **Sign a BAA with the operator** of the MCP server. If self-hosting, this means your organization is the operator and the BAA chain starts with you and your cloud provider.
- [ ] **Sign a BAA with your cloud provider.** Vercel BAAs are offered on Enterprise plans. AWS, GCP, Azure each have their own BAA processes.
- [ ] **Sign BAAs with any downstream services** the agent calls — LLM providers (Anthropic, OpenAI, Google, etc.), monitoring services (Datadog, Sentry, etc.), logging services.
- [ ] **Vendor management entry** for each BAA-covered party in your organization's vendor inventory.

## Phase 2 — HIPAA Security Rule administrative safeguards

Per `docs/COMPLIANCE.md` §3:

- [ ] Designate a **Security Officer** responsible for this deployment (§164.308(a)(2))
- [ ] Conduct a **Risk Analysis** specific to this deployment (§164.308(a)(1)(ii)(A)). HHS offers a free Security Risk Assessment Tool at healthit.gov/topic/privacy-security-and-hipaa/security-risk-assessment-tool
- [ ] Document a **Risk Management Plan** addressing each identified risk (§164.308(a)(1)(ii)(B))
- [ ] Establish **Workforce Security** policies — authorization, supervision, termination procedures (§164.308(a)(3))
- [ ] Establish **Information Access Management** — authorization process for ePHI access (§164.308(a)(4))
- [ ] Conduct **Security Awareness and Training** for all workforce who configure or operate the service (§164.308(a)(5))
- [ ] Document **Security Incident Procedures** — response, reporting, escalation (§164.308(a)(6))
- [ ] Document a **Contingency Plan** — backup, disaster recovery, emergency mode operation (§164.308(a)(7))
- [ ] Schedule the first **periodic Evaluation** (§164.308(a)(8))

## Phase 3 — Technical configuration

These items configure the v0.1 codebase or upcoming v0.2 features. Refer to `docs/COMPLIANCE.md` §1 for the corresponding HIPAA Security Rule citations.

- [ ] **Enable OAuth 2.1 + SMART-on-FHIR authorization** (v0.2 feature). For v0.1, you must front this server with your own authorization gateway and reject unauthenticated requests at the edge.
- [ ] **Configure SMART scopes** with the minimum-necessary principle. The defaults (`patient/Patient.rs`, `patient/Observation.rs`, `patient/Condition.rs`, `patient/Encounter.rs`, `patient/MedicationRequest.rs`) are appropriate for most ED scoring use cases.
- [ ] **Verify TLS 1.3** at your custom domain. Vercel provisions automatically; for non-Vercel deployments, ensure the TLS terminator is configured for TLS 1.3 with HSTS preload.
- [ ] **Configure no-PHI logging.** v0.1.1 already ships with PHI-safe logging. If you add additional log destinations (Datadog, CloudWatch, etc.), audit each for compliance.
- [ ] **Configure log retention and access controls** per §164.312(b) audit controls and your organization's retention policy.
- [ ] **Provision FHIR resource server with appropriate access controls.** This MCP server does not host FHIR data; it operates on bundles passed in. Your FHIR resource server (Aidbox, Medplum, HAPI FHIR, etc.) must have its own access controls.
- [ ] **Configure CORS to your trusted origins** if not exposing publicly. v0.1 defaults to `*` (open) which is appropriate only for public read-only stateless APIs.

## Phase 4 — Monitoring and operations

- [ ] **SIEM or log aggregation** receiving Vercel function logs and your application audit trail
- [ ] **Alerting** on error rates, latency spikes, and authentication failures
- [ ] **Vulnerability management** — at minimum, `pip-audit` against `requirements.txt` weekly
- [ ] **Dependabot or Renovate** configured on the GitHub repo to auto-PR dependency bumps
- [ ] **Backup / disaster recovery** documented and tested. (For this server: stateless, so DR = redeploy from git tag. Verify your deploy is reproducible.)
- [ ] **Incident response runbook** referencing the contact in `SECURITY.md`

## Phase 5 — SOC 2 readiness (if pursuing attestation)

If your organization is pursuing a SOC 2 Type II report:

- [ ] **Define your TSC scope.** For a healthcare-AI MCP server, recommend Security + Availability + Processing Integrity + Confidentiality. (Privacy mainly applies if you collect PII for organizational use.)
- [ ] **Engage a CPA firm** for the attestation engagement. Budget $20–50k+ for first audit, $15–30k+ annually thereafter.
- [ ] **Collect six to twelve months of evidence** before the audit period begins.
- [ ] **Implement continuous evidence collection** via your SIEM, ticketing system, training records, vendor management system.
- [ ] **Document policies** mapped to each of CC1–CC9 (and Availability / PI / Confidentiality / Privacy criteria if in scope).
- [ ] **Annual penetration test** by an independent third party.
- [ ] **Annual SOC 2 audit** by the CPA firm.

## Phase 6 — Clinical deployment governance

Healthcare-AI-specific items beyond HIPAA / SOC 2:

- [ ] **Clinical governance committee** approval. Decision-support tools should be reviewed by the deploying facility's Pharmacy & Therapeutics Committee or equivalent.
- [ ] **Physician review process** for the bundled rule recommendations. The MODEL_CARD describes the FDA CDS classification — your facility must concur and document that the tool's output is advisory.
- [ ] **Workflow integration design** — where the score appears (EHR sidecar, CDS Hooks card, native AI panel), how it integrates with existing order sets, and what action it does or does not take automatically.
- [ ] **Periodic model performance review** — recommend quarterly for first year, annually thereafter. Compare against MACE outcomes for HEART scoring patients, etc.
- [ ] **Clinician feedback channel** for false positives, false negatives, and recommendation misalignment.
- [ ] **Decommissioning plan** — how to retire the tool if performance degrades or evidence base shifts.

---

## Sign-off

For each deployment of this software with real PHI, the following parties should review and sign off on completion of this checklist:

- HIPAA Security Officer
- Privacy Officer
- Chief Medical Information Officer (or equivalent clinical sponsor)
- Compliance / Legal counsel
- Information Security (CISO or designee)

A sample sign-off template is below:

```
HIPAA / SOC 2 Pre-Deployment Sign-Off
=====================================

Deployment:     ____________________________________________
Endpoint:       ____________________________________________
Date:           ____________________________________________
Software:       ED Decision Rules MCP, version __________

Signed BAA chain:
  - Operator <-> Deploying org:      ☐ on file, dated ____
  - Deploying org <-> Cloud:         ☐ on file, dated ____
  - Deploying org <-> LLM provider:  ☐ on file / N/A
  - Deploying org <-> Monitoring:    ☐ on file / N/A

Risk Analysis completed:             ☐ ____ Yes  ____ No
Risk Management Plan filed:          ☐ ____ Yes  ____ No
Security Officer designated:         ☐ ____ Yes  ____ No
Incident Response runbook:           ☐ ____ Yes  ____ No
Backup / DR tested:                  ☐ ____ Yes  ____ No

Approved by:
  Security Officer:   _________________________ Date: ____
  Privacy Officer:    _________________________ Date: ____
  CMIO:               _________________________ Date: ____
  Compliance/Legal:   _________________________ Date: ____
  CISO:               _________________________ Date: ____
```

This template is offered as a starting point and is not legal advice. Adapt it to your organization's signature policies.
