"""Judge characterization tests.

No dedicated judge tests existed before Phase 2. This suite locks the judge's
parser, prompt, fairness contract, trajectory formatter, and skepticism presets
so regressions break CI, not a pilot.
"""
