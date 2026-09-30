# Native Ollama structured-command feasibility — v2 proposal

Date: 2026-09-30. Scope: read-only inspection of existing HealthCraft code and
primary upstream documentation/source. No model calls, binary grammar tests,
package installation, repository edits or changes to retained v1 results were
performed for this research.

## Finding and evidence boundary

Ollama's native `POST /api/chat` accepts a top-level `format` value containing a
JSON Schema object. This is not an `options` member and not the OpenAI-compatible
`response_format` envelope. Its documented use does not require native tool
calling; the proposed controller continues to send text messages with
`tools=None`.

- [Official structured-output guide](https://docs.ollama.com/capabilities/structured-outputs)
  documents schema objects in `format`, application-side validation, and lower
  temperature for more repeatable output.
- [Official native chat API](https://docs.ollama.com/api/chat) documents `format`,
  `options`, `think`, `keep_alive`, `done` and `done_reason`.
- [Ollama v0.34.4 request types](https://github.com/ollama/ollama/blob/v0.34.4/api/types.go#L121)
  define `ChatRequest.Format` as raw JSON, separate from options/tools.
- [v0.34.4 routes](https://github.com/ollama/ollama/blob/v0.34.4/server/routes.go#L2653)
  pass `Format` to completion; the native chat path also forwards it at lines
  2773–2782.
- [v0.34.4 llama-server adapter](https://github.com/ollama/ollama/blob/v0.34.4/llm/llama_server.go#L2255)
  converts a schema object to its runner's JSON-schema response format. Its
  completion path uses `json_schema`; JSON mode uses a generic grammar.
- [v0.34.4 release](https://github.com/ollama/ollama/releases/tag/v0.34.4)
  explicitly describes structured-output changes for thinking models.
- [Pinned llama.cpp version](https://github.com/ollama/ollama/blob/v0.34.4/LLAMA_CPP_VERSION)
  is `b11081`, selected by the
  [release build configuration](https://github.com/ollama/ollama/blob/v0.34.4/llama/server/CMakeLists.txt#L103).
- [b11081 converter](https://github.com/ggml-org/llama.cpp/blob/b11081/common/json-schema-to-grammar.cpp#L825)
  handles any-of, constant, enum and object nodes. An object without declared
  properties and with unrestricted additional properties uses a generic object
  grammar.

The cached local metadata previously captured runtime `0.34.4`, with installed
Nano and MedGemma aliases both using GGUF. Nano declares completion/tools/thinking;
MedGemma declares completion only. Metadata was not queried again during this
research. Source compatibility does not prove that the installed binary will
compile this exact schema or that either model will complete the task. No live
schema compilation, generation, successful structured response or performance
improvement has been established here.

## Minimum proposed command schema

This schema describes exactly the existing call-or-finish envelope. It includes
no record IDs, expected facts, note contents, clinical labels or action sequence.
Tool parameters remain an arbitrary object; existing strict JSON parsing and
actual tool validation remain authoritative.

```json
{
  "anyOf": [
    {
      "type": "object",
      "properties": {
        "action": {"const": "call"},
        "name": {
          "enum": [
            "getEncounterDetails",
            "getPatientHistory",
            "searchEncounters",
            "searchPatients",
            "updateEncounter"
          ]
        },
        "params": {
          "type": "object",
          "additionalProperties": true
        }
      },
      "required": ["action", "name", "params"],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "action": {"const": "finish"}
      },
      "required": ["action"],
      "additionalProperties": false
    }
  ]
}
```

The root has only `anyOf`; it does not mix root properties with the union.
The two alternatives are disjoint because their action constants differ.
`params.additionalProperties` must be explicit: the converter defaults omitted
additional properties to false, unlike general JSON Schema defaults.

The [pinned grammar documentation](https://github.com/ggml-org/llama.cpp/blob/b11081/grammars/README.md#L120)
warns that only a schema subset is supported, some unsupported features may be
ignored, and the schema constrains decoding without entering the prompt. It
also documents limitations around unrestricted additional properties. Therefore
schema-constrained decoding does not replace strict duplicate-key/nonfinite JSON
rejection, normal completion checks, command validation or downstream tool
errors. Existing prompt instructions already explain the command envelope; no
prompt rewrite is needed for this bounded proposal.

## Smallest provider integration

At the inspected checkpoint, `OllamaClient.chat` in
`src/healthcraft/llm/local_models.py` does not send `format`.
`RecordingOllamaClient._request` in
`src/healthcraft/reconciliation/controller.py` already adds `keep_alive` before
journaling the exact request and dispatching it. Add an explicitly versioned
v2 opt-in there, attaching a detached copy of the frozen schema as top-level
`format` before both recording and transport. Leave the base client and v1
behavior unchanged. Both execution arms share this recording client.

Bind a separate protocol version and canonical schema SHA-256 in the frozen
configuration. Use the shared `canonical_json` encoder and UTF-8 SHA-256 for the
schema identity. Reject unknown versions, missing/mismatched schema identity or
unsupported configuration before inference; do not silently fall back to JSON
mode or unconstrained generation. Preserve raw upstream errors and original
response text. The existing `initial_messages_sha256` must remain enforced, but
it does not bind the new top-level decoding field.

Do not copy full public per-tool parameter schemas into this decoding schema:
that would change which invalid calls can be emitted and silently add semantic
constraints to the prior protocol. For example, synthetic identifiers may not
satisfy every published format/pattern. Let the actual tool response preserve
that distinction, with no automatic repair or retry.

## Reproducibility and interpretation

For both models and arms, freeze the same schema and declared settings:
`temperature=0`, `seed=42`, `num_ctx=32768`, `num_predict=4096`, maximum 16
responses, `keep_alive=0`, native request/socket timeout 240 seconds, parent hard
process deadline 900 seconds. Retain the existing completion/cancellation and
postflight identity requirements. Record the existing capability-dependent wire
difference: Nano receives `think:false`; the client omits that field for
completion-only MedGemma. No model/provider/cloud fallback is proposed.

Matching declared settings is not a claim of identical sampling or all-turn
byte identity. Model templates, tokenizers, quantization, backend/runtime builds,
implicit model defaults and evolving histories can differ. Context or generation
limits can still truncate output. Valid JSON and schema shape do not establish
correct source selection, persistence, task completion or clinical validity.

Keep every failed v1 attempt and its original configuration intact. Schedule v2
as a separate decoding-condition cohort with new exclusive outputs and a full
scheduled denominator. Do not reinterpret v1 outputs under v2 or present this
engineering change as a demonstrated clinical or comparative performance gain.
