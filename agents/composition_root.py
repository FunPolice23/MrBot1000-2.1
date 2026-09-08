"""
agents/composition_root.py — Unified application composition root (v2.1 Phase 3).

Builds the canonical shared instances that must be ONE per process so lifecycle
authority and autonomous-run history are consistent across the GUI, manager,
pipeline, portfolio, and loop:

    - one OpportunityPortfolio (persistent SQLite work queue)
    - one AutonomousRunStore (durable autonomous-run ledger)
    - one EarningPipeline (owns the authoritative OpportunityLifecycleTracker,
      wired to the portfolio + run store)

Injecting these same objects everywhere removes the "two parallel lifecycle
systems" hazard: the pipeline's lifecycle is the authority, the portfolio is a
query/queue projection, and the run store is the durable loop ledger.

``build_composition_root(...)`` is a plain factory (no Qt, no network) so it is
testable headlessly and safe to call at application startup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class CompositionRoot:
    """The shared, canonical instances for one application process."""
    pipeline: Any
    portfolio: Any
    run_store: Any
    lifecycle: Any
    base_dir: str

    def close(self) -> None:
        """Release resources owned by the root (idempotent)."""
        close_pipe = getattr(self.pipeline, "close", None)
        if callable(close_pipe):
            try:
                close_pipe()
            except Exception:
                pass


def build_composition_root(
        base_dir: Optional[str] = None,
        db_path: Optional[str] = None,
        memory_path: Optional[str] = None,
        portfolio_path: Optional[str] = None,
        run_store_path: Optional[str] = None,
        log_fn: Optional[Callable[[str], None]] = None) -> CompositionRoot:
    """Construct one canonical set of shared pipeline/portfolio/run-store objects.

    Paths default under ``base_dir`` (project root unless overridden). Any
    already-existing store is recovered (incomplete runs marked interrupted),
    so a restart leaves a consistent ledger.
    """
    base_dir = base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = db_path or os.path.join(base_dir, "earning.db")
    memory_path = memory_path or os.path.join(base_dir, "earning_memory.db")
    portfolio_path = portfolio_path or os.path.join(base_dir, "opportunity_portfolio.db")
    run_store_path = run_store_path or os.path.join(base_dir, "autonomous_runs.db")

    from agents.opportunity_portfolio import OpportunityPortfolio
    from agents.autonomous_run_store import AutonomousRunStore

    portfolio = OpportunityPortfolio(portfolio_path)
    run_store = AutonomousRunStore(run_store_path)
    # Restart safety: any run left mid-flight by a crash becomes FAILED.
    run_store.recover_incomplete()

    from earning_pipeline import EarningPipeline
    pipeline = EarningPipeline(
        db_path=db_path,
        memory_path=memory_path,
        log_fn=log_fn or print,
        portfolio=portfolio,
        run_store=run_store,
    )
    return CompositionRoot(
        pipeline=pipeline,
        portfolio=portfolio,
        run_store=run_store,
        lifecycle=pipeline.lifecycle,
        base_dir=base_dir,
    )


__all__ = ["CompositionRoot", "build_composition_root"]
