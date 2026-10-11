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
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class CompositionRoot:
    """The shared, canonical instances for one application process."""
    pipeline: Any
    portfolio: Any
    run_store: Any
    lifecycle: Any
    base_dir: str
    reconciliation_report: Any = None
    log_fn: Optional[Callable[[str], None]] = None
    code_patch_service: Any = None

    def close(self) -> None:
        """Release resources owned by the root (idempotent)."""
        close_pipe = getattr(self.pipeline, "close", None)
        if callable(close_pipe):
            try:
                close_pipe()
            except Exception as exc:
                message = f"Composition root shutdown failed: {exc}"
                if self.log_fn is not None:
                    self.log_fn(message)
                logger.exception(message)


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
    base_dir = base_dir or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    db_path = db_path or os.path.join(base_dir, "earning.db")
    memory_path = memory_path or os.path.join(base_dir, "earning_memory.db")
    portfolio_path = portfolio_path or os.path.join(base_dir, "opportunity_portfolio.db")
    run_store_path = run_store_path or os.path.join(base_dir, "autonomous_runs.db")

    from agents.earning.opportunity_portfolio import OpportunityPortfolio
    from agents.services.autonomous_run_store import AutonomousRunStore
    from agents.core.persistence_contract import validate_store_paths

    validate_store_paths({
        "earning": db_path,
        "memory": memory_path,
        "portfolio": portfolio_path,
        "autonomous_runs": run_store_path,
    })

    portfolio = OpportunityPortfolio(portfolio_path)
    run_store = AutonomousRunStore(run_store_path)
    # Restart safety: any run left mid-flight by a crash becomes FAILED.
    run_store.recover_incomplete()

    from app.earning_pipeline import EarningPipeline
    pipeline = EarningPipeline(
        db_path=db_path,
        memory_path=memory_path,
        log_fn=log_fn or print,
        portfolio=portfolio,
        run_store=run_store,
    )
    from agents.core.state_reconciliation import reconcile_many
    opportunity_ids = {
        state.get("opportunity_id")
        for state in pipeline.lifecycle.get_all_states()
        if state.get("opportunity_id")
    }
    opportunity_ids.update(
        entry.opportunity_id for entry in portfolio.list_all()
        if getattr(entry, "opportunity_id", None)
    )
    opportunity_ids.update(pipeline.evidence_store.subject_ids("opportunity"))
    reconciliation_report = reconcile_many(
        opportunity_ids,
        lifecycle=pipeline.lifecycle,
        portfolio=portfolio,
        evidence_store=pipeline.evidence_store,
        accounting=pipeline.accounting,
        run_store=run_store,
    )
    emit_log = log_fn or print
    for conflict in reconciliation_report.conflicts:
        emit_log(
            f"Reconciliation conflict [{conflict.severity}] "
            f"{conflict.opportunity_id}: {conflict.message}"
        )

    # Self-improvement is an optional, human-review-gated capability. When the
    # feature flag is off, no CodePatchService is built and nothing can propose
    # or apply a patch — the capability is simply absent.
    code_patch_service = None
    try:
        from agents.core.feature_flags import feature_enabled
        if feature_enabled("self_improvement"):
            from agents.safety.approval import HumanApprovalQueue
            from agents.services.code_patch_service import CodePatchService
            code_patch_service = CodePatchService(
                approval_queue=HumanApprovalQueue.instance(),
                root_dir=base_dir,
            )
    except Exception as exc:  # pragma: no cover - never block startup
        emit_log(f"Self-improvement service unavailable: {exc}")

    return CompositionRoot(
        pipeline=pipeline,
        portfolio=portfolio,
        run_store=run_store,
        lifecycle=pipeline.lifecycle,
        base_dir=base_dir,
        reconciliation_report=reconciliation_report,
        log_fn=log_fn,
        code_patch_service=code_patch_service,
    )

__all__ = ["CompositionRoot", "build_composition_root"]
