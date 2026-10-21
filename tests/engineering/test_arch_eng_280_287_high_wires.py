"""ARCH-ENG-280..287 — the high-tier depth findings: wired, not just guarded.

Each class pins one finding from the 11A-11D depth sweeps.  The common shape was
the same as the low tier: a mechanism had been built and then the last hop was
missing.  Here the missing hops were safety-relevant (live orders, crypto
sends, independent payment reconciliation, quarantined instructions, feature
gates) and ranking-relevant (scheduler results and learned weights that no live
decision read).

Every behavioural assertion is paired with a vacuity probe: a control case that
must take the other branch (gate off, cold start, wrong variable, duplicate
delivery, non-independent method) so the test cannot pass because the code
under test never ran.
"""

from __future__ import annotations

import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from app.earning_pipeline import EarningPipeline, Opportunity as LegacyOpportunity  # noqa: E402
from agents.autonomy.self_improvement import (  # noqa: E402
    OutcomeRecord, SelfImprovementEngine,
)
from agents.discovery.discovery_engine import DiscoveryEngine  # noqa: E402
from agents.discovery.discovery_scheduler import (  # noqa: E402
    DiscoveryScheduler, DiscoveryTask,
)
from agents.discovery.discovery_sources import (  # noqa: E402
    AirdropSource, DefiSource, SocialSource,
)
from agents.earning.discovery import EarningDiscoveryService  # noqa: E402
from agents.earning.opportunity_models import Opportunity as CanonicalOpportunity  # noqa: E402
from agents.earning.live_trading import (  # noqa: E402
    LiveTradingService, RiskAssessment, TradeIntent,
)
from agents.evidence.evidence import (  # noqa: E402
    Evidence, EvidenceStatus, VerificationLevel,
)
from agents.evidence.evidence_store import EvidenceStore  # noqa: E402
from agents.earning.opportunity_lifecycle import (  # noqa: E402
    OpportunityLifecycleTracker,
)
from agents.integrations.wallet import Chain  # noqa: E402
from agents.safety.approval import (  # noqa: E402
    ApprovalItem, ApprovalKind, ApprovalStatus, HumanApprovalQueue,
)
from app.database import AgentDB  # noqa: E402
from gui.builders.tab_workers import LiveOrderProposalWorker  # noqa: E402
from main import MainWindow  # noqa: E402


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _canonical(oid: str = "c1", *, url: str = "https://example.test/job/1",
               title: str = "Write a thing") -> CanonicalOpportunity:
    return CanonicalOpportunity(
        opportunity_id=oid,
        source="upwork",
        platform="upwork",
        title=title,
        description="A paid writing gig.",
        category="gig",
        task_type="writing",
        external_url=url,
        provenance=f"upwork::{url}::strategy:s1",
    )


class _Memory:
    """Small memory double with only the reads the pipeline uses here."""

    def __init__(self, *, history=None, evidence_ids=None):
        self.history = history or {}
        self.evidence_ids = evidence_ids or []
        self.remembered = {}

    def remember_opportunity(self, opportunity_id, data, category):
        self.remembered[opportunity_id] = dict(data)

    def get_opportunity_history(self, opportunity_id):
        return dict(self.history.get(opportunity_id, {}))

    def get_platform_reputation(self, platform):
        return {}

    def get_pattern_confidence(self, *args):
        return 0.0

    def get_outcome_evidence(self, opportunity_id):
        return list(self.evidence_ids)


class _Scheduler:
    def __init__(self, found, tasks=1):
        self.found = list(found)
        self.tasks = tasks

    def tick(self, discover_fn, sources=None, now=None):
        return {
            "tasks": self.tasks,
            "opportunities": len(self.found),
            "found": list(self.found),
            "errors": {},
            "exploration": 0,
            "exploitation": self.tasks,
        }


def _pipeline_shell(service, scheduler):
    pipe = EarningPipeline.__new__(EarningPipeline)
    pipe.discovery_service = service
    pipe.discovery_scheduler = scheduler
    pipe._log = lambda message: None
    return pipe


# ── ARCH-ENG-282 (F-01) — the scheduler's results reach the live cycle ─────

