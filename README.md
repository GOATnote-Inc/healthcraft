# HEALTHCRAFT

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
