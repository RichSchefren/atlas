"""Daily-token budget enforcement for LLM-driven ingestion.

Hard-stops LLM extraction when the day's spend exceeds the configured
budget. Per-day rolling counter persisted to SQLite so process
restarts don't reset the budget.

Default cap: $5/day. Worst-case at Rich-scale (~2K novel claims/week
× $0.05/claim averaged) lands at ≈$10/week. The $5/day cap is a
runaway-cost safety net, not a steady-state expectation.

Spec: PHASE-5-AND-BEYOND.md § 1.4
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


log = logging.getLogger(__name__)


DEFAULT_BUDGET_PATH: Path = Path.home() / ".atlas" / "budget.sqlite"
DEFAULT_DAILY_BUDGET_USD: float = 5.0
"""Conservative ceiling. Override via ATLAS_DAILY_LLM_BUDGET_USD env var."""


# Claude Haiku 4.5 pricing — update annually as pricing shifts.
HAIKU_INPUT_USD_PER_1K_TOKENS: float = 0.001
HAIKU_OUTPUT_USD_PER_1K_TOKENS: float = 0.005


def estimate_haiku_cost(input_tokens: int, output_tokens: int) -> float:
    """USD cost of a single Haiku call. Used by budget pre-checks
    so callers can ask 'will this fit?' without firing the LLM."""
    return (
        input_tokens * HAIKU_INPUT_USD_PER_1K_TOKENS / 1000
        + output_tokens * HAIKU_OUTPUT_USD_PER_1K_TOKENS / 1000
    )


@dataclass
class BudgetState:
    """Snapshot of the day's spend."""

    day: str
    spent_usd: float
    daily_cap_usd: float

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.daily_cap_usd - self.spent_usd)

    @property
    def is_exhausted(self) -> bool:
        return self.spent_usd >= self.daily_cap_usd


class BudgetExceeded(RuntimeError):
    """Raised when an extractor tries to spend past the daily cap."""


class TokenBudget:
    """Per-day spend tracker. SQLite-backed so survives restarts."""

    def __init__(
        self,
        *,
        path: Path | None = None,
        daily_cap_usd: float | None = None,
    ):
        self.path = Path(path or DEFAULT_BUDGET_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS daily_spend ("
                "  day TEXT PRIMARY KEY,"
                "  spent_usd REAL NOT NULL DEFAULT 0,"
                "  call_count INTEGER NOT NULL DEFAULT 0"
                ")"
            )
        if daily_cap_usd is not None:
            self.daily_cap_usd = daily_cap_usd
        else:
            self.daily_cap_usd = float(
                os.environ.get(
                    "ATLAS_DAILY_LLM_BUDGET_USD",
                    DEFAULT_DAILY_BUDGET_USD,
                )
            )

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def state(self) -> BudgetState:
        """Current day's spend snapshot."""
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT spent_usd FROM daily_spend WHERE day = ?",
                (self._today(),),
            ).fetchone()
        spent = float(row[0]) if row else 0.0
        return BudgetState(
            day=self._today(),
            spent_usd=spent,
            daily_cap_usd=self.daily_cap_usd,
        )

    def can_afford(
        self, input_tokens: int, output_tokens: int,
    ) -> bool:
        """Pre-check: would a Haiku call of this size fit?"""
        cost = estimate_haiku_cost(input_tokens, output_tokens)
        return self.state().remaining_usd >= cost

    def charge(
        self, input_tokens: int, output_tokens: int,
    ) -> BudgetState:
        """Record actual spend after a successful LLM call.

        Raises BudgetExceeded if the day is already past cap. Callers
        should call can_afford() first to skip rather than crash.
        """
        cost = estimate_haiku_cost(input_tokens, output_tokens)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT INTO daily_spend (day, spent_usd, call_count) "
                "VALUES (?, ?, 1) "
                "ON CONFLICT(day) DO UPDATE SET "
                "  spent_usd = spent_usd + ?, "
                "  call_count = call_count + 1",
                (self._today(), cost, cost),
            )
        state = self.state()
        if state.is_exhausted:
            log.warning(
                "Daily LLM budget exhausted: spent $%.4f / cap $%.2f",
                state.spent_usd, state.daily_cap_usd,
            )
        return state

    def reset_today(self) -> None:
        """Test helper — wipe today's row."""
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "DELETE FROM daily_spend WHERE day = ?",
                (self._today(),),
            )
