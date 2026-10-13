"""tests/test_autonomous_run_store.py — Durable autonomous-run ledger (v2.1 Phase 3).

Offline: uses real SQLite temp files; no network/model/Qt required.
"""

import os
import tempfile
import unittest

from agents.services.autonomous_run_store import AutonomousRunStore
from agents.services.autonomous_loop import AutonomousLoop, AutonomousResult, StageResult, StageStatus
from agents.core.composition_root import CompositionRoot, build_composition_root


class _FakeFacts:
    opportunity_id = "opp-1"


def _sample_result(opportunity_id="opp-1", decision="completed_unpaid",
                   success=True, paid=False):
    result = AutonomousResult(
        opportunity_id=opportunity_id,
        success=success,
        paid=paid,
        payment_amount=12.0 if paid else 0.0,
        decision=decision,
        decision_reason="stages completed",
        duration_s=1.0,
        explanation="Selected because: meets minimum criteria",
    )
    result.stages = [
        StageResult(stage="discovered", status=StageStatus.COMPLETED,
                    opportunity_id=opportunity_id, duration_s=0.1,
                    data={"found": True}),
        StageResult(stage="evaluate", status=StageStatus.COMPLETED,
                    opportunity_id=opportunity_id, duration_s=0.2,
                    data={"verdict": "attractive"}),
    ]
    return result


class TestRunStorePersistence(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="hermes-runstore-")
        self._path = os.path.join(self._dir, "runs.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_save_and_load_run(self):
        store = AutonomousRunStore(self._path)
        run_id = store.save_run(_sample_result(), "opp-1")
        self.assertEqual(store.count(), 1)
        loaded = store.get_run(run_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["opportunity_id"], "opp-1")
        self.assertEqual(loaded["decision"], "completed_unpaid")
        self.assertEqual(len(loaded["stages"]), 2)
        self.assertEqual(loaded["success"], True)

    def test_survives_reopen(self):
        store = AutonomousRunStore(self._path)
        store.save_run(_sample_result(), "opp-1")
        # Reopen the same file (simulates restart).
        store2 = AutonomousRunStore(self._path)
        self.assertEqual(store2.count(), 1)

    def test_stages_persisted_separately(self):
        store = AutonomousRunStore(self._path)
        store.save_run(_sample_result(), "opp-1")
        with store._conn() as conn:
            rows = conn.execute(
                "SELECT stage, status FROM autonomous_stage_runs "
                "WHERE run_id=? ORDER BY id", (store.list_runs()[0]["run_id"],)).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["stage"], "discovered")


class TestIdempotency(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="hermes-runstore-")
        self._path = os.path.join(self._dir, "runs.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_mark_and_check(self):
        store = AutonomousRunStore(self._path)
        self.assertFalse(store.is_idempotent("opportunity:opp-1"))
        store.mark_idempotent("opportunity:opp-1", "run-1", "opp-1")
        self.assertTrue(store.is_idempotent("opportunity:opp-1"))
        # Re-marking the same key is a no-op (no duplicate row).
        store.mark_idempotent("opportunity:opp-1", "run-2", "opp-1")
        with store._conn() as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM idempotency_keys WHERE key=?",
                ("opportunity:opp-1",)).fetchone()[0]
        self.assertEqual(n, 1)


