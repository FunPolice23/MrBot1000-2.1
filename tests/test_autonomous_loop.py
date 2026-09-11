"""tests/test_autonomous_loop.py — Unified Autonomous Planning Loop (v2.0.36k)."""

import os
import tempfile
import time
import unittest
from types import SimpleNamespace

from agents.provenance import TruthStatus, ProvenanceRecord, InfoAtom, ProvenanceChain, FactStore
from agents.autonomous_loop import StageStatus, AutonomousLoop, AutonomousResult


# ── Fake Opportunity ───────────────────────────────────────────────────────────

class FakeOpp:
    def __init__(self, opp_id="opp-1", title="Test opp", source="test", platform="TestPlatform",
                 category="coding", task_type="bug_fix", payment_type="usd", advertised_amount=500,
                 estimated_net_value=400, estimated_effort=2, risk_level="low"):
        self.id = opp_id
        self.opportunity_id = opp_id
        self.title = title
        self.source = source
        self.platform = platform
        self.category = category
        self.task_type = task_type
        self.payment_type = payment_type
        self.advertised_amount = advertised_amount
        self.estimated_net_value = estimated_net_value
        self.estimated_effort = estimated_effort
        self.risk_level = risk_level
        self.required_skills = ["python", "debugging"]
        self.description = "Test opportunity description"
        self.external_url = "https://example.com/opp-1"
        self.currency = "usd"
        self.payment_currency = "usd"
        # Numeric/flag defaults the OpportunityIntelligenceEngine reads (avoid None crashes).
        self.estimated_duration = 1.0
        self.completion_time = 0.0
        self.source_reliability = 0.5
        self.scam_risk = 0.1
        self.automation_potential = 0.5
        self.human_required = False
        self.risk_level_safe = True
        self.required_tools = []
        self.deadline = 0.0
        self.external_id = "ext-1"
        self.payment_type = "usd"

    def __getattr__(self, name):
        # Tolerate any other optional opportunity attributes the engine/loop may read.
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return None


# ── Fake Pipeline ──────────────────────────────────────────────────────────────

class FakePortfolio:
    def __init__(self, entries=None):
        self._entries = entries or []
    def load_all(self):
        return self._entries


class FakeMemory:
    def __init__(self, db_path=":memory:", platform_reputations=None):
        self.db_path = db_path
        self._platform_reputations = platform_reputations or {}
    def get_opportunity_history(self, opp_id):
        return []
    def get_outcome_history(self, opp_id):
        return []
    def get_platform_reputation(self, platform):
        return self._platform_reputations.get(platform)


class FakeLifecycle:
    pass


class FakeEvidenceStore:
    pass


class FakeAccounting:
    def get_profile(self, opp_id):
        return None


class FakeTaskExecutor:
    def run(self, task):
        return SimpleNamespace(success=True, errors=[], output={})


class FakePipeline:
    def __init__(self, db_path=":memory:", platform_reputations=None):
        self.memory = FakeMemory(db_path, platform_reputations)
        self.lifecycle = FakeLifecycle()
        self.portfolio = FakePortfolio()
        self.evidence_store = FakeEvidenceStore()
        self.accounting = FakeAccounting()
        self.task_executor = FakeTaskExecutor()


# ── Provenance Tests ───────────────────────────────────────────────────────────

