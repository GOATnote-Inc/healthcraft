# Local diagnostic evidence

These artifacts use synthetic HEALTHCRAFT data and already-installed Ollama
weights. They are integration/research evidence, not clinical validation or a
frontier leaderboard submission. No paid APIs or model downloads were used.

- `native-smoke.json`: passed Nemotron native tool round trip against the real
  seeded world and two known-label MedGemma judge sanity cases (25.121 seconds).
  This report predates the added runtime-version and explicit judge-error
  fields; its two saved judge verdicts contain valid evidence.
- `native-smoke-completion-checked.json` and `.log`: rerun with explicit
  agent/judge completion guards. Native tool round trip and both judge
  sanity cases passed in 28.926 seconds, with no judge errors. Records
  Ollama 0.34.4, model digests, seed 42, 8,192 context, thinking disabled,
  command/exit status, and source hashes. This tiny diagnostic is not
  clinical judge calibration or a benchmark result.
- `ir001-nano-medgemma/`: first full IR-001/v10 diagnostic, run while fixes were
  still being developed. The process used the earlier completion handling.
  It contains 25 tool calls and ends on a tool response without a final answer.
  Its historical reward and zero-error summary are **not valid completed
  evaluation metrics**. Preserve the artifact as evidence of the defect;
  compare new runs from the corrected runner in a fresh directory.
- `ir001-nano-medgemma-fixed/`: rerun after the completion and accounting
  fixes. The repeated search again reached the 25-round bound; this time the
  runner explicitly records `tool_round_limit`, zero reward, one error run,
  and seven ungraded criteria. It skips judging the incomplete rollout.
  `evaluation_mode` is `local_diagnostic`; no benchmark pass rate is inferred.
- `ir008-qwen-medgemma/`: Qwen3 8B ran the reachable protocol-retrieval task,
  issued 34 tool calls over 25 rounds, and reached the same completion limit.
  Its trace includes encounter updates beyond the requested retrieval. The
  runner preserves the trace, returns zero reward, and skips judging the
  incomplete rollout. This is one configuration/seed, not a model ranking.

Observed behavior: after retrieving patient history, Nemotron repeatedly
searched for cephalexin references without reaching a conclusion. MedGemma
credited a reasoning criterion from retrieved tool text despite no final
reasoning from the agent. IR-001-C03 separately has an assertion/check mismatch
(`checkResourceAvailability` for a cross-reactivity assertion). The benchmark
task remains unchanged pending a versioned rubric audit.

See [the local evaluation guide](../../../docs/LOCAL_MODELS.md) for the runtime
contract, installed model identities, and commands.
