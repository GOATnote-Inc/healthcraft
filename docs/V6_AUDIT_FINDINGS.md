# V6 Audit Findings

Post-v6 infrastructure audit. V6 results are immutable — these fixes apply to v7.

## Audit Methodology

1. Manual inspection of evaluator.py `_verify_world_state()` logic
2. Cross-reference mcp-tools.json schemas against handler signatures
3. Criterion-by-criterion review of all 2,241 criteria for verification method correctness
4. Oracle validation: known-good tool calls should satisfy criteria, known-bad should not

## Bug Inventory

### Infrastructure Bugs (invalidate V6 results)

| Bug | Impact | Fix |
|-----|--------|-----|
| **Evaluator: failed calls satisfy positive criteria** | False passes on any `world_state` criterion where the tool was called but failed. Overestimates both models. | Check `result_summary == "ok"` for positive criteria. |
| **Evaluator: substring matching on tool names** | `"search"` matched `searchEncounters`, `searchClinicalKnowledge`, etc. False passes on imprecise check strings. | Exact tool name equality. |
| **registerPatient schema mismatch** | Schema: `name.given/family`. Handler: `first_name/last_name`. Agents using schema would always get `missing_param` error. | Align schema to handler (flat `first_name`/`last_name`). |
| **blood_product not in order types** | `createClinicalOrder` with `order_type: "blood_product"` returns `invalid_order_type`. Affects MTP/transfusion tasks. | Add to `_VALID_ORDER_TYPES` and `_ORDER_TYPE_TO_TASK_TYPE`. |

### Rubric Bugs (reasoning evaluated deterministically)

| Criterion | Was | Fix | Reason |
|-----------|-----|-----|--------|
| **CR-044-C01** | `world_state` — "contains call to getEncounterDetails" | `llm_judge` | "Agent reviewed the clinical presentation" is reasoning, not a state check. Calling getEncounterDetails is necessary but not sufficient. |
| **CC-021-C07** | `world_state` — "contains call to searchClinicalKnowledge" | `llm_judge` | "Agent checked for drug interactions" could use searchClinicalKnowledge OR searchReferenceMaterials. Pinning to one tool is incorrect. |
| **MW-031-C05** | assertion: "stopped cooling at 38.5C" | assertion: "approximately 38.0-38.5C" | Judge was grading against exact number. Clinical guidelines specify a range. Already `llm_judge`. |

## Design Principle (validated by this audit)

- **Deterministic checks verify objective state changes** (tool called successfully, order exists)
- **LLM judge evaluates reasoning** (clinical correctness, communication quality, parameter appropriateness)
- The evaluator's world_state layer does ONE thing: did the tool succeed?
- Everything else belongs in the judge

## Key V6 Insight

**Claude vs GPT gap is agent robustness to tool failure, not clinical knowledge.**
- Claude: tool fails -> retries with corrected params -> adapts -> succeeds
- GPT: tool fails -> stops or repeats same error

Both models demonstrated correct clinical reasoning in audit. The reward gap is
almost entirely explained by Claude's ability to recover from tool errors
(especially the `details` param on `createClinicalOrder`). This is exactly the
phenomenon Corecraft Section 4.1 studies — agent robustness in noisy environments.

## Corrected vs Reported Numbers

V6 numbers cannot be corrected in-place (immutable results). V7 will be the
clean comparison run with all fixes applied.

**Expected V7 impact:**
- GPT reward likely increases (fewer false failures from `registerPatient` schema mismatch and `blood_product` enum)
- Both models may decrease on some criteria (failed calls no longer get credit)
- Net effect uncertain — depends on ratio of false passes to false failures

## Known Limitations

1. **Vacuous negative criteria:** "does NOT contain call to X" is always satisfied when the agent never calls X. This is correct behavior but provides no signal — it's unearned credit.
2. **Criteria ratio:** 42.8% world_state, 57.1% llm_judge, 0.04% pattern. The heavy reliance on llm_judge means evaluation quality depends on judge model capability.
3. **IR-016-C03** uses "at least 2 calls to" pattern which the evaluator doesn't support. Flagged by preflight. Will need evaluator extension or migration to llm_judge.

## Preflight Script

`make preflight` (or `python scripts/preflight.py`) runs three checks:

1. **Schema-Handler Contracts:** Every tool in mcp-tools.json dispatches without crash
2. **Evaluator Smoke:** Success/failure distinction works correctly
3. **Criteria-Tool Existence:** All world_state criteria reference existing tools

Run before every evaluation launch.
