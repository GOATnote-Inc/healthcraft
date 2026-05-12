# Compliance Posture — HIPAA & SOC 2 Readiness

**Version:** v0.1.1
**Last reviewed:** 2026-05-11
**Scope:** ED Decision Rules MCP server hosted at `https://mcp.thegoatnote.com/mcp` and the open-source codebase at `github.com/GOATnote-Inc/healthcraft`.

---

## What this document is — and what it is not

This document maps the **technical and administrative controls implemented in this codebase** to the relevant clauses of the **HIPAA Security Rule (45 CFR §164.312)** and the **AICPA SOC 2 Trust Service Criteria**. It is intended as a reference for security engineers, compliance officers, and prospective deploying organizations.

**It is not** a claim of HIPAA compliance, SOC 2 certification, or regulatory approval. Those are properties of an *organization* with documented policies, signed Business Associate Agreements (BAAs), workforce training, an independent third-party audit (for SOC 2), and operational evidence over time — not properties of source code. This document describes the **technical substrate** an organization would build on, and explicitly enumerates the **administrative, physical, and operational controls the organization must add** before any clinical deployment involving Protected Health Information (PHI).

The default disposition of this software, in its v0.1 form, is:

> **Research-use, demo, and hackathon use only. Not for production use with real PHI without (a) a signed BAA between the deploying organization and any cloud provider, (b) a completed HIPAA Security Rule risk analysis, (c) implementation of the administrative controls listed in §3 below, and (d) — for any SOC 2 attestation — an independent CPA audit.**

---

## 1. HIPAA Security Rule — Technical Safeguards (45 CFR §164.312)

| § | Standard / Implementation Spec | Required / Addressable | Status in v0.1.1 | Evidence |
|---|---|---|---|---|
| **(a)(1)** | Access Control | Required | **Partial (open access)** | v0.1 is explicitly open-access; OAuth 2.1 + RFC 8707 Resource Indicators per MCP June 2025 spec are scheduled for v0.2. See `.well-known/oauth-protected-resource` for explicit `auth_required: false` disclosure. |
| **(a)(2)(i)** | Unique User Identification | Required | **Deferred to v0.2** | No per-user identity in v0.1; deploying organization must front this server with a SMART-on-FHIR authorization server before clinical use. |
| **(a)(2)(ii)** | Emergency Access Procedure | Required | **Org responsibility** | Operational procedure; not a code artifact. Document in deploying org's emergency access policy. |
| **(a)(2)(iii)** | Automatic Logoff | Addressable | **N/A in v0.1** | No sessions; every request is stateless. |
| **(a)(2)(iv)** | Encryption and Decryption (at rest) | Addressable | **N/A — no PHI at rest** | The server persists no PHI. Audit hashes (rule version + bundle SHA-256) are returned in the response, never stored. |
| **(b)** | Audit Controls | Required | **Implemented** | Every `applyDecisionRule` response includes (i) `ruleVersion` = SHA-256 of the rule definition, (ii) `sharp.trace[].bundleSha256` = SHA-256 of the input bundle, (iii) `extraction.rationale` mapping FHIR resources to scored variables. The caller is responsible for persisting these. Server-side logs intentionally exclude PHI per security review M1 fix. |
| **(c)(1)** | Integrity | Required | **Implemented** | SHA-256 hashes provide cryptographic integrity for both the rule artifact and the input bundle. A future re-execution with the same inputs is bit-for-bit reproducible — asserted by property tests. |
| **(c)(2)** | Mechanism to Authenticate ePHI | Addressable | **Implemented** | The hashes in §(b) above also authenticate that the ePHI scored was the ePHI received; tampering is detectable. |
| **(d)** | Person or Entity Authentication | Required | **Deferred to v0.2** | No authentication in v0.1. Production clinical use requires the deploying organization to authenticate callers via OAuth 2.0 / SMART-on-FHIR; the MCP June 2025 spec defines the upgrade path. |
| **(e)(1)** | Transmission Security | Required | **Implemented** | TLS 1.3 enforced via Vercel edge; HSTS `max-age=63072000` (2-year preload-eligible). Let's Encrypt cert valid through 2026-08-09; auto-renewed by Vercel. |
| **(e)(2)(i)** | Integrity Controls (in transit) | Addressable | **Implemented** | TLS 1.3 provides AEAD encryption with integrity. Application layer adds SHA-256 audit hashes (§b). |
| **(e)(2)(ii)** | Encryption (in transit) | Addressable | **Implemented** | TLS 1.3, modern cipher suites enforced by Vercel edge. |

### HIPAA Privacy Rule — Minimum Necessary (§164.502(b))

