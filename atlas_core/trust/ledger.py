"""HashChainedLedger scaffold — Phase 2 Week 4 stub.

This is the module that will be REBUILT, not ported. Bicameral's change_ledger.py
uses random event IDs (no chain); Atlas builds a real SHA-256 chain.
See spec § 6 in `05 - Atlas Architecture & Schema.md`.
"""

from __future__ import annotations


class HashChainedLedger:
    """Stub. Real implementation in Phase 2 Week 4.

    Atlas-original work (NOT a port from Bicameral):
      - SHA-256 chained event_id = sha256(previous_hash + canonical_payload)
      - chain_sequence monotonic counter with UNIQUE constraint
      - verify_chain() walks from genesis to latest, validates every link
      - append_event() in BEGIN IMMEDIATE transaction (atomic)
      - typed_roots materialized view for current-state queries
    """

    def is_promoted(self, edge_uuid: str) -> bool:
        """Phase 2 Week 1 stub: returns False. Real impl in Week 4."""
        return False
