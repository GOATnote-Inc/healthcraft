# Two local care source-reading attempts

One fixed-text request each to the already installed Nemotron and MedGemma
models on 2026-09-30. These are engineering transcription checks on an explicitly
synthetic fixture, not clinical reasoning, autonomous tool use, safety scoring,
a model ranking or comparative-value evidence. No retries or output repair.

| Model alias | Native completion | Strict source-reading outcome |
|---|---|---|
| `counsel-nano-q5:latest` | Complete; one request | All four requested fields exactly matched |
| `counsel-medgemma-27b-text-q5:latest` | Complete; one request | Invalid format: output enclosed in a Markdown JSON fence |

Two attempts were scheduled, both attempted and completed. One source-reading
comparison was assessed; the format-invalid attempt remains in the denominator
and its field agreement remains unassessed. Clinical and safety outcomes are
unassessed for both. The process exited zero because the diagnostic finished;
this does not mean that both models met its output contract.

Each model received identical actual `getEncounterDetails`,
`validateTreatmentPlan` and `processDischarge` outputs as text. Before inference,
the harness verified source fields, unknown administration status, response
identities and the persisted discharge note. Models copied four literal fields;
they did not select or execute these tool calls. No real patient data was used.

`attempts.json` preserves exact prompts, native request/response envelopes,
tool outputs, source snapshot, audit and final state. Both native envelopes had
assistant roles and normal stop reasons. All 354 source/config hashes, runtime
metadata and installed model identities were unchanged before/after the run.
The model digests are recorded in full in that file. Ollama was 0.34.4, both
models used Q5_K_M, seed 42, temperature zero, context 8192 and a 768-token output
budget. The 45-second stage deadlines and 320-second outer process limit were
not reached. Each model was requested to unload after its single completion.

Wall durations were 5.992 seconds for Nemotron and 32.211 seconds for MedGemma,
including per-attempt metadata work; total process time was 38.415 seconds.
The repository test suite ran concurrently. These observations are not a
controlled latency comparison or evidence of relative clinical capability.

The source candidate was `/private/tmp/healthcraft-care-final-ydju6d2l`, based on
`aa21717` plus the named care/imaging repairs. A clean environment contained no
API keys; the only inference endpoint was `http://127.0.0.1:11434`. No weights
were downloaded and no hosted fallback was used. The process wrapper is
preserved as `run-process.py.txt`; `manifest.json` hashes all captured files.

Reproduce with a new output path and the installed local aliases:

```sh
env -i PATH=/usr/bin:/bin .venv/bin/python scripts/local_care_probe.py \
  --output /tmp/new-local-care-probe.json --timeout 45 --max-output-tokens 768
```

Changing the prompt, parser or decoding after observing these outputs would
constitute a new diagnostic. The unmodified artifacts here retain this run's
format failure. The broader superiority and clinical-validation gates remain
unmet; formal red-team review and publication have not begun.