class TestProvenance(unittest.TestCase):
    def test_truth_status_ranking(self):
        self.assertLess(TruthStatus.ESTIMATE.reliability_rank, TruthStatus.PREDICTION.reliability_rank)
        self.assertLess(TruthStatus.PREDICTION.reliability_rank, TruthStatus.OBSERVATION.reliability_rank)
        self.assertLess(TruthStatus.OBSERVATION.reliability_rank, TruthStatus.VERIFIED_RESULT.reliability_rank)
        self.assertLess(TruthStatus.VERIFIED_RESULT.reliability_rank, TruthStatus.FACT.reliability_rank)

    def test_info_atom_is_at_least(self):
        atom = InfoAtom(value=100, status=TruthStatus.VERIFIED_RESULT, key="test")
        self.assertTrue(atom.is_at_least(TruthStatus.ESTIMATE))
        self.assertTrue(atom.is_at_least(TruthStatus.VERIFIED_RESULT))
        self.assertFalse(atom.is_at_least(TruthStatus.FACT))

    def test_fact_store_add_and_get(self):
        store = FactStore("opp-1")
        atom = InfoAtom(value=100, status=TruthStatus.OBSERVATION, key="price")
        store.add(atom)
        self.assertEqual(len(store.get("price")), 1)
        self.assertEqual(store.get_best_value("price"), 100)

    def test_fact_store_most_reliable_wins(self):
        store = FactStore("opp-1")
        store.add(InfoAtom(value=50, status=TruthStatus.ESTIMATE, key="revenue"))
        store.add(InfoAtom(value=100, status=TruthStatus.VERIFIED_RESULT, key="revenue"))
        store.add(InfoAtom(value=75, status=TruthStatus.PREDICTION, key="revenue"))
        best = store.get_best("revenue")
        self.assertEqual(best.status, TruthStatus.VERIFIED_RESULT)
        self.assertEqual(best.value, 100)

    def test_fact_store_has_fact(self):
        store = FactStore("opp-1")
        store.add(InfoAtom(value=100, status=TruthStatus.ESTIMATE, key="test"))
        self.assertFalse(store.has_fact("test"))
        store.add(InfoAtom(value=100, status=TruthStatus.FACT, key="test"))
        self.assertTrue(store.has_fact("test"))

    def test_fact_store_has_verified(self):
        store = FactStore("opp-1")
        store.add(InfoAtom(value=100, status=TruthStatus.VERIFIED_RESULT, key="test"))
        self.assertTrue(store.has_verified("test"))

    def test_fact_store_explain(self):
        store = FactStore("opp-1")
        store.add(InfoAtom(value=100, status=TruthStatus.VERIFIED_RESULT, key="price"))
        explanation = store.explain("price")
        self.assertIn("price", explanation)
        self.assertIn("verified_result", explanation)

    def test_fact_store_explain_missing(self):
        store = FactStore("opp-1")
        self.assertEqual(store.explain("missing"), "No information about 'missing'.")

    def test_fact_store_to_dict(self):
        store = FactStore("opp-1")
        store.add(InfoAtom(value=100, status=TruthStatus.OBSERVATION, key="test"))
        d = store.to_dict()
        self.assertEqual(d["opportunity_id"], "opp-1")
        self.assertIn("test", d["atoms"])

    def test_provenance_chain(self):
        chain = ProvenanceChain()
        chain.add(ProvenanceRecord(source="test", method="discovery"))
        self.assertEqual(len(chain.records), 1)
        d = chain.to_dict()
        self.assertIn("chain_id", d)
        self.assertEqual(len(d["records"]), 1)


# ── Autonomous Loop Tests ──────────────────────────────────────────────────────

