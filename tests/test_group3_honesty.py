"""Group 3 regression tests: stop false learning signals from unverified / advertised
revenue (H-3 ramp win-rate, H-4 paid-without-evidence reputation, H-5 simple-execute
success fabrication).

Run:  python -m unittest tests.test_group3_honesty
All tests are offline (no network, no credentials).
"""
import os
import sys
import tempfile
import shutil
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Keep Qt off-screen when any gui-ish import sneaks in.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _tmp_db():
    d = tempfile.mkdtemp(prefix="g3_")
    return d, os.path.join(d, "mem.sqlite")


class _Opp:
    """Minimal opportunity stub for the pipeline's simple-execute path."""
    def __init__(self, platform="FaucetX", source="faucet", min_amount=5.0,
                 status="execute", url="https://faucet.example/claim"):
        self.id = "opp-simple-1"
        self.platform = platform
        self.source = source
        self.min_amount = min_amount
        self.status = status
        self.url = url


def _opp_ramp(platform="RampPlat"):
    o = type("O", (), {})()
    o.id = "opp-ramp-1"
    o.platform = platform
    o.proposal_variant = None
    return o


class H5SimpleExecuteNoFabricatedSuccess(unittest.TestCase):
    """H-5: _execute_simple must not record success/revenue for a mere discovery."""

    def setUp(self):
        self._d, self._db = _tmp_db()
        from earning_memory import EarningMemory
        self.mem = EarningMemory(db_path=self._db)
        class P:
            pass
        self.p = P()
        self.p.memory = self.mem
        from earning_pipeline import EarningPipeline
        self.run_simple = EarningPipeline._execute_simple.__get__(self.p, EarningPipeline)

    def tearDown(self):
        shutil.rmtree(self._d, ignore_errors=True)

    def test_no_success_revenue_recorded(self):
        self.run_simple(_Opp())
        rows = self.mem.get_outcome_history("opp-simple-1")
        self.assertEqual(len(rows), 1, "exactly one outcome should be recorded")
        r = rows[0]
        self.assertFalse(r["success"], "discovery must NOT be a successful outcome")
        self.assertEqual(r["revenue"], 0.0, "discovery must NOT carry revenue")
        rep = self.mem.get_platform_reputation("FaucetX")
        self.assertEqual(rep["success"], 0, "no win should be recorded")
        self.assertEqual(rep["total"], 0, "no attempt should be recorded as a win")


class H4PaidWithoutEvidenceNoReputation(unittest.TestCase):
    """H-4: mark_final_outcome('paid') without verified evidence must not update
    platform reputation as a win / write a paid revenue event."""

    def setUp(self):
        self._d, self._db = _tmp_db()
        from earning_memory import EarningMemory
        from agents.opportunity_lifecycle import OpportunityLifecycleTracker
        from earning_learning_loop import LearningLoop
        self.mem = EarningMemory(db_path=self._db)
        self.lc = OpportunityLifecycleTracker()  # no evidence store -> unverified path
        self.lc._learning_loop = LearningLoop(self.mem)  # real loop so outcome_memory_v2 is written

    def tearDown(self):
        shutil.rmtree(self._d, ignore_errors=True)

    def test_paid_without_evidence_does_not_update_reputation(self):
        self.lc.mark_final_outcome(
            "oppX2", outcome_state="paid", platform="TestPlat",
            category="coding", task_type="bug_fix", revenue=250.0,
            cost=0.0, effort_hours=1.0)
        state = self.lc._ensure("oppX2")
        self.assertNotEqual(state.status, "paid",
                            "unverified 'paid' must not flip lifecycle to paid")
        rep = self.mem.get_platform_reputation("TestPlat")
        self.assertEqual(rep["success"], 0, "no reputation win for unverified paid")
        self.assertEqual(rep["total"], 0, "no attempt counted for unverified paid")
        with __import__("sqlite3").connect(self._db) as c:
            states = [row[0] for row in c.execute(
                "SELECT outcome_state FROM outcome_memory_v2 WHERE opportunity_id='oppX2'")]
        self.assertIn("completed", states)
        self.assertNotIn("paid", states, "outcome_memory_v2 must not record a paid win")


class H3RampAcceptRequiresVerifiedPayment(unittest.TestCase):
    """H-3: the submission ramp must only credit an accept (win) when a verified
    L3+ payment exists; an unverified 'paid' call must NOT inflate the win-rate."""

    def setUp(self):
        self._d, self._db = _tmp_db()
        from earning_memory import EarningMemory
        from earning_pipeline import EarningPipeline
        from agents.submission_ramp import set_ramp_memory
        self.mem = EarningMemory(db_path=self._db)
        set_ramp_memory(self.mem)  # ensure the ramp singleton uses THIS test's memory
        class P:
            pass
        self.p = P()
        self.p.memory = self.mem
        self.record_ramp = EarningPipeline._record_ramp_real_outcome.__get__(self.p, EarningPipeline)

    def tearDown(self):
        shutil.rmtree(self._d, ignore_errors=True)

    def test_unverified_paid_records_no_ramp_win(self):
        # An unverified "paid" self-report must NOT credit a ramp win (no win-rate inflation).
        opp = _opp_ramp()
        self.record_ramp(opp, accepted=True, verified=False, verified_amount=250.0)
        ramp = __import__("agents.submission_ramp", fromlist=["get_ramp"]).get_ramp(self.mem)
        rep = ramp.status(opp.platform)
        self.assertEqual(rep.get("success_rate", 0.0), 0.0,
                         "unverified paid must NOT credit a ramp win")

    def test_verified_paid_records_ramp_win(self):
        # A verified payment (verified=True) MUST credit the ramp accept (win).
        opp = _opp_ramp()
        self.record_ramp(opp, accepted=True, verified=True, verified_amount=180.0)
        ramp = __import__("agents.submission_ramp", fromlist=["get_ramp"]).get_ramp(self.mem)
        rep = ramp.status(opp.platform)
        self.assertGreaterEqual(rep.get("success_rate", 0.0), 0.99,
                                "verified paid MUST credit a ramp win")


if __name__ == "__main__":
    unittest.main()
