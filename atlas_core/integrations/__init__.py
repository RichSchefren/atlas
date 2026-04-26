"""Atlas integrations into Rich's existing capture stack.

Atlas absorbs vault-search, integrates with the Intelligence Engine
brain pipeline, and writes back to BRIEFING.md so the existing
morning ritual surfaces Atlas activity.

Spec: PHASE-5-AND-BEYOND.md § 1.7
"""

from atlas_core.integrations.intelligence_engine import (
    DEFAULT_BRAIN_DIR,
    DEFAULT_EVENTS_FILE,
    AtlasEvent,
    IntelligenceEngineBridge,
)

__all__ = [
    "DEFAULT_BRAIN_DIR",
    "DEFAULT_EVENTS_FILE",
    "AtlasEvent",
    "IntelligenceEngineBridge",
]
