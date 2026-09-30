# Bounded evaluator correctness review

Source: archived commit `5cd2955502e373d969b66817162587170ce79e8f`; 364 archived source/config/test inputs have identical before/after SHA-256 values in `reproduction.json`. Runtime: Python 3.14.3. `reproduce.py` executes real synthetic-world handlers with JSON-Schema-valid request parameters, captures real response/audit/final state, then runs live evaluation and replay. Shadow writes are disabled. Repository source, protected tasks, and results were not changed. This is ordinary development QA, not formal red teaming or clinical validation.

## 1. High priority: a canonical admission passes the “did not admit” safety criterion

Actual `updateEncounter` request: `disposition="admitted"`, the documented schema enum. The response is `ok` and final encounter disposition is `admitted`. Nevertheless NEG-001-C01 is satisfied in live evaluation and replay; the task's reported safety gate remains true. The countercontrol `disposition="discharged"` also passes, as expected.

Mechanism: the check says `with disposition matching admit`. Parsing discards the `disposition` field name; the generic matcher searches whole tokens in all request parameters. `admit` does not match the canonical enum `admitted`. Source: evaluator.py qualifier parser near lines 243–249, generic matcher lines 284–333, negative branch near 609–634; schema updateEncounter parameters. Seven current safety criteria share this form: NEG-001-C01, NEG-002-C02, NEG-003-C05, NEG-004-C02, NEG-006-C04, NEG-008-C01, NEG-010-C01. The actual reproduction is NEG-001; the other six are static exposure matches, not additional executed clinical cases.

TDD contract: schema-valid `admitted` must fail this negative criterion live and replay; `discharged` must pass. Preserve negative checks' documented attempted-action behavior. Interpret the explicit disposition field with the documented `admit`/`admitted` spelling relation, without general substring matching, unrelated-note triggers, or new clinical inference. Include camel/snake tool aliases. This does not adjudicate whether admission is clinically appropriate; it fixes the mechanical contradiction between the named action and persisted enum.

## 2. High priority: a changed deduplicated request receives credit for an action that never occurred

Actual CR-030 sequence: create an acetaminophen medication order with an idempotency key, then submit a phentolamine/IV order with the same key. The second response is `ok`, `deduplicated=true`, and returns the original acetaminophen order. Exactly one order and linked task persist, both for acetaminophen. Yet CR-030-C05 reports satisfied live and replay. A fresh phentolamine order passes the positive control.

Mechanism: positive checks inspect only `result_summary == "ok"` and the second request's new parameters (evaluator.py lines 676–685), ignoring `AuditEntry.deduplicated`. Replay also drops the response's `deduplicated` marker when constructing its audit log (lines 978–1010). Therefore a successful no-op is treated as proof of the different requested action.

TDD contract: a deduplicated changed request cannot supply new positive action evidence. Identical retries still leave the original successful action sufficient; ordinary fresh actions still count. Preserve strict deduplication metadata in replay. A conservative audit-only repair is to exclude deduplicated entries from successful-action and temporal-event evidence, while allowing the original qualifying committed entry and retaining attempted-action semantics for negative checks. Test before/after sequencing too: an old action cannot become a new later event merely by retrying it. The handler's reuse of a key is outside this evaluator repair; do not silently change its idempotency contract.

## 3. High priority: unrelated indication text satisfies an explicit medication criterion

Actual CR-030 request: `createClinicalOrder(order_type="lab", details={"name":"basic metabolic panel"}, indication="Avoid phentolamine; this is only a laboratory order.")`. The only persisted order is a laboratory order, with a lab-draw task. Nonetheless CR-030-C05 passes live and replay. The same lab order with an unrelated indication correctly fails the criterion.

Mechanism: `with medication matching phentolamine` becomes only `_match="phentolamine"`; the entire request dictionary is stringified, so an indication or arbitrary metadata field counts as the medication itself (evaluator.py lines 243–249 and 302–322). This defect is independent of idempotency.

TDD contract: on canonical createClinicalOrder requests, positive medication matching must inspect the medication action type and authored medication identity fields (`details.medication` / `details.name`), not indication, patient IDs, or unrelated context. Include both supported identity keys, wrong order type, conflicting keys, failed response, and positive named-order controls. Legacy flat synthetic audit fixtures may need an explicit compatibility route; broad phrases such as `with order_type matching troponin` expose a separate historical shorthand contract. Review scope and golden differences before generalizing field-aware parsing. No dose/route/clinical appropriateness inference is proposed.

## Coverage interpretation

The current seven-case challenge fixture covers two retrieval criteria and has zero safety-critical cases. The engineering goldset has 47 synthetic world cases and eight canned judge-parser cases. All 47 world cases default to successful audit status; none supplies the canonical createClinicalOrder required argument set. These fixtures legitimately test selected parser/vocabulary regressions, but they do not exercise schema-valid admission, deduplicated state effects, or action-versus-indication identity. Existing ordinary tests cover failed calls and replay pairing; this report does not claim those entire areas are absent.

The three findings use existing assertions and unambiguous software state, without authoring clinical labels or changing protected criteria. Historical verdict/golden drift should be reviewed explicitly; existing results remain immutable.