class TestSchedulerReadSideReachesTheLiveCycle(unittest.TestCase):
    def test_tick_returns_the_discovered_opportunities_not_only_counts(self):
        scheduler = DiscoveryScheduler(memory=None)
        task = DiscoveryTask(
            source="upwork", strategy=None, category="gig",
            priority=1.0, is_exploration=False, reason="test",
        )
        scheduler.select_tasks = lambda sources, now=None: [task]
        found = _canonical()

        stats = scheduler.tick(
            lambda source, strategy: [found],
            sources=["upwork"], now=1_000.0,
        )

        self.assertEqual(stats["opportunities"], 1)
        self.assertEqual(stats["found"], [found],
                         "tick discarded the opportunities it found (F-01)")
        # Vacuity: the old count-only keys must still exist for existing readers.
        self.assertEqual(stats["tasks"], 1)
        self.assertIn("exploration", stats)

    def test_run_discovery_cycle_dedupes_persists_and_returns_legacy_rows(self):
        memory = _Memory()
        service = EarningDiscoveryService(
            memory=memory, log_fn=lambda message: None,
            legacy_type=LegacyOpportunity, sleep_fn=lambda seconds: None,
        )
        first = _canonical("c1")
        duplicate = _canonical("c1-dup")          # same identity, different id
        second = _canonical("c2", url="https://example.test/job/2",
                            title="Second listing")
        pipe = _pipeline_shell(service, _Scheduler([first, duplicate, second]))

        stats = pipe.run_discovery_cycle(sources=["upwork"])

        self.assertEqual(stats["opportunities"], 3,
                         "the scheduler's raw count should be preserved")
        self.assertEqual(len(stats["found"]), 2,
                         "the live path must dedupe before hand-off")
        self.assertTrue(all(isinstance(row, LegacyOpportunity)
                            for row in stats["found"]))
        self.assertEqual(set(memory.remembered), {"c1", "c2"},
                         "deduped discoveries must be persisted exactly once")
        self.assertIn("strategy:s1",
                      memory.remembered["c1"]["provenance"],
                      "provenance must survive the scheduler -> pipeline hop")

    def test_run_full_cycle_uses_run_discovery_cycle(self):
        pipe = EarningPipeline.__new__(EarningPipeline)
        calls = {"cycle": 0, "discover": 0}
        pipe._log = lambda message: None

        def run_cycle(sources=None):
            calls["cycle"] += 1
            return {"tasks": 1, "found": [], "opportunities": 0}

        def explicit_scan(sources=None):
            calls["discover"] += 1
            return []

        pipe.run_discovery_cycle = run_cycle
        pipe.discover = explicit_scan
        pipe.evaluate = lambda opportunities: []
        pipe.filter = lambda opportunities, max_risk="medium": []
        pipe.run_self_audit = lambda: None

        EarningPipeline.run_full_cycle(pipe, sources=["upwork"])

        self.assertEqual(calls["cycle"], 1,
                         "run_full_cycle bypassed the scheduler read side")
        self.assertEqual(calls["discover"], 0,
                         "a due scheduler tick must not also run a second scan")

    def test_run_full_cycle_falls_back_only_when_nothing_is_due(self):
        pipe = EarningPipeline.__new__(EarningPipeline)
        calls = {"discover": 0}
        pipe._log = lambda message: None
        pipe.run_discovery_cycle = lambda sources=None: {
            "tasks": 0, "found": [], "opportunities": 0,
        }

        def explicit_scan(sources=None):
            calls["discover"] += 1
            return []

        pipe.discover = explicit_scan
        pipe.evaluate = lambda opportunities: []
        pipe.filter = lambda opportunities, max_risk="medium": []
        pipe.run_self_audit = lambda: None

        EarningPipeline.run_full_cycle(pipe, sources=["upwork"])

        self.assertEqual(calls["discover"], 1,
                         "an operator-triggered cycle outside every cooldown "
                         "should still scan explicitly")


# ── ARCH-ENG-285 (W-01) — the dead parallel discovery island is gone ──────

