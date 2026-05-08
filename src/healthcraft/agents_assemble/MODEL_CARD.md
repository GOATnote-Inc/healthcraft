# Model Card — Mercy Point Triage Agent + ED Decision Rules Superpower

**Submission:** Agents Assemble — The Healthcare AI Endgame (Prompt Opinion / Darena Health, May 2026).
**License:** Apache-2.0.
**Repository:** https://github.com/GOATnote-Inc/healthcraft.
**Branch:** `claude/agents-assemble-ideas-Rl9X3`.

This card follows the Mitchell et al. (2019) "Model Cards for Model Reporting" template, adapted for clinical decision-support tools.

## 1. Intended use

**Primary use case:** Advisory support for emergency-department physicians applying validated risk-stratification scores (HEART, Wells PE/DVT, qSOFA, CURB-65, PERC, ABCD2, NEWS2, NEXUS, PECARN, …) to a patient's FHIR Bundle at the point of triage or disposition.

**User:** Licensed emergency-medicine clinicians. The output is *advisory only* (`advisory_only=True`, `requires_physician_review=True` on every `TriagePlan`); it does not place orders, alter the chart, or override clinician judgment.

**Out of scope:**
- Pediatric / neonatal triage beyond the included pediatric rules (PECARN Head CT). No NICU/PICU use.
- ICU-level scoring (SOFA full, APACHE II) — not currently bundled.
- Pharmacy dosing — not implemented.
- Direct patient-facing chatbot use.

## 2. FDA Clinical Decision Support classification

We position this submission as **FDA "Class I" Clinical Decision Support** under the FDA's CDS guidance (21st Century Cures Act §3060, 21 USC §360j(o)(1)(E)). Specifically:

1. The output **describes the basis** for the recommendation — every CDS Hooks card lists the rule name, score, and rule version (SHA-256).
2. The output is **intended for healthcare professionals** to "independently review the basis for such recommendation" — clinicians can verify each variable that fed the score.
3. The output **does not acquire, process, or analyze a medical image**.
4. The output is **not intended to replace** a clinician's judgment.

Together these criteria match the FDA's "non-device CDS" carve-out. A vendor pursuing 510(k) clearance would still need their own regulatory submission; this model card reflects design intent, not regulatory clearance.

## 3. Privacy / safety guardrails

- **PHI scrubber** strips names, telecom, address, identifier values, MRNs, SSNs, phone numbers, and email addresses from any FHIR Bundle before it is shown to the LLM extractor (`agents_assemble.superpower_decision_rules.phi_scrubber`).
- **Safety gate** (rubric criterion `TRG-C05`): blocks `discharge` recommendations when the highest-severity rule risk is `moderate` or `high`.
- **Conflict gate** (rubric criterion `TRG-C06`): when the reasoner finds two rules disagreeing by ≥2 severity levels, or no rule applies, the disposition escalates to `physician_review` rather than silently picking one.
- **Audit log:** every invocation is appended to a JSONL log keyed by `correlationId` with `bundleSha256` + `ruleVersion` + score + risk + disposition (`agents_assemble.audit`). PHI is never written to the log.
- **Determinism:** rule scoring is pure arithmetic; same Bundle + same rule version always produces the same score (asserted by property tests).

## 4. Validation

### 4.1 Property-based testing (engine correctness)

`tests/test_agents_assemble/test_fuzz.py` parameterizes 75 randomized variable assignments against each of 30 rules, asserting:

- Score equals sum of supplied variables (Corecraft Eq. 1 contract).
- Returned risk level is the unique entry in the rule's `score_ranges` containing the score.
- Idempotent under variable insertion order.
- Monotonic in each variable.
- Returned risk level is always in the rule's declared vocabulary.

Two real defects in bundled rule data were found and fixed during property-test development (Wells DVT high-range cap, Wells PE half-step gaps).

### 4.2 Fuzz throughput (engine performance)

