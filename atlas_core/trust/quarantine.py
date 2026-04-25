"""QuarantineStore scaffold — Phase 2 Week 4 stub. Ports Bicameral's candidates.py."""

from __future__ import annotations


class QuarantineStore:
    """Stub. Real implementation in Phase 2 Week 4.

    Ports ~95% of Bicameral's truth/candidates.py:
      - SQLite candidates.db with SHA-256 fingerprinting
      - ULID primary keys
      - Trust score thresholds (0.25 / 0.6 / 1.0)
      - Promotion policy v3 (4-gate)
      - Lane matrix for retrieval-vs-candidate eligibility
    """
