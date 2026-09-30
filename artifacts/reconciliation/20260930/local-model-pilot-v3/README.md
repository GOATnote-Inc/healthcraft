# Local model source-reconciliation pilot v3

All **four scheduled attempts** reached normal controller termination and stored
one note each. **None satisfied the independent mechanical reconciliation
oracle.** The cohort contains 22 actual native model requests/responses, 18
actual tool calls and four stored notes. These counts distinguish execution and
persistence from correctness; they are not clinical scores or a model ranking.

V3 is a separate open development cohort after the one-line direct-runner
filesystem path-canonicalization repair. It retains the v2 command schema,
initial messages, settings and four-attempt roster. The earlier
[v1](../local-model-pilot-v1/README.md) and [v2](../local-model-pilot-v2/README.md)
cohorts remain unchanged, including their format and preparation failures.
This is not an externally registered or held-out comparison.

## Recorded outcomes

| Scheduled attempt | Native responses | Actual tool calls | Stored notes | Post-write readback | Mechanical result |
|---|---:|---:|---:|---|---|
| Nano direct | 5 | 4 | 1 | No | Not verified |
| Nano Harbor | 5 | 4 | 1 | No | Not verified |
| MedGemma Harbor | 6 | 5 | 1 | Yes | Not verified |
| MedGemma direct | 6 | 5 | 1 | Yes | Not verified |

Each stored note preserves the six target-current source observations and their
explicit conflict exactly. Every note contains incorrect scope exclusions;
neither model retrieved the excluded encounters. Nano reused `SRC-A01` and
`SRC-A06` as exclusion IDs. MedGemma used `SRC-B01` for the prior encounter and
invented `SRC-C01` with `ENC-DDDDDDDD` for the other patient. The authored
exclusions were `SRC-A07` at `ENC-CCCCCCCC` for the target patient's prior
encounter and `SRC-B01` at `ENC-BBBBBBBB` for the other patient. Exact stored-note
comparisons and audit-linked calls appear in
[independent-review.json](independent-review.json).

Both MedGemma runs made an actual post-write readback returning the final
encounter and stored note. Both Nano runs stopped after the write. The oracle's
`persisted_action:false` means the requested **correct** reconciliation was not
persisted; it does not mean that no write occurred. Likewise, its content-qualified
`readback:false` does not erase MedGemma's real readback calls. All four oracle
replays establish provenance and execution completion, but fail source fidelity,
content-qualified persistence and readback. Both Harbor rewards were `1` for
terminal connectivity only, separate from the failed mechanical verification.
Benchmark score is null; assessed clinical and safety criteria are zero.

## Matched inputs and bounded interpretation

The [executed protocol](protocol.json), [roster](roster.json) and per-attempt
`model-config.json` preserve one attempt per model/arm in the order Nano direct,
Nano Harbor, MedGemma Harbor, MedGemma direct. There was no retry, output repair
or model fallback. The direct arm is `direct_http_via_coordinator`, using fixed
Docker-exec HTTP operations; the other arm uses Harbor's terminal lifecycle.
Both controllers consume public tool discovery/responses and use text JSON
commands with native `tools=None`.

The opt-in schema is `healthcraft-reconciliation-command/v2`, SHA-256
`40c74bce3587de9fbd7385f81314f8f6d3d23e978b3024bba2d7b7a734b48794`.
It constrains the call-or-finish envelope, not note accuracy or tool-parameter
semantics. The initial-message digest remains
`1a2e7eafc6eb84042fd4495a65d7c348f6e38e6c044d95801125cc8bec5fb6c7`.
Declared settings remain seed42, temperature0, context32768, at most16 responses
with4096 output tokens each, keep_alive0, native socket timeout240 seconds and
parent direct-child cap900 seconds. Coordinator container lifecycle is outside
that cap; descendant or in-flight Ollama termination is not guaranteed by it.

The independent review verifies equality of the **complete saved native request
JSON objects** across arms for all five Nano turns and all six MedGemma turns,
including message content and options. Raw HTTP bytes were not captured. This
observation does not prove identical repeated outputs, runtime performance,
reliability, clinical validity or causal improvement from constrained decoding.
All22 responses have explicit normal native stops; a provider stop or controller
`finish` is still separate from correct source reconciliation.

Fresh before/after metadata identifies Ollama0.34.4 and Q5_K_M weights: Nano
digest `36896b6271148892f83130812cb14116beeb2a518f98a0a17b469250b84901c8`,
MedGemma digest `2b0cb8e40675a79615511f634e09bfe9f4ea3d36165ff1e357799ce749293f67`.
The recorded Harbor runtime is0.8.0 at commit
`22b83271db78ef4bcbeb2402cdd154979cf87912`. Nano receives `think:false`;
MedGemma's completion-only capability means the native client omits that field.
The [runtime evidence index](runtime-evidence-index.json) points to all four
original identity receipts. Recorded residency is empty before and after the
attempts; recorded backend/network cleanup succeeded. No new daemon observation
was made during packaging.

## Review and exact capture

[independent-review.json](independent-review.json) records **116 checks passed,
no consistency findings**, including frozen-oracle replay, all four outcomes,
request-object parity, source identities, persisted notes, journals and cleanup.
The reviewer checked 142 JSON and 22 JSONL files for finite, unique-key JSON.
This was ordinary read-only engineering review with zero new model/tool calls,
not formal red team or clinical adjudication. Saved evidence is checked for
consistency, not cryptographically authenticated.

The [initial checker receipt](actual-model-review-initial-checker.json) is also
retained. Its two failed assertions incorrectly required a native `think:false`
field for MedGemma. The final checker follows the frozen capability-dependent
client behavior. No runtime, model outcome or source artifact was repaired for
that correction. The exact [reviewer source](review_actual.py.txt) is preserved.

All442 frozen candidate entries match
[host-input-manifest.json](host-input-manifest.json). Six host source snapshots
are listed in [host-runtime-inputs/manifest.json](host-runtime-inputs/manifest.json),
including the repaired direct runner. All386 image build inputs are preserved in
[build-context.tar.gz](build-context.tar.gz) and checked by the
[archive receipt](build-archive-receipt.json). This archive is byte-identical to
v2 because the repaired host script is outside the image build context. The
[source-capture receipt](source-capture-receipt.json) records that boundary.
Related post-repair development checks are in the separate
[v3 validation package](../../../validation/20260930/reconciliation-structured-v3/README.md).

[manifest.json](manifest.json) hashes the completed payload, excluding itself
and the ignored `build/` directory whose exact members are archived. Static
inputs were captured while execution continued; active journals were left
untouched. Outcome capture and final hashing occurred only after all four
attempts and the independent review finished. All560 pre-existing completed
files and the v1/v2 rosters were rechecked unchanged. One open synthetic fixture
and one attempt per model/arm provide no model ranking, clinical-readiness,
operator-value or superiority evidence. Host controllers retain host privileges;
bounded container checks do not prove general sandbox security. Published
benchmark metrics, manuscript claims and previous artifacts remain unchanged.
