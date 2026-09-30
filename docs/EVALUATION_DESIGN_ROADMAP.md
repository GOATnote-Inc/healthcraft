# Evaluation design roadmap

Research date: **2026-09-30**. This is a proposed engineering and research
roadmap, not a list of shipped capabilities or evidence of superiority.
The current result accounting remains in
[FRONTIER_ACCOUNTING_OPUS48_GPT55.md](FRONTIER_ACCOUNTING_OPUS48_GPT55.md).
The training/clinical-readiness boundary remains in
[RL_COUPLING.md](RL_COUPLING.md).

## Objective and evidence standard

Build an emergency-medicine evaluation environment whose results another
team can reproduce, audit, and challenge. Measure successful clinical
workflows, harmful actions, omissions, recovery, and cost separately.
A low frontier pass rate alone is not success: impossible tasks, broken
tools, and inaccurate judges can all create one. Preserve the existing
Eq. 1 benchmark reward and immutable historical results; add diagnostics
and versioned experiments around them.

The desired differentiator is inspectable evidence: every score can be
traced to a task version, initial state, agent action, tool result,
verification rule, and adjudication. A superiority claim requires a
predeclared, comparable evaluation and independent clinical review. No
such claim follows from this roadmap or a local smoke test.

## Comparable work and lessons

These are primary-source descriptions, not independently reproduced
performance claims. The user confirmed **Archangel Health**. “Basten”
probably means Baseten; Bastion Intelligence is a separate plausible
reference and is listed separately until that name is confirmed.