| Concern | Status | Evidence |
|---|---|---|
| Minimum-necessary scope requests | **Implemented** | SMART v2 `patient/Resource.rs` (read+search) for 5 narrow resource types: `Patient`, `Observation`, `Condition`, `Encounter`, `MedicationRequest`. No wildcards, no `system/*.*`, no `.write` / `.delete`. |
| PHI minimization in logs | **Implemented (v0.1.1)** | Per security review M1: `[MCP-IN]` log line carries only method, byte count, User-Agent. No body content. |
| PHI minimization in responses | **Implemented** | Responses contain `bundleSha256` (hash, not data), scoring output, and `extraction.rationale` (mapping of FHIR `Observation.code` → variable, no values). Patient name/DOB/MRN are not echoed. Verified by planted-PII test in audit. |
| De-identification claims | **Not asserted** | This server does not de-identify; it operates on whatever the caller sends. De-identification is the caller's responsibility before sending PHI to a non-BAA-covered service. |

---

## 2. SOC 2 — Trust Service Criteria Mapping

The SOC 2 framework (AICPA TSP §100A, 2017 TSC with 2022 points-of-focus) defines five Trust Service Categories. **Security** is the only TSC required for every SOC 2 report; the others are added based on the service's commitments. For a healthcare-AI MCP server, **Security + Availability + Processing Integrity + Confidentiality** are the relevant in-scope categories. **Privacy** mainly applies to systems that *collect* PII for organizational purposes; we do not collect, store, or process PII for our own use.

### Common Criteria (Security) — CC1 through CC9

| Criterion | Description | v0.1.1 control | Evidence |
|---|---|---|---|
| **CC1** | Control Environment | Governance files in repo; published roadmap; named maintainer | `LICENSE` (Apache-2.0), `CONTRIBUTING.md`, `SECURITY.md`, `CITATION.cff` |
| **CC2** | Communication and Information | Public security review, model card, FDA-CDS positioning | `docs/SECURITY_REVIEW_v0.1.1.md`, `src/healthcraft/agents_assemble/MODEL_CARD.md` |
| **CC3** | Risk Assessment | Informal threat model; per-finding writeup | `docs/SECURITY_REVIEW_v0.1.1.md` §Threat Model |
| **CC4** | Monitoring Activities | Vercel function logs + non-PHI observability | App.py `[MCP-IN]` log; Vercel deployment dashboard. (No SIEM in v0.1 — deploying org responsibility.) |
| **CC5** | Control Activities | OWASP hardening headers, body size cap, exception sanitization, CORS, TLS | v0.1.1 commits; verified live via test suite |
| **CC6** | Logical and Physical Access Controls | **Deferred to v0.2** for application-layer access (OAuth). Physical access = Vercel data center controls (SOC 2 Type II covered by Vercel). | Vercel SOC 2 report (separate); roadmap in `docs/COMPLIANCE.md` |
| **CC7** | System Operations | Deployment via Vercel; incident response = email channel in `SECURITY.md` | `SECURITY.md` reporting policy; deploy history in Vercel dashboard |
| **CC8** | Change Management | Git history, branch protection on `main`, CI tests, signed releases | GitHub branch protection on `main` (per project memory); `.github/workflows/` (CI); 253 tests on every PR |
| **CC9** | Risk Mitigation | Documented in `SECURITY_REVIEW_v0.1.1.md` per finding | Per-finding mitigation table |

### Availability TSC

| Criterion | v0.1.1 control | Notes |
|---|---|---|
| Availability commitments | None published; demo SLA | Production deploying org must establish their own SLA backed by Vercel's regional uptime guarantees. |
| Capacity planning | Vercel Fluid Compute auto-scaling | Function autoscales horizontally; cold-start measured ~250ms, warm <300ms. |
| Backup and recovery | Stateless server — no data to back up | Rule library re-loaded from code on every cold start; deterministic. |
| Disaster recovery | Multi-region failover provided by Vercel edge | Vercel handles regional failover. |

### Processing Integrity TSC

| Criterion | v0.1.1 control |
|---|---|
| Inputs validated for completeness, accuracy, validity | F1 fix (v0.1.1): rules with no resolvable variables return `status: error, code: missing_variables` rather than silently scoring 0. JSON-RPC parse errors return -32700. Unknown tools return -32602. Oversize bodies return 413. |
| Processing reproducibility | Rule version SHA-256 + bundle SHA-256 in every response; same inputs produce bit-for-bit identical outputs (property-tested). |
| Output completeness | Every response includes the scored result, extraction rationale, supplied/missing variable lists, and rule version hash. |
| Output authorized | Every response is generated by deterministic code paths only; no LLM in the scoring path. |