class TestLegacyDiscoveryIslandIsDeleted(unittest.TestCase):
    LEGACY = {
        "_discover_source", "_discover_upwork", "_discover_fiverr",
        "_discover_social", "_discover_airdrops", "_discover_defi",
        "_discover_microtasks", "_discover_content", "_discover_dynamic",
    }

    def test_production_pipeline_has_no_legacy_discovery_handlers(self):
        source = _read("app/earning_pipeline.py")
        tree = ast.parse(source)
        names = {
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        # Vacuity: prove the parse found the live methods, so "absent" below
        # cannot mean "the file was empty / the wrong file was read".
        self.assertIn("run_discovery_cycle", names)
        self.assertIn("_adapt_to_legacy", names)
        self.assertFalse(
            names & self.LEGACY,
            f"dead legacy discovery handlers reappeared: {names & self.LEGACY}",
        )
        self.assertNotIn("_discover_content", source)

    def test_live_discovery_path_still_exists(self):
        source = _read("app/earning_pipeline.py")
        self.assertIn("self.discovery_scheduler.tick(", source)
        self.assertIn("self.discovery_service.remember_and_adapt(", source)
        self.assertIn("from agents.discovery.discovery_sources import "
                      "all_builtin_sources", source)


# ── ARCH-ENG-286 (W-02) — the three gates are on the live sources ─────────

class TestLiveFeatureGatesOnDiscoverySources(unittest.TestCase):
    def test_social_airdrop_and_defi_are_disabled_by_default(self):
        env = {
            "MRBOT_ENABLE_SOCIAL_AUTOMATION": "0",
            "ENABLE_SOCIAL_AUTOMATION": "0",
            "MRBOT_ENABLE_AIRDROPS": "0",
            "ENABLE_AIRDROPS": "0",
            "MRBOT_ENABLE_DEFI": "0",
            "ENABLE_DEFI": "0",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertFalse(SocialSource().is_enabled())
            self.assertFalse(AirdropSource().is_enabled())
            self.assertFalse(DefiSource().is_enabled())

    def test_each_gate_opens_with_its_own_flag(self):
        with patch.dict(os.environ, {
            "MRBOT_ENABLE_SOCIAL_AUTOMATION": "1",
        }, clear=False):
            self.assertTrue(SocialSource().is_enabled())
        with patch.dict(os.environ, {
            "MRBOT_ENABLE_AIRDROPS": "1",
        }, clear=False):
            self.assertTrue(AirdropSource().is_enabled())
        with patch.dict(os.environ, {
            "MRBOT_ENABLE_DEFI": "1",
        }, clear=False):
            self.assertTrue(DefiSource().is_enabled())

    def test_disabled_source_is_never_called_by_the_live_engine(self):
        called = []

        class _TrackedSocial(SocialSource):
            def _discover(self, query=None, categories=None, page=1):
                called.append(query)
                return [_canonical()]

        with patch.dict(os.environ, {
            "MRBOT_ENABLE_SOCIAL_AUTOMATION": "0",
            "ENABLE_SOCIAL_AUTOMATION": "0",
        }, clear=False):
            found, errors, stats = DiscoveryEngine(
                sources=[_TrackedSocial()], throttle=False).discover_all()
            self.assertEqual(found, [])
            self.assertEqual(errors, {})
            self.assertEqual(called, [],
                             "the disabled live source was still executed")

        # Vacuity: the same source runs when the gate is explicitly enabled.
        with patch.dict(os.environ, {
            "MRBOT_ENABLE_SOCIAL_AUTOMATION": "1",
        }, clear=False):
            found, errors, stats = DiscoveryEngine(
                sources=[_TrackedSocial()], throttle=False).discover_all()
            self.assertEqual(len(found), 1)
            self.assertEqual(errors, {})
            self.assertEqual(called, [None])


# ── ARCH-ENG-280 (A-01) — learned state reaches the live ranking ──────────

def _learned_engine(outcomes: int = 6) -> SelfImprovementEngine:
    engine = SelfImprovementEngine()
    for index in range(outcomes):
        engine.record_outcome(OutcomeRecord(
            opportunity_id=f"o{index}",
            strategy="s1",
            platform="upwork",
            outcome="success",
            tags=["gig", "writing"],
            verified=True,
            evidence_ids=["ev-1"],
        ))
    return engine


class TestSelfImprovementReadSide(unittest.TestCase):
    def test_weights_are_seeded_and_score_is_normalized(self):
        engine = _learned_engine(6)
        self.assertIn("s1", engine.state.strategy_weights,
                      "learned strategies never got a weight entry")
        self.assertGreater(engine.score_strategy("s1"), 0.5)
        self.assertEqual(engine.score_strategy("never-seen"), 0.5,
                         "an unknown strategy must stay neutral")
        self.assertGreater(engine.get_platform_reliability("upwork"), 0.5)
        self.assertGreater(engine.get_tag_success_rate("writing"), 0.5)

    def test_cold_start_is_neutral(self):
        engine = _learned_engine(4)
        self.assertLess(4, SelfImprovementEngine.MIN_OUTCOMES)
        pipe = EarningPipeline.__new__(EarningPipeline)
        pipe._log = lambda message: None
        pipe.memory = _Memory(history={
            "o1": {"provenance": "upwork::x::strategy:s1",
                   "platform": "upwork", "category": "gig"},
        })
        pipe._self_improvement = engine
        opportunity = LegacyOpportunity(
            id="o1", source="upwork", platform="upwork", type="gig",
            payment_type="usd", estimated_usd_value=100.0,
            skill_match=0.5, effort_score=0.5, risk_level="low",
        )

        out = pipe.filter([opportunity], min_skill_match=0.0,
                          min_usd_value=0.0)

        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].skill_match, 0.5)
        self.assertFalse(hasattr(out[0], "learning_signal"),
                         "cold-start ranking must not be adjusted")

    def test_verified_outcomes_nudge_the_live_filter(self):
        engine = _learned_engine(6)
        pipe = EarningPipeline.__new__(EarningPipeline)
        pipe._log = lambda message: None
        pipe.memory = _Memory(history={
            "o1": {"provenance": "upwork::x::strategy:s1",
                   "platform": "upwork", "category": "gig",
                   "task_type": "writing"},
        })
        pipe._self_improvement = engine
        opportunity = LegacyOpportunity(
            id="o1", source="upwork", platform="upwork", type="gig",
            payment_type="usd", estimated_usd_value=100.0,
            skill_match=0.5, effort_score=0.5, risk_level="low",
        )

        out = pipe.filter([opportunity], min_skill_match=0.0,
                          min_usd_value=0.0)

        self.assertEqual(len(out), 1)
        self.assertGreater(out[0].skill_match, 0.5,
                           "learned state did not reach the live filter")
        signal = getattr(out[0], "learning_signal", None)
        self.assertIsInstance(signal, dict)
        self.assertEqual(signal["strategy"], "s1")
        self.assertGreater(signal["signal"], 0.0)
        self.assertEqual(signal["outcomes"], 6)

    def test_outcome_feed_uses_provenance_and_discovery_keys(self):
        class _RecordingEngine:
            def __init__(self):
                self.records = []

            def record_outcome(self, record):
                self.records.append(record)

        engine = _RecordingEngine()
        pipe = EarningPipeline.__new__(EarningPipeline)
        pipe._log = lambda message: None
        pipe.memory = _Memory(evidence_ids=["ev-1"])
        pipe._self_improvement = engine

        pipe._feed_self_improvement(
            "o1", "paid",
            {"provenance": "upwork::x::strategy:s1",
             "platform": "upwork", "category": "gig",
             "task_type": "writing"},
            revenue=250.0, cost=5.0, effort_hours=2.0,
        )

        self.assertEqual(len(engine.records), 1)
        record = engine.records[0]
        self.assertEqual(record.strategy, "s1",
                         "strategy was read from a key discovery never writes")
        self.assertEqual(record.platform, "upwork")
        self.assertIn("gig", record.tags)
        self.assertIn("writing", record.tags)
        self.assertTrue(record.verified)
        self.assertEqual(record.evidence_ids, ["ev-1"])


