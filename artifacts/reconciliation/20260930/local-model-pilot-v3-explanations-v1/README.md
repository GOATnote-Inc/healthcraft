# Reading the four saved reconciliation attempts

These reports explain the [frozen v3 local-model pilot](../local-model-pilot-v3/README.md).
They replay its existing evidence offline. **No new model or tool calls occurred.**
All four complete oracle results match the originals, and all 181 original
payload hashes remain unchanged.

| Attempt and report | Acknowledged writes | New stored notes | Actual post-write target reads | Correct reconciliation verified |
|---|---:|---:|---:|---|
| [Nano, direct](nano-direct-01/report.html) | 1 | 1 | 0 | No |
| [Nano, Harbor](nano-harbor-01/report.html) | 1 | 1 | 0 | No |
| [MedGemma, Harbor](medgemma-harbor-01/report.html) | 1 | 1 | 1 | No |
| [MedGemma, direct](medgemma-direct-01/report.html) | 1 | 1 | 1 | No |

Each report separates recorded execution from content-qualified verification.
The Nano notes omit both required exclusions and supply two unexpected source
IDs. The MedGemma notes omit one required exclusion, invent another, and
misattribute the remaining source. The report shows exact values and source
pointers rather than guessing how an incorrect row should be paired with a
missing one. A real read of an incorrect stored note remains a real read.

The explanation covers write acknowledgements, final-state stored notes,
post-write reads and scope exclusions. Observation/conflict content, retrieval
coverage and clinical validity are **unassessed by this explanation**. Its
selected diagnostics do not replace the full oracle or create a new reward.
Final-state text matches do not uniquely attribute note creation to a call.

Each attempt directory contains exact input copies, the unchanged recomputed
oracle result, the explanation, standalone HTML and a payload manifest. The
[derivation receipt](derivation.json) binds the original cohort manifest and
each earlier result. The parent manifest hashes this new package. The CLI
source inventory identifies Python files, not a complete executable runtime.
Hashes establish content identity, not authenticated execution.

Reproduce with `scripts/explain_reconciliation.py` and a new output directory;
see the [command and contract](../../../../docs/SYNTHETIC_RECONCILIATION.md#explain-a-recorded-attempt).
The optional prior-verification input takes a standalone oracle object, not the
larger model-pilot result envelope.

Automated HTML structure, escaping, input binding and static evidence checks
are recorded separately in the development validation package. Browser visual
QA and independent user testing have not been performed. These are four exposed
development attempts, not held-out performance, clinical benefit, user time
savings, a model ranking or comparative superiority. The value → formal red team
→ remote main and manuscript release gate remains open.