### Confidentiality TSC

| Criterion | v0.1.1 control |
|---|---|
| Confidential data identified | PHI in caller-supplied FHIR Bundles. |
| Retention policy | **Zero retention.** Stateless server. No PHI persisted on disk, in logs, or in caches. |
| Access restrictions | TLS 1.3 in transit; no at-rest storage. CORS open to public for demo (read-only stateless API). |
| Disposal | N/A — no storage to dispose. |

### Privacy TSC

Not asserted in v0.1. This server does not act as a data controller; it processes what the caller provides and returns scoring results without retaining PII. Organizations deploying this in a Privacy-TSC-relevant context (consumer-facing applications under GLBA, CCPA, GDPR, etc.) must add their own privacy controls upstream.

---

## 3. What the deploying organization must add (administrative & physical safeguards)

This codebase delivers technical safeguards. **Production clinical use with real PHI requires the deploying organization to implement the following separately:**

### HIPAA Security Rule — Administrative Safeguards (§164.308)

- [ ] Designated **Security Officer** (§164.308(a)(2))
- [ ] **Risk Analysis** documenting threats to ePHI processed by this service (§164.308(a)(1)(ii)(A))
- [ ] **Risk Management** plan addressing identified risks (§164.308(a)(1)(ii)(B))
- [ ] **Workforce Security** policies including authorization, supervision, termination (§164.308(a)(3))
- [ ] **Information Access Management** — authorization process for ePHI access (§164.308(a)(4))
- [ ] **Security Awareness and Training** for all workforce who configure or operate the service (§164.308(a)(5))
- [ ] **Security Incident Procedures** including response and reporting (§164.308(a)(6))
- [ ] **Contingency Plan** — data backup, disaster recovery, emergency mode operation (§164.308(a)(7))
- [ ] **Evaluation** — periodic technical and non-technical evaluation (§164.308(a)(8))
- [ ] **Business Associate Contracts** (§164.308(b)) — see §4 below

### HIPAA Security Rule — Physical Safeguards (§164.310)

These are largely fulfilled by Vercel's underlying SOC 2 Type II posture for the data center, server, and workstation controls. The deploying organization must:

- [ ] Obtain and review Vercel's current **SOC 2 Type II report**
- [ ] Document the Vercel relationship in the organization's **vendor management** inventory
- [ ] Confirm Vercel offers a **BAA** for the chosen plan tier (Vercel offers BAAs on Enterprise plans; verify before any PHI deployment)

### SOC 2 Type II — additional requirements

- [ ] Six-to-twelve-month **evidence collection period** before audit
- [ ] **CPA firm engagement** for the independent audit (typical cost $20-50k+)
- [ ] **Continuous monitoring** infrastructure (SIEM, log aggregation, alerting)
- [ ] **Vendor management program**
- [ ] **HR controls** (background checks, training records, terminations)
- [ ] **Documented policies** mapped to each TSC

---

## 4. Business Associate Agreement (BAA) — when required

### When you need a BAA

Under HIPAA, a Business Associate is any entity that *creates, receives, maintains, or transmits* PHI on behalf of a Covered Entity. **If you, the deploying organization, are a Covered Entity (provider, plan, or clearinghouse) and you send real patient PHI through this MCP server**, then:

1. **You need a BAA with this software's operator.** For the v0.1 reference deployment at `mcp.thegoatnote.com`, **no BAA is currently offered** — that endpoint is research/demo use only. Do not send real PHI to it.
2. **You need a BAA with your hosting provider.** If self-hosting on Vercel, you need Vercel's BAA (offered on Enterprise plans). If self-hosting on AWS/GCP/Azure, you need their respective BAAs.
3. **You need BAAs with any downstream service** (logging, monitoring, LLM providers if you call this server from an LLM agent that processes PHI).

### What the BAA must cover

Per 45 CFR §164.504(e)(2), the BAA must establish that the Business Associate will:

- Use/disclose PHI only as permitted by the BAA or required by law
- Use appropriate safeguards to prevent unauthorized use/disclosure
- Report breaches and security incidents
- Ensure that any subcontractors agree to the same restrictions
- Make PHI available for amendment, accounting of disclosures, and individual access
- Return or destroy PHI at termination of the contract

### Recommended pre-deployment checklist for clinical use

See `docs/PRE_DEPLOYMENT_CHECKLIST.md`.

---

## 5. Verifiable claims and their evidence

This is the section a reviewer or auditor can run against. Every claim in this document maps to a verifiable artifact.

