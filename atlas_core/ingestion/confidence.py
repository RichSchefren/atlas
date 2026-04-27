"""Per-stream confidence floors — Spec 07 § 3.

Different streams have different reliability profiles. Atlas's quarantine
starting confidence varies by source so noisy streams (Screenpipe OCR) don't
get the same trust as deliberate vault edits.
"""

from __future__ import annotations

from atlas_core.ingestion.base import StreamType

STREAM_CONFIDENCE_FLOORS: dict[StreamType, float] = {
    # Vault edit — Rich deliberately wrote it down → highest trust
    StreamType.VAULT: 0.70,
    # Claude session — Rich's own typed claims in conversation
    StreamType.CLAUDE_SESSIONS: 0.60,
    # Fireflies — scheduled meetings with named speakers
    StreamType.FIREFLIES: 0.50,
    # Limitless — ambient capture, weaker speaker attribution
    StreamType.LIMITLESS: 0.40,
    # iMessage — casual context, easy misread (opt-in only for content)
    StreamType.IMESSAGE: 0.40,
    # Screenpipe — OCR/visual, inference-heavy, lots of noise → lowest trust
    StreamType.SCREENPIPE: 0.30,
}
