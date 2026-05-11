"""ED Decision Rules — MCP Superpower for the Prompt Opinion platform.

Wraps three HEALTHCRAFT MCP tool handlers (``run_decision_rule``,
``get_protocol_details``, ``get_reference_article``) behind a thin MCP
server with a FHIR-Bundle-aware variable extractor. The extractor is the
GenAI surface ("AI Factor"): it reasons over the noisy, free-text portions
of a FHIR Bundle to populate decision-rule variables; the rule itself runs
deterministically against HEALTHCRAFT's validated rule library.
"""

from healthcraft.agents_assemble.superpower_decision_rules.server import (
    SuperpowerServer,
    create_superpower,
)

__all__ = ["SuperpowerServer", "create_superpower"]