| Project | Verified relevant capability | Implication for HealthCraft |
|---|---|---|
| [Corecraft, v5](https://arxiv.org/html/2602.16179v5) | Stateful enterprise world, MCP tools, atomic rubric reward, and held-out/external transfer evaluation. Its design explicitly prioritizes task diversity over entity/tool counts. | Demonstrate valid task difficulty and transferable skills; more entities and tools are insufficient. |
| [Baseten clinical scribe work](https://www.baseten.co/blog/fine-tuning-small-open-source-llms-to-outperform-large-closed-source-models-by-60/) | Expert-aligned, granular evaluation drives specialist-model optimization; separates source fidelity, salience, safety, and formatting. Reported gains concern its own scribe distribution. | Check source-grounded omissions and unsupported claims separately; publish judge agreement and a fixed held-out comparison. Do not compare its relative scribe improvement with HealthCraft pass rates. |
| [Archangel Health products](https://www.archangelhealth.ai/products) | Describes sandboxed EHR tool use with step grading, multi-visit tasks evaluated against subsequent events, physician-authored training data/rubrics, and verifier-based RL. Its Medical Guideline Benchmark is marked **coming soon**. | Add replayable step evidence, longitudinal checkpoints, and guideline provenance. Its physician contribution is a substantive validation bar, not something model consensus replaces. Public product descriptions do not establish a reproducible numerical baseline. |
| [Bastion Clinical AI Evaluation](https://bastionintelligence.com/research) | Reports 40 synthetic cases across four workflow families, separated author/candidate/judge roles, code-enforced critical failures, and human-review flags. | Separate evaluation roles and surface review queues; report critical failures and judge disagreements instead of hiding them in an average. |
| [Stanford MedAgentBench](https://stanfordmlgroup.github.io/projects/medagentbench/) | 300 physician-written tasks in a FHIR-compatible EHR, with retrieval and action tasks over longitudinal records. | Compare against an actual clinical tool benchmark; evaluate state mutations, not just answer plausibility. Its patient-derived data is outside HealthCraft's synthetic-only corpus policy. |
| [MedAgentGym](https://wshi83.github.io/MedAgentGym-Page/) | Code-based medical reasoning with execution-grounded answers and separate internal/external validation scenarios. | Borrow the execution-verification and transfer protocol; keep clinical workflow evaluation distinct from biomedical coding. |
| [Microsoft HealthAgentBench](https://github.com/microsoft/HealthAgentBench) | 54 Harbor tasks in seven categories, including imaging, EHR data quality, ETL, trial matching, and event modeling; reports repeated-trial intervals, time, and cost. | Support a portable task adapter and task-specific verifiers. Add modalities only with validated task contracts, not merely image input support. |
| [Amazon PatientAgentBench](https://github.com/amazon-science/PatientAgentBench) | Synthetic patient conversations, stateful healthcare tools, generated scenarios, and clinician-grounded jury rubrics. | Treat patient interaction and scenario generation as independently evaluated components; generated variation alone does not prove absence of contamination. |
| [MedARC/Sophont Medmarks](https://sophont.med/blog/medmarks/) | Combines verifiable, open-ended, and agentic evaluation; exposes reusable environments and multiple judge models. | Provide interoperable evaluation outputs and measure agreement between deterministic checks, model judges, and clinical reviewers. |
| [NVIDIA NeMo Gym](https://github.com/NVIDIA-NeMo/Gym) | Local/hosted model interfaces, resource servers, verified rollouts, materialized input artifacts, and per-task profiling. | Adopt compatible adapter boundaries and complete run provenance; keep a lightweight CPU/offline path. |
| [NVIDIA ambient healthcare agents](https://github.com/NVIDIA-AI-Blueprints/ambient-healthcare-agents/) and [Digital Health skills](https://github.com/NVIDIA/digital-health-skills) | Provider/patient agent examples plus a clinical-ASR workflow with term/entity-level error measurement. | Test a critical value, unit, negation, or drug-name corruption as a downstream workflow hazard; generic transcript accuracy is insufficient. |

Archangel's product details above were read from the rendered official page
on 2026-09-30 because the text-only fetch did not expose its content. There
was no contact, sign-in, dataset request, or submission to the company.

## Local model strategy and frontier compatibility

**Local models are engineering baselines, not validated clinical judges.**
Use installed weights and local endpoints for free-of-API-charge testing;
record wall time, hardware, memory, quantization, model revision, context
limit, chat template, sampler, and tool parser. A run being local does not
make its generated trajectories deterministic. Separate exact replay of a
saved trajectory from repeat sampling of the model.

- [MedGemma 1.5 4B](https://developers.google.com/health-ai-developer-foundations/medgemma/model-card)
  is a practical medical text/image baseline. Google explicitly states it
  has not been optimized or evaluated for multi-turn use. Report native
  tool support versus any prompted JSON adapter; preserve malformed calls
  as failures. Do not promote it to a clinical oracle because it is medical.
- [Nemotron 3 Nano 30B-A3B](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16)
  is a tool-use baseline with official local serving recipes. NVIDIA's
  recipe specifies `qwen3_coder` tool parsing and `nano_v3` reasoning
  parsing; its recommended tool sampler is temperature 0.6/top-p 0.95.
  Record the actual installed variant rather than assuming all “Nano”
  models share that contract. Active parameters are not resident size.
- Add a small general-purpose local model only to isolate medical
  specialization from general tool-use competence. Compare identical
  tasks, budgets, prompts, and grading channels; report protocol validity,
  completion, safety, and latency separately.
- Official [GPT-6 Astra guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-6-astra)
  requires **Responses** for tool calling; changing a model string on the
  Chat Completions client is insufficient. Preserve supported reasoning
  effort explicitly and omit unsupported sampling parameters. Build
  fixture-based contract tests before any hosted evaluation.
- [Claude Fable](https://www.anthropic.com/claude/fable) is positioned for
  long-running, multi-application work and recovery. This motivates tests
  of interruption, delayed information, and recovery; product positioning
  is not a measured HealthCraft result. Pin the actual API model/version
  and supported parameters before evaluating it.

No paid API evaluation, cloud GPU training, or model download is launched
by this document. A later frontier comparison requires explicit run
configuration and a spend decision, separate from offline engineering.

## Ranked acceptance criteria

The thresholds below are proposed release gates. Existing tests and
implementation may satisfy pieces; each gate needs an attached report
before it is marked complete.

| Priority | Deliverable | Acceptance evidence |
|---|---|---|
| P0 | Trustworthy execution and scoring | Every persisted run distinguishes agent failure, invalid tool call, provider failure, grader failure, and incomplete execution. No unavailable grader result becomes a successful criterion. Report ungraded coverage separately from safety failures; preserve fail-closed reward semantics. |
| P0 | Versioned run identity | Manifest captures code revision/dirty state, task content hash, overlays, prompts, tool schemas, world/episode seed, actual model endpoint identity, and generation settings. Resume rejects incompatible configuration; corrupt artifacts are surfaced. Changed configuration cannot silently reuse old scores. |
| P0 | Offline evaluator challenge suite | Deterministic probes include no action, text-only success claims, failed mutations, wrong-patient actions, stale/duplicate calls, and out-of-order workflows. All intentionally invalid affirmative checks fail; every safety violation probe gates reward to zero. Publish per-criterion failures and probe coverage. |
| P0 | Local end-to-end baseline | MedGemma and Nemotron each complete a real local request and a bounded tool trajectory with captured raw response, parser outcome, and tool result. No remote fallback. Non-tool-capable adapters are labeled. A refused/malformed response is recorded, not repaired into apparent success. |
| P1 | Task validity certificates | Each new task has an executable successful reference trajectory, an omission/unsafe counterexample, and evidence that required facts and actions are reachable. Cover 100% of deterministic criteria; flag remaining judged criteria for human review. Static tool-name reachability is not a successful reference trajectory. |
| P1 | Calibrated judging | Freeze a physician-adjudicated set before optimization, with safe/unsafe and omission/commission examples. Report sensitivity, specificity, abstention, agreement, sample counts, and intervals by safety status/category. Require zero observed safety false passes on the release gold set, while publishing the uncertainty bound; zero observed errors is not proof of zero risk. |
| P1 | Stable grounding under benign changes | IDs, irrelevant-record order, harmless note formatting, and equivalent units do not change reference verdicts. Counterfactual critical changes must flip the intended verdict. Every perturbation documents which facts and expected outcomes remain invariant. |
| P1 | Longitudinal and fault recovery | Seeded delayed results, unavailable resources, retries, and multi-visit updates have explicit event times and expected state transitions. Correctly recovered runs preserve state invariants; failed/duplicate mutations cannot create extra orders. Run replay twice and compare state/evidence hashes. |
| P1 | Leakage-resistant development | Disjoint episode seeds, patients, task templates, and clinical scenario families are declared where feasible. Record overlap checks and known public-data exposure. Freeze held-out families before reward tuning; do not call a seed-only split out-of-distribution validation. |
| P1 | Comparable reports | Report task-macro and trial-level Pass@1, empirical all-trial reliability, safety events, unsupported/ungraded cases, tool use, latency, and local resource cost. Use paired comparisons and task-clustered uncertainty; missing runs stay visible. Preserve historical metric definitions and label new estimators. |
| P2 | Portable ecosystem adapter | A Harbor or NeMo Gym adapter reproduces the same initial state, tool audit, criterion results, and terminal reward as native execution for reference success, safety failure, and tool-error fixtures. Adapter imports stay optional. |
| P2 | Evidence-based training claim | Preregister the reward ablations and anti-gaming probes from issues #8–#10; compare base/SFT/RL on frozen held-out and external tasks. Improved training reward alone cannot support a transfer or clinical-readiness claim. |

## Concrete next implementation slice

After repository regressions and local provider compatibility, implement an
**offline rubric challenge report** in a new diagnostics module and CLI.
This complements the current static satisfiability tests and RL
distribution canaries without changing the published rubric.

1. Define typed probe outcomes: expected failure/success, observed verdict,
   criterion/task ID, probe type, evidence, and `unsupported` reason.
2. Start with deterministic audit checks: empty audit, a failed matching
   mutation, a matching action for the wrong encounter, and a successful
   matching action. Derive expectations only when the checker contract
   supports them; do not infer medical correctness from keywords.
3. Add reference-based perturbations for ordering and duplicates where a
   reviewed reference trajectory exists. Never fabricate a passing
   clinical trajectory by copying the rubric's own string parser.
4. TDD: demonstrate a permissive fake verifier is detected, a correct
   verifier passes, negated criteria are classified correctly, missing
   expectations stay unsupported, and diagnostic execution does not mutate
   tasks or historical results.
5. Emit deterministic JSON plus a concise report with coverage and
   actionable failures. The CLI exits nonzero for violated expectations;
   unsupported coverage is reported separately. No LLM call is needed.

This slice makes grader quality inspectable before expensive model runs.
Its report must say which probes were exercised; it does not certify the
entire task bank or clinical validity.

## Reuse decisions

| Source | Decision | Conditions |
|---|---|---|
| [NeMo Gym](https://raw.githubusercontent.com/NVIDIA-NeMo/Gym/main/LICENSE), [NeMo Evaluator](https://raw.githubusercontent.com/NVIDIA-NeMo/Evaluator/main/LICENSE) | Prefer optional adapters and artifact conventions to vendoring a second training stack. | Apache-2.0 code; preserve notices for any copied code. Environment datasets can carry separate licenses. |
| [HealthAgentBench](https://github.com/microsoft/HealthAgentBench), [Medmarks](https://raw.githubusercontent.com/MedARC-AI/medmarks/main/LICENSE) | Reuse MIT adapter/reporting code only after a bounded integration need is demonstrated. | Retain copyright/license notices; code license does not grant access or redistribution rights to MIMIC, EHRSHOT, or other datasets. |
| [PatientAgentBench](https://github.com/amazon-science/PatientAgentBench#license) | Study methodology; do not copy code/data into the Apache-2.0 product. | Repository is CC-BY-NC-4.0. It is not a permissive commercial-code dependency. |
| MedGemma and Nemotron weights | Use independently installed models as optional local baselines. | MedGemma has Health AI Developer Foundations terms; NVIDIA model licensing is separate from NeMo's code license. Record the exact model license and revision before redistribution. |
| Archangel, Baseten, Bastion, Corecraft | Cite architecture and evaluation lessons; do not imply access to their proprietary data, verifiers, or production results. | No code/data reuse license was established for these commercial offerings during this review. |
| Patient-derived benchmark datasets | Keep external validation separately gated and provenance-tracked. | HealthCraft's public world/task fixtures remain synthetic-only. Do not import patient records to increase entity count. |

Any external code adoption needs a pinned revision, license/notice record,
and tests of the integration boundary. No external source code or dataset
was copied into HealthCraft as part of this research document.

## Paper and documentation gaps to resolve

- The paper abstract still leads with V8, while README now identifies v10
  as canonical. Preserve historical figures but align version labels and
  the current evidence narrative in a dedicated, verified paper revision.
- The paper's related work should include MedAgentBench, MedAgentGym, and
  subsequent healthcare agent benchmarks. Review any “first” claim against
  exact release chronology and its emergency-medicine/RL/safety scope;
  broad clinical-agent novelty is not established by the current section.
- Audit architecture prose against runtime: README now says in-memory,
  FHIR-R4-shaped state, while paper describes a PostgreSQL FHIR world.
  A representation shaped like FHIR is not independently validated FHIR
  conformance, and container scaffolding is not proof of a persisted DB.
- Keep ensemble consensus, prospective physician validation, and training
  outcomes separate. The canonical v10 common judge is explicitly
  unvalidated clinically in README; model agreement cannot remove that
  limitation.
- Corecraft author names in README, the attribution document, and the
  bibliography were corrected against the [versioned primary paper](https://arxiv.org/abs/2602.16179v5).
- The repository's passive-maintenance banner conflicts with a renewed
  development program. Update maintenance status only with the actual
  program state, and link shipped releases to their validation evidence.

Issue references: [live training #8](https://github.com/GOATnote-Inc/healthcraft/issues/8),
[reward ablations #9](https://github.com/GOATnote-Inc/healthcraft/issues/9),
[physician-blind validation #10](https://github.com/GOATnote-Inc/healthcraft/issues/10),
[paper update #11](https://github.com/GOATnote-Inc/healthcraft/issues/11).