class TestAutonomousLoop(unittest.TestCase):
    def setUp(self):
        self.pipeline = FakePipeline()
        self.loop = AutonomousLoop(self.pipeline)

    def test_full_loop_completes(self):
        """Full 24-stage loop should complete for a valid opportunity (terminal non-failure)."""
        opp = FakeOpp(advertised_amount=50)  # below approval threshold
        result = self.loop.run(opp)
        self.assertIsInstance(result, AutonomousResult)
        self.assertEqual(result.opportunity_id, "opp-1")
        self.assertTrue(result.success)
        # With no verified payment evidence the loop completes but does NOT claim paid.
        self.assertEqual(result.decision, "completed_unpaid")
        self.assertFalse(result.paid)
        self.assertGreater(len(result.stages), 15)

    def test_missing_executor_fails_without_claiming_completion(self):
        self.pipeline.task_executor = None
        self.loop.task_executor = None
        result = self.loop.run(FakeOpp(advertised_amount=50))
        self.assertEqual(result.decision, "failed")
        self.assertFalse(result.success)
        self.assertIn("no_task_executor", result.errors)
        self.assertNotIn(result.decision, {"completed_unpaid", "proceed"})

    def test_loop_stages_recorded(self):
        """Each stage should be recorded."""
        opp = FakeOpp(advertised_amount=50)
        result = self.loop.run(opp)
        stage_names = [s.stage for s in result.stages]
        expected = ["discovered", "deduplicate", "classify", "evaluate", "check_memory",
                     "check_reputation", "check_skill_fit", "check_economics", "check_risk",
                     "prioritize", "plan", "request_approval", "execute", "validate",
                     "submit", "wait", "verify", "account", "learn", "rerank"]
        for stage in expected:
            self.assertIn(stage, stage_names, f"Stage '{stage}' not found in loop")

    def test_loop_detects_duplicate(self):
        """A prior terminal-success outcome should be blocked as a duplicate (state-aware dedup)."""
        opp = FakeOpp()
        # A prior COMPLETED outcome is a legitimate "already did this" duplicate -> block.
        self.pipeline.memory.get_outcome_history = lambda x: [{"result": "completed", "ts": 1.0}]
        result = self.loop.run(opp)
        self.assertEqual(result.decision, "reject")
        self.assertIn("Duplicate", result.decision_reason)

    def test_loop_requests_approval_for_high_value(self):
        """High-value opportunities should require approval."""
        opp = FakeOpp(advertised_amount=5000)  # above 100 threshold
        result = self.loop.run(opp)
        self.assertEqual(result.decision, "await_approval")

    def test_loop_preserves_provenance(self):
        """Provenance should be preserved throughout the loop."""
        opp = FakeOpp(advertised_amount=50)
        result = self.loop.run(opp)
        self.assertIsNotNone(result.explanation)
        self.assertGreater(len(result.explanation), 0)

    def test_loop_explanation_for_rejection(self):
        """Rejection should include explanation."""
        opp = FakeOpp()
        self.pipeline.memory.get_outcome_history = lambda x: [{"result": "paid", "ts": 1.0}]
        result = self.loop.run(opp)
        self.assertIn("Rejected", result.explanation)

    def test_loop_explanation_for_approval(self):
        """Await approval should include explanation."""
        opp = FakeOpp(advertised_amount=5000)
        result = self.loop.run(opp)
        self.assertIn("approval", result.explanation.lower())

    def test_loop_duration_recorded(self):
        """Loop duration should be recorded."""
        opp = FakeOpp(advertised_amount=50)
        result = self.loop.run(opp)
        self.assertGreaterEqual(result.duration_s, 0)

    def test_loop_to_dict(self):
        """Result should be serializable to dict."""
        opp = FakeOpp(advertised_amount=50)
        result = self.loop.run(opp)
        d = result.to_dict()
        self.assertIn("opportunity_id", d)
        self.assertIn("stages", d)
        self.assertIn("decision", d)
        self.assertIn("explanation", d)

    def test_loop_with_no_duplicates(self):
        """Non-duplicate should proceed past deduplicate stage."""
        opp = FakeOpp(advertised_amount=50)
        result = self.loop.run(opp)
        dedup_stage = next(s for s in result.stages if s.stage == "deduplicate")
        self.assertEqual(dedup_stage.status, StageStatus.COMPLETED)
        self.assertFalse(dedup_stage.data["is_duplicate"])


# ── Group 1 regression tests: dead stages must now actually run ───────────────

