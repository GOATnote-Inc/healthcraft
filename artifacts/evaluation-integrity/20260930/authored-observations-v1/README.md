# Authored observation development evidence

These are engineering reproductions and TDD logs, not clinical calibration,
model evaluation, a comparative study, or formal red-team review.

The temporal read-only audit used a source snapshot of `7d9e54b`. Its manifest
records the frozen source/task hashes. The snapshot itself remains reconstructible
from that commit; `audit-reproduce.py.txt` records the original temporary snapshot path.
`reproduction.json` captures real tool responses and bounded arrival searches;
`python310-reproduction.json` preserves the separate supported-runtime failure.
The vitals inventory summary and contract draft are exploratory counts, not
clinical expectations. The draft's proposed `last_documented` alias was rejected
in development review: the final contract preserves it as documentation time,
without promoting it to measurement time.

The failing logs capture defects before their respective repairs. The missing
shared temporal module initially prevents collection, separately from executable
regression failures. The first nonfinite test had a test-harness error (`to_dict`
does not exist); only the corrected executable contract failure is included here.
No clinical labels were authored from these tests.

`interim-full-tests.log` is a non-final, in-progress run: 2463 passed, seven
skipped, nine failures from outdated timestamp/monkeypatch expectations, and
35 local-socket sandbox setup errors. The tests were updated for the source
contract; the final frozen candidate is tested with local socket permission.
It is deliberately retained rather than presented as a successful final run.

The final source-concordance witness and validation logs live under
`artifacts/validation/20260930/observation-checkpoint/`. Those artifacts bind the
completed source snapshot, not the intermediate files here. See
`docs/AUTHORED_OBSERVATIONS.md` for scope and remaining limitations.
