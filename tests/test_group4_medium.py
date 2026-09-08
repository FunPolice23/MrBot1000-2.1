"""Group 4 regression tests: medium-severity correctness fixes (M-1 .. M-7).

Run:  QT_QPA_PLATFORM=offscreen python -m unittest tests.test_group4_medium -v

Covers:
  M-1  lifecycle state persists across restart (RAM-only hole)
  M-2  dedup is state-aware (failed opps re-enter; paid/completed stay blocked)
  M-3  content discovery uses stable, platform-keyed ids (not positional index)
  M-4  manual reference (operator attestation) never auto-verifies a "paid"
  M-5  LLM free-text scam verdict must not unilaterally reject an opp
  M-6  evaluate() must not mark a failed eval as "evaluated"
  M-7  revenue report uses a single source of truth (verified accounting)
"""
import os
import sys
import json
import tempfile
import shutil
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from earning_pipeline import EarningPipeline, Opportunity
from agents.opportunity_lifecycle import OpportunityLifecycleTracker, OpportunityState
from agents.autonomous_loop import AutonomousLoop, AutonomousResult, StageStatus

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _tmp_db_dir():
    return tempfile.mkdtemp(prefix="mrbot_g4_")


# --------------------------------------------------------------------------- M-1
class M1LifecyclePersistsAcrossRestart(unittest.TestCase):
    def setUp(self):
        self._d = _tmp_db_dir()
        self._sp = os.path.join(self._d, "lifecycle_states.json")

    def tearDown(self):
        shutil.rmtree(self._d, ignore_errors=True)

    def test_state_survives_restart(self):
        t1 = OpportunityLifecycleTracker(state_path=self._sp)
        o = type("O", (), {"id": "op_X", "estimated_usd_value": 10.0,
                          "deadline": 0.0, "score": 0.7})()
        t1.start(o)
        t1.mark_researched("op_X", "r")
        t1.mark_applied("op_X", "a")
        t1.mark_in_progress("op_X", "ip")
        t1.mark_submitted("op_X", "s")
        st = t1._ensure("op_X")
        st.current_stage = "paid"
        st.status = "paid"
        st.last_amount = 5.0
        st.evidence_ids = ["ev-1", "ev-2"]
        t1._persist()
        self.assertTrue(os.path.exists(self._sp))

        t2 = OpportunityLifecycleTracker(state_path=self._sp)
        rec = t2.get_state("op_X")
        self.assertEqual(rec["current_stage"], "paid")
        self.assertEqual(rec["status"], "paid")
        self.assertAlmostEqual(float(rec["last_amount"]), 5.0)
        # M-1 fix: evidence_ids + verification must round-trip through persistence.
        self.assertEqual(rec.get("evidence_ids"), ["ev-1", "ev-2"])
        # Recovered in-memory state is a real OpportunityState (post-restart transitions work).
        self.assertIsInstance(t2._states.get("op_X"), OpportunityState)
        # A post-restart transition must NOT raise on the recovered object.
        t2.mark_failed("op_X", "re-evaluated after restart")
        self.assertEqual(t2._states["op_X"].status, "failed")


# --------------------------------------------------------------------------- M-2
class M2DedupStateAware(unittest.TestCase):
    def _make_loop(self, history):
        # Provide get_outcome_history (the real signal the dedup now uses). It is
        # called as a bound method, so the fake must accept `self` first.
        pipe = type("P", (), {})()
        def get_outcome_history(self, opp_id):
            return history.get(opp_id, [])
        pipe.memory = type("M", (), {"get_outcome_history": get_outcome_history})()
        loop = AutonomousLoop(pipe)
        loop.memory = pipe.memory
        return loop

    def _facts(self, oid):
        f = type("F", (), {})()
        f.opportunity_id = oid
        return f

    def _opp(self, oid):
        o = type("O", (), {})()
        o.id = oid
        return o

    def test_failed_opp_reenters(self):
        history = {"op_F": [{"result": "failed", "ts": 1.0}]}
        loop = self._make_loop(history)
        res = AutonomousResult()
        cont = loop._stage_deduplicate(res, self._opp("op_F"), self._facts("op_F"))
        self.assertTrue(cont)
        self.assertEqual(res.stages[-1].status, StageStatus.COMPLETED)

    def test_paid_opp_blocked(self):
        history = {"op_P": [{"result": "paid", "ts": 1.0}]}
        loop = self._make_loop(history)
        res = AutonomousResult()
        cont = loop._stage_deduplicate(res, self._opp("op_P"), self._facts("op_P"))
        self.assertFalse(cont)
        self.assertEqual(res.stages[-1].status, StageStatus.BLOCKED)

    def test_no_history_not_blocked(self):
        loop = self._make_loop({})
        res = AutonomousResult()
        cont = loop._stage_deduplicate(res, self._opp("op_N"), self._facts("op_N"))
        self.assertTrue(cont)


# --------------------------------------------------------------------------- M-3
class M3ContentDiscoveryStableIds(unittest.TestCase):
    def test_ids_are_platform_keyed_not_positional(self):
        stub = type("S", (), {})()
        opps = EarningPipeline._discover_content(stub)
        ids = [o.id for o in opps]
        self.assertFalse(any(i.startswith("content_") and i.split("_")[-1].isdigit()
                             for i in ids), "positional content_{i} id found")
        self.assertEqual(len(ids), len(set(ids)))
        opps2 = EarningPipeline._discover_content(stub)
        self.assertEqual([o.id for o in opps2], ids)