`scripts/fuzz_agents_assemble.py` exercises **30 rules × 200 randomized trials = 6,000 evaluations per run** in ≤90 ms (~70K evals/sec, deterministic with `--seed`). 100% pass on every commit.

### 4.3 End-to-end labeled scenarios

`scripts/validate_agents_assemble.py` runs four labeled ED scenarios (STEMI, PE high pretest, PE low pretest, sepsis) end-to-end through the agent and asserts rule selection, risk level, and disposition match the published clinical answer. Current run: **rule 4/4, risk 4/4, disposition 4/4, sensitivity 1.0, specificity 1.0**.

### 4.4 Baseline comparison

`scripts/compare_baseline.py` pits a naive LLM-alone agent (no Superpower, no reasoner, no rule library) against the full agent on the same scenarios:

| Metric | Naive LLM | Ours |
|---|---|---|
| Disposition correct | 3/4 | **4/4** |
| Rule cited | 0/4 | **4/4** |
| Forced-discharge blocked for elevated-risk | 3/3 | 3/3 |
| Conflict / gap detected | n/a | reported per case |

The naive baseline's only "safety win" is by overcorrection — it admits the healthy 28-year-old with reproducible chest-wall pain. Our agent correctly discharges her *while still* blocking discharge for the elevated-risk cohort.

### 4.5 Cohorts NOT yet validated against

The bundled rules cite their respective primary-validation cohorts (HEART on Backus 2010 / Mahler 2018; Wells PE on Wells 2000 / Wolf 2004; qSOFA on Singer 2016; CURB-65 on Lim 2003; etc.). **This submission has not been independently re-validated on those cohorts.** The framework supports such validation — drop a labeled MIMIC-ED or PROMISE export through the harness — but no such run is included.

## 5. Limitations

- **Rule library is 30 of ~80** routinely-used ED rules. Rules using non-additive/regression scoring (PESI full, NIHSS sub-items, GRACE) require an engine extension and are not yet supported.
- **Heuristic reasoner is single-pattern** (most-specific chief-complaint match wins). True multi-rule synthesis requires an LLM client; without one, rules outside the dominant family are not run.
- **Determinism vs LLM extraction.** The deterministic FHIR extractor covers HEART / Wells PE / qSOFA in regex; other rules require LLM extraction, which is non-deterministic without `temperature=0` (we set it).
- **No SMART-on-FHIR launch context handling yet.** The CDS Hooks endpoint accepts unauthenticated POSTs by design (hackathon demo); production needs OAuth2.
- **No multi-tenancy isolation.** A production deployment serving multiple facilities must add tenant-scoped audit logs and rule libraries.

## 6. Ethical considerations

- **Clinical bias:** the bundled rules are derived from cohorts that are predominantly North American and European. Performance on under-represented populations may differ. We surface this risk explicitly rather than smoothing it over.
- **Automation bias:** clinicians may anchor on the agent's recommendation. The CDS Hooks card always shows "physician review required"; the safety + conflict gates force escalation in the highest-stakes cases.
- **Data minimization:** we ship the PHI scrubber on by default and recommend infrastructure-level controls (Prompt Opinion's auth + audit layers) for any production deployment.
- **No HIPAA Business Associate Agreement is in force** for this hackathon submission. A production deployment would require a BAA between the deploying facility and the operator.

## 7. Citation

If you use this Superpower or build on it, please cite:

> Lo, B. (2026). *Mercy Point Triage Agent + ED Decision Rules Superpower.* GOATnote Autonomous Research, Inc. Apache-2.0. https://github.com/GOATnote-Inc/healthcraft

And the prior art it stands on (see `NOTICE`):

- Ehtesham, A.; Singh, A.; Kumar, S. (2025). *Enhancing Clinical Decision Support and EHR Insights through LLMs and the Model Context Protocol: An Open-Source MCP-FHIR Framework.* arXiv:2506.13800.
- HL7. *FHIR R4 specification.* https://hl7.org/fhir/R4/.
- HL7. *CDS Hooks 1.0 specification.* https://cds-hooks.org/.
