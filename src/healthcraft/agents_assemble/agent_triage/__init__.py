"""Mercy Point Triage — A2A Full Agent for the Prompt Opinion platform.

Orchestrates three sub-agents over a FHIR Bundle:

1. **Differential Agent** — generates a ranked differential from chief
   complaint + Conditions + Observations using HEALTHCRAFT's
   ``searchClinicalKnowledge`` and ``getConditionDetails`` tools.
2. **Decision-Rule Agent** — invokes the ``ed-decision-rules`` Superpower
   to score the most relevant rule for the working differential.
3. **Disposition Agent** — uses ``checkResourceAvailability``,
   ``calculateTransferTime``, and ``getInsuranceCoverage`` to recommend
   admit / discharge / transfer.

Every hop propagates SHARP context (``contextId`` / ``correlationId`` and
the bundle hash) so the trace can be replayed end-to-end. The agent emits
a final structured plan plus a binary-criteria rubric self-evaluation
following HEALTHCRAFT's Corecraft Eq. 1 contract.
"""

from healthcraft.agents_assemble.agent_triage.agent import (
    TriageAgent,
    TriagePlan,
    create_triage_agent,
)

__all__ = ["TriageAgent", "TriagePlan", "create_triage_agent"]
