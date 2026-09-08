"""agents/evidence_store.py — Append-only persistence + query for Evidence (v2.0.34aq).

The store NEVER mutates an existing record. "Updating" an evidence's status means writing
a NEW row with the same id but a later `recorded_at` and an appended `history` (immutability,
point 10 of the design). Reads return the LATEST row for an id; `history()` returns all rows
for an id in chronological order so audits/migrations can see the full progression.

Backed by `database.AgentDB` (sqlite, WAL). Producers call `store.record(ev)`; the lifecycle
calls `store.for_subject(...)` / `store.for_type(...)` to decide transitions.

Mock-first: an in-memory AgentDB (or a fake with the same `Evidence` table) works for tests.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from agents.evidence import Evidence, EvidenceStatus


class EvidenceStore:
    def __init__(self, db):
        """`db` is an `AgentDB` instance (has `_execute(sql, params, commit=...)` + `_lock`)."""
        self._db = db

    # ── Write (append-only) ──
    def record(self, ev: Evidence) -> Evidence:
        """Persist one evidence record. Idempotent on id (INSERT OR REPLACE keeps history
        in the row's `history` blob, which the caller extended via `ev.verify()`)."""
        d = ev.to_dict()
        self._db._execute(
            """INSERT OR REPLACE INTO evidence (
                id, source, evidence_type, subject_type, subject_id, external_id,
                parent_evidence_id, observed_at, recorded_at, status, verification_method,
                verification_level, amount, currency, gross_amount, fees, gas, tax_expense,
                other_expenses, source_reference, raw_reference, metadata, provenance, history
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                d["id"], d["source"], d["evidence_type"], d["subject_type"], d["subject_id"],
                d["external_id"], d["parent_evidence_id"], d["observed_at"], d["recorded_at"],
                d["status"], d["verification_method"], d["verification_level"], d["amount"],
                d["currency"], d["gross_amount"], d["fees"], d["gas"], d["tax_expense"],
                d["other_expenses"], d["source_reference"], d["raw_reference"],
                json.dumps(d["metadata"]), json.dumps(d["provenance"]), json.dumps(d["history"]),
            ),
            commit=True,
        )
        return ev

    def record_many(self, evs: List[Evidence]) -> None:
        for ev in evs:
            self.record(ev)

    # ── Read ──
    def get(self, evidence_id: str) -> Optional[Evidence]:
        row = self._db._execute(
            "SELECT * FROM evidence WHERE id = ? ORDER BY recorded_at DESC LIMIT 1",
            (evidence_id,),
        ).fetchone()
        return self._row_to_evidence(row) if row else None

    def for_subject(self, subject_type: str, subject_id: str) -> List[Evidence]:
        rows = self._db._execute(
            "SELECT * FROM evidence WHERE subject_type = ? AND subject_id = ? "
            "ORDER BY recorded_at ASC",
            (subject_type, subject_id),
        ).fetchall()
        return [self._row_to_evidence(r) for r in rows]

    def for_type(self, evidence_type: str, subject_type: str = None,
                 subject_id: str = None) -> List[Evidence]:
        sql = "SELECT * FROM evidence WHERE evidence_type = ?"
        params: List[Any] = [evidence_type]
        if subject_type is not None:
            sql += " AND subject_type = ?"; params.append(subject_type)
        if subject_id is not None:
            sql += " AND subject_id = ?"; params.append(subject_id)
        sql += " ORDER BY recorded_at ASC"
        return [self._row_to_evidence(r) for r in self._db._execute(sql, params).fetchall()]

    def by_status(self, status: EvidenceStatus) -> List[Evidence]:
        rows = self._db._execute(
            "SELECT * FROM evidence WHERE status = ? ORDER BY recorded_at ASC",
            (status.value,),
        ).fetchall()
        return [self._row_to_evidence(r) for r in rows]

    def children(self, parent_evidence_id: str) -> List[Evidence]:
        rows = self._db._execute(
            "SELECT * FROM evidence WHERE parent_evidence_id = ? ORDER BY recorded_at ASC",
            (parent_evidence_id,),
        ).fetchall()
        return [self._row_to_evidence(r) for r in rows]

    # ── Duplicate detection (content fingerprint) ──
    def find_duplicate(self, ev: Evidence) -> Optional[Evidence]:
        """Return an EXISTING record with the same content fingerprint (dup_key), if any.

        Distinct ids are preserved (no overwrite); this only flags that the same observation was
        already recorded, so callers can avoid double-counting. Returns the latest matching row.
        """
        dk = ev.dup_key()
        rows = self._db._execute(
            "SELECT * FROM evidence ORDER BY recorded_at ASC",
        ).fetchall()
        for r in rows:
            cand = self._row_to_evidence(r)
            if cand.id != ev.id and cand.dup_key() == dk:
                return cand
        return None

    def is_duplicate(self, ev: Evidence) -> bool:
        return self.find_duplicate(ev) is not None

    def confidence_for(self, ev: Evidence) -> float:
        from agents.evidence_policy import confidence_for as _cf
        return _cf(ev)

    def history(self, evidence_id: str) -> List[Evidence]:
        """All rows ever written for an id, oldest first (immutability audit trail)."""
        rows = self._db._execute(
            "SELECT * FROM evidence WHERE id = ? ORDER BY recorded_at ASC",
            (evidence_id,),
        ).fetchall()
        return [self._row_to_evidence(r) for r in rows]

    # ── Helpers ──
    @staticmethod
    def _row_to_evidence(row) -> Evidence:
        d = dict(row)
        d["metadata"] = json.loads(d.get("metadata") or "{}")
        d["provenance"] = json.loads(d.get("provenance") or "{}")
        d["history"] = json.loads(d.get("history") or "[]")
        return Evidence.from_dict(d)
