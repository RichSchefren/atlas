"""Atlas ingestion pipeline — 6 streams feeding the trust quarantine.

Per Spec 07 - Atlas Ingestion Pipeline:
  Screenpipe  → 30 min cadence
  Limitless   → 30 min cadence
  Fireflies   → on-new-file (fswatch)
  Claude sessions → hourly
  Vault edits → fswatch
  iMessage    → hourly (metadata-only by default)

Each stream is a subclass of `BaseExtractor` that:
  1. Tracks a per-stream cursor (where it left off)
  2. Pulls new events since the cursor
  3. Runs sanitization + LLM claim extraction
  4. Resolves entities (alias dictionary + LLM fallback)
  5. Pushes ExtractedClaim list into the quarantine

Phase 2 W5 ships:
  - BaseExtractor abstraction + IngestionResult / cursor types
  - Per-stream confidence floors (Spec 07 § 3)
  - Vault extractor (fswatch-driven; deterministic file→claim mapping)
  - Limitless extractor (YAML-pre-processed; deterministic)
  - Orchestrator (runs streams on cadence, idempotent cursors)
  - 17 unit tests covering all of the above

Deferred to Phase 2 W6/W7 (require live API/SDK access for true integration):
  - Screenpipe (SQLite reader; needs Rich's actual schema)
  - Fireflies (Webhook ingestion)
  - Claude sessions (full extraction prompts)
  - iMessage (Full Disk Access; opt-in per thread)
"""

from atlas_core.ingestion.base import (
    BaseExtractor,
    ExtractedClaim,
    IngestionCursor,
    IngestionResult,
    StreamConfig,
    StreamType,
)
from atlas_core.ingestion.claude_sessions import ClaudeSessionExtractor
from atlas_core.ingestion.confidence import STREAM_CONFIDENCE_FLOORS
from atlas_core.ingestion.fireflies import (
    FirefliesExtractor,
    FirefliesNotConfiguredError,
)
from atlas_core.ingestion.imessage import (
    ImessageExtractor,
    ImessageNotConfiguredError,
)
from atlas_core.ingestion.limitless import LimitlessExtractor
from atlas_core.ingestion.orchestrator import (
    IngestionOrchestrator,
    OrchestrationReport,
)
from atlas_core.ingestion.screenpipe import ScreenpipeExtractor
from atlas_core.ingestion.vault import VaultExtractor

__all__ = [
    "BaseExtractor",
    "ExtractedClaim",
    "IngestionCursor",
    "IngestionResult",
    "StreamConfig",
    "StreamType",
    "STREAM_CONFIDENCE_FLOORS",
    "VaultExtractor",
    "LimitlessExtractor",
    "ScreenpipeExtractor",
    "ClaudeSessionExtractor",
    "FirefliesExtractor",
    "FirefliesNotConfiguredError",
    "ImessageExtractor",
    "ImessageNotConfiguredError",
    "IngestionOrchestrator",
    "OrchestrationReport",
]
