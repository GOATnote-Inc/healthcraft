# Local model source-reconciliation pilot v2

All **four scheduled attempts** are retained. Two direct-arm attempts failed in
preparation before inference because of a filesystem path-alias error. Both
Harbor attempts reached normal model/controller termination and wrote a note,
but neither satisfied the independent mechanical reconciliation oracle.
These are distinct outcomes; this cohort does not support a cross-arm or model
ranking, a clinical conclusion, or a superiority claim.

This is an open exploratory follow-up after observing the retained
[v1 format failures](../local-model-pilot-v1/README.md), not an externally
registered or held-out comparison. V2 adds native Ollama `format` schema
`healthcraft-reconciliation-command/v2`, SHA-256
`40c74bce3587de9fbd7385f81314f8f6d3d23e978b3024bba2d7b7a734b48794`.
It constrains the existing call-or-finish envelope, without adding expected
records, note contents or clinical labels. There was no output repair, model
fallback or retry of a failed attempt.

## Recorded outcomes

| Scheduled attempt | Native responses | Actual tool calls | Stored notes | Post-write readback call | Outcome |
|---|---:|---:|---:|---|---|
| Nano direct | 0 | 0 | 0 | Not reached | Preparation failure; no model access |
| Nano Harbor | 5 | 4 | 1 | No | Normal termination; mechanical verification failed |
| MedGemma Harbor | 6 | 5 | 1 | Yes | Normal termination; mechanical verification failed |
| MedGemma direct | 0 | 0 | 0 | Not reached | Preparation failure; no model access |

The direct runner mixed `/var/...` and resolved `/private/var/...` paths while
computing source identity, raising `ValueError` before model preflight or tool
discovery. Its model identities therefore remain null. These are infrastructure
failures, not failures of either model. Their raw receipts and empty model logs
remain intact. The later path repair is excluded from this v2 capture and belongs
to a fresh cohort; it does not replace or repair these recorded attempts.

Both Harbor notes preserve the six target-current observations and the explicit
conflict exactly. Their scope exclusions are incorrect, and neither run retrieved
the excluded encounters. Nano reused `SRC-A01` and `SRC-A06` as exclusion IDs.
MedGemma used `SRC-B01` for the prior encounter and invented `SRC-C01` with
`ENC-DDDDDDDD` for the other patient. The authored exclusions were `SRC-A07` at
`ENC-CCCCCCCC` for the target patient's prior encounter and `SRC-B01` at
`ENC-BBBBBBBB` for the other patient. See the exact note comparisons in
[independent-review.json](independent-review.json).

**MedGemma did perform a real post-write readback.** The oracle's
`readback:false` means the required correct note was not verified; it does not
mean that call was absent. Likewise, `persisted_action:false` does not deny the
observed write: a note exists, but it is not the requested correct reconciliation.
Nano made no post-write readback call. Both Harbor verifier rewards were `1`,
which checks terminal connectivity only. Both independent mechanical results
were `not_verified`. Provider stop, controller finish, a write acknowledgement
and connectivity reward are separate from task correctness.

## Protocol and retained evidence

[protocol.json](protocol.json), [roster.json](roster.json) and each
`model-config.json` preserve the executed declarations. The order was Nano direct,
Nano Harbor, MedGemma Harbor, MedGemma direct, with one attempt per model/arm.
The declared settings remain seed42, temperature0, context32768, at most16 model
responses with4096 output tokens each, keep_alive0, native socket timeout240
seconds and parent direct-child cap900 seconds. The cap includes child imports,
setup, model work and postflight; coordinator container lifecycle is outside it.
It does not guarantee termination of every descendant or an in-flight Ollama
request. No timeout occurred in these four recorded child processes.

Both model arms use text JSON commands with native `tools=None`. The declared
initial messages and settings are unchanged from v1. Only Harbor reached model
access here, so actual cross-arm request parity was not demonstrated. Nano's
wire uses `think:false`; the completion-only MedGemma client omits that field.
All11 actual Harbor model responses had explicit normal native stops, and their
captured requests contain the exact frozen format schema. That enabled these
recorded interactions to proceed, but does not establish a general improvement
in source selection, reliability or clinical performance.

Fresh before/after Harbor metadata identifies Ollama0.34.4 and the installed
Q5_K_M weights: Nano digest
`36896b6271148892f83130812cb14116beeb2a518f98a0a17b469250b84901c8`,
MedGemma digest
`2b0cb8e40675a79615511f634e09bfe9f4ea3d36165ff1e357799ce749293f67`.
The actual Harbor SDK receipt records version0.8.0 and commit
`22b83271db78ef4bcbeb2402cdd154979cf87912`. The
[runtime evidence index](runtime-evidence-index.json) links original receipts
and explicitly retains unknown direct-arm identities. Initial and per-attempt
residency captures are empty. Packaging performed no new runtime or daemon check.

[independent-review.json](independent-review.json) reports **134 checks passed,
zero failed checks**, including all four scheduled outcomes, eleven native
requests/responses, nine tool calls, two notes, model/source bindings, journal
consistency and fresh oracle agreement. This was ordinary read-only engineering
review, not formal red team or clinical adjudication. Raw native envelopes,
terminal exchanges, backend audit/state snapshots, finalization and cleanup
receipts remain in each attempt directory. Benchmark score is null; assessed
clinical and safety criteria are zero. Mechanical failure is not a clinical
safety violation.

## Frozen source capture

All442 candidate entries match [host-input-manifest.json](host-input-manifest.json).
Six exact host input snapshots are listed in
[host-runtime-inputs/manifest.json](host-runtime-inputs/manifest.json). They come
from the executed frozen candidate, including the failing direct runner, rather
than a newer checkout. All386 members of [build-context.tar.gz](build-context.tar.gz)
match the original image build inputs; the deterministic archive uses the same
method as v1/v4. [Source capture](source-capture-receipt.json) and
[archive verification](build-archive-receipt.json) state those boundaries.
Development tests and primary-source research are separate in the
[v2 validation package](../../../validation/20260930/reconciliation-structured-v2/README.md).

[manifest.json](manifest.json) hashes the final payload, excluding itself and the
ignored `build/` directory whose exact members are archived. Existing raw files
were checked unchanged. One open-fixture attempt per model/arm, with two
infrastructure failures, supplies no reliability estimate, transport comparison,
operator-value or clinical-readiness evidence. Host controllers retain host
privileges; bounded container checks are not general sandbox proof. No published
benchmark metric, manuscript claim or earlier artifact was changed.