# ── ARCH-ENG-281 (D-01) — crypto operations are gated at the boundary ────

class _CryptoRequest:
    def __init__(self):
        self.request_id = "req-1"
        self.from_address = "0xfrom"
        self.to_address = "0xto"
        self.amount = 5.0
        self.currency = "USDC"
        self.chain = "ethereum"
        self.status = "pending"
        self.tx_hash = ""
        self.confirmations = 0

    def to_dict(self):
        return {"request_id": self.request_id, "to": self.to_address,
                "amount": self.amount, "currency": self.currency}


class _CryptoStub:
    def __init__(self):
        self.created = []
        self.calls = []

    def create_payment(self, frm, to, amount, currency, chain, memo=""):
        self.created.append(to)
        return _CryptoRequest()

    def get_request(self, request_id):
        return _CryptoRequest() if request_id == "req-1" else None

    def simulate_payment(self, request):
        return {"ok": True}

    def try_real_payment(self, request, rpc_url="", private_key=""):
        self.calls.append(("try_real_payment", request.request_id))
        return {"ok": True, "tx_hash": "0xtx"}

    def confirm_payment(self, request_id):
        self.calls.append(("confirm_payment", request_id))
        return {"confirmations": 3}


class _FlagGuard:
    class _Result:
        action = "flag"
        reasons = ["high-value send"]
        blocked = False

    def check(self, action):
        return self._Result()


