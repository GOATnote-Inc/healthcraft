# Local model source-reconciliation pilot v1

All **four scheduled attempts** are recorded. Each received one native Ollama response and then failed the strict text-command format check before any clinical tool call or note write. There were no retries, automatic repairs or filtered-out attempts. Tool discovery succeeded before model access; discovery is not a clinical tool call.

The direct arm is **direct HTTP via the coordinator**, using a fixed Docker-exec bridge to the same backend handlers. The other arm uses the actual Harbor 0.8.0 terminal lifecycle. Both installed models used text commands with native `tools=None`; MedGemma did not receive unsupported native tools. The common initial-message digest was enforced before model access, and the peer review verifies byte-identical first native requests between arms for each model.

## Recorded outcomes

The assistant-text column below is JSON-string encoded so literal Markdown fences and newline characters remain visible. The supplied token counters are diagnostic observations, not costs or performance comparisons.

| Attempt | Actual raw assistant text, JSON-string encoded | Input / output tokens reported | Result |
| --- | --- | --- | --- |
| nano-direct-01 | <code>&quot;{\&quot;action\&quot;:\&quot;searchPatients\&quot;,\&quot;params\&quot;:{\&quot;name\&quot;:\&quot;Rowan Example\&quot;}}&quot;</code> | 1919 / 15 | Format rejected; 0 tool calls, 0 notes |
| nano-harbor-01 | <code>&quot;{\&quot;action\&quot;:\&quot;searchPatients\&quot;,\&quot;params\&quot;:{\&quot;name\&quot;:\&quot;Rowan Example\&quot;}}&quot;</code> | 1919 / 15 | Format rejected; 0 tool calls, 0 notes |
| medgemma-harbor-01 | <code>&quot;```json\n{\&quot;action\&quot;:\&quot;call\&quot;,\&quot;name\&quot;:\&quot;searchPatients\&quot;,\&quot;params\&quot;:{\&quot;name\&quot;:\&quot;Rowan Example\&quot;}}\n```&quot;</code> | 1916 / 24 | Format rejected; 0 tool calls, 0 notes |
| medgemma-direct-01 | <code>&quot;```json\n{\&quot;action\&quot;:\&quot;call\&quot;,\&quot;name\&quot;:\&quot;searchPatients\&quot;,\&quot;params\&quot;:{\&quot;name\&quot;:\&quot;Rowan Example\&quot;}}\n```&quot;</code> | 1916 / 24 | Format rejected; 0 tool calls, 0 notes |

Nano used the tool name as `action`, omitting the required `action:call`/`name` structure. MedGemma surrounded an otherwise shaped command with Markdown fences. Both deviations were rejected under the frozen no-repair protocol. Each provider reported `done:true` and `done_reason:stop`: that completed the single provider response, not the reconciliation task. No source records were retrieved by a clinical tool, and no source reconciliation or note persistence capability was demonstrated in these attempts.

## Protocol and evidence

[roster.json](roster.json), per-attempt `model-config.json` and captured initial messages are the executed protocol; no earlier proposal replaces them. The order was Nano direct, Nano Harbor, MedGemma Harbor, MedGemma direct. Each model/arm had one attempt, using seed42, temperature0, thinking disabled, context32768, at most16 responses with4096 output tokens each, and keep_alive0. The native socket timeout was240 seconds; the parent hard cap was900 seconds for each child process including imports, setup, metadata, inference and postflight. Coordinator container lifecycle was outside that cap. All four actual children ended within their cap after their first response.

Both Q5_K_M models ran on Ollama0.34.4. Nano's installed digest was `36896b6271148892f83130812cb14116beeb2a518f98a0a17b469250b84901c8`; MedGemma's was `2b0cb8e40675a79615511f634e09bfe9f4ea3d36165ff1e357799ce749293f67`. Fresh identity checks, raw native payloads/envelopes, process receipts, terminal exchanges, backend calls/audit/state, private finalization receipts and independent oracle output remain in each attempt directory. The initially empty residency observation and all per-attempt empty residency observations are preserved; no new model or daemon check was performed while packaging.

[independent-review.json](independent-review.json) reports **115 checks passed, zero failed checks**. It checks four scheduled/recorded attempts, four requests/responses, prompt/settings/identity/source bindings, actual zero-call/zero-note outcomes, fresh oracle agreement and retained failures. This was ordinary read-only engineering review, not the formal red team.

The independent mechanical verifier recorded provenance evidence but did not establish source fidelity, persistence, readback or execution completion. Benchmark score is null; clinical and safety coverage are both zero. Harbor's verifier is only a connectivity check, not the source/persistence oracle or a clinical reward. A mechanical failure here is not a clinical safety violation.

## Source capture and limits

All442 frozen candidate entries were checked against [host-input-manifest.json](host-input-manifest.json). Six executed host files are preserved as `.py.txt` snapshots in [host-runtime-inputs/manifest.json](host-runtime-inputs/manifest.json), including the native client. [build-archive-receipt.json](build-archive-receipt.json) binds the deterministic [build-context.tar.gz](build-context.tar.gz): all386 members match the original image build manifest. [source-capture-receipt.json](source-capture-receipt.json) states the capture boundary. Software/runtime setup is documented in the separate [transport-v4 artifact](../harbor-transport-v4/README.md); model weights are not bundled.

[manifest.json](manifest.json) hashes every final payload file except itself and the ignored `build/` directory. The archived build and its per-member manifest retain that directory's exact inputs. Existing raw evidence was not edited. Supporting memory/runtime observations are copied from their original temporary captures and keep their limitations, including the denied `sysctl` query.

This is a locally frozen, open-fixture feasibility pilot, not an externally preregistered or held-out comparison. One attempt per model/arm provides no reliability estimate, model ranking, superiority claim, clinical validation or operator-value result. Earlier scripted controls are separate evidence, not additional model trials. Host-side controllers retain host privileges; the bounded container observations do not prove general sandbox security. Published benchmark metrics and manuscript claims are unchanged.
