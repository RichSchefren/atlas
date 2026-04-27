"""Fireflies extractor — pulls meeting transcripts from Fireflies' GraphQL
API and emits structured claims for participants, decisions, and
action items.

Spec 07 § 2.3: Fireflies is medium-trust ambient (transcribed meetings).
Atlas pulls via GraphQL polling (preferred) or webhook ingestion (when
Rich's webhook server is up). Each transcript becomes:
  - Person.attended_meeting claims (one per participant)
  - Decision claims (one per decision marker in the summary)
  - Commitment.action_item claims (one per action item)

This module is a hardened stub — the run-once contract is wired but
fetch_new_events explicitly raises until the Fireflies API key is
configured. That's intentional: a silent no-op would mask the missing
setup; a loud error fails fast and tells Rich what to fix.

Setup needed (Rich's hand):
  1. Get API key at app.fireflies.ai/settings → Developer Settings
  2. Store as 1Password 'Fireflies API Key' in Developer vault
  3. Export FIREFLIES_API_KEY env var when running orchestrator
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from atlas_core.ingestion.base import (
    BaseExtractor,
    ExtractedClaim,
    IngestionCursor,
    StreamConfig,
    StreamType,
)
from atlas_core.ingestion.confidence import STREAM_CONFIDENCE_FLOORS

log = logging.getLogger(__name__)


FIREFLIES_GRAPHQL_ENDPOINT: str = "https://api.fireflies.ai/graphql"


class FirefliesNotConfiguredError(RuntimeError):
    """Raised when FIREFLIES_API_KEY is not in the environment.

    The orchestrator catches this, marks the stream errored, and continues
    other extractors — Atlas keeps ingesting from configured streams.
    """


class FirefliesExtractor(BaseExtractor):
    """Polls Fireflies GraphQL for transcripts since the cursor.

    Phase 2 W7: structure ready, network call deferred until API key
    available.
    """

    stream = StreamType.FIREFLIES

    def __init__(
        self,
        *,
        quarantine,
        api_key_env: str = "FIREFLIES_API_KEY",
        config: StreamConfig | None = None,
    ):
        super().__init__(
            quarantine=quarantine,
            config=config or StreamConfig(
                confidence_floor=STREAM_CONFIDENCE_FLOORS[StreamType.FIREFLIES],
            ),
        )
        self.api_key_env = api_key_env

    def fetch_new_events(self, cursor: IngestionCursor) -> list[dict[str, Any]]:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise FirefliesNotConfiguredError(
                f"{self.api_key_env} not set; configure to enable Fireflies "
                "ingestion. See atlas_core/ingestion/fireflies.py docstring."
            )
        # Phase 3: real GraphQL poll using `since=cursor.last_processed_at`.
        # Returning empty list keeps the contract honest until then.
        log.info("Fireflies API key present; full poll lands in Phase 3.")
        return []

    def extract_claims_from_event(
        self, event: dict[str, Any],
    ) -> list[ExtractedClaim]:
        # Wired in Phase 3 once GraphQL response shape is fixed.
        return []

    def cursor_for_event(self, event: dict[str, Any]) -> IngestionCursor:
        return IngestionCursor(
            stream=self.stream,
            last_processed_at=(
                event.get("date") or datetime.now(timezone.utc).isoformat()
            ),
            last_processed_id=str(event.get("id", "")),
        )
