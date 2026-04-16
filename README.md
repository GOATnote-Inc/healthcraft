# HEALTHCRAFT

[![Tests](https://github.com/GOATnote-Inc/healthcraft/actions/workflows/tests.yml/badge.svg)](https://github.com/GOATnote-Inc/healthcraft/actions/workflows/tests.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**Emergency Medicine RL Training Environment**

An open-source, high-fidelity reinforcement learning environment for training and evaluating AI agents in emergency medicine workflows. Built on the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) with 24 tools, 14 entity types, and 6 task categories spanning the full complexity of a Level I Trauma Center ED.

> **Attribution:** HEALTHCRAFT directly adapts the architecture described in
> [EnterpriseBench Corecraft: Training Generalizable Agents on High-Fidelity RL Environments](https://arxiv.org/abs/2602.16179)
> by Sushant Mehta, Alexander Ritchie, Sai Mahesh Garre, Paulo Niebres, Brady Heiner, and Albert Chen (Surge AI). The Corecraft team demonstrated that
> high-fidelity RL environments with task-centric world building, expert-authored
> rubrics, and realistic workflows produce agents that generalize beyond their
> training distribution. HEALTHCRAFT extends this architecture to emergency
> medicine -- a domain with temporal reasoning, cyclic entity graphs, safety-gated
> rewards, and clinical uncertainty that creates substantially harder agent tasks.
> See [`docs/CORECRAFT_ATTRIBUTION.md`](docs/CORECRAFT_ATTRIBUTION.md) for the
> complete entity, tool, and task mapping.

## Evaluation Results

**v8** (2026-03-15). 195 tasks, 2,255 criteria (515 safety-critical), 3 trials per model.

| Model | Pass@1 | Pass@3 | Pass^3 | Avg Reward | Safety Failures |
|-------|--------|--------|--------|------------|-----------------|
| Claude Opus 4.6 | 24.8% | 37.9% | 13.8% | 0.634 | 27.5% |
| GPT-5.4 | 12.6% | 24.6% | 3.1% | 0.546 | 34.0% |

Claude Pass@1 (24.8%) within Corecraft range (22.1%-30.8%).
See [Evaluation Findings](docs/EVALUATION_FINDINGS.md) for per-category
breakdown and [Evaluation Integrity](docs/EVALUATION_INTEGRITY.md) for
version history, known limitations, and audit trail.

### Per-Category Pass@1

| Category | Tasks | Claude | GPT |
|----------|-------|--------|-----|
| Clinical Reasoning | 50 | 44.0% | 16.7% |
| Information Retrieval | 30 | 38.9% | 18.9% |
| Clinical Communication | 30 | 22.2% | 20.0% |
| Safety-Critical Judgment | 27 | 16.0% | 9.9% |
| Temporal Reasoning | 25 | 13.3% | 8.0% |
| Multi-Step Workflows | 33 | 1.0% | 0.0% |

104 tasks (53%) unsolved by both models across all 6 trials.

## Setting: Mercy Point Emergency Department

Fictional Level I Trauma Center in a mid-sized American city. 85,000 annual visits. 54 treatment bays (12 resuscitation, 18 acute care, 14 observation, 10 fast-track). 24/7 trauma surgery, interventional cardiology, neurosurgery, and OB coverage. Teaching hospital with residency program.

## Architecture

HEALTHCRAFT provides a stateful RL environment where agents interact with an emergency department through MCP tools:

```
Agent (any MCP client)
  |
  v
MCP Server (24 tools) ---- World State (PostgreSQL + FHIR R4)
  |                              |
  v                              v
Task Engine (rubrics)     Entity Generator (OpenEM-powered)
```

**Key properties:**
- **Deterministic seeding** -- identical world states from identical seeds
- **Temporal spine** -- every entity has timestamps; world state represents a specific moment
- **Stateful mutations** -- tool calls persist across a session
- **FHIR R4 compliance** -- world state is valid FHIR R4
- **MCP native** -- works with Claude Desktop, Claude Code, or custom harnesses
- **Safety-gated rewards** -- lethal errors zero the score regardless of other dimensions

## Entity Types (14)

| Entity | Count | Source |
|--------|-------|--------|
| Patients | 500+ | OpenEM presentations, FHIR R4 Patient |
| Encounters | 1,200+ | ED visits with ESI, timeline, disposition |
| Clinical Knowledge | 370 | OpenEM condition corpus |
| Treatment Plans | 800+ | Multi-step pathways with dependencies |
| Clinical Tasks | 2,000+ | Active orders, pending results, consults |
| Time Constraints | 200+ | Door-to-ECG, door-to-balloon, sepsis bundle |
| Transfer Records | 300+ | Inter-facility, EMS, EMTALA documentation |
| Clinical Decision Rules | 150+ | Ottawa SAH, HEART, Wells, PECARN |
| Protocols & Guidelines | 100+ | Sepsis, stroke, MTP, difficult airway |
| Insurance & Coverage | 50+ | Commercial, Medicare, Medicaid, VA |
| Reference Materials | 500+ | Drug monographs, procedure guides, dosing |
| Resource Availability | 100+ | Bed census, OR, blood bank, staffing |
| Supplies & Medications | 400+ | Formulary, shortages, substitution rules |
| Regulatory & Legal | 80+ | EMTALA, consent, AMA, mandatory reporting |

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

HEALTHCRAFT supports any MCP-compatible LLM. See
[Evaluate Your Model](docs/EVALUATE_YOUR_MODEL.md) for setup and protocol.

```bash
python -m healthcraft.llm.orchestrator \
  --agent-model <your-model> --trials 3 \
  --results-dir results/<run-name>
```

Results welcome. Open a PR or issue with your summary.json.

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Run tests
make test

# Start the environment (Docker)
make docker-up

# Run smoke test
make smoke
```

### With OpenEM integration

```bash
pip install -e ".[openem]"
```

## Evaluation Integrity

HEALTHCRAFT maintains a public audit trail of every evaluation version,
bug discovery, and correction. See
[Evaluation Integrity](docs/EVALUATION_INTEGRITY.md).

## Known Limitations

**Environment:**
- Static world state -- patient vitals don't evolve during agent interaction
- No interruption testing -- real EDs have interruptions every 3-5 minutes
- Episodic tasks only -- no sustained multi-patient workload management
- Single-agent -- no team coordination or consultant disagreement scenarios

**Evaluation methodology:**
- Infrastructure bugs have affected every major version (V6 invalidated, V7
  had 5 bugs, V8 corrected 6). V8 is current but not guaranteed bug-free.
- 57% of criteria use LLM judge (non-deterministic). Judge context overload
  on long trajectories is a known failure mode.
- 3 trials per model. Confidence intervals are wide.
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
All changes are opt-in (default off) to preserve V8 result reproducibility.

- **Evaluator integrity:** Schema-handler contracts, golden-trajectory replay, audit-log invariants, task satisfiability checks
- **Judge validation:** 52 judge tests, v9 deterministic rubric overlay (`--rubric-channel v9`), BEFORE/AFTER temporal operators
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
