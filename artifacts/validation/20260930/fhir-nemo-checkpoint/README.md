# Local engineering checkpoint: source export and NeMo adapters

All code checks below used the source hashes in `validation.json`, based on
local commit `d1e3c8b` plus the recorded staged patch. Nothing was pushed.

| Check | Result |
|---|---|
| Full Python 3.10 suite | 2,144 passed, 38 skipped |
| Full Python 3.12 suite | 2,144 passed, 38 skipped |
| Full Python 3.14 suite | 2,189 passed, 7 skipped |
| Native adapter with actual pinned Gym SDK | 36 passed |
| Resource adapter with actual pinned Gym SDK | 8 passed |
| Smoke | 48 passed, zero failed |
| Preflight | Passed; structural checks only |
| `make lint` on tracked index export | Passed; 301 files formatted |

The minimal 3.10/3.12 environments omit optional SDK/plot dependencies. Skips
are not passes. The ordinary checkout contains 115 unrelated lint findings in
untracked archive/deliverable directories. Lint above used a clean
`git checkout-index --all --prefix=...` export after staging explicit filenames.
No unrelated files were changed or excluded by a new lint rule.

Full suite commands used `make test` with `PYTHON` and `PYTEST` pointing to
each existing environment. Root environment: `.venv`; compatibility environments:
`/private/tmp/healthcraft-check-py310` and `...-py312`. `make smoke` and
`make preflight` used the root environment. The full suites finished before
the subsequent model feasibility attempts; timings are not performance claims.

Optional Gym tests used Python 3.13.14 at
`/private/tmp/healthcraft-nemo-gym-probe/runtime-venv` and source revision
`82e1834ccf2dd578af26a1abc686c15e17569594`. The direct `python -m pytest`
invocation failed before collection because that isolated environment does not
include pytest; this failure is retained in `sdk-direct-pytest-unavailable.log`.
The successful native test invocation appended the existing project's
`.venv/lib/python3.14/site-packages` **after** the SDK environment's paths to
provide pure-Python pytest dependencies, with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.
The isolated SDK dependencies retained import priority. No packages were installed.

```python
import sys
sys.path.append('/Users/kiteboard/healthcraft/.venv/lib/python3.14/site-packages')
import pytest
raise SystemExit(pytest.main(['tests/test_integrations/test_nemo_native.py', '-q']))
```

Both optional commands set `PYTHONPATH` to `src`, the repository root, and the
pinned Gym source checkout, and `NEMO_GYM_OTEL_ENABLED=0`. Resource tests used
`python -m unittest discover -s tests/test_integrations -p test_nemo_roster_resources.py -v`.
Provider transport is stubbed in these tests; they do not perform inference.
The native test log retains the disabled-plugin configuration warning and two
upstream deprecation warnings. Resource tests retain the upstream warnings.

The separate [FHIR evidence](../../../fhir/20260930/roster-source-v1/validation/README.md)
validates exact generated Bundles and preserves its warnings and offline
terminology limitations. These engineering checks do not establish clinical
truth, comparative value, UI usability, or deployment readiness, and are not
the deferred formal red-team review.
