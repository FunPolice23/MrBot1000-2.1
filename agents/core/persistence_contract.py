"""Canonical ownership contract for MrBot1000's SQLite stores.

The application intentionally keeps some domains in separate databases, but
their ownership must remain explicit.  This module is dependency-light so
startup code and tests can validate store paths before opening connections.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class StoreAuthority:
    """Authoritative persistence boundary for one domain."""

    name: str
    filename: str
    authority: str
    projections: tuple[str, ...] = ()
    classification: str = "authoritative"


STORE_AUTHORITIES: tuple[StoreAuthority, ...] = (
    StoreAuthority(
        "earning",
        "earning.db",
        "EarningPipeline lifecycle, evidence, and economic accounting",
        ("opportunity_portfolio.db", "autonomous_runs.db"),
    ),
    StoreAuthority(
        "memory",
        "earning_memory.db",
        "Opportunity learning memory and outcome history",
    ),
    StoreAuthority(
        "portfolio",
        "opportunity_portfolio.db",
        "Opportunity queue projection and work status",
        classification="projection",
    ),
    StoreAuthority(
        "autonomous_runs",
        "autonomous_runs.db",
        "Durable autonomous-run and idempotency ledger",
    ),
    StoreAuthority(
        "agent",
        "agent.db",
        "Agent thoughts, events, settings, instruction provenance, and evidence",
    ),
    StoreAuthority(
        "goals",
        "goals.db",
        "Goal subsystem state; not authoritative for earning lifecycle or accounting",
        classification="subsystem",
    ),
    StoreAuthority(
        "dual_brain",
        "dual_brain.db",
        "Dual-brain/UI runtime state and cached coordination data",
        classification="projection",
    ),
)


def validate_store_paths(paths: Mapping[str, str | Path]) -> None:
    """Validate configured store paths before opening any database.

    Every configured store name must be known and no two authorities may point
    at the same normalized path.  Shared paths would destroy the intended
    transaction and backup boundaries.
    """
    known = {store.name for store in STORE_AUTHORITIES}
    unknown = sorted(set(paths) - known)
    if unknown:
        raise ValueError(f"Unknown persistence store(s): {', '.join(unknown)}")

    normalized: dict[Path, str] = {}
    for name, raw_path in paths.items():
        path = Path(raw_path).expanduser().resolve(strict=False)
        previous = normalized.get(path)
        if previous is not None:
            raise ValueError(
                f"Persistence stores {previous!r} and {name!r} share path {path}"
            )
        normalized[path] = name


def authority_for(name: str) -> StoreAuthority:
    """Return the contract entry for a store name."""
    for store in STORE_AUTHORITIES:
        if store.name == name:
            return store
    raise KeyError(f"Unknown persistence store: {name}")


__all__ = [
    "StoreAuthority",
    "STORE_AUTHORITIES",
    "authority_for",
    "validate_store_paths",
]
