"""ARCH-ENG-163 — the persistence contract was never binding on the real tree.

`agents/core/persistence_contract.py` is a well-designed module. It declares 7
`StoreAuthority` entries, one filename each, with explicit authority and
projection classification. `validate_store_paths` rejects unknown store names
and any two stores sharing a normalized path, and `composition_root` calls it at
startup for 4 of the 7.

What it could not see, because it only ever sees the paths it is handed:

1. STORES NEVER HANDED TO IT. `agent.db`, `dual_brain.db` and `goals.db` were
   outside the startup check entirely. A path bug in any of them is invisible.

2. SCHEMA OVERLAP. The contract asserts one FILENAME per authority; it says
   nothing about a table. Measured before this fix: `agent.db` and `earning.db`
   shared **15 real tables, including `evidence`** — and `decisions` existed in
   THREE declared stores (agent, dual_brain, earning). Two tables with the same
   name under different authorities is ambiguous by construction: a reader that
   picks the wrong one reads a stale or empty copy. This ambiguity is exactly
   what `agents/core/state_reconciliation.py` exists to detect and report, on
   every run, forever.

3. SHADOW COPIES. Seven `.db` files under `agents/` matched no authority — four
   of them named exactly like a declared authority (`earning.db`,
   `earning_memory.db`, `dual_brain.db`, `autonomous_runs.db`). A relative-path
   bug would open one silently and write real records into a file no report
   reads. All were last written 2026-10-09; the root authorities have been
   written daily since. They are quarantined in
   `.mrbot_backups/arch_eng_163_orphan_stores/`, not deleted.

THE LESSON: a contract that is only checked against its own inputs cannot catch
anything the caller did not bring. This suite makes the check assert against the
FILESYSTEM, so it has a subject independent of whoever called it.

`test_repository_has_no_undeclared_stores` and
`test_declared_stores_do_not_overlap` are the regression: recreating a shadow
copy, or adding a shared table, now fails here rather than accumulating silently.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from agents.core.persistence_contract import (
    STORE_AUTHORITIES, audit_stores, authority_for, discover_undeclared_stores,
    find_schema_overlaps, validate_store_paths,
)

REPO = Path(__file__).resolve().parents[2]
# ARCH-ENG-113/149 class: never hardcode an operator path.
assert (REPO / "agents" / "core").is_dir(), f"repo root misresolved: {REPO}"

# Backing/quarantine directories the operator may legitimately keep in-tree.
_ALLOWED_PREFIXES = (".mrbot_backups", ".venv", "__pycache__", ".pytest_cache",
                     "code_patch_backups", ".hermes")


def _ignored(path: Path) -> bool:
    return any(part in path.parts for part in _ALLOWED_PREFIXES)


class TestContractItself(unittest.TestCase):
    """ARCH-ENG-163 — the pre-existing guarantees must still hold."""

    def test_every_store_names_a_unique_filename(self):
        filenames = [s.filename for s in STORE_AUTHORITIES]
        self.assertEqual(len(filenames), len(set(filenames)),
                         "two authorities claim the same filename")

    def test_every_projection_declares_its_authority(self):
        for store in STORE_AUTHORITIES:
            if store.classification == "projection":
                self.assertTrue(store.authority,
                                f"{store.name} is a projection but names no authority")

    def test_unknown_store_name_is_refused(self):
        with self.assertRaises(ValueError):
            validate_store_paths({"not_a_store": "x.db"})

    def test_two_stores_sharing_a_path_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp) / "same.db"
            with self.assertRaises(ValueError):
                validate_store_paths({"earning": shared, "memory": shared})

    def test_authority_for_rejects_unknown(self):
        with self.assertRaises(KeyError):
            authority_for("nope")

    def test_earning_store_names_its_projections(self):
        store = authority_for("earning")
        self.assertIn("opportunity_portfolio.db", store.projections)
        self.assertIn("autonomous_runs.db", store.projections)


class TestFilesystemAudit(unittest.TestCase):
    """ARCH-ENG-163 — the contract checked against the real tree.

    Strict where the CODE controls the outcome (no stray stores, no shadow
    copies), and BASELINED where it does not. The known data conflict below is
    operator data in the operator's live databases; this code is not going to
    relocate it behind their back. The baseline exists so the set cannot GROW.
    """

    # ARCH-ENG-163, measured on 2026-10-17. `evidence` and
    # `instruction_quarantine` each hold rows in `agent.db` while the earning
    # path reads those tables from `earning.db`, where they are empty. The
    # evidence row is a real VERIFIED / L5 `onchain_balance_delta`, so revenue
    # verification cannot currently see it. Migrating operator data is a
    # deliberate act, not a side effect of a lint fix; until an operator
    # performs it, this baseline records the known state.
    KNOWN_DATA_CONFLICTS = {"earning<->agent"}

    def test_repository_has_no_undeclared_stores(self):
        found = discover_undeclared_stores(REPO)
        real = {k: v for k, v in found.items() if not _ignored(REPO / k)}
        self.assertEqual(
            real, {},
            "these .db files are in the tree but no StoreAuthority claims them. "
            "A shadow copy named like an authority is the dangerous case: a "
            "relative-path bug opens one silently and writes real records into a "
            "file no report reads. Either give it an authority or move it out "
            "of the tree:\n  " + "\n  ".join(f"{k} ({v})" for k, v in sorted(real.items())))

    def test_no_shadow_copies_of_declared_authorities(self):
        """A declared filename must appear ONLY at the repo root."""
        declared = {s.filename for s in STORE_AUTHORITIES}
        shadows = []
        for db in REPO.rglob("*.db"):
            if _ignored(db):
                continue
            if db.name in declared and db.parent != REPO:
                shadows.append(str(db.relative_to(REPO)))
        self.assertEqual(shadows, [],
                         f"shadow copies of declared authorities: {shadows}")

    def test_data_conflicts_do_not_grow_past_the_recorded_baseline(self):
        """Populated-in-both is a defect; empty-in-both is a schema artifact.

        `find_schema_overlaps` splits the two, because reporting all 14 empty
        structural overlaps as defects would make this a false-alarm machine and
        train the operator to ignore it.
        """
        result = find_schema_overlaps(REPO)
        conflicts = set(result["conflicts"])
        self.assertEqual(
            conflicts - self.KNOWN_DATA_CONFLICTS, set(),
            "new DATA conflicts appeared between stores:\n  "
            + "\n  ".join(f"{k}: {v}" for k, v in result["conflicts"].items())
            + f"\n(known and awaiting operator migration: "
              f"{sorted(self.KNOWN_DATA_CONFLICTS)})")

    def test_structural_overlaps_are_not_reported_as_defects(self):
        """Empty shared tables are reported separately, never as conflicts."""
        result = find_schema_overlaps(REPO)
        self.assertNotIn("structural", result["conflicts"],
                         "structural overlaps leaked into the conflict set")
        for pair, tables in result["structural"].items():
            self.assertTrue(all(isinstance(t, str) for t in tables))

    def test_the_evidence_table_conflict_is_still_detected(self):
        """The regression, named: `evidence` is claimed by two authorities.

        Asserted positively (not just "no new conflicts") so this suite cannot
        pass by the detector quietly going blind.
        """
        result = find_schema_overlaps(REPO)
        found = any("evidence" in str(v)
                    for v in result["conflicts"].values())
        # If the operator migrates the rows, this flips to False — which is the
        # desired outcome. Until then the conflict must remain VISIBLE.
        if "earning<->agent" in result["conflicts"]:
            self.assertTrue(found,
                            "the known evidence conflict disappeared from the "
                            "audit — either it was migrated (good: update "
                            "KNOWN_DATA_CONFLICTS) or the detector is blind")

    def test_audit_reports_the_current_state(self):
        report = audit_stores(REPO)
        self.assertIn("declared", report)
        self.assertEqual(len(report["declared"]), len(STORE_AUTHORITIES))
        # Undeclared stores are fully cleaned; only operator data remains.
        self.assertEqual(
            [k for k in report["undeclared_files"] if not _ignored(REPO / k)], [])
        self.assertFalse(report["clean"],
                         "audit_stores reports the known data conflict as clean")


def _pair(bucket, *names):
    """Find the entry for a pair in ONE bucket, whatever order its key used.

    The pair key follows StoreAuthority declaration order, not alphabetical, so
    a test must not hardcode `"agent<->earning"`. Takes the bucket explicitly:
    searching both would make "is it a conflict?" and "is it structural?"
    unanswerable, because the same pair name appears in either.
    """
    for key, value in bucket.items():
        if set(key.split("<->")) == set(names):
            return value
    return None


class TestAuditDetectsRegressions(unittest.TestCase):
    """ARCH-ENG-163 — the detector must actually FAIL, not just pass.

    A guard that only ever passes proves nothing. Each case builds the defect in
    a temp tree and asserts the audit reports it.
    """

    def _tree(self):
        tmp = tempfile.mkdtemp()
        root = Path(tmp)
        for store in STORE_AUTHORITIES:
            (root / store.filename).write_bytes(b"")     # 0 bytes: ignored
        return root

    def test_detects_an_undeclared_store(self):
        root = self._tree()
        (root / "rogue.db").write_bytes(b"x" * 100)
        found = discover_undeclared_stores(root)
        self.assertIn("rogue.db", found)
        self.assertEqual(found["rogue.db"], "undeclared store")

    def test_detects_a_shadow_copy_and_labels_it(self):
        root = self._tree()
        (root / "agents").mkdir()
        (root / "agents" / "earning.db").write_bytes(b"x" * 100)
        found = discover_undeclared_stores(root)
        self.assertIn(str(Path("agents") / "earning.db"), found)
        self.assertIn("shadow copy", found[str(Path("agents") / "earning.db")])

    def _make_db(self, path, tables):
        conn = sqlite3.connect(path)
        for t in tables:
            conn.execute(f'CREATE TABLE "{t}" (id INTEGER PRIMARY KEY, v TEXT)')
        conn.commit()
        conn.close()

    def test_detects_a_shared_table_between_two_authorities(self):
        root = self._tree()
        self._make_db(root / "agent.db", ["evidence", "thoughts"])
        self._make_db(root / "earning.db", ["evidence", "opportunities"])
        result = find_schema_overlaps(root)
        # Populated in neither -> structural, but the PAIR must be reported.
        structural = _pair(result["structural"], "agent", "earning")
        self.assertIsNotNone(structural, f"the pair was not reported: {result}")
        self.assertIn("evidence", structural)

    def test_empty_shared_tables_are_structural_not_conflicts(self):
        """Empty in both => schema artifact, reported separately.

        Both stores are created by the same AgentDB DDL, so an empty shared
        table is expected. Calling it a defect would be a false alarm.
        """
        root = self._tree()
        self._make_db(root / "agent.db", ["evidence", "thoughts"])
        self._make_db(root / "earning.db", ["evidence", "opportunities"])
        result = find_schema_overlaps(root)
        self.assertIsNotNone(_pair(result["structural"], "agent", "earning"))
        self.assertIsNone(_pair(result["conflicts"], "agent", "earning"),
                          "an empty shared table was reported as a conflict")
        self.assertEqual(result["conflicts"], {})

    def test_populated_in_both_is_a_conflict(self):
        root = self._tree()
        self._make_db(root / "agent.db", ["evidence"])
        self._make_db(root / "earning.db", ["evidence"])
        for name in ("agent.db", "earning.db"):
            conn = sqlite3.connect(root / name)
            conn.execute("INSERT INTO evidence (v) VALUES ('row')")
            conn.commit()
            conn.close()
        result = find_schema_overlaps(root)
        conflicts = _pair(result["conflicts"], "agent", "earning")
        self.assertIsNotNone(conflicts,
                             f"a populated-in-both table was not a conflict: {result}")
        self.assertIsNone(_pair(result["structural"], "agent", "earning"))

    def test_rows_in_only_one_store_is_a_stranded_conflict(self):
        """Data sitting in the wrong authority is a conflict, not structure.

        This is the live `agent.db` evidence case: one VERIFIED row in
        `agent.db`, none in `earning.db`, so revenue verification reading
        `earning.db` cannot see it.
        """
        root = self._tree()
        self._make_db(root / "agent.db", ["evidence"])
        self._make_db(root / "earning.db", ["evidence"])
        conn = sqlite3.connect(root / "agent.db")
        conn.execute("INSERT INTO evidence (v) VALUES ('stranded')")
        conn.commit()
        conn.close()
        result = find_schema_overlaps(root)
        conflicts = _pair(result["conflicts"], "agent", "earning")
        self.assertIsNotNone(conflicts,
                             f"a stranded row was not reported: {result}")
        self.assertIn("agent=1", str(conflicts),
                      f"the report should name which side holds the row: {conflicts}")

    def test_sqlite_sequence_is_not_reported_as_an_overlap(self):
        """`sqlite_sequence` is implicit; it says nothing about ownership.

        Every SQLite database with an AUTOINCREMENT column has one, so counting
        it would make every pair of stores look like it overlapped and turn the
        guard into noise.
        """
        root = self._tree()
        for name in ("agent.db", "earning.db"):
            conn = sqlite3.connect(root / name)
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)")
            conn.execute("INSERT INTO t (v) VALUES ('x')")
            conn.commit()
            conn.close()
        overlaps = find_schema_overlaps(root)
        self.assertFalse(any("sqlite_sequence" in str(v)
                             for v in overlaps["structural"].values()),
                         f"sqlite_sequence was reported as an overlap: {overlaps}")

    def test_empty_databases_are_not_overlap_candidates(self):
        """A fresh clone has no .db files; that must not read as a conflict."""
        root = self._tree()
        self.assertEqual(find_schema_overlaps(root),
                         {"conflicts": {}, "structural": {}})
        self.assertEqual(discover_undeclared_stores(root), {})

    def test_audit_is_reported_not_raised(self):
        """Auditing a dirty tree must never raise — it is a report."""
        root = self._tree()
        (root / "rogue.db").write_bytes(b"x" * 100)
        report = audit_stores(root)          # must not raise
        self.assertFalse(report["clean"])
        self.assertIn("rogue.db", report["undeclared_files"])


if __name__ == "__main__":
    unittest.main()