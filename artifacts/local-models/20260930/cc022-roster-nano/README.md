# CC-022 experimental roster diagnostic

One native Ollama Nemotron trial used `roster-observations/v1`, seed 42,
context 32768, temperature zero, and thinking disabled. The installed model
digest and effective settings are recorded in the trajectory and
`assessed-outcome.json`. No judge was called and no weights were downloaded.

The trial exhausted 25 tool rounds without a final response. Four
`searchPatients` calls incorrectly used patient IDs as MRNs and returned no
matches. Four `searchEncounters` calls returned the four roster encounter IDs.
The remaining calls searched clinical knowledge or reference materials;
there were no `getEncounterDetails` or `getPatientHistory` calls. The agent
did not retrieve the projected detailed observations.

Accounting is **one scheduled, one attempted, zero completed, one incomplete**.
All ten original clinical criteria remain ungraded. Summary benchmark and
safety metrics are null; raw trajectory reward/pass/gate fields are legacy
placeholders, not measured clinical outcomes. The orchestrator process exited
zero because it saved the experiment successfully; that is not task success.

`provenance.json` captures source/runtime identity before and after the run,
explicit settings, exact invocation, and hashes of the initial outputs.
Source provenance was unchanged. The 26.854-second wall time includes launch
and recording overhead; repository test suites ran concurrently, so this is
not a latency benchmark. This trial was not rerun.

The separate six-task roster reference certificate exercises a scripted
controller. Its successful mechanical retrieval does not establish model
performance or clinical validity for this trial. The pinned NeMo Gym probe
used a different task and settings and is not a performance comparator.
