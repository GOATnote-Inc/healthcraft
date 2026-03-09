# Corecraft Attribution

HEALTHCRAFT directly adapts the architecture described in:

> **EnterpriseBench Corecraft: Training Generalizable Agents on High-Fidelity RL Environments**
> Sushant Mehta, Alexander Ritchie, Sai Mahesh Garre, Paulo Niebres, Brady Heiner, Albert Chen
> Surge AI
> arXiv:2602.16179v5

The Corecraft team demonstrated that high-fidelity RL environments with
task-centric world building, expert-authored rubrics, and realistic workflows
produce agents that generalize beyond their training distribution (+4.5% BFCL,
+7.4% tau2-Bench, +6.8% Toolathlon). HEALTHCRAFT extends this architecture to
emergency medicine.

## What We Adapted

HEALTHCRAFT adapts Corecraft's **architecture** (entity types, tool design,
task categories, rubric dimensions, difficulty progression) to a new domain.
No Corecraft code was used. The mapping below shows how each Corecraft concept
translates to emergency medicine.

## Entity Type Mapping

| # | Corecraft Entity | HEALTHCRAFT Entity | Rationale |
|---|-----------------|-------------------|-----------|
| 1 | Customers | Patients | Primary actors in the domain |
| 2 | Orders | Encounters | Transaction unit (visit vs. purchase) |
| 3 | Products | Clinical Knowledge | Domain knowledge base |
| 4 | Builds | Treatment Plans | Multi-component compositions |
| 5 | Support Tickets | Clinical Tasks | Action items with status tracking |
| 6 | SLAs | Time Constraints | Time-bound performance requirements |
| 7 | Shipping Records | Transfer Records | Movement/logistics records |
| 8 | Compatibility Rules | Clinical Decision Rules | Validation logic |
| 9 | Warranty Policies | Protocols & Guidelines | Standard operating procedures |
| 10 | Loyalty Tiers | Insurance & Coverage | Tiered service/access rules |
| 11 | Knowledgebase Articles | Reference Materials | Reference documentation |
| 12 | Promotions | Resource Availability | Available resources/offers |
| 13 | Inventory | Supplies & Medications | Stock management |
| 14 | Company Policies | Regulatory & Legal | Governance constraints |

## Tool Mapping

| # | Corecraft Tool | HEALTHCRAFT Tool |
|---|---------------|-----------------|
| 1 | searchOrders | searchEncounters |
| 2 | searchProducts | searchClinicalKnowledge |
| 3 | getOrderDetails | getEncounterDetails |
| 4 | getProductDetails | getConditionDetails |
| 5 | updateTicketStatus | updateTaskStatus |
| 6 | processReturn | processDischarge |
| 7 | validateBuildCompatibility | validateTreatmentPlan |
| 8 | searchCustomers | searchPatients |
| 9 | getCustomerHistory | getPatientHistory |
| 10 | createTicket | createClinicalOrder |
| 11 | updateOrder | updateEncounter |
| 12 | calculateShipping | calculateTransferTime |
| 13 | checkInventory | checkResourceAvailability |
| 14 | applyPromotion | applyProtocol |
| 15 | searchKnowledgebase | searchReferenceMaterials |
| 16 | getKnowledgebaseArticle | getReferenceArticle |
| 17 | createCustomer | registerPatient |
| 18 | updateCustomer | updatePatientRecord |
| 19 | getWarrantyPolicy | getProtocolDetails |
| 20 | getShippingStatus | getTransferStatus |
| 21 | getLoyaltyTier | getInsuranceCoverage |
| 22 | searchPromotions | searchAvailableResources |
| 23 | processExchange | processTransfer |
| 24 | *(new)* | runDecisionRule |

Tool 24 (`runDecisionRule`) is new -- it has no Corecraft equivalent. Clinical
decision rules (HEART Score, Wells Criteria, Ottawa SAH Rule, PECARN, Canadian
C-Spine) are a first-class concept in emergency medicine that requires dedicated
tool support.

## Task Category Mapping

| # | Corecraft Category | HEALTHCRAFT Category |
|---|-------------------|---------------------|
| 1 | Information Retrieval | Information Retrieval |
| 2 | Communication | Clinical Communication |
| 3 | Problem Solving | Clinical Reasoning |
| 4 | Multi-Step Workflows | Multi-Step Clinical Workflows |
| 5 | *(new)* | Temporal Reasoning |
| 6 | *(new)* | Safety-Critical Judgment |

Categories 5 and 6 are new. Emergency medicine requires explicit temporal
reasoning (time-critical interventions, overlapping protocols) and safety-critical
judgment (capacity assessment, regulatory compliance, protocol override) that
do not have equivalents in retail customer support.

## Rubric Dimension Mapping

| # | Corecraft Dimension | HEALTHCRAFT Dimension | Weight |
|---|--------------------|-----------------------|--------|
| 1 | Completeness | Clinical Completeness | 0.20 |
| 2 | Correctness | Clinical Correctness | 0.25 |
| 3 | Constraint Satisfaction | Protocol Adherence | 0.15 |
| 4 | Format Compliance | Documentation Quality | 0.10 |
| 5 | *(new)* | Safety | 0.20 |
| 6 | *(new)* | Temporal Sequencing | 0.10 |

Safety is a **hard gate**: a lethal dose, missed critical allergy, or discharged
emergency zeroes the total score regardless of performance on other dimensions.

## Difficulty Level Mapping

| Level | Corecraft | HEALTHCRAFT | Tool Calls |
|-------|-----------|-------------|------------|
| 1 | Easy | Triage | 1-2 |
| 2 | Medium | Workup | 2-4 |
| 3 | Hard | Treatment | 4-8 |
| 4 | Expert | Resuscitation | 8-15 |
| 5 | *(new)* | Mass Casualty | 15+ |

Level 5 (Mass Casualty) is new. It requires managing multiple simultaneous
crises with shared resource constraints -- a scenario class that does not
exist in retail support.

## What Makes EM Harder

1. **Temporal dependence** -- entity meaning changes over time (troponin trending)
2. **Adversarial confusion pairs** -- 152 condition pairs with identical presentations but opposite treatments
3. **Seven communication registers** -- patients, nurses, consultants, EMS, insurance, regulators, families
4. **Cyclic entity graph** -- encounters generate tasks that change conditions that change encounters
5. **Safety as hard constraint** -- non-convex reward landscape
6. **Uncertain ground truth** -- many tasks have no single correct answer

## Contact

Questions about this attribution: open an issue on this repository.

Questions about Corecraft: contact the Surge AI team at [surgehq.ai](https://surgehq.ai).