class TestCryptoFeatureBoundary(unittest.TestCase):
    VALID_EVM = "0x" + "a1" * 20

    def setUp(self):
        HumanApprovalQueue.reset_singleton()
        from agents.earning.real_crypto_operator import RealCryptoOperator
        self.op = RealCryptoOperator.__new__(RealCryptoOperator)
        self.op.crypto = _CryptoStub()
        self.op.safety_guard = _FlagGuard()

    def test_disabled_propose_creates_nothing(self):
        from agents.earning.real_crypto_operator import RealCryptoOperator
        with patch.dict(os.environ, {
            "MRBOT_ENABLE_CRYPTO": "0", "ENABLE_CRYPTO": "0",
        }, clear=False):
            result = RealCryptoOperator.propose_payment(
                self.op, "0xfrom", self.VALID_EVM, 5.0, "USDC", Chain.ETHEREUM)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "disabled")
        self.assertEqual(self.op.crypto.created, [],
                         "a disabled crypto boundary created a payment request")

    def test_enabled_propose_still_validates_and_reaches_the_queue(self):
        from agents.earning.real_crypto_operator import RealCryptoOperator
        with patch.dict(os.environ, {"MRBOT_ENABLE_CRYPTO": "1"},
                        clear=False):
            result = RealCryptoOperator.propose_payment(
                self.op, "0xfrom", self.VALID_EVM, 5.0, "USDC", Chain.ETHEREUM)
            # Vacuity for the disabled test: with the flag on, a refusal must
            # be for a content reason, never "disabled".
            bad = RealCryptoOperator.propose_payment(
                self.op, "0xfrom", "not-an-address", 5.0, "USDC", Chain.ETHEREUM)
        self.assertNotEqual(bad["status"], "disabled")
        self.assertEqual(len(self.op.crypto.created), 1)
        self.assertTrue(result["ok"])

    def test_disabled_send_never_reaches_the_chain(self):
        from agents.earning.real_crypto_operator import RealCryptoOperator
        with patch.dict(os.environ, {
            "MRBOT_ENABLE_CRYPTO": "0", "ENABLE_CRYPTO": "0",
        }, clear=False):
            result = RealCryptoOperator.confirm_and_send(
                self.op, "req-1", approval_id="anything")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "disabled")
        self.assertEqual(self.op.crypto.calls, [],
                         "a disabled crypto send reached the chain path")


# ── ARCH-ENG-284 (U-01) — quarantined instructions have a review surface ──

class _EmptyQueue:
    def pending(self):
        return []


class _LogSignal:
    def __init__(self):
        self.messages = []

    def emit(self, message):
        self.messages.append(message)


