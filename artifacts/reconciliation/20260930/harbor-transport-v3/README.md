# Synthetic transport development controls v3

All four scheduled controls completed and matched their expected mechanical outcomes. This exercises actual Harbor Trial and DockerEnvironment, plus a direct coordinator HTTP bridge.

| Attempt | Execution | Mechanical check | Real tool calls | Stored notes |
|---|---|---|---:|---:|
| native-reference | completed | True | 10 | 1 |
| native-noop | completed | False | 0 | 0 |
| harbor-reference | completed | True | 10 | 1 |
| harbor-noop | completed | False | 0 | 0 |

These are four scripted controls, not model trials, a clinical study, operator-value evidence or a benchmark comparison. No model calls or patient-derived inputs were used. Prior failed rosters remain recorded; a later roster does not replace them. The five-axis independent oracle measures zero clinical/safety criteria.

The direct arm uses fixed host-coordinator `docker exec` HTTP requests to the private backend. The Harbor arm uses a fixed terminal CLI through the real SDK. Harbor reward checks connectivity only; it does not grade note correctness or persistence. Backend source/expectations are unavailable through the public tool credential. Shared Harbor verifier files are not independently trusted evidence.

`roster.json` precedes execution; `summary.json` contains every scheduled row. Each attempt retains actual commands, raw exits, backend journal, write-once state evidence and independent oracle output. `run_probe.py.txt` records the coordinator source used. `build-context.tar.gz` holds the exact staged image inputs; every member was checked against `build-input-manifest.json`. The unpacked build directories remain local and are ignored by Git. Image identities are in `image-*.json`; the source snapshot location in the coordinator script is local provenance, not a portable installation path.

The disposable image network probe establishes only that probe container could reach its backend and failed one TCP connection to 1.1.1.1:443. It does not inspect the actual Harbor-created container or prove comprehensive egress isolation. No browser visual QA, clinical validation, formal red team, remote push or manuscript update is represented.

Independent ordinary peer review reproduces the saved verdicts and passes 107 checks. Exact reference tool schemas, ordered calls/responses, audit entries and before/after snapshots match across the two interfaces. The executed host adapter/controller sources are preserved separately in `host-runtime-inputs/` with hashes; current development source may differ. This review is not the later formal red team.
