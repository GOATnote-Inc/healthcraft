"""Deterministic PoC-validator for HEALTHCRAFT safety-critical criteria.

Design: docs/POC_VALIDATOR_EXTENSION.md
Invariants: docs/SAFETY_INVARIANTS_PILOT.md

Phase 0: module lands with 3 pilot invariants (MW-011 C01/C02/C05).
The gate is not yet wired into judge.py -- this is the shadow-mode
library used for agreement measurement against V8 judge verdicts.
"""

# Import invariant modules so their @register decorators run.
from healthcraft.evaluator import (
    invariants_mw_011,  # noqa: F401,E402
    invariants_scj_006,  # noqa: F401,E402
)
from healthcraft.evaluator.shadow import (
    ShadowEntry,
    append_shadow_log,
    is_shadow_enabled,
    run_shadow_pass,
    shadow_log_path,
)
from healthcraft.evaluator.validator import (
    ValidationResult,
    Verdict,
    get_validator,
    register,
    registered_criteria,
    validate,
)

__all__ = [
    "ShadowEntry",
    "ValidationResult",
    "Verdict",
    "append_shadow_log",
    "get_validator",
    "is_shadow_enabled",
    "register",
    "registered_criteria",
    "run_shadow_pass",
    "shadow_log_path",
    "validate",
]
