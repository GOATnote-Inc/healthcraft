# Independent offline validation of the roster source export

The six exact bundles in the parent directory contain 99 resources representing 33 supplied roster members. Official validator 6.10.4 against FHIR R4 4.0.1 reported **0 errors/fatals, 99 warnings and 33 information issues**. Official R4 JSON-schema checks and local reference-closure/ownership checks also passed for every bundle.

This is limited structural/FHIRPath evidence. **Complete FHIR conformance and clinical validity are not established.** No benchmark, clinical-safety, comparative-value, or deployment-readiness claims follow.

| Bundle | Errors/fatals | Warnings | Information |
|---|---:|---:|---:|
| CC-022.bundle.json | 0 | 12 | 4 |
| CC-027.bundle.json | 0 | 9 | 3 |
| CC-028.bundle.json | 0 | 21 | 7 |
| IR-018.bundle.json | 0 | 21 | 7 |
| IR-023.bundle.json | 0 | 21 | 7 |
| IR-025.bundle.json | 0 | 15 | 5 |

Each resource has one dom-6 warning recommending a human-readable narrative: three warnings per roster member. Each DocumentReference has one information issue stating that application/json could not be terminology-validated without a terminology server. These findings are retained in the raw and parsed outcomes. They are not silently dropped or treated as complete terminology coverage.

`-tx n/a -no-http-access` disabled external terminology and HTTP access. The official validator selected auxiliary packages from a copied isolated cache; all package versions and content-tree hashes are recorded in report.json and parsed-outcomes.json. Package content hashes were rechecked unchanged after validation. The local cache contents were hashed, not independently authenticated against signed package releases. Validator binary SHA-256 was matched to the official 6.10.4 GitHub release digest; its license is Apache-2.0. R4 package metadata identifies CC0-1.0. No validator JAR, schema archive, or package cache is vendored here.

Input bundle hashes, the export manifest, and every source path in that manifest were checked before and after execution. All six canonical bundle hashes matched the export manifest, all source pins matched current files, all six outcome source-file identities matched the inputs exactly, and no drift occurred. The export manifest remains unchanged with validation status not_run; this directory holds separate evidence bound to those exact bytes.

The source-fidelity certificate belongs to the exporter; these FHIR checks cannot judge the clinical truth of attachment content. Local reference controls rejected a duplicated fullUrl, a DocumentReference linked to the wrong patient's source, and an unresolved Encounter patient reference. The official validator can report an unresolved reference as a warning, so the separate closure check is necessary.

- report.json: counts, per-bundle schema/link checks, control outcomes, exact command, tool/package/schema provenance, and limitations.
- official-outcomes.json / official-validator.log: unmodified independent validator output.
- parsed-outcomes.json: fail-closed parser result. It explicitly leaves complete_conformance=false and provenance_authenticated=false; the parser alone does not authenticate execution.
- before-sha256.json / after-sha256.json: identical validated-input and source-file snapshots.
- evidence-sha256.json: hashes of these validation artifacts.

The official validator can exit 0 for multi-file output containing error issues. Consumers must parse every OperationOutcome and cannot use the process exit status alone.

Primary references: [HL7 R4 downloads](https://hl7.org/fhir/R4/downloads.html), [FHIR validation guidance](https://hl7.org/fhir/R4/validation.html), [validator 6.10.4](https://github.com/hapifhir/org.hl7.fhir.core/releases/tag/6.10.4).