class TestGroup1DeadStages(unittest.TestCase):
    """Verifies C-3 / H-1 / H-2 fixes: learn + rerank + portfolio-sync must persist."""

    def setUp(self):
        import tempfile
        from earning_memory import EarningMemory
        from earning_learning_loop import LearningLoop
        from agents.opportunity_portfolio import OpportunityPortfolio, PortfolioEntry, WorkStatus

        self._tmp = tempfile.mkdtemp(prefix="al_g1_")
        self.mem_db = os.path.join(self._tmp, "mem.sqlite")
        self.port_db = os.path.join(self._tmp, "port.sqlite")
        memory = EarningMemory(db_path=self.mem_db)
        # EarningMemory.get_opportunity_history returns None for unknown opps; the loop
        # calls len() on it, so expose a None-safe wrapper for the test pipeline.
        _raw_hist = memory.get_opportunity_history
        memory.get_opportunity_history = lambda oid: _raw_hist(oid) or []
        self.learning_loop = LearningLoop(memory)
        self.portfolio = OpportunityPortfolio(db_path=self.port_db)
        # Pre-seed a portfolio entry for the opp under test.
        entry = PortfolioEntry(
            opportunity_id="opp-g1", work_status=WorkStatus.EVALUATING,
            priority=10, expected_value=40.0, expected_hourly_value=20.0,
            confidence=0.7, risk="low", effort=2.0, next_action="review",
            platform="TestPlatform", category="coding", task_type="bug_fix")
        self.portfolio.add(entry)

        class RealPipeline:
            pass
        p = RealPipeline()
        p.memory = memory
        p.learning_loop = self.learning_loop
        p.portfolio = self.portfolio
        p.lifecycle = FakeLifecycle()
        p.evidence_store = FakeEvidenceStore()
        p.accounting = FakeAccounting()
        p.task_executor = FakeTaskExecutor()
        self.pipeline = p
        self.loop = AutonomousLoop(self.pipeline)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _opp(self, advertised_amount=50):
        return FakeOpp(opp_id="opp-g1", advertised_amount=advertised_amount)

    def test_stage_learn_writes_outcome(self):
        """C-3: LEARN stage must persist an outcome via LearningLoop.process_outcome."""
        opp = self._opp()
        # Low-value opp: pipeline completes (proceed == paid only when payment verified; here none,
        # so decision is 'completed_unpaid' — and learn still records the outcome).
        result = self.loop.run(opp)
        self.assertEqual(result.decision, "completed_unpaid")
        learn_stage = next(s for s in result.stages if s.stage == "learn")
        self.assertTrue(learn_stage.data["learned"],
                        f"LEARN stage did not persist; errors={result.errors}")
        # The outcome must be persistently recorded in outcome_memory_v2 (append-only raw event).
        import sqlite3
        with sqlite3.connect(self.pipeline.memory.db_path) as conn:
            rows = conn.execute(
                "SELECT outcome_state FROM outcome_memory_v2 WHERE opportunity_id=?",
                ("opp-g1",)).fetchall()
        self.assertTrue(any(r[0] == "completed" for r in rows),
                        f"no completed outcome recorded in outcome_memory_v2; rows={rows}")

    def test_stage_rerank_persists_priority(self):
        """H-1: RERANK stage must persist priority via portfolio.update()."""
        opp = self._opp()
        result = self.loop.run(opp)
        self.assertEqual(result.decision, "completed_unpaid")
        rerank_stage = next(s for s in result.stages if s.stage == "rerank")
        self.assertTrue(rerank_stage.data["reranked"],
                        f"RERANK stage did not persist; errors={result.errors}")
        entry = self.portfolio.get("opp-g1")
        self.assertIsNotNone(entry)
        # result.success is True for a terminal non-failure (completed_unpaid), so priority increments.
        self.assertEqual(entry.priority, 11, "priority should have incremented on completed_unpaid")

    def test_sync_final_state_updates_portfolio(self):
        """H-2: _sync_final_state must update the portfolio via update() (not save())."""
        opp = self._opp()
        result = self.loop.run(opp)
        self.assertEqual(result.decision, "completed_unpaid")
        entry = self.portfolio.get("opp-g1")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.policy_score, True)
        from agents.opportunity_portfolio import WorkStatus
        self.assertIn(entry.work_status, (WorkStatus.IN_PROGRESS, WorkStatus.AWAITING_APPROVAL, WorkStatus.EVALUATING))


class _MemEvidenceStore:
    """Minimal in-memory EvidenceStore stand-in for Group 2 tests (no real AgentDB)."""
    def __init__(self):
        self._rows = []
    def record(self, ev):
        self._rows.append(ev)
        return ev
    def for_subject(self, subject_type, subject_id):
        return [e for e in self._rows if e.subject_type == subject_type and e.subject_id == subject_id]


