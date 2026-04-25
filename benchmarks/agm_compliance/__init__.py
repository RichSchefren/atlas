"""AGM compliance verification suite — reproduces Kumiho Table 18.

49 scenarios across 5 categories (simple, multi-item, chain, temporal, adversarial)
testing all 7 postulates Kumiho proves: K*2 (Success), K*3 (Inclusion), K*4 (Vacuity),
K*5 (Consistency), K*6 (Extensionality), Hansson Relevance, Hansson Core-Retainment.

Target: 100% pass rate matching Kumiho's published verification.

Spec: 03 - Atlas Technical Foundation § 2.3, Kumiho § 15.7
"""

from benchmarks.agm_compliance.runner import (
    ComplianceCategory,
    ComplianceResult,
    Postulate,
    Scenario,
    SuiteReport,
    run_suite,
)

__all__ = [
    "ComplianceCategory",
    "ComplianceResult",
    "Postulate",
    "Scenario",
    "SuiteReport",
    "run_suite",
]
