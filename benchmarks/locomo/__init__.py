"""LoCoMo runner — Atlas's parity claim against Kumiho's published 0.447 F1.

LoCoMo (Long Conversation Memory) is the four-category token-level F1
benchmark Kumiho cites as their headline. Atlas measures parity against
the same evaluation protocol.

Spec: PHASE-5-AND-BEYOND.md § 2.3
"""

from benchmarks.locomo.runner import (
    LoCoMoRunner,
    LoCoMoScore,
    run_locomo_against,
)

__all__ = [
    "LoCoMoRunner",
    "LoCoMoScore",
    "run_locomo_against",
]
