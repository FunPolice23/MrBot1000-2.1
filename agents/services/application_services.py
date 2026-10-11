"""Non-Qt application service factories used by the desktop composition root."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class EarningServices:
    """Shared earning services owned by one application process."""

    root: Any

    @property
    def pipeline(self) -> Any:
        return self.root.pipeline

    @property
    def portfolio(self) -> Any:
        return self.root.portfolio

    @property
    def run_store(self) -> Any:
        return self.root.run_store

    @property
    def code_patch_service(self) -> Any:
        return getattr(self.root, "code_patch_service", None)

    def close(self) -> None:
        self.root.close()


def build_earning_services(
    root_folder: str,
    *,
    portfolio_path: Optional[str] = None,
    log_fn: Optional[Callable[[str], None]] = None,
) -> EarningServices:
    """Build the canonical earning services without importing Qt."""
    from agents.core.composition_root import build_composition_root
    from agents.earning.opportunity_portfolio import canonical_portfolio_path

    root = build_composition_root(
        db_path=os.path.join(root_folder, "earning.db"),
        portfolio_path=portfolio_path or canonical_portfolio_path(),
        log_fn=log_fn,
    )
    return EarningServices(root)


__all__ = ["EarningServices", "build_earning_services"]
