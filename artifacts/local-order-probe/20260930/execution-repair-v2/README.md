# Local order round trip after execution repairs

One scheduled, free Nemotron attempt on the frozen staged candidate from
2026-09-30. It completed with two model responses and one actual
`createClinicalOrder` call. The independent literal action-fidelity check
passed: requested details, urgent priority, indication, encounter linkage,
world-clock time and linked clinical task matched persisted state.

This is a restricted one-tool software integration check, not an autonomous
clinical evaluation. Clinical and safety criterion coverage are both zero;
benchmark score and unassessed trajectory reward/pass/gate fields are null.
No physician labels, healthcare benefit or comparative outcome were measured.
MedGemma was not invoked in this particular tool-capable probe; its earlier
[source-reading attempt](../../../local-care-probe/20260930/source-reading-v1/README.md)
remains separately recorded, including its format failure.

## Identity and bounds

- Model: `ollama:counsel-nano-q5:latest`, `nemotron_h_moe`, `Q5_K_M`.
- Digest: `36896b6271148892f83130812cb14116beeb2a518f98a0a17b469250b84901c8`.
- Ollama `0.34.4`, loopback `http://127.0.0.1:11434`.
- Seed 42, context 8192, temperature zero, thinking disabled.
- Maximum four model responses, 256 output tokens each, 45 seconds per request,
  180 seconds for inference between calls, 300 seconds outer process limit.
- One attempt, zero inference retries, no downloads or cloud fallback.
- Clean process environment without API credentials.

`report.json` captures the exact requested action, normalized adapter exchanges,
actual tool requests/responses, audit entries, final stored state, trajectory,
352 source/config/prompt hashes and runtime/model identities before and after.
All identity checks match. `trajectory.json` preserves the trajectory object
separately, with its frozen/sealed review context validated against actual
prompts, tool definitions and turns. This does not claim native provider
wire-envelope capture or independent authenticity.

`process-status.json` and logs retain the process outcome; `process-runner.py.txt`
is the exact outer invocation. The probe reported 13.883 seconds; the outer
process took 13.976 seconds. Full regression testing was running concurrently,
so these timings are not controlled performance measurements.

`independent-review.json` and its checker preserve 25 ordinary read-only
evidence checks, all passing. This review verifies captured software behavior;
it is not independent clinical review or the gated formal red team.

## Reproduction and scope

Use a new exclusive output path with the installed pinned model:

```sh
.venv/bin/python scripts/local_order_probe.py \
  --agent-model ollama:counsel-nano-q5:latest \
  --output /new/exclusive/path/report.json \
  --max-responses 4 --max-output-tokens 256 --timeout 45
```

The recorded invocation uses the frozen export identified in the process
receipt and an outer 300-second bound. Existing output is refused. Seeded
inference does not guarantee identical generations or UUID order IDs across
runs. The fixture supplies the literal action; no diagnosis, treatment choice
or medication dosing is inferred. Retry conflicts, malformed envelopes and
report binding are covered by separate offline tests, not by this one success.