| Claim | How to verify |
|---|---|
| Every response includes rule version SHA-256 | `curl https://mcp.thegoatnote.com/mcp -d ... | jq '.result.structuredContent.data.ruleVersion'` returns a 64-char hex string |
| Every response includes bundle SHA-256 | `... | jq '.result.structuredContent.sharp.trace[].bundleSha256'` returns 64-char hex (or "" for empty bundle) |
| No PHI in observability logs | `grep -n "body=" app.py` returns no match in the log statement |
| TLS 1.3 + HSTS enforced | `curl -sI https://mcp.thegoatnote.com/healthz | grep -i strict-transport-security` returns `max-age=63072000` |
| OWASP hardening headers present | Same curl returns `x-content-type-options: nosniff`, `x-frame-options: DENY`, `referrer-policy: no-referrer`, `content-security-policy: default-src 'none'; frame-ancestors 'none'` |
| Body size cap enforced | Raw-socket POST with `Content-Length: 6291457` returns HTTP 413 |
| Discovery endpoint declares open access | `curl https://mcp.thegoatnote.com/.well-known/oauth-protected-resource` returns `auth_required: false` + supported scopes |
| MCP spec compliance | `npx -y @modelcontextprotocol/inspector --cli https://mcp.thegoatnote.com/mcp --method tools/list` exits 0 |
| Tests for every security control | `pytest tests/test_agents_assemble/test_excellence_audit.py -v` — 22 tests, all pass |
| 253 tests across the full suite | `pytest tests/test_agents_assemble/ -q` — 253 pass |
| No shell injection / eval / pickle | `grep -rE "os.system|shell=True|eval\(|exec\(|pickle.load" src/healthcraft/agents_assemble/ app.py` returns empty |
| No secrets in tracked files | `git ls-files | xargs grep -lE "AIzaSy[A-Za-z0-9_-]{30,}|sk-[A-Za-z0-9]{40,}|sso-key"` returns empty |
| Production deps free of known CVEs | `pip-audit -r requirements.txt` (note: `.venv` includes dev deps with CVEs; runtime image installs only `pyyaml`, `jsonschema`, `fastapi`) |
| Reproducible scoring | `pytest tests/test_agents_assemble/test_fuzz.py` — 19,600 fuzz evaluations all pass |

---

## 6. Roadmap to v0.2 (compliance-driven)

The following items are committed to v0.2 and are the gating items for HIPAA Security Rule §164.312(a)(2)(i) and §164.312(d) compliance:

1. **OAuth 2.1 + PKCE + RFC 8707 Resource Indicators** per [MCP June 2025 spec](https://auth0.com/blog/mcp-specs-update-all-about-auth/) — closes §(a)(1) Access Control and §(d) Person/Entity Authentication
2. **Per-tool scope enforcement** at the application layer — closes "incremental scope consent" requirement
3. **CI vulnerability scanning** — pip-audit in CI with failure on new CVEs; closes CC4 monitoring expectation
4. **SBOM generation** (CycloneDX) — supply-chain transparency
5. **Container image digest pinning** with Renovate auto-bumps — closes supply-chain risk
6. **Application-layer rate limiting** — closes availability/DDoS gap
7. **Webhook signature verification** for callback-style integrations (when added)
8. **Centralized PHI-detection middleware** as a defense-in-depth check that no PHI ever lands in a log line, regardless of caller behavior

---

## 7. Sources

- [HIPAA Security Rule, 45 CFR Part 164 Subpart C](https://www.hhs.gov/hipaa/for-professionals/security/laws-regulations/index.html)
- [HIPAA Privacy Rule, 45 CFR Part 164 Subpart E](https://www.hhs.gov/hipaa/for-professionals/privacy/index.html)
- [AICPA Trust Service Criteria (TSP §100A, 2017 with 2022 points-of-focus)](https://us.aicpa.org/interestareas/frc/assuranceadvisoryservices/trustservices)
- [MCP June 2025 spec — OAuth 2.1 Resource Servers](https://auth0.com/blog/mcp-specs-update-all-about-auth/)
- [SMART App Launch v2.2.0 — Best Practices](https://hl7.org/fhir/smart-app-launch/best-practices.html)
- [HHS HIPAA Security Risk Assessment Tool](https://www.healthit.gov/topic/privacy-security-and-hipaa/security-risk-assessment-tool)
- [Vercel Trust Center](https://vercel.com/security) (for the underlying platform's SOC 2 Type II coverage)
- This repo's `docs/SECURITY_REVIEW_v0.1.1.md` for the per-finding technical review
- This repo's `src/healthcraft/agents_assemble/MODEL_CARD.md` for the FDA Clinical Decision Support positioning
- This repo's `docs/PRE_DEPLOYMENT_CHECKLIST.md` for the operational gating items
