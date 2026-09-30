# V2 casebook: first local-model development cohort

All sixteen scheduled attempts ran once using installed Nemotron Nano and
MedGemma weights. Fifteen executions completed; one ended on a tool lookup error.
There were **116 recorded model requests, 101 native tool calls, 15 stored notes
and two actual stored-text readbacks**. None met the full mechanical contract.
Every attempt is retained, with zero grading errors or missing attempts.

The CLI correctly exited 1 with cohort status `incomplete` because one execution
failed. That status does not mean captures are missing. All sixteen provenance
checks passed and source identities were unchanged. Mechanical content failure,
normal execution, actual storage and actual readback are separate observations.
Clinical and safety criteria remain unassessed; there is no benchmark score.

## Fixed conditions and captured evidence

The [plan](run/plan.json) was pinned before inference to canonical SHA-256
`c6b21023c6eaac2ae1bf0dd764656cf109fc3d1e465fbe07d9347430afa82d49`.
It uses all eight exposed v2 cases, each with Nano then MedGemma, exactly once.
Both models receive identical initial public messages for a given target,
containing target IDs, common rules and canonical tool schemas; private cases,
expected answers and designated controls are absent from worker inputs.

Both use Ollama 0.34.4, exact installed weight digests, a 32,768-token context,
4,096-token output limit, seed 42, temperature zero, thinking disabled,
16-response ceiling, 240-second request timeout and 900-second attempt deadline.
MedGemma uses the same text-JSON command interface as Nano, not native tool calls
or clinical judging. `keep_alive=0` is frozen; per-request reload overhead is not
an operator-time endpoint. No keys, downloads, paid fallback, retries or response
repairs were used. [Launch](launch.json) and [exit](cli-receipt.json) receipts
record the actual external CLI command and minimal environment names.

The parent ran real native handlers against fresh worlds and retained snapshots,
audit and tool responses. Spawned workers retained fresh pre/postflight model
identities, actual initial prompts, controller messages and exact successful
HTTP response bodies before parsing. [The run manifest](run/manifest.json)
binds all 260 payloads plus source and plan identities. Request counts describe
recorded dispatch attempts, not independent attestation of daemon inference.

## Complete roster

| Attempt | Execution | Requests | Tools | Stored notes | Notes read back |
| --- | --- | ---: | ---: | ---: | ---: |
| REC2-001/nano | completed | 7 | 6 | 1 | 0 |
| REC2-001/medgemma | failed | 6 | 6 | 0 | 0 |
| REC2-002/nano | completed | 8 | 7 | 1 | 0 |
| REC2-002/medgemma | completed | 8 | 7 | 1 | 0 |
| REC2-003/nano | completed | 6 | 5 | 1 | 0 |
| REC2-003/medgemma | completed | 10 | 9 | 1 | 1 |
| REC2-004/nano | completed | 6 | 5 | 1 | 0 |
| REC2-004/medgemma | completed | 6 | 5 | 1 | 0 |
| REC2-005/nano | completed | 6 | 5 | 1 | 0 |
| REC2-005/medgemma | completed | 8 | 7 | 1 | 0 |
| REC2-006/nano | completed | 6 | 5 | 1 | 0 |
| REC2-006/medgemma | completed | 8 | 7 | 1 | 0 |
| REC2-007/nano | completed | 7 | 6 | 1 | 0 |
| REC2-007/medgemma | completed | 8 | 7 | 1 | 1 |
| REC2-008/nano | completed | 6 | 5 | 1 | 0 |
| REC2-008/medgemma | completed | 10 | 9 | 1 | 0 |

All sixteen full mechanical verdicts are false. The strict `persisted_action`
and `readback` axes require correct reconciliation content; a false value must
not be interpreted as no physical write or retrieval. The table above counts
those literal events independently and respects duplicate-note multiplicity.

## Inspectable findings

- [REC2-001/medgemma](run/REC2-001/medgemma/execution.json), call-0006, supplied
  `PAT-20010002` as an encounter ID to `getEncounterDetails`. The native lookup
  returned `not_found`; the controller stopped without retry or a note write.
  The peer prose's "sixth getEncounterDetails call" refers to the sixth tool
  command overall, identified as call-0006 in the raw capture.
- [REC2-002/medgemma](run/REC2-002/medgemma/execution.json) retained all three
  expected observation IDs and correctly listed both prior-encounter exclusions,
  but gave incorrect source paths, including a `/patient` prefix. Preserving
  values and supplying valid traceability are distinct requirements.
- [REC2-004/nano](run/REC2-004/nano/execution.json) retained the expected
  three-member conflict group. That partial success does not repair its other
  source-fidelity defects or omitted readback.
- [REC2-003/medgemma](run/REC2-003/medgemma/execution.json) and
  [REC2-007/medgemma](run/REC2-007/medgemma/execution.json) actually retrieved
  their stored note text. Both notes still fail the full reconciliation checks.

The [independent review](independent-review/peer-review.json) recomputes each
verdict and records source-literal differences, native request details, actual
actions and unavailable evidence. It found no artifact or accounting discrepancy.
Its [detailed findings](independent-review/findings.md) distinguish incorrect
paths from unchanged raw values, omitted rows from prior-encounter misattribution,
and a duplicate-key note from parseable notes. The copied source filenames in
peer inventories are mapped to this package by `copied-originals.json`; Python
helpers are preserved byte-for-byte as `.py.txt`.
Those exact-JSON comparisons are engineering diagnoses, not clinical labels.
The [capture summary](capture-summary.json) preserves all outcomes compactly.

## Limits and next value work

These eight exposed cases share an engineering authoring ledger with their
expectations. One attempt per model/case cannot establish reliability, model
ranking, operator benefit, clinical safety or superiority over other products.
Model-independent clinical review and a registered comparative study remain
absent. Content hashes prove consistency, not execution authenticity or reviewer
independence. Prior model cohorts and results remain unchanged.

The [next operator contract proposal](next-operator-contract/proposal.md) was
prepared without inspecting this cohort's live outcomes. It is design only:
target/incident identification, source citations, separate report-validity
adjudication and explicit timing provenance. No interface, participant study,
independent human judgment or measured operator endpoint is claimed by it.

The [engineering validation checkpoint](../../../validation/20260930/local-casebook-model-v1/README.md)
contains TDD repairs, 4,316 passed / 58 skipped, inventoried lint and ordinary peer
review. Formal red team, remote main and manuscript updates remain behind the
user's value-evidence gate. No remote or paper publication occurred.
