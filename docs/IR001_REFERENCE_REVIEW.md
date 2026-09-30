# IR-001 reference repair and evidence scope

Status: proposed task revision; no replacement clinical scoring rule is
implemented. Primary sources were checked on 2026-09-30. This note does not
change the historical task, rubric channels or model results. The source brief
can be published with the engineering release; external clinical review is
future research, not a prerequisite for publication.

IR-001-C03 currently awards cross-reactivity credit for a resource-availability
lookup. The current development replay still reproduces that false pass.
Changing the tool name to a knowledge search would not establish that an agent
retrieved relevant evidence or interpreted it correctly. The task's teaching
text also groups cephalexin and cefazolin under one approximate risk estimate.
The sources below identify distinctions that any revision must preserve.

## Sources and their different scopes

| Primary source | Relevant content | Limit on its use here |
|---|---|---|
| [Ascend cephalexin label, DailyMed, section 5.1](https://dailymed.nlm.nih.gov/dailymed/fda/fdaDrugXsl.cfm?setid=4fec8daf-6e09-4153-926f-64709dbdd26c) | The label asks about hypersensitivity history and gives an up-to-10% warning for cross-hypersensitivity among beta-lactams in people with a penicillin-allergy history. | A broad label warning is not this fictional patient's cephalexin-specific probability. The displayed prescribing revision is January 2025; that does not establish when the exact currently served SPL record became available. |
| [CDC STI Treatment Guidelines, 2021: Penicillin Allergy](https://www.cdc.gov/std/treatment-guidelines/penicillin-allergy.htm) | The cross-reactivity section gives a 1–8% range for first- and second-generation cephalosporins in its discussion of IgE-mediated penicillin allergy. | Preserve the population and drug-group context. Do not average this range with label wording or convert it to an individual estimate. |
| [AAAAI/ACAAI 2022 drug-allergy practice parameter](https://www.aaaai.org/Aaaai/media/Media-Library-PDFs/Allergist%20Resources/Statements%20and%20Practice%20Parameters/Drug-Allergy-2022.pdf) | The beta-lactam discussion emphasizes R1 side chains and distinguishes cefazolin's unique side chain despite its first-generation classification. | Generation alone does not justify treating cephalexin and cefazolin as interchangeable evidence. This does not establish the patient's culprit molecule, allergy phenotype or prescribing decision. |
| [CDC clinical features of penicillin allergy, August 25, 2025](https://www.cdc.gov/antibiotic-use/hcp/clinical-signs/index.html) | History assessment includes the implicated medicine, reaction timing and symptoms, treatment, and later exposures. | Preserve the task's supplied history, while leaving absent details unknown. A chart field named `verified` is not evidence of a positive diagnostic test. |

These source-selection findings are not a comprehensive guideline review or
a replacement answer. A versioned task must identify the references it uses
and their scope; differing numerical ranges cannot be merged into an automatic
patient-specific risk estimate.

## Bounded engineering revision

The proposed workflow retrieves the intended patient's literal allergy and
pending-order facts, discovers and retrieves a dated reference, and writes a
review note that separates chart facts, attributed source statements, and
unknowns. A final readback verifies persistence on the intended encounter.
Alternative-antibiotic selection, permission to administer, and allergy
de-labeling would be outside this retrieval/documentation task.

The existing `searchReferenceMaterials` and `getReferenceArticle` tools fit
this workflow: the first searches titles and keywords; the second returns a
selected article's content. `searchClinicalKnowledge` searches condition names.
The reference corpus currently lacks the required cephalexin source, so merely
changing the task's expected tool would leave the knowledge gap unresolved.

Implement the retrieval and documentation contract in a separate task/profile
version with source identifiers, section locators, content hashes, source dates
and an explicit knowledge-as-of date. Tests can verify source fidelity and
persistence without assigning clinical interpretation credit. Verify historical
availability before using a current source snapshot in the original January
2026 setting; otherwise use a new setting with an explicit source cutoff.

Mechanical acceptance should require actual patient-scoped retrieval, article
content returned under its pinned identity, a source-attributed note persisted
on the intended encounter, and successful readback. Wrong-patient records,
resource-only lookups, title-only search hits, unrelated or unavailable articles,
fabricated citations and unpersisted notes need negative controls. These checks
cannot certify clinical interpretation or prove a physician received a message.

## Distribution and next decision

CDC's [agency-material policy](https://www.cdc.gov/other/agencymaterials.html)
describes reuse of public-domain content with attribution, nonendorsement,
unchanged substance and notice of free availability; third-party content and
marks have exceptions. CDC source pages are free to access. References here
do not imply endorsement of HealthCraft by CDC, HHS or the US government.

NLM's [copyright policy](https://www.nlm.nih.gov/web_policies.html)
distinguishes government works from privately authored material. DailyMed hosting
alone does not establish unrestricted redistribution rights for every label.
No permissive redistribution license was verified for the AAAAI-hosted PDF.
This brief links to sources and uses original paraphrases; it does not vendor
their full text, tables, figures or logos under the repository's Apache license.

The next engineering step is a tested, versioned retrieval/documentation
contract. Clinical risk interpretation remains unassessed unless supported by
a separate explicit evaluation contract and evidence. Optional external review
can strengthen that evidence without blocking repository or paper publication.
The [validity findings](TASK_VALIDITY_FINDINGS.md) remain disclosed under the
[automated release workflow](RELEASE_EVIDENCE_PLAN.md).
