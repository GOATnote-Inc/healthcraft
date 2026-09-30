# HEALTHCRAFT

[![Tests](https://github.com/GOATnote-Inc/healthcraft/actions/workflows/tests.yml/badge.svg)](https://github.com/GOATnote-Inc/healthcraft/actions/workflows/tests.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**Emergency Medicine RL Training Environment**


> **Development status (2026-09-30):** evaluation integrity and reproducible
> local-model testing are under active development. See the
> [evaluation design roadmap](docs/EVALUATION_DESIGN_ROADMAP.md) for the
> evidence required for further capability and validation claims.

> **Research artifact — synthetic data only.** HEALTHCRAFT is a research
> benchmark and RL environment, not a medical device, and must not be used
> for clinical decision-making. Physician-blind validation
> ([#10](https://github.com/GOATnote-Inc/healthcraft/issues/10)) is required
> before any deployment conversation.

An open-source reinforcement learning environment for training and evaluating AI agents in synthetic emergency medicine workflows. Built on the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) with 24 tools, 14 entity types, and 6 task categories representing selected workflows of a Level I Trauma Center ED.

> **Attribution:** HEALTHCRAFT directly adapts the architecture described in
> [EnterpriseBench Corecraft: Training Generalizable Agents on High-Fidelity RL Environments](https://arxiv.org/abs/2602.16179)
> by Sushant Mehta, Logan Ritchie, Suhaas Garre, Ian Niebres, Nick Heiner, and Edwin Chen (Surge AI). The Corecraft team demonstrated that
> high-fidelity RL environments with task-centric world building, expert-authored
> rubrics, and realistic workflows produce agents that generalize beyond their
> training distribution. HEALTHCRAFT extends this architecture to emergency
> medicine, adding clinical workflows, safety-gated rewards, and temporal
> constraints. Cross-domain pass rates do not establish comparative difficulty.
> See [`docs/CORECRAFT_ATTRIBUTION.md`](docs/CORECRAFT_ATTRIBUTION.md) for the
> complete entity, tool, and task mapping.

## Evaluation Results

For testing without hosted-model API charges, see
[local MedGemma/Nemotron evaluation](docs/LOCAL_MODELS.md). Local smoke tests
are integration diagnostics and do not establish benchmark or clinical
performance. Historical scores below have not been recomputed by these fixes.

Experimental [NVIDIA NeMo Gym adapters](integrations/nemo_gym/README.md) reuse
the local Ollama transport and source-retrieval tools. The additive
[FHIR source export](docs/FHIR_SOURCE_EXPORT.md) preserves 33 reviewed roster
members as linked identity resources and source documents. Both are engineering
capabilities; the [comparative value gate](docs/RELEASE_EVIDENCE_PLAN.md) remains open.

The [synthetic reconciliation workflow](docs/SYNTHETIC_RECONCILIATION.md) retrieves
eight original source rows, preserves unknowns and opposing assertions, and
persists a source-linked note through actual handlers. Its independent checks
and optional Microsoft CSV verifier measure separate engineering contracts;
no clinical criteria or benchmark performance are assessed.

**Canonical: v10 grading channel** (2026-06). 205 tasks, 2,323 binary criteria
(529 safety-critical), 3 trials per model, seed 42, one common neutral judge
(grok-4) for both models — an apples-to-apples cross-model comparison on the
post-audit grader.

| Model | Pass@1 [95% CI] | Pass@3 | Pass^3 | Avg Reward | Safety Failures |
|-------|-----------------|--------|--------|------------|-----------------|
| claude-opus-4-8 | **23.7%** [20.5, 27.3] | 36.1% | 13.7% | 0.618 | 28.9% |
| gpt-5.5 | 13.7% [11.2, 16.6] | 22.0% | 7.3% | 0.570 | 32.0% |

claude-opus-4-8 leads by +10.1 pp Pass@1 (p < 0.001). The multi-step-workflows
collapse persists for both models (1–2% Pass@1), and that single category
produces 79 of each model's safety failures.

**Caveats** ([Red Team 2026-06](docs/RED_TEAM_2026-06.md)): grok-4 is
unvalidated as a clinical judge (no measured kappa); fail-closed grading plus an
unmeasured judge error rate biases Pass@1 low and safety-fail high; gpt-5.5 ran
at temperature=1 with no provider seed, so its trajectories are not reproducible
run-to-run. Neither model supports `temperature=0` (Opus 4.7+ deprecated the
param; gpt-5.5 mandates the default), so reproducibility rests on seed +
multi-trial aggregation. Methodology and full accounting:
[Frontier Accounting](docs/FRONTIER_ACCOUNTING_OPUS48_GPT55.md).

### Per-Category Pass@1 (v10; safety-fail counts in parentheses)

| Category | Tasks | claude-opus-4-8 | gpt-5.5 |
|----------|-------|-----------------|---------|
| Clinical Reasoning | 51 | 41.8% (10) | 17.6% (20) |
| Clinical Communication | 30 | 26.7% (14) | 17.8% (18) |
| Information Retrieval | 30 | 24.4% (7) | 17.8% (10) |
| Safety-Critical Judgment | 31 | 21.5% (47) | 16.1% (47) |
| Temporal Reasoning | 28 | 16.7% (21) | 10.7% (23) |
| Multi-Step Workflows | 35 | 1.9% (79) | 1.0% (79) |

### Historical: V8 (pre-audit grader — superseded)

> The V8 numbers below were produced by the grader superseded after the
> [2026-05-31 grader-fidelity audit](docs/GRADER_FIDELITY_AUDIT_2026-05-31.md):
> the judge failed **open** on safety-critical criteria, so V8 safety-failure
> rates are biased LOW. They are retained as history (relabeled, not
> re-derived) and are **not comparable** to the v10 table above (different
> judge, grading channel, and task corpus).

**v8** (2026-03-15). 195 tasks, 2,255 criteria (515 safety-critical), 3 trials per model.

| Model | Pass@1 | Pass@3 | Pass^3 | Avg Reward | Safety Failures |
|-------|--------|--------|--------|------------|-----------------|
| Claude Opus 4.6 | 24.8% | 37.9% | 13.8% | 0.634 | 27.5% |
| GPT-5.4 | 12.6% | 24.6% | 3.1% | 0.546 | 34.0% |

Claude Pass@1 (24.8%) within Corecraft range (22.1%-30.8%). 104 of the 195
tasks (53%) were unsolved by both models across all 6 trials. See
[Evaluation Findings](docs/EVALUATION_FINDINGS.md) for the V8 per-category
breakdown and [Evaluation Integrity](docs/EVALUATION_INTEGRITY.md) for
version history, known limitations, and the audit trail.

## Setting: Mercy Point Emergency Department

Fictional Level I Trauma Center in a mid-sized American city. 85,000 annual visits. 54 treatment bays (12 resuscitation, 18 acute care, 14 observation, 10 fast-track). 24/7 trauma surgery, interventional cardiology, neurosurgery, and OB coverage. Teaching hospital with residency program.

## Architecture

HEALTHCRAFT provides a stateful RL environment where agents interact with an emergency department through MCP tools:

```
Agent (any MCP client)
  |
  v
MCP Server (24 tools) ---- World State (in-memory, FHIR-R4-shaped)
  |                              |
  v                              v
Task Engine (rubrics)     Entity Generator (OpenEM-powered)
```

**Key properties:**
- **Deterministic seeding** -- identical world states from identical seeds
- **Temporal spine** -- the world has an explicit simulation clock; sparse
  source profiles retain unknown arrival times as unknown
- **Stateful mutations** -- tool calls persist across a session
- **FHIR-R4-shaped** -- entities mirror FHIR R4 resource structure (no formal
  profile validation covers the full entity graph). The separate source exporter
  has [bounded R4 structural evidence](docs/FHIR_SOURCE_EXPORT.md)
- **In-memory persistence only** -- the docker-compose PostgreSQL service is
  provisioned for a future backend; no code path connects to it
  (`src/healthcraft/world/fhir_store.py`)
- **MCP native** -- works with Claude Desktop, Claude Code, or custom harnesses
- **Safety-gated rewards** -- lethal errors zero the score regardless of other dimensions

## Reinforcement-learning coupling (research scaffold)

The Corecraft Megatron+SGLang+GRPO loop is scaffolded under
[`src/healthcraft/rl/`](src/healthcraft/rl/) with the full design at
[`docs/RL_COUPLING.md`](docs/RL_COUPLING.md). HealthCraft owns the
environment + reward; an external trainer (slime / verl) owns Megatron
training and SGLang weight sync. The training-reward design responds to
the whitepaper's NEG-smoke 0.929 overall criterion-prevalence finding (verifiable
anchoring + restraint folding + judge abstention) and keeps the Eq. 1
evaluation-reward formula separate and unchanged.

> **Empirical training-safety validation — soft-gate/hard-gate ablation,
> restraint-criterion reweighting study, reward-hacking probes — remains
> future work** per the whitepaper's Limitations §. A model trained against
> HealthCraft is a research artifact, not deployment-ready; held-out
> prospective physician-blind validation is required before any deployment
> conversation.

## Entity Types (14)

Counts below are the world actually built by `healthcraft seed` at the default
seed 42 (`configs/world/mercy_point_v1.yaml`) on a base install —
4,075 entities; a test asserts this table matches `WorldSeeder.entity_counts`. With
OpenEM installed from a source checkout (see below), clinical knowledge grows
to 370 and clinical tasks to 1,785 (4,450 entities total). The seed YAML's
`entity_generation` block carries larger roadmap targets that the seeder does
not yet honour, and time constraints / transfer records from the original
design are not yet seeded as standalone entities.

| Entity | Seeded count | Source |
|--------|--------------|--------|
| Patients | 500 | OpenEM presentations, FHIR R4 Patient |
| Encounters | 500 | ED visits with ESI, timeline, disposition (1:1 per patient) |
| Clinical Knowledge | 5 (370 with OpenEM) | OpenEM condition corpus |
| Treatment Plans | 500 | Multi-step pathways with dependencies |
| Clinical Tasks | 1,775 | Active orders, pending results, consults |
| Clinical Decision Rules | 100 | Ottawa SAH, HEART, Wells, PECARN |
| Protocols & Guidelines | 8 | Sepsis, stroke, MTP, difficult airway |
| Insurance & Coverage | 500 | Commercial, Medicare, Medicaid, VA |
| Reference Materials | 15 | Drug monographs, procedure guides, dosing |
| Resource Availability | 104 | Bed census, OR, blood bank, staffing |
| Supplies & Medications | 28 | Formulary, shortages, substitution rules |
| Regulatory & Legal | 10 | EMTALA, consent, AMA, mandatory reporting |
| Locations | 22 | Treatment bays, imaging, lab, ancillary areas |
| Staff | 8 | Attendings, residents, nurses, ancillary |

## Tools (24 MCP)

See [`docs/TOOL_MAPPING.md`](docs/TOOL_MAPPING.md) for the complete tool reference with Corecraft mapping.

## Task Categories (6)

1. **Information Retrieval** -- entity lookup (Easy-Medium)
2. **Clinical Communication** -- transfer summaries, discharge instructions (Medium-Hard)
3. **Clinical Reasoning** -- differential diagnosis, decision rule application (Hard-Expert)
4. **Multi-Step Clinical Workflows** -- sepsis bundle, STEMI alert, trauma activation (Expert)
5. **Temporal Reasoning** -- time-critical sequencing, overlapping protocols (Hard-Expert)
6. **Safety-Critical Judgment** -- capacity assessment, EMTALA, protocol override (Expert)

## Rubric Dimensions (6)

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Clinical Completeness | 0.20 | All required elements addressed |
| Clinical Correctness | 0.25 | Medically accurate actions/recommendations |
| Protocol Adherence | 0.15 | Compliance with clinical pathways and regulations |
| Documentation Quality | 0.10 | Appropriate format, terminology, and structure |
| Safety | 0.20 | No harmful actions; **hard gate** (lethal error = zero) |
| Temporal Sequencing | 0.10 | Correct ordering and timing of actions |

## Evaluate Your Model

The installed `healthcraft` command and `python -m healthcraft` share the same
entry point. `evaluate` runs the actual model orchestrator; `list-tasks` only
lists definitions. A local run can use an already installed tool-capable model:

```bash
healthcraft evaluate --agent-model ollama:counsel-nano-q5 \
  --tasks IR-001 --trials 1 --rubric-channel v10 \
  --results-dir results/new-local-run
```

Without an explicit local judge, judge-dependent criteria remain unverified.
See [local models](docs/LOCAL_MODELS.md) for capability and runtime requirements.
`healthcraft evaluate --help` exposes the same options as the module command
below. Neither command substitutes a scripted agent when inference is requested.

HEALTHCRAFT exposes MCP tools and provides native adapters for selected hosted
providers and installed local Ollama models. See
[Evaluate Your Model](docs/EVALUATE_YOUR_MODEL.md) for supported clients and
protocol, and [local testing](docs/LOCAL_MODELS.md) for free diagnostic runs.

```bash
python -m healthcraft.llm.orchestrator \
  --agent-model <your-model> --trials 3 \
  --tasks IR-001 --rubric-channel v10 \
  --results-dir results/<run-name>
```

Task selection is validated before provider access or run output. Execution
errors produce a nonzero exit; completed rubric failures and intentionally
ungraded diagnostics can return `0`. See the
[selection and exit-status contract](docs/EVALUATE_YOUR_MODEL.md#task-selection-and-exit-status).

Results welcome. Open a PR or issue with your summary.json.

Inspect saved attempts, criterion evidence, tool calls, and incomplete runs in
a self-contained offline report:

```bash
python scripts/build_evidence_report.py results/<run-name> \
  --output /tmp/healthcraft-evidence-review.html
```

The report preserves recorded scores and their limitations; it does not
regrade results or establish clinical readiness. Comparative-value evidence
and publication requirements are tracked in the
[release evidence plan](docs/RELEASE_EVIDENCE_PLAN.md).

For independent criterion review, the [offline review workflow](docs/CLINICAL_REVIEW.md)
creates separate masked reviewer packets and private coordinator records from
new execution-time captures. It retains every supplied attempt and pending or
unassessed response. Imported submissions are not authenticated expert labels,
clinical calibration, or a release approval.

For captured reconciliation attempts, the [operator review tutorial](docs/OPERATOR_REVIEW.md)
provides raw and assisted evidence views, six response questions, source
citations and offline JSON export. Its importer preserves every assigned
question, including pending answers and invalid submissions, for later
adjudication. Tutorial responses do not establish operator or clinical value.

The [authored observation contract](docs/AUTHORED_OBSERVATIONS.md) explains
source-linked vitals/labs, explicit timing, and unknown values in new runs.
The [care and imaging contract](docs/CARE_IMAGING_FIDELITY.md) keeps authored
plans and reports distinct from performed treatments, preserves imaging
source fields, and makes unresolved encounter medication checks explicit.

## Quick Start

```bash
# Install
python -m pip install -c constraints-security.txt -e ".[dev]"

# Run tests
make test

# Start the environment (Docker)
make docker-up

# Run smoke test
make smoke
```

To connect an MCP client to the full seeded tool environment over stdio:

```bash
python -m pip install -c constraints-security.txt -e ".[mcp]"
healthcraft serve --config configs/world/mercy_point_v1.yaml --seed 42
```

Configure the client to launch that command and communicate over its stdin/stdout.
The server stays running until the connection closes. `--transport http --port
8000` instead starts the existing loopback HTTP tool API (`/tools`, `/tool`);
that API is a separate transport and does not implement MCP JSON-RPC. Native
stdio advertises the 24 canonical tool names and input schemas. It returns the
actual JSON response in both MCP text and structured content; it does not
advertise the currently mismatched authored return descriptions as an output
schema. Source-checkout configuration files remain required.

`healthcraft simulate`, `make simulate` (and its legacy alias `make eval`), and
the default Docker task engine run **scripted, ungraded smoke checks**. They
attempt a task's listed tools with empty parameters, preserve returned errors,
and never call a model or award a clinical score. They only accept the model
label `simulated`; use `healthcraft evaluate` for actual model inference.
Each simulation gets a new output directory. Tool/setup errors produce a
nonzero exit status; rejected smoke inputs are not clinical failures. The
Docker task engine uses its own in-process world, rather than evaluating a
model against the separately running HTTP service.

The task-engine entrypoint consumes `HEALTHCRAFT_MODEL` (only `simulated`),
`HEALTHCRAFT_TRIALS`, `HEALTHCRAFT_SEED`, and `HEALTHCRAFT_LOG_LEVEL`. An optional
`HEALTHCRAFT_RESULTS_DIR` must name a new directory. It also accepts simulation
flags directly, for example:

```bash
docker compose -f docker/docker-compose.yaml run --rm task-engine \
  --tasks IR-001 --trials 1 --seed 42
```

Run installation commands from the repository root. The security constraints
pin five patched dependency versions when those packages are selected; they
do not install optional network or model dependencies into a core-only setup.
Use the same constraint file for core (`-e .`) and evaluation (`-e ".[eval]"`)
installs. These repository constraints apply to commands that pass `-c`.
`requirements-lock.txt` is a legacy development snapshot with optional
dependencies, not a portable lock for every supported Python version.

### With OpenEM integration

OpenEM is not published to PyPI. The `.[openem]` extra installs the `openem`
package from the
[openem-corpus](https://github.com/GOATnote-Inc/openem-corpus) repo at the
commit pinned in `pyproject.toml` / `requirements-lock.txt`:

```bash
python -m pip install -c constraints-security.txt -e ".[openem]"
```

Note: the packaged install provides the Python API only — openem locates its
370-condition corpus relative to a source checkout, so the seeder still falls
back to the 5 bundled conditions. For the full corpus (370 clinical-knowledge
entries, 4,450 entities total), install OpenEM editable from a clone, matching
`requirements-lock.txt`:

```bash
git clone https://github.com/GOATnote-Inc/openem-corpus ../openem-corpus
git -C ../openem-corpus checkout 8d0820e81ed60eaf814388ca15935e5fc5c7d7ac
python -m pip install -c constraints-security.txt -e ../openem-corpus
```

## Evaluation Integrity

HEALTHCRAFT maintains a public audit trail of every evaluation version,
bug discovery, and correction. See
[Evaluation Integrity](docs/EVALUATION_INTEGRITY.md).

## Known Limitations

**Environment:**
- Static patient vitals by default -- optional seeded dynamics and simplified
  action-conditioned physiology are available, but are not clinically validated
- No interruption testing -- real EDs have interruptions every 3-5 minutes
- Episodic tasks only -- no sustained multi-patient workload management
- Single-agent -- no team coordination or consultant disagreement scenarios

**Evaluation methodology:**
- Infrastructure bugs have affected every major version (V6 invalidated, V7
  had 5 bugs, V8 corrected 6, and the 2026-05-31 audit superseded the V8
  grader). v10 is the canonical grading channel; it is not guaranteed bug-free
  either.
- 57% of criteria use LLM judge (non-deterministic). Judge context overload
  on long trajectories is a known failure mode.
- 3 trials per model. Confidence intervals are wide.
- V8-era cross-vendor judging was asymmetric (each model judged by a
  different vendor). The 2026-06 frontier accounting (the canonical v10
  result above) addressed this with a common neutral third-vendor judge
  (grok-4), whose own clinical-judge reliability is unmeasured.
- Frontier reasoning models are dropping `temperature=0` support (Opus 4.7+
  deprecated the param; gpt-5.5 mandates the default). For those models,
  determinism comes from seed + multi-trial aggregation, not temp=0.
- See [Evaluation Integrity](docs/EVALUATION_INTEGRITY.md) for the full
  audit trail and known limitations.

See [Task Expansion Roadmap](docs/TASK_EXPANSION_ROADMAP.md) for planned phases addressing environment gaps.

## Development

```bash
make install   # Install with dev dependencies
make test      # Run pytest
make lint      # Ruff check + format check
make format    # Auto-format
make smoke     # Seed world + run 5 tasks
make docker-up # Start Docker environment
```

## Clinical Knowledge Foundation

HEALTHCRAFT builds on [OpenEM](https://github.com/GOATnote-Inc/openem-corpus), an open corpus of 370 emergency medicine conditions with structured safety metadata including 152 confusion pairs, 45 decision rules, and FHIR R4 bundles. OpenEM is Apache 2.0 / CC-BY-SA 4.0.

## Roadmap

Target: ~260 tasks covering the full operational complexity of a Level I Trauma Center ED. See [Task Expansion Roadmap](docs/TASK_EXPANSION_ROADMAP.md).

### v0.2 Hardening

v0.2 addresses shortcomings identified in a staff-engineer review of v0.1.
Defaults differ by feature: dynamic patient state is opt-in, while tool
idempotency is enabled by default. Set `HC_IDEMPOTENT_TOOLS=0` when the
historical evaluation protocol requires the earlier mutation behavior.

- **Evaluator integrity:** Schema-handler contracts, golden-trajectory replay, audit-log invariants, task satisfiability checks
- **Judge validation:** 92 judge tests, v9 deterministic rubric overlay (`--rubric-channel v9`), BEFORE/AFTER temporal operators
- **Dynamic patient state:** Vitals trajectories (sepsis, ACS, respiratory failure, stable) with reassessment triggers (`--dynamic-state`)
- **Idempotent tools:** Duplicate-order and duplicate-append bug fixes behind `HC_IDEMPOTENT_TOOLS` flag
- **Paper revision:** Sharpened limitations, measured-vs-not-measured separator for arXiv v2

See [Paper Revision Notes](docs/PAPER_REVISION_NOTES.md) for v2 whitepaper planning and [Evaluation Integrity Hardening](docs/EVALUATION_INTEGRITY_HARDENING.md) for test coverage additions.

## License

Apache 2.0. See [LICENSE](LICENSE).

## Citation

```bibtex
@software{healthcraft2026,
  title = {HEALTHCRAFT: Emergency Medicine RL Training Environment},
  author = {GOATnote Inc.},
  year = {2026},
  url = {https://github.com/GOATnote-Inc/healthcraft},
  license = {Apache-2.0}
}
```

See also: [EnterpriseBench Corecraft](https://arxiv.org/abs/2602.16179) by Mehta, Ritchie, Garre, Niebres, Heiner, and Chen (Surge AI), whose architecture HEALTHCRAFT adapts.
