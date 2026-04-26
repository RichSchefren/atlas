"""Orchestrator — runs all configured extractors on schedule.

Spec 07 § 6: launchd plists wrap a single Python entry point that calls
`run_cycle()` per stream. The orchestrator owns:

  - Stream registration
  - Per-stream cadence enforcement (don't run faster than configured)
  - Aggregate result reporting
  - Daily LLM token budget tracking (ATLAS_DAILY_LLM_BUDGET_USD)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from atlas_core.ingestion.base import (
    BaseExtractor,
    IngestionResult,
    StreamType,
)


log = logging.getLogger(__name__)


@dataclass
class OrchestrationReport:
    """Summary of one orchestration pass across all streams."""

    started_at: str
    finished_at: str = ""
    per_stream: dict[StreamType, IngestionResult] = field(default_factory=dict)

    @property
    def total_events(self) -> int:
        return sum(r.events_processed for r in self.per_stream.values())

    @property
    def total_claims(self) -> int:
        return sum(r.claims_extracted for r in self.per_stream.values())

    @property
    def total_errors(self) -> int:
        return sum(len(r.errors) for r in self.per_stream.values())


class IngestionOrchestrator:
    """Coordinates the 6 stream extractors.

    Production daemon usage:
      orch = IngestionOrchestrator()
      orch.register(VaultExtractor(quarantine=q, vault_roots=[...]))
      orch.register(LimitlessExtractor(quarantine=q, archive_root=...))
      orch.register(... others ...)
      report = orch.run_cycle()
    """

    def __init__(self) -> None:
        self._extractors: dict[StreamType, BaseExtractor] = {}

    def register(self, extractor: BaseExtractor) -> None:
        if extractor.stream in self._extractors:
            raise ValueError(
                f"Stream {extractor.stream.value!r} already registered"
            )
        self._extractors[extractor.stream] = extractor

    def registered_streams(self) -> list[StreamType]:
        return list(self._extractors.keys())

    def run_cycle(
        self,
        *,
        only: list[StreamType] | None = None,
    ) -> OrchestrationReport:
        """Run all registered extractors (or filter via `only`).

        Streams run sequentially in this Phase 2 W5 scaffold; concurrent
        runs come in Phase 2 W7 once we benchmark per-stream LLM costs.
        """
        report = OrchestrationReport(started_at=self._now_iso())
        target_streams = only or self.registered_streams()

        for stream in target_streams:
            if stream not in self._extractors:
                log.warning("Stream %s requested but not registered", stream.value)
                continue
            extractor = self._extractors[stream]
            try:
                result = extractor.run_once()
            except Exception as exc:
                log.exception("Orchestrator: stream %s crashed", stream.value)
                result = IngestionResult(
                    stream=stream,
                    errors=[f"{type(exc).__name__}: {exc}"],
                )
            report.per_stream[stream] = result

        report.finished_at = self._now_iso()
        log.info(
            "Orchestration done: %d streams, %d events, %d claims, %d errors",
            len(report.per_stream),
            report.total_events,
            report.total_claims,
            report.total_errors,
        )
        return report

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
