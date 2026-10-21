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


# ── ARCH-ENG-163 — the contract was not binding on the real filesystem ─────────
#
# `validate_store_paths` checks the paths it is HANDED, at the moment it is
# handed them. It cannot see a store that is never passed in, a shadow copy in a
# wrong directory, or two stores whose schemas overlap. Measured on this
# repository before the fix:
#
#   * 7 declared authorities, but only 4 passed to validate_store_paths at
#     startup — agent.db, dual_brain.db and goals.db were outside the check.
#   * agent.db and earning.db shared 15 real tables, INCLUDING `evidence`.
#     Two tables with the same name under different authorities is precisely
#     the ambiguity `state_reconciliation` exists to paper over.
#   * `decisions` existed in THREE declared stores.
#   * 3 undeclared .db files (agents/job_search.db, agents/summarizer.db,
#     agents/services/summarizer.db) plus 4 shadow COPIES of declared
#     authorities under agents/ (earning.db, earning_memory.db, dual_brain.db,
#     autonomous_runs.db) left over from the pre-migration layout. A relative
#     path bug would silently open a shadow copy and write real records into a
#     file no report reads.

# Tables SQLite creates implicitly; they say nothing about domain ownership.
_IMPLICIT_TABLES = frozenset({"sqlite_sequence"})


def _declared_filenames() -> frozenset:
    return frozenset(s.filename for s in STORE_AUTHORITIES)


def discover_undeclared_stores(base_dir: str | Path) -> dict:
    """`.db` files under `base_dir` that no StoreAuthority claims.

    Includes shadow copies: a declared filename sitting anywhere other than
    `base_dir` is exactly the dangerous case, because it looks legitimate.
    """
    root = Path(base_dir).expanduser().resolve(strict=False)
    if not root.is_dir():
        return {}
    declared = _declared_filenames()
    found: dict = {}
    for db in sorted(root.rglob("*.db")):
        # Backup/quarantine directories are not the running tree.
        if any(part in _BACKUP_DIR_NAMES for part in db.parts):
            continue
        if db.name in declared and db.parent == root:
            continue                      # the legitimate one
        rel = str(db.relative_to(root))
        found[rel] = "shadow copy of a declared store" if db.name in declared \
            else "undeclared store"
    return found


def _tables_of(db_path: Path) -> set:
    try:
        import sqlite3
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        finally:
            conn.close()
    except Exception:
        return set()
    return {r[0] for r in rows} - _IMPLICIT_TABLES


def _row_count(db_path: Path, table: str) -> int:
    try:
        import sqlite3
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        finally:
            conn.close()
    except Exception:
        return 0


# Directories that hold backups/quarantine rather than the running tree. An
# operator may legitimately keep archived databases on disk; they are not part
# of the application and must not be reported as stray stores.
_BACKUP_DIR_NAMES = frozenset({
    ".mrbot_backups", "code_patch_backups", "backups", ".venv",
    "__pycache__", ".pytest_cache", ".hermes",
})


def find_schema_overlaps(base_dir: str | Path) -> dict:
    """Declared stores that share a real table name, split by severity.

    ARCH-ENG-163. A shared table NAME is not automatically a defect, and a guard
    that treats every one as a defect is a false-alarm machine — which is how a
    control loses its value. So this distinguishes two cases:

      "conflicts"  — the table is POPULATED in more than one store. Two
                     authorities genuinely disagree about where live rows are,
                     and a reader that picks the wrong one silently sees an
                     empty table. This is a defect.

      "structural" — the table exists in more than one store but is EMPTY
                     everywhere. Both stores are created by the same `AgentDB`
                     DDL, so this is a schema artifact, not a data conflict.
                     Reporting it as a defect would be noise.

    Measured on this repository before the fix: 14 structural overlaps (all
    empty) and ONE data conflict — a VERIFIED, L5 `onchain_balance_delta` row
    sitting in `agent.db` while the earning path reads `evidence` from
    `earning.db`, where that table has 0 rows. That row is invisible to revenue
    verification. Nothing moved it: operator data is not this code's to relocate.
    """
    root = Path(base_dir).expanduser().resolve(strict=False)
    schemas: dict = {}
    for store in STORE_AUTHORITIES:
        path = root / store.filename
        if path.is_file() and path.stat().st_size > 0:
            tables = _tables_of(path)
            if tables:
                schemas[store.name] = (path, tables)

    conflicts: dict = {}
    structural: dict = {}
    names = list(schemas)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            left_name, right_name = names[i], names[j]
            left_path, left_tables = schemas[left_name]
            right_path, right_tables = schemas[right_name]
            shared = left_tables & right_tables
            if not shared:
                continue
            pair = f"{left_name}<->{right_name}"
            populated = sorted(
                t for t in shared
                if _row_count(left_path, t) > 0 and _row_count(right_path, t) > 0
            )
            stranded = sorted(
                f"{t} ({left_name}={_row_count(left_path, t)}, "
                f"{right_name}={_row_count(right_path, t)})"
                for t in shared
                if (_row_count(left_path, t) > 0) != (_row_count(right_path, t) > 0)
            )
            if populated:
                conflicts[pair] = populated
            elif stranded:
                # Data sits in only one of two stores that both claim the table.
                conflicts[pair] = stranded
            else:
                structural[pair] = sorted(shared)
    return {"conflicts": conflicts, "structural": structural}


def audit_stores(base_dir: str | Path) -> dict:
    """Full read-only audit. Returns a report; raises nothing.

    Intended for startup validation and diagnostics. It is deliberately a REPORT
    and not a gate: refusing to start because a stale file exists somewhere
    would be worse than reporting it, and the operator may legitimately keep
    backups in the tree.
    """
    root = Path(base_dir).expanduser().resolve(strict=False)
    undeclared = discover_undeclared_stores(root)
    overlaps = find_schema_overlaps(root)
    return {
        "base_dir": str(root),
        "declared": [s.name for s in STORE_AUTHORITIES],
        "undeclared_files": undeclared,
        "data_conflicts": overlaps["conflicts"],
        "schema_overlaps": overlaps["structural"],
        "clean": not undeclared and not overlaps["conflicts"],
    }


__all__ = [
    "StoreAuthority",
    "STORE_AUTHORITIES",
    "authority_for",
    "validate_store_paths",
    "discover_undeclared_stores",
    "find_schema_overlaps",
    "audit_stores",
]
