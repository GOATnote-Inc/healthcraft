# V2 incident review development demo

This bundle exercises a source-bound incident form and a separate report-validity
form against existing synthetic captures. It contains no new model executions,
participants, clinical assessments, measured timing or superiority evidence.
**Every filled response and judgment is script-generated test data.** Both initial
reviewer declarations and the resolver explicitly declare that they are not
independent human reviews.

Open a blank operator form:

- [Native captures, assisted](native-assisted/public/report.html)
- [The same native captures, raw](native-raw/public/report.html)
- [Saved local-model captures, assisted](model-assisted/public/report.html)
- [The same local-model captures, raw](model-raw/public/report.html)

Distribute only an assignment's `public/` subfolder. The rest is coordinator/test
material and reveals selections and fixture judgments. Do not use this exposed
bundle as a blinded or held-out study. The model forms are about 22 MB each because
they retain captured runtime/source text and navigation; browser rendering speed,
visual layout and usability have not been tested. Node tests check serialization
and form wiring, not browser usability.

The native selection contains four deliberately chosen development controls:
wrong-target persistence, acknowledgement without storage, interruption after a
write, and an incomplete capture. The model selection contains three saved attempts:
MedGemma REC2-001 (tool error), MedGemma REC2-002 (literal readback) and Nemotron
REC2-007 (stored content with source-attribution issues). Selection is explicit and
not representative of model performance. Raw and assisted documents are identical;
derived assistance is the only added evidence view, and answers start blank.

Fifteen command executions met their expected outcomes and cover four packet builds, blank/invalid/form
imports, two initial validity assignments/imports, a disputed summary, and a
separate resolver assignment/import/summary. The invalid import intentionally exits
1 after preserving bytes; the others exit0. `commands/` retains exact commands,
stdout, stderr and exit status.

The synthetic operator report deliberately enters the wrong patient and encounter,
unsupported assertions and invalid negative self-reported timing. Its one submitted
case is retained without answer repair, three cases remain pending and one timing
error is separate. The invalid-byte submission and blank template each retain four
pending cases in their own test imports.

[Initial summary](disputed-summary/summary.json) retains eight assigned opportunities
(two initial reviewers × four reports): two opposing fixture declarations and six
pending judgments. [Resolver summary](resolved-summary/summary.json) retains those
same eight opportunities plus one separately assigned fixture resolution, with both
original opposing declarations visible. No vote, human validity rate or time estimate
is computed. The test resolver declares invalid; that is not an actual expert label.

`demonstration-receipt.json` binds source manifests and issuing code. Each packet and
import has its own inventory; the outer manifest covers this complete demonstration.
Hashes establish consistency, not identity, independence or authentic execution.
Earlier source bundles are unchanged and are not regraded. To create another packet
or import, follow [the workflow documentation](../../../../docs/OPERATOR_INCIDENTS.md)
and use a fresh output directory.

Independent intended-user feasibility and validity assessment remain pending. The
user's healthcare-value gate is not met; formal red team, remote main, the manuscript
and arXiv submission remain untouched.