# --------------------------------------------------------------------------- M-4
class M4ManualReferenceNeverVerifies(unittest.TestCase):
    def setUp(self):
        self._d = _tmp_db_dir()
        self._db = os.path.join(self._d, "pipeline.db")

    def tearDown(self):
        shutil.rmtree(self._d, ignore_errors=True)

    def test_manual_reference_does_not_flip_paid(self):
        p = EarningPipeline(db_path=self._db)
        o = Opportunity(id="ref1", source="faucet", type="faucet",
                        platform="FaucetX", payment_type="usd",
                        estimated_usd_value=3.0, min_amount=3.0,
                        url="https://faucet.x/claim", found_at=0.0)
        state = p.track_opportunity(o, "paid", note="ref:txn-abc-123", amount=3.0)
        # Manual reference must NOT flip status to "paid" (it is pending/unverified).
        self.assertNotEqual(getattr(state, "status", ""), "paid")
        # And it must not credit a ramp win.
        from agents.submission_ramp import get_ramp, set_ramp_memory
        set_ramp_memory(p.memory)
        ramp = get_ramp(p.memory)
        st = ramp.status(o.platform)
        self.assertAlmostEqual(float(st.get("success_rate", 0.0)), 0.0)


# --------------------------------------------------------------------------- M-5
class M5LLMDoesNotUnilaterallyReject(unittest.TestCase):
    def setUp(self):
        self._d = _tmp_db_dir()
        self._db = os.path.join(self._d, "pipeline.db")

    def tearDown(self):
        shutil.rmtree(self._d, ignore_errors=True)

    def test_high_scam_prob_sets_risk_not_rejected(self):
        p = EarningPipeline(db_path=self._db)
        o = Opportunity(id="m5", source="social", type="gig", platform="Reddit",
                        payment_type="usd", estimated_usd_value=10.0,
                        min_amount=10.0, url="https://x", found_at=0.0)
        fake_json = json.dumps({"profit": 6, "effort": 3, "risk": 8,
                                "urgency": 2, "skill_match": 7, "scam_prob": 0.95})
        fake_content = json.dumps({"message": {"content": fake_json}})

        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return json.loads(fake_content)

        with mock.patch("httpx.post", return_value=FakeResp()):
            p._evaluate_opportunity(o)
        self.assertNotEqual(o.status, "rejected")
        self.assertEqual(o.status, "evaluated")
        self.assertEqual(o.risk_level, "high")


# --------------------------------------------------------------------------- M-6
class M6EvalFailureNotEvaluated(unittest.TestCase):
    def setUp(self):
        self._d = _tmp_db_dir()
        self._db = os.path.join(self._d, "pipeline.db")

    def tearDown(self):
        shutil.rmtree(self._d, ignore_errors=True)

    def test_eval_exception_marks_eval_error_and_skips(self):
        p = EarningPipeline(db_path=self._db)

        def _boom(opp):
            raise RuntimeError("eval exploded")

        o = Opportunity(id="m6", source="social", type="gig", platform="Reddit",
                        payment_type="usd", estimated_usd_value=10.0,
                        min_amount=10.0, url="https://x", found_at=0.0)
        with mock.patch.object(p, "_evaluate_opportunity", side_effect=_boom):
            out = p.evaluate([o])
        self.assertEqual(len(out), 0)
        self.assertEqual(o.status, "eval_error")


# --------------------------------------------------------------------------- M-7
class M7RevenueReportSingleSource(unittest.TestCase):
    def setUp(self):
        self._d = _tmp_db_dir()
        self._db = os.path.join(self._d, "pipeline.db")

    def tearDown(self):
        shutil.rmtree(self._d, ignore_errors=True)

    def _make_evidence(self, verified):
        from agents.evidence import Evidence, EvidenceStatus
        status = EvidenceStatus.VERIFIED if verified else EvidenceStatus.UNVERIFIED
        level = 3 if verified else 1
        return Evidence.create(
            source="reconcile", evidence_type="payment",
            subject_type="opportunity", subject_id="op_ev",
            amount=12.34, currency="USD", verification_method="reconcile",
            verification_level=level, status=status)

    def test_verified_payment_counts_as_verified_revenue(self):
        p = EarningPipeline(db_path=self._db)
        p.evidence_store.record(self._make_evidence(verified=True))
        prof = p.accounting.get_profile("op_ev")
        # Single source of truth: VERIFIED payment -> verified_revenue, not unverified.
        self.assertAlmostEqual(prof.verified_revenue, 12.34, places=4)
        self.assertAlmostEqual(prof.unverified_revenue, 0.0, places=4)

    def test_unverified_payment_not_counted_as_verified(self):
        p = EarningPipeline(db_path=self._db)
        p.evidence_store.record(self._make_evidence(verified=False))
        prof = p.accounting.get_profile("op_ev")
        # An unverified (manual-attested) payment must NEVER inflate verified revenue.
        self.assertAlmostEqual(prof.verified_revenue, 0.0, places=4)
        self.assertGreater(prof.unverified_revenue, 0.0)

    def test_report_delegates_to_accounting(self):
        p = EarningPipeline(db_path=self._db)
        ev = self._make_evidence(verified=True)
        p.evidence_store.record(ev)
        # Wire a minimal portfolio so get_revenue_report aggregates the profile.
        entry = type("E", (), {"opportunity_id": "op_ev"})()
        fake_portfolio = type("FP", (), {"load_all": lambda *a: [entry]})()
        p.portfolio = fake_portfolio
        report = p.get_revenue_report(days=30)
        self.assertAlmostEqual(float(report["verified_revenue_usd"]), 12.34, places=4)


if __name__ == "__main__":
    unittest.main()