class TestRestartRecovery(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="hermes-runstore-")
        self._path = os.path.join(self._dir, "runs.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_incomplete_run_marked_failed(self):
        store = AutonomousRunStore(self._path)
        store.save_run(_sample_result(), "opp-1")
        # Force one run into a mid-flight (non-terminal) state, as a crash would.
        store.update_run_status(store.list_runs()[0]["run_id"], "RUNNING")
        recovered = store.recover_incomplete()
        self.assertEqual(recovered, 1)
        loaded = store.get_run(store.list_runs()[0]["run_id"])
        self.assertEqual(loaded["status"], "FAILED")
        self.assertIn("interrupted by restart", loaded["decision_reason"])


def _submitting_stub(opp, draft):
    """A pipeline whose submit_gig_proposal succeeds (irreversible)."""
    class _R:
        success = True
        message = "submitted"
    return _R()


class TestLoopPersistence(unittest.TestCase):
    """A real AutonomousLoop run must persist when a run_store is injected."""

    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="hermes-runstore-")
        self._path = os.path.join(self._dir, "runs.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_loop_persists_run_to_store(self):
        from tests.earning.test_autonomous_loop import FakePipeline, FakeOpp
        store = AutonomousRunStore(self._path)
        pipeline = FakePipeline()
        loop = AutonomousLoop(pipeline, run_store=store)
        result = loop.run(FakeOpp(advertised_amount=50))
        self.assertEqual(store.count(), 1)
        loaded = store.get_run(store.list_runs()[0]["run_id"])
        self.assertEqual(loaded["opportunity_id"], "opp-1")
        self.assertEqual(loaded["decision"], result.decision)
        # No idempotency key: this pipeline has no submission path, so nothing
        # irreversible happened. The key is marked only when an irreversible
        # action actually goes out (ARCH-ENG-074) — marking it at finalize
        # made every completed run un-replayable and blocked the re-entry
        # _stage_deduplicate allows for failures, rejections and
        # await_approval pauses.
        self.assertFalse(store.is_idempotent("opportunity:opp-1"))
        self.assertEqual(loaded["status"], result.status)

    def test_loop_marks_idempotent_after_an_irreversible_submission(self):
        """A real submission must block a replay across a restart."""
        from tests.earning.test_autonomous_loop import FakePipeline, FakeOpp
        store = AutonomousRunStore(self._path)
        pipeline = FakePipeline()
        pipeline.submit_gig_proposal = _submitting_stub
        loop = AutonomousLoop(pipeline, run_store=store)
        loop.run(FakeOpp(advertised_amount=50, task_type="freelance"))
        self.assertTrue(store.is_idempotent("opportunity:opp-1"),
                        "a submitted opportunity was left replayable")


class TestCompositionRoot(unittest.TestCase):
    def test_close_reports_pipeline_shutdown_failure(self):
        messages = []

        class BrokenPipeline:
            def close(self):
                raise RuntimeError("close failed")

        root = CompositionRoot(
            pipeline=BrokenPipeline(),
            portfolio=None,
            run_store=None,
            lifecycle=None,
            base_dir=".",
            log_fn=messages.append,
        )

        root.close()

        self.assertEqual(messages, ["Composition root shutdown failed: close failed"])

    def test_builds_shared_instances(self):
        base = tempfile.mkdtemp(prefix="hermes-comproot-")
        try:
            root = build_composition_root(base_dir=base)
            self.assertIsNotNone(root.pipeline)
            self.assertIsNotNone(root.portfolio)
            self.assertIsNotNone(root.run_store)
            self.assertIsNotNone(root.lifecycle)
            self.assertIsNotNone(root.reconciliation_report)
            self.assertFalse(root.reconciliation_report.has_conflicts)
            # The pipeline and the root share the SAME lifecycle/portfolio/run_store.
            self.assertIs(root.pipeline.portfolio, root.portfolio)
            self.assertIs(root.pipeline.autonomous_loop.run_store, root.run_store)
            self.assertIs(root.pipeline.lifecycle, root.lifecycle)
            root.close()
        finally:
            import shutil
            shutil.rmtree(base, ignore_errors=True)

    def test_recover_incomplete_on_build(self):
        base = tempfile.mkdtemp(prefix="hermes-comproot-")
        try:
            run_store_path = os.path.join(base, "autonomous_runs.db")
            # Pre-create a store with a mid-flight run, then build the root.
            from agents.services.autonomous_run_store import AutonomousRunStore
            pre = AutonomousRunStore(run_store_path)
            pre.save_run(_sample_result(), "opp-9")
            pre.update_run_status(pre.list_runs()[0]["run_id"], "RUNNING")
            root = build_composition_root(base_dir=base)
            loaded = root.run_store.get_run(root.run_store.list_runs()[0]["run_id"])
            self.assertEqual(loaded["status"], "FAILED")
            root.close()
        finally:
            import shutil
            shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
