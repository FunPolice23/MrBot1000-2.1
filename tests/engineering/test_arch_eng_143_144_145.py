"""ARCH-ENG-143/144/145 — three reachable defects on the real-money and
budget paths, each reproduced by execution BEFORE the fix.

ARCH-ENG-143 (P0/P1) — the autonomous loop computed a verified payout and then
threw it away. `AutonomousLoop._stage_verify` established `verified=True` and
`payment_amount` from the EvidenceStore (policy-eligible SUBMITTED->PAID or
CLAIMED->REVENUE_REALIZED, payment evidence VERIFIED at >= L3), then called
`lifecycle.mark_paid_verified(id, amount=...)` with NO `evidence=` kwarg. Inside
`mark_paid_verified` an `evidence is None` call skips every policy gate and
lands in the fail-closed tail ("no evidence attached" -> stays 'submitted'); the
next line then overwrote the freshly-computed `verified` with
`status != "paid"`. Reproduced on clean HEAD against the REAL loop, REAL
OpportunityLifecycleTracker and REAL EvidenceStore, with a genuine chain of
platform_submission + completion_confirmation + a $750 on-chain balance_delta:

    loop computed : eligible=True verified=True amount=750.0
    AS SHIPPED    -> result.paid=False  payment_amount=750.0
                     lifecycle.status='active'  last_amount=0.0

So genuinely verified crypto/airdrop revenue was computed and discarded, and
because `EconomicAccounting` reads the EVIDENCE store (not the lifecycle) both
authorities agreed on 0.0 — the loss was silent, not flagged. The fix passes the
Evidence object that satisfied the gate, re-entering the same policy contract the
stage had already checked, so the lifecycle reaches 'paid' on evidence rather
than on the caller's assertion.

ARCH-ENG-144 (P1) — WinRateGuard failed OPEN. `SubmissionRamp._platform_key`
wrote reputation under `platform.strip().title()` while every reader
(`EarningPipeline.filter`, `OpportunityIntelligence`, `AutonomousLoop`,
`SelfAudit`, `DiscoveryScheduler`) queried the RAW platform string. Reproduced:
8 real losses recorded through the real ramp stored `total=9, success_rate=0.00`
under 'Upwork' while `get_platform_reputation('upwork')` returned `total=0`, so
`should_decline` reported insufficient_data and a proven 0%-win-rate platform
was NOT filtered — the bot kept spending proposals + LLM $ on proven losers.
`EarningMemory.platform_key` is now the single authority used by BOTH sides.

ARCH-ENG-145 (P2) — the project's own primary brain was classified as a BILLABLE
cloud provider. `is_local_provider` squashed '-', '_' and ' ' but not '.', so
"llama.cpp" (the display name `ProviderManager._detect_llamacpp` puts on
ProviderInfo.name) missed LOCAL_PROVIDERS' "llamacpp" entry. A misclassified
local brain takes the cloud tier (1.0/sec, 500 calls/day) and becomes
$-skippable by CostGuard — the exact inversion `agents/safety/cost.py`'s own
docstring warns about. Confirmed failing on clean HEAD by
tests/safety/test_provider_rate_limiter.py::test_local_providers.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.database import AgentDB
from app.earning_memory import EarningMemory
from app.earning_pipeline import EarningPipeline, Opportunity
from agents.earning.opportunity_lifecycle import OpportunityLifecycleTracker
from agents.earning.submission_ramp import SubmissionRamp
from agents.evidence.evidence import (
    Evidence,
    EvidenceStatus,
    VerificationLevel,
    VerificationResult,
)
from agents.evidence.evidence_policy import is_transition_eligible
from agents.evidence.evidence_store import EvidenceStore
from agents.earning.payment_evidence import TRANSITION_PAYMENT_EVIDENCE_TYPES
from agents.earning.win_rate_guard import WinRateGuard
from agents.services.autonomous_loop import AutonomousLoop


# ── helpers ──────────────────────────────────────────────────────────────────

def _verified(evidence_type, level, amount=0.0, subject_id="opp"):
    ev = Evidence.create(source="chain", evidence_type=evidence_type,
                         subject_type="opportunity", subject_id=subject_id,
                         amount=amount)
    return ev.verify(VerificationResult(
        status=EvidenceStatus.VERIFIED, method="external_api",
        level=level, actor="test"))


def _verified_store(tmpdir, subject_id="opp", payout=750.0):
    """A real EvidenceStore holding a genuine, fully-verified payout chain."""
    store = EvidenceStore(AgentDB(os.path.join(tmpdir, "evidence.db")))
    store.record(_verified("platform_submission",
                           VerificationLevel.L3_EXTERNAL_SOURCE,
                           subject_id=subject_id))
    store.record(_verified("completion_confirmation",
                           VerificationLevel.L3_EXTERNAL_SOURCE,
                           subject_id=subject_id))
    store.record(_verified("balance_delta", VerificationLevel.L5_CRYPTOGRAPHIC,
                           amount=payout, subject_id=subject_id))
    return store


def _loop(store, lifecycle):
    loop = AutonomousLoop.__new__(AutonomousLoop)
    loop.evidence_store = store
    loop.lifecycle = lifecycle
    loop.accounting = None
    loop.run_store = None
    return loop


# ── ARCH-ENG-143 ─────────────────────────────────────────────────────────────

class TestStageVerifyBooksVerifiedPayout(unittest.TestCase):
    """The autonomous loop must not discard a payout it has verified."""

    def test_fully_verified_onchain_payout_is_paid(self):
        """The exact reproduction: $750 L5 balance delta behind a real chain."""
        tmp = tempfile.mkdtemp(prefix="arch143_a_")
        store = _verified_store(tmp)
        tracker = OpportunityLifecycleTracker(
            state_path=os.path.join(tmp, "life.json"), evidence_store=store)
        loop = _loop(store, tracker)

        result = SimpleNamespace(opportunity_id="opp", errors=[], stages=[])
        opp = SimpleNamespace(id="opp", opportunity_id="opp", platform="ugig")
        loop._stage_verify(result, opp, SimpleNamespace(opportunity_id="opp"))

        self.assertEqual(result.payment_amount, 750.0)
        self.assertTrue(result.paid,
                        "a policy-eligible L5 payout must reach paid=True")
        state = tracker._states["opp"]
        self.assertEqual(state.status, "paid")
        self.assertEqual(state.last_amount, 750.0,
                         "the verified amount must be booked, not dropped")
        self.assertEqual(list(result.errors), [])

    def test_payment_evidence_is_handed_to_the_lifecycle(self):
        """The fix is specifically that the Evidence object is passed through.

        `mark_paid_verified(id, amount=...)` with no evidence fails closed, so
        pinning the kwarg guards the actual mechanism, not just the outcome.
        """
        tmp = tempfile.mkdtemp(prefix="arch143_b_")
        store = _verified_store(tmp)

        seen = {}

        class _Spy:
            def mark_paid_verified(self, opp_id, amount=0.0, evidence=None):
                seen["evidence"] = evidence
                return SimpleNamespace(status="paid")

        loop = _loop(store, _Spy())
        result = SimpleNamespace(opportunity_id="opp", errors=[], stages=[])
        loop._stage_verify(result, SimpleNamespace(id="opp", opportunity_id="opp"),
                           SimpleNamespace(opportunity_id="opp"))

        ev = seen.get("evidence")
        self.assertIsNotNone(ev, "mark_paid_verified must receive the Evidence")
        self.assertIn(ev.evidence_type, TRANSITION_PAYMENT_EVIDENCE_TYPES)
        self.assertEqual(ev.amount, 750.0)
        self.assertTrue(result.paid)

    def test_unverified_payment_still_fails_closed(self):
        """The fix must not become a way to book unverified money."""
        tmp = tempfile.mkdtemp(prefix="arch143_c_")
        store = EvidenceStore(AgentDB(os.path.join(tmp, "evidence.db")))
        # A $5000 payment claim that is only SELF-REPORTED (no verification).
        claim = Evidence.create(source="test", evidence_type="payment_gross",
                                subject_type="opportunity", subject_id="opp",
                                amount=5000.0)
        store.record(claim)
        tracker = OpportunityLifecycleTracker(
            state_path=os.path.join(tmp, "life.json"), evidence_store=store)
        loop = _loop(store, tracker)

        result = SimpleNamespace(opportunity_id="opp", errors=[], stages=[])
        loop._stage_verify(result, SimpleNamespace(id="opp", opportunity_id="opp"),
                           SimpleNamespace(opportunity_id="opp"))

        self.assertFalse(result.paid, "an L1 self-report is not a payout")
        self.assertEqual(result.payment_amount, 0.0)
        # No lifecycle state is created at all when nothing was verified.
        state = tracker._states.get("opp")
        if state is not None:
            self.assertNotEqual(state.status, "paid")
            self.assertEqual(state.last_amount, 0.0)

    def test_advertised_amount_never_becomes_payment_amount(self):
        """A verified chain whose payment evidence carries no amount books 0."""
        tmp = tempfile.mkdtemp(prefix="arch143_d_")
        store = _verified_store(tmp, payout=0.0)
        tracker = OpportunityLifecycleTracker(
            state_path=os.path.join(tmp, "life.json"), evidence_store=store)
        loop = _loop(store, tracker)

        result = SimpleNamespace(opportunity_id="opp", errors=[], stages=[])
        opp = SimpleNamespace(id="opp", opportunity_id="opp",
                              advertised_amount=9999.0)
        loop._stage_verify(result, opp, SimpleNamespace(opportunity_id="opp"))

        self.assertEqual(result.payment_amount, 0.0,
                         "amount comes from EVIDENCE, never from the listing")

    def test_unverified_balance_delta_is_not_paid(self):
        """A crypto-chain payout still needs the L5 cryptographic floor.

        Note the deliberate asymmetry with the freelance chain: an L5 on-chain
        `balance_delta` DOES satisfy CLAIMED->REVENUE_REALIZED on its own (there
        is no Upwork-style submission stage to require) — that is the documented
        intent of `mark_paid_verified`. What it may never do is qualify while
        merely SELF-REPORTED. An unverified delta books nothing.
        """
        tmp = tempfile.mkdtemp(prefix="arch143_e_")
        store = EvidenceStore(AgentDB(os.path.join(tmp, "evidence.db")))
        # Same evidence type, but never verified -> L1 self-report.
        store.record(Evidence.create(
            source="test", evidence_type="balance_delta",
            subject_type="opportunity", subject_id="opp", amount=750.0))
        tracker = OpportunityLifecycleTracker(
            state_path=os.path.join(tmp, "life.json"), evidence_store=store)
        loop = _loop(store, tracker)

        result = SimpleNamespace(opportunity_id="opp", errors=[], stages=[])
        loop._stage_verify(result, SimpleNamespace(id="opp", opportunity_id="opp"),
                           SimpleNamespace(opportunity_id="opp"))

        self.assertFalse(result.paid,
                         "the cryptographic floor is what makes it revenue")
        self.assertEqual(result.payment_amount, 0.0)
        state = tracker._states.get("opp")
        if state is not None:
            self.assertNotEqual(state.status, "paid")
            self.assertEqual(state.last_amount, 0.0)


# ── ARCH-ENG-144 ─────────────────────────────────────────────────────────────

class TestWinRateGuardPlatformKey(unittest.TestCase):
    """Write and read must agree on the platform key, or the guard fails open."""

    def _memory(self, tmp):
        return EarningMemory(db_path=os.path.join(tmp, "mem.db"))

    def test_write_and_read_agree_on_raw_spelling(self):
        tmp = tempfile.mkdtemp(prefix="arch144_a_")
        mem = self._memory(tmp)
        SubmissionRamp(memory=mem).record_reject("upwork")
        rep = mem.get_platform_reputation("upwork")
        self.assertGreater(rep["total"], 0,
                           "the recorder's own key must be readable back")

    def test_proven_loser_is_declined_not_insufficient_data(self):
        tmp = tempfile.mkdtemp(prefix="arch144_b_")
        mem = self._memory(tmp)
        for _ in range(8):
            SubmissionRamp(memory=mem).record_reject("upwork")
        rep = mem.get_platform_reputation("upwork")
        self.assertEqual(rep["success_rate"], 0.0)
        self.assertGreaterEqual(rep["total"], WinRateGuard.from_env().min_samples)
        self.assertTrue(WinRateGuard.from_env().should_decline(rep),
                        "0% win-rate past the sample floor MUST decline")

    def test_filter_actually_drops_the_proven_loser(self):
        """End-to-end through the real EarningPipeline.filter()."""
        tmp = tempfile.mkdtemp(prefix="arch144_c_")
        mem = self._memory(tmp)
        for _ in range(8):
            SubmissionRamp(memory=mem).record_reject("upwork")

        pipe = EarningPipeline.__new__(EarningPipeline)
        pipe.memory = mem
        pipe._log = lambda *a, **k: None

        opp = Opportunity(id="J-1", source="upwork_api", platform="upwork",
                          type="gig", title="Write 10 posts",
                          description="content", payment_type="usd",
                          payment_amount=500.0, estimated_usd_value=500.0,
                          effort_score=0.3, skill_match=0.0, risk_level="low")
        self.assertEqual(pipe.filter([opp], max_risk="medium"), [],
                         "a proven-losing platform must be filtered out")

    def test_every_production_platform_spelling_round_trips(self):
        """The real spellings discovery/freelance sources emit."""
        tmp = tempfile.mkdtemp(prefix="arch144_d_")
        mem = self._memory(tmp)
        ramp = SubmissionRamp(memory=mem)
        for platform in ("upwork", "fiverr", "uGig", "reddit", "prolific"):
            for _ in range(6):
                ramp.record_reject(platform)
            rep = mem.get_platform_reputation(platform)
            self.assertEqual(rep["success_rate"], 0.0, platform)
            self.assertGreaterEqual(rep["total"], 6, platform)
            self.assertTrue(WinRateGuard.from_env().should_decline(rep), platform)

    def test_cold_start_still_not_declined(self):
        """The fix must not turn the guard into a blanket decline."""
        tmp = tempfile.mkdtemp(prefix="arch144_e_")
        mem = self._memory(tmp)
        SubmissionRamp(memory=mem).record_reject("upwork")   # 1 sample only
        rep = mem.get_platform_reputation("upwork")
        self.assertFalse(WinRateGuard.from_env().should_decline(rep),
                         "insufficient data must stay insufficient")

    def test_a_win_is_still_a_win(self):
        tmp = tempfile.mkdtemp(prefix="arch144_f_")
        mem = self._memory(tmp)
        ramp = SubmissionRamp(memory=mem)
        for _ in range(4):
            ramp.record_reject("upwork")
        ramp.record_accept("upwork", revenue=250.0)
        rep = mem.get_platform_reputation("upwork")
        self.assertEqual(rep["success"], 1)
        self.assertGreater(rep["success_rate"], 0.0)

    def test_platform_key_is_the_single_authority(self):
        """The ramp must not carry a second, divergent normalisation."""
        tmp = tempfile.mkdtemp(prefix="arch144_g_")
        mem = self._memory(tmp)
        ramp = SubmissionRamp(memory=mem)
        for raw in ("upwork", " upwork ", "UPWORK", "Upwork"):
            self.assertEqual(ramp._platform_key(raw), mem.platform_key(raw), raw)


# ── ARCH-ENG-145 ─────────────────────────────────────────────────────────────

class TestLocalProviderClassification(unittest.TestCase):
    """llama.cpp is this project's own brain; it must never be billable."""

    def _local(self, name):
        from agents.safety.provider_rate_limiter import is_local_provider
        return is_local_provider(name)

    def test_llama_cpp_spellings_are_local_and_uncapped(self):
        from agents.safety.provider_rate_limiter import _defaults_for
        for n in ("llama.cpp", "llama-cpp", "llamacpp", "Llama.CPP"):
            self.assertTrue(self._local(n), n)
            rate, cap = _defaults_for(n)
            self.assertEqual(cap, 0, f"{n} is on-machine — no $ cap")
            self.assertGreaterEqual(rate, 2.0, f"{n} is hardware-bound")

    def test_other_local_backends_stay_local(self):
        for n in ("ollama", "Ollama", "local", "vllm", "lmstudio", "lm-studio",
                  "LM Studio", "koboldcpp", "big-brain", "small-brain"):
            self.assertTrue(self._local(n), n)

    def test_cloud_vendors_stay_cloud(self):
        """The dot-squash must not pull a cloud vendor into the free tier."""
        for n in ("openai", "anthropic", "groq", "openrouter", "nous",
                  "deepseek", "gemini", "mistral", "together", "google"):
            self.assertFalse(self._local(n), n)

    def test_cloud_marker_still_wins_over_a_local_substring(self):
        """llama-cloud / localstack-cloud contain local tokens but are remote."""
        for n in ("llama-cloud", "localstack-cloud", "lmstudio-cloud"):
            self.assertFalse(self._local(n), n)

    def test_cost_guard_never_skips_the_local_brain(self):
        """The consequence that matters: CostGuard must not spend money here."""
        from agents.safety.cost import CostGuard

        class _SpentDB:
            """A db reporting $50 of spend in the last 24h (cap already blown)."""

            def get_llm_cost_usd(self, days=1):
                return 50.0

        guard = CostGuard(daily_budget_usd=0.01)
        db = _SpentDB()
        self.assertTrue(guard.is_exceeded(db), "the cap must register as blown")
        for n in ("llama.cpp", "llamacpp", "big-brain", "small-brain"):
            self.assertFalse(guard.should_skip(db, n),
                             f"{n} is free — the budget guard must never skip it")
        # A cloud provider IS skipped once the cap is blown.
        self.assertTrue(guard.should_skip(db, "openai"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
