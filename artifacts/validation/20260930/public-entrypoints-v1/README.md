# Public evaluation and MCP entrypoint repair

The public commands now distinguish actual model evaluation, task inventory,
and scripted handler diagnostics. The legacy runner could attach a real model's
name and a clinical score to placeholder output without calling that model.
`simulate` now accepts only `simulated`, preserves the attempted tool requests
and responses, and leaves all clinical/benchmark outcomes unassessed. Prompt
and handler failures remain in the scheduled trial denominator. Existing
simulation output cannot be overwritten.

`healthcraft evaluate` delegates to the actual orchestrator instead of merely
listing tasks. `python -m healthcraft` and the installed command share the
same entry point. `list-tasks` explicitly provides the inventory operation.
`healthcraft serve` now runs a seeded native MCP stdio server instead of
printing a placeholder readiness message and exiting. Actual SDK clients
discovered all 24 canonical tools, performed mutations, and read stored state
back through the public command. The separate HTTP tool API remains explicitly
identified as a different protocol.

The Docker entrypoint now consumes its declared environment settings and
accepts simulation flags. Reports separately count selected trials with
criterion errors, preventing a headline of zero errors when a saved judge
criterion failed. These categories can overlap with trajectory errors.

## Validation

| Scope | Evidence |
|---|---|
| Final complete suite with loopback fixture access | 3,598 passed; 58 skipped; 270.67 seconds; [final log](cli/final-full-suite.log) |
| Complete suite before the seven Docker tests were added | 3,591 passed; 58 skipped; [log](cli/full-suite.log) |
| Final affected integration | 231 passed; 13 optional SDK skips; [log](cli/final-integration.log) |
| Public CLI TDD | 13 initial failures and 3 passes, then 17 passes; [RED](cli/red.log), [GREEN](cli/final-green.log) |
| Simulation TDD and peer review | 69 tests on Python 3.10/3.12/3.14; 15 additional offline checks; [receipt](simulation/validation.json), [review](simulation/peer-review.json) |
| Actual optional MCP SDK | 55 passed without skips on Python 3.13.14, MCP 1.29.0; [receipt](stdio/receipt.json), [review](stdio/peer-review.json) |
| Report counters | 8 initial failures; 132 reporting/review tests pass on Python 3.10/3.12/3.14; [receipt](reporting/receipt.json) |
| Docker entrypoint | 3 initial failures; 60 related tests pass on Python 3.10/3.12/3.14; [receipt](docker/receipt.json) |
| Final isolated `make lint` | Passed for 739 inventoried files, including 372 Python files; [receipt](cli/final-lint-receipt.json), [hashes](cli/final-lint-inputs.json) |

Counts overlap and must not be added. The complete core suite skips optional
SDK tests; the separate SDK run exercises them. The SDK runtime has AnyIO
4.15.1, while the repository's constrained install selects 4.14.2. This is
not evidence of a fresh constrained installation on every supported Python.
CI now selects the MCP extra for its Python 3.12 leg; remote CI has not run.

The broader workspace `make lint` still reports 115 errors in unrelated
untracked archives/deliverables ([unaltered log](cli/root-make-lint.log)).
The isolated candidate excludes those directories and raw artifact/result
collections. It is not a claim that the entire working directory is clean.
Docker validation executes the literal declared entrypoint with its copied
shell wrapper and a recording child, then uses the real argument parser.
No image build or container launch was performed for this change.

The [public smoke receipt](cli/public-smoke.json) and [saved output](cli/smoke-output/summary.json)
retain a real synthetic CR-001 scripted attempt: one scheduled run, actual
tool errors, zero model calls, and null clinical scores. Its nonzero exit is
expected for rejected empty-parameter smoke inputs. Real model labels and
an evaluation command missing its required model are rejected before execution.

## Boundaries and provenance

Native MCP advertises complete input schemas but no output schema: the authored
return descriptions do not match the actual status/data envelopes. State
persistence is scoped to one running in-memory server. Source-checkout
configuration files remain required. Simulation is not a durable process
supervisor; disk failure or process termination can prevent final capture.

[Checkpoint](checkpoint.json) binds the changed source and test bytes to the
parent commit. The [copy inventory](copied-originals.json) preserves original
paths and hashes for selected logs and receipts; not every intermediate log
mentioned inside an original receipt is included. Temporary paths are
historical provenance. The manifest hashes every payload except itself.
Hashes identify bytes, not authenticated execution or reviewer identity.

These are engineering checks, with ordinary development peer review. No model
inference, formal red-team exercise, user study, or independent clinical
validation was performed in this change. Previous local-model attempts and
their failures remain unchanged. Comparative end-user and healthcare value
is still unproven. The value → formal red team → remote main and manuscript
release order remains in force; this is a local checkpoint only.
