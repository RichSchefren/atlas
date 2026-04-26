"""Atlas continuous-ingestion daemon entry points.

Two long-running processes Atlas ships as launchd plists:

  com.atlas.ingestion   — runs IngestionOrchestrator every 30 minutes
  com.atlas.api-server  — runs the FastAPI server on port 9879

Both use rolling logs at ~/.atlas/health/ for audit + debugging.

Spec: PHASE-5-AND-BEYOND.md § 1.1
"""

from atlas_core.daemon.cycle import run_ingestion_cycle
from atlas_core.daemon.health import HealthLogger

__all__ = ["run_ingestion_cycle", "HealthLogger"]