class TestGroup2NoFabricatedPayment(unittest.TestCase):
    """Verifies C-1/C-2: the loop must NOT report paid/success without verified L3+ payment."""

    def setUp(self):
        import tempfile
        from earning_memory import EarningMemory
        from earning_learning_loop import LearningLoop
        from agents.opportunity_portfolio import OpportunityPortfolio, PortfolioEntry, WorkStatus
        from agents.evidence import Evidence, EvidenceStatus, VerificationLevel

        self._tmp = tempfile.mkdtemp(prefix="al_g2_")
        memory = EarningMemory(db_path=os.path.join(self._tmp, "mem.sqlite"))
        _raw = memory.get_opportunity_history
        memory.get_opportunity_history = lambda oid: _raw(oid) or []
        port = OpportunityPortfolio(db_path=os.path.join(self._tmp, "port.sqlite"))
        port.add(PortfolioEntry(opportunity_id="opp-g2", work_status=WorkStatus.EVALUATING,
                               priority=10, expected_value=40.0, expected_hourly_value=20.0,
                               confidence=0.7, risk="low", effort=2.0, next_action="review",
                               platform="TestPlatform", category="coding", task_type="bug_fix"))
        self.ev = Evidence
        self.EST = EvidenceStatus
        self.VL = VerificationLevel

        class RealPipeline:
            pass
        p = RealPipeline()
        p.memory = memory
        p.learning_loop = LearningLoop(memory)
        p.portfolio = port
        p.lifecycle = type("L", (), {})()
        p.evidence_store = _MemEvidenceStore()
        p.accounting = type("A", (), {"get_profile": lambda s, o: None})()
        p.task_executor = FakeTaskExecutor()
        self.pipeline = p
        self.portfolio = port
        self.loop = AutonomousLoop(p)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _opp(self, advertised_amount=50):
        return FakeOpp(opp_id="opp-g2", advertised_amount=advertised_amount)

    def test_no_payment_without_verified_evidence(self):
        """C-1/C-2: running the loop over an opp with NO payment evidence must NOT report paid."""
        opp = self._opp()
        result = self.loop.run(opp)
        self.assertFalse(result.paid, f"loop reported paid with no payment evidence; decision={result.decision}")
        self.assertEqual(result.payment_amount, 0.0)
        # decision must be 'completed_unpaid', never 'proceed' (proceed == payment verified)
        self.assertEqual(result.decision, "completed_unpaid", f"decision={result.decision}")

    def test_submission_only_is_not_payment(self):
        """C-2: a self-reported L1 platform_submission must NOT be treated as paid."""
        opp = self._opp()
        # Simulate the loop's submit stage writing an L1 submission evidence.
        self.pipeline.evidence_store.record(
            self.ev.create(source="system", evidence_type="platform_submission",
                           subject_type="opportunity", subject_id="opp-g2",
                           external_id="ext-1", verification_method="local_record",
                           verification_level=self.VL.L1_SELF_REPORTED,
                           provenance={"producer": "autonomous_loop", "stage": "submit"}))
        result = self.loop.run(opp)
        verify = next(s for s in result.stages if s.stage == "verify")
        self.assertFalse(verify.data["paid"], "L1 submission was treated as payment")
        self.assertFalse(result.paid)

    def test_verified_l3_payment_reports_paid(self):
        """Positive control: a real L3+ payment_gross evidence flips the loop to paid."""
        opp = self._opp(advertised_amount=50)
        self.pipeline.evidence_store.record(
            self.ev.create(source="system", evidence_type="payment_gross",
                           subject_type="opportunity", subject_id="opp-g2",
                           external_id="ext-1", amount=180.0, currency="usd",
                           verification_method="authenticated_api",
                           verification_level=self.VL.L3_EXTERNAL_SOURCE,
                           status=self.EST.VERIFIED,
                           provenance={"producer": "payment_provider"}))
        result = self.loop.run(opp)
        self.assertTrue(result.paid, f"loop did not report paid with L3 payment; decision={result.decision}")
        self.assertAlmostEqual(result.payment_amount, 180.0)
        self.assertEqual(result.decision, "proceed")


if __name__ == "__main__":
    unittest.main()