class TestQuarantineReviewSurface(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QWidget
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = AgentDB(os.path.join(self.tmp.name, "gate.db"))
        from agents.safety.instructions import InstructionGate
        self.gate = InstructionGate(self.db)
        self.parent = QWidget()
        self.parent.instruction_gate = self.gate
        self.parent.log_signal = _LogSignal()
        self.url = "https://example.test/SKILL.md"
        self.db.add_quarantined_instruction(
            self.url, "skill.md", "Demo skill", "hash-1", "instructions")
        self.tab = None

    def tearDown(self):
        if self.tab is not None:
            self.tab.cleanup()
            self.tab.deleteLater()
        self.parent.deleteLater()
        try:
            self.db._conn.close()
        except Exception:
            pass
        self.tmp.cleanup()

    def _build(self):
        from agents.safety.approval import HumanApprovalQueue
        from gui.tabs.safety_tools_tab import SafetyTab
        with patch.object(HumanApprovalQueue, "instance",
                          return_value=_EmptyQueue()):
            self.tab = SafetyTab(parent=self.parent)
        self.tab.refresh_timer.stop()
        self.tab.set_instruction_gate(self.gate)

    def test_pending_instruction_is_listed_and_approvable(self):
        self._build()
        self.assertEqual(self.tab.quarantine_table.rowCount(), 1)
        self.assertIn("Pending: 1",
                      self.tab.quarantine_counts_label.text())
        self.assertFalse(self.db.in_instruction_allowlist(self.url),
                         "the fixture was already allowed before review")

        self.tab.quarantine_table.selectRow(0)
        self.tab._on_quarantine_decision(True)

        self.assertTrue(self.db.in_instruction_allowlist(self.url),
                        "the review action did not reach the gate")
        self.assertEqual(self.tab.quarantine_table.rowCount(), 0)
        self.assertTrue(any("APPROVED" in message
                            for message in self.parent.log_signal.messages))

    def test_blacklist_is_the_other_live_decision(self):
        self._build()
        self.tab.quarantine_table.selectRow(0)
        self.tab._on_quarantine_decision(False)

        self.assertTrue(self.db.in_instruction_blacklist(self.url))
        self.assertEqual(self.tab.quarantine_table.rowCount(), 0)


# ── ARCH-ENG-287 (Z-01) — independent evidence reconciliation ─────────────

class _Label:
    def __init__(self):
        self.value = ""

    def setText(self, text):
        self.value = text

    def text(self):
        return self.value


class _LifecycleFixture:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = AgentDB(os.path.join(self.tmp.name, "lifecycle.db"))
        self.store = EvidenceStore(self.db)
        self.lifecycle = OpportunityLifecycleTracker(evidence_store=self.store)
        self.submission = Evidence.create(
            source="upwork", evidence_type="platform_submission",
            subject_id="J3", status=EvidenceStatus.VERIFIED,
            verification_method="authenticated_api_response",
            verification_level=VerificationLevel.L3_EXTERNAL_SOURCE,
        )
        self.completion = Evidence.create(
            source="upwork", evidence_type="completion_confirmation",
            subject_id="J3", status=EvidenceStatus.VERIFIED,
            verification_method="authenticated_api_response",
            verification_level=VerificationLevel.L3_EXTERNAL_SOURCE,
        )
        self.payment = Evidence.create(
            source="operator", evidence_type="manual_attestation",
            subject_id="J3", amount=250.0, currency="USD",
            status=EvidenceStatus.VERIFIED,
            verification_method="manual_attestation",
            verification_level=VerificationLevel.L1_SELF_REPORTED,
        )
        for evidence in (self.submission, self.completion, self.payment):
            self.store.record(evidence)
        state = self.lifecycle._ensure("J3")
        state.current_stage = "submitted"
        state.status = "active"
        state.last_amount = 250.0

    def close(self):
        try:
            self.db._conn.close()
        except Exception:
            pass
        self.tmp.cleanup()


class TestEvidenceReconciliationSurface(unittest.TestCase):
    def setUp(self):
        self.fx = _LifecycleFixture()
        self.label = _Label()
        self.log = _LogSignal()
        self.fake = SimpleNamespace(
            pay_status=self.label,
            log_signal=self.log,
            earning_pipeline=SimpleNamespace(
                lifecycle=self.fx.lifecycle,
                memory=_Memory(),
            ),
        )

    def tearDown(self):
        self.fx.close()

    def _call(self, evidence_id, method, opp_id="J3", note="bank statement"):
        MainWindow._reconcile_paid_evidence(
            self.fake, opp_id, evidence_id, method, note)

    def test_operator_reconciliation_promotes_manual_payment_and_books_paid(self):
        self._call(self.fx.payment.id, "external_reconciliation")

        reconciled = self.fx.store.get(self.fx.payment.id)
        self.assertEqual(reconciled.status, EvidenceStatus.VERIFIED)
        self.assertGreaterEqual(
            reconciled.verification_level,
            VerificationLevel.L3_EXTERNAL_SOURCE)
        self.assertEqual(reconciled.verification_method,
                         "external_reconciliation")
        self.assertEqual(self.fx.lifecycle.get_state("J3")["status"], "paid")
        self.assertIn("VERIFIED via external_reconciliation", self.label.text())

    def test_blank_id_selects_the_latest_unresolved_payment(self):
        self._call("", "authenticated_api_response")

        reconciled = self.fx.store.get(self.fx.payment.id)
        self.assertEqual(reconciled.verification_method,
                         "authenticated_api_response")
        self.assertIn("VERIFIED via authenticated_api_response",
                      self.label.text())

    def test_unknown_explicit_id_is_refused_without_substitution(self):
        self._call("does-not-exist", "external_reconciliation")

        after = self.fx.store.get(self.fx.payment.id)
        self.assertEqual(after.verification_method, "manual_attestation")
        self.assertEqual(self.fx.lifecycle.get_state("J3")["current_stage"],
                         "submitted")
        self.assertIn("not found", self.label.text())

    def test_non_independent_method_is_refused_and_changes_nothing(self):
        before = self.fx.store.get(self.fx.payment.id)
        self._call(self.fx.payment.id, "manual_attestation")

        after = self.fx.store.get(self.fx.payment.id)
        self.assertEqual(after.verification_level,
                         before.verification_level)
        self.assertEqual(after.verification_method, before.verification_method)
        self.assertEqual(self.fx.lifecycle.get_state("J3")["current_stage"],
                         "submitted")
        self.assertIn("not an independent method", self.label.text())

    def test_evidence_from_another_opportunity_is_refused(self):
        foreign = Evidence.create(
            source="operator", evidence_type="manual_attestation",
            subject_id="J4", amount=250.0, currency="USD",
            status=EvidenceStatus.VERIFIED,
            verification_method="manual_attestation",
            verification_level=VerificationLevel.L1_SELF_REPORTED,
        )
        self.fx.store.record(foreign)

        self._call(foreign.id, "external_reconciliation")

        after = self.fx.store.get(foreign.id)
        self.assertEqual(after.verification_method, "manual_attestation")
        self.assertEqual(self.fx.lifecycle.get_state("J3")["current_stage"],
                         "submitted")
        self.assertIn("does not belong", self.label.text())


# ── ARCH-ENG-283 (G-05) — the live order path has a production caller ─────

class _LiveAdapter:
    exchange_id = "fake"


class _RecordingService:
    def __init__(self):
        self.calls = []

    def execute_order(self, intent, assessment, approval_id=""):
        self.calls.append((intent, assessment, approval_id))
        return {"execution_mode": "live", "order": {"id": "order-1"}}


class _FakeQueue:
    def __init__(self, item):
        self.item = item

    def find_by_id(self, item_id):
        return self.item if item_id == self.item.id else None


class TestLiveOrderApprovalPath(unittest.TestCase):
    def setUp(self):
        HumanApprovalQueue.reset_singleton()

    def _intent(self):
        return TradeIntent(
            exchange="coinbase", symbol="BTC/USD", side="buy",
            quantity=0.01, order_type="market", limit_price=0.0,
            expected_profit_pct=1.0, strategy_confidence=0.9,
        )

    def test_canonical_flag_enables_live_and_the_old_spelling_does_not(self):
        with patch.dict(os.environ, {
            "MRBOT_LIVE_TRADING_ENABLED": "1",
        }, clear=False):
            for key in ("MRBOT_ENABLE_LIVE_TRADING", "ENABLE_LIVE_TRADING"):
                os.environ.pop(key, None)
            wrong = LiveTradingService(adapter=_LiveAdapter())
        self.assertFalse(
            wrong.live_enabled,
            "the unused MRBOT_LIVE_TRADING_ENABLED spelling still gates live")

        with patch.dict(os.environ, {"MRBOT_ENABLE_LIVE_TRADING": "1"},
                        clear=False):
            right = LiveTradingService(adapter=_LiveAdapter())
        self.assertTrue(right.live_enabled)
        self.assertTrue(right.status()["live_enabled"])

    def test_propose_order_records_the_exact_intent_for_the_human(self):
        service = LiveTradingService(adapter=_LiveAdapter())
        assessment = RiskAssessment(
            decision="needs_approval", risk_score=0.4,
            factors={"last_price": 100.0}, reasons=("volatility",),
        )

        proposal = service.propose_order(self._intent(), assessment)

        self.assertEqual(proposal["status"], "awaiting_approval")
        item = HumanApprovalQueue.instance().find_by_id(
            proposal["approval_id"])
        self.assertIsNotNone(item)
        self.assertEqual(item.requested_by, "live_trading")
        self.assertEqual(item.kind, ApprovalKind.ACTION)
        self.assertEqual(item.payload["intent"]["symbol"], "BTC/USD")
        self.assertEqual(item.payload["intent"]["quantity"], 0.01)

    def test_approval_decision_routes_a_live_order_to_execution(self):
        item = ApprovalItem(
            kind=ApprovalKind.ACTION, title="Live BUY 0.01 BTC/USD",
            description="review", requested_by="live_trading",
            payload={"intent": self._intent().__dict__},
            details={"assessment": {"last_price": 100.0}, "reasons": ["x"]},
        )
        item.status = ApprovalStatus.APPROVED
        calls = {"live": [], "generic": []}
        fake = SimpleNamespace(
            _refresh_approval_alert=lambda: None,
            approval_queue=_FakeQueue(item),
            log_signal=_LogSignal(),
            _execute_approved_live_order=lambda chosen: calls["live"].append(chosen),
            _execute_approved_action=lambda chosen: calls["generic"].append(chosen),
        )

        MainWindow._on_approval_decided(fake, item.id, "APPROVED", "")

        self.assertEqual(calls["live"], [item],
                         "a live order fell through to the generic dispatcher")
        self.assertEqual(calls["generic"], [])

        # Vacuity: an ordinary ACTION still takes the generic branch.
        ordinary = ApprovalItem(
            kind=ApprovalKind.ACTION, title="Ordinary action",
            description="review", requested_by="chat",
            payload={"tool": "some_tool"},
        )
        ordinary.status = ApprovalStatus.APPROVED
        fake.approval_queue = _FakeQueue(ordinary)
        MainWindow._on_approval_decided(fake, ordinary.id, "APPROVED", "")
        self.assertEqual(calls["generic"], [ordinary])

    def test_handler_reconstructs_and_submits_the_approved_order_once(self):
        item = ApprovalItem(
            kind=ApprovalKind.ACTION, title="Live BUY 0.01 BTC/USD",
            description="review", requested_by="live_trading",
            payload={"intent": self._intent().__dict__},
            details={"assessment": {"last_price": 100.0}, "reasons": ["x"]},
        )
        service = _RecordingService()
        fake = SimpleNamespace(
            live_trading_service=service,
            log_signal=_LogSignal(),
            _executed_approval_ids=set(),
        )

        MainWindow._execute_approved_live_order(fake, item)
        MainWindow._execute_approved_live_order(fake, item)

        self.assertEqual(len(service.calls), 1,
                         "a re-delivered approval submitted a second order")
        intent, assessment, approval_id = service.calls[0]
        self.assertEqual(intent.symbol, "BTC/USD")
        self.assertEqual(intent.quantity, 0.01)
        self.assertEqual(approval_id, item.id)
        self.assertTrue(any("duplicate" in message.lower()
                            for message in fake.log_signal.messages))

    def test_worker_assesses_then_proposes_off_the_gui_thread(self):
        class _WorkerService:
            def sync_portfolio(self):
                return "portfolio"

            def fetch_market_snapshot(self, symbol):
                return "market"

            def assess_order(self, intent, portfolio, market):
                return RiskAssessment(
                    decision="needs_approval", risk_score=0.2,
                    factors={"last_price": 100.0},
                    reasons=("strategy confidence",),
                )

            def propose_order(self, intent, assessment):
                return {"ok": True, "status": "awaiting_approval",
                        "approval_id": "approval-1"}

        received = []
        worker = LiveOrderProposalWorker(_WorkerService(), self._intent())
        worker.finished.connect(received.append)
        worker.run()

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["status"], "awaiting_approval")
        self.assertEqual(received[0]["approval_id"], "approval-1")
        self.assertEqual(received[0]["decision"], "needs_approval")


if __name__ == "__main__":
    unittest.main()
