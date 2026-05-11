"""Standalone demo FHIR Bundles for the hackathon submission.

Each scenario is a real ED clinical pattern that exercises the full agent
call chain end-to-end. Loaders return new dict objects on every call so
mutations don't leak between callers (FHIR Bundles are mutable by nature).

The same bundles power:
- ``tests/test_agents_assemble/test_e2e_workflow.py`` (canonical assertions)
- ``scripts/validate_agents_assemble.py`` (metrics harness)
- ``make agents-assemble-demo`` (live CLI demo for the video)
"""

from healthcraft.agents_assemble.demo.bundles import (
    SCENARIOS,
    Scenario,
    list_scenarios,
    load_scenario,
)

__all__ = ["SCENARIOS", "Scenario", "list_scenarios", "load_scenario"]
