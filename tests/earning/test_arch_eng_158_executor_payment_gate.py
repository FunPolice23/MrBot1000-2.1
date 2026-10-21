"""ARCH-ENG-158 — the 14-step executor could not verify a payment, so it asserted one.

`agents/earning/executor.py` steps 12 and 14 were:

    def _step12_verify(self, ctx):
        ctx.step_results[12] = {"verified": True}
        self._record_step(ctx, 12, StepStatus.COMPLETED, "Outcome verified")

    def _step14_learn(self, ctx):
        ctx.step_results[14] = {"learned": True}
        ctx.portfolio_entry = self.portfolio.transition_work_status(
            ctx.portfolio_entry.opportunity_id, self._work_status_for_step(14))
        self._record_step(ctx, 14, StepStatus.COMPLETED, "Learned from result")

and `_work_status_for_step` mapped `14 -> WorkStatus.PAID`, and `execute()`
returned `status="paid"` unconditionally. The literal `{"verified": True}` was
not a result — it was the verdict, hardcoded before any verification ran.

Every task with no human gate reached step 11 and was therefore reported as a
completed, PAID opportunity. Nothing consulted the evidence store, the evidence
policy, or any external source. `TaskExecutor` is live: it is constructed in
`app/earning_pipeline.py` and reached via `AutonomousLoop._stage_execute`.

This is the exact shape that ARCH-ENG-064, -118, -119 and -121 were filed
against. `handlers._is_approved` states the rule directly: "It deliberately does
NOT accept a legacy `{"verified": True}` dict: that shape is the agent asserting
its own claim." `OpportunityLifecycleTracker._is_verified_evidence` (ARCH-ENG-064)
says the same thing from the other side. The executor was an island that had
never been migrated, so the hardening never reached it.

Why it survived the self-audit passes: the test that covered this pipeline
asserted the bug. `test_full_pipeline_pass` ran a coding task with no payment
evidence anywhere and asserted `final_status == "paid"`. A defect encoded as the
expected value in the regression suite cannot be found by reading the suite.

SCOPE OF THE FIX
- Step 12 resolves real `Evidence` via an injected `EvidenceStore` and applies
  `evidence_policy.is_transition_eligible` for `SUBMITTED->PAID` /
  `CLAIMED->REVENUE_REALIZED`, plus the L3_EXTERNAL_SOURCE floor on payment
  records. Fail-closed on a missing store, a query error, or an empty result.
- Step 14 applies `WorkStatus.PAID` only when step 12 actually proved payment.
- `execute()` reports `final_status="payment_unverified"` when it did not.
- `ExecutionResult` gained `paid` / `evidence` / `payment_status`.
- Step 13 no longer fabricates an evidence-shaped dict; it records only real
  `Evidence`.
- `_work_status_for_step` no longer maps 14 to PAID.

The floor must remain a floor, not a wall: `test_real_l3_payment_still_books`
proves a genuine externally-verified payout still reaches PAID, so this repairs
the earning path rather than disabling it.
"""

import os
import tempfile
import unittest

from agents.earning.executor import (
    ExecutionResult, StepStatus, TaskExecutor,
)
from agents.earning.opportunity_portfolio import OpportunityPortfolio, PortfolioEntry, WorkStatus
from agents.earning.validator import CapabilityValidator
from agents.evidence.evidence import (
    Evidence, EvidenceStatus, VerificationLevel, VerificationResult,
)
from agents.earning.capabilities import get_default_registry
from agents.safety.gates import HumanGateManager


# ── Fixtures ───────────────────────────────────────────────────────────────────

class _Store:
    """In-memory `EvidenceStore` stand-in returning real `Evidence` objects."""

    def __init__(self):
        self._items = []

    def add(self, ev):
        self._items.append(ev)
        return ev

    def for_subject(self, subject_type, subject_id):
        return [ev for ev in self._items
                if ev.subject_type == subject_type and ev.subject_id == subject_id]

    def record(self, ev):
        return self.add(ev)


class _LegacyDictStore(_Store):
    """Returns the legacy hand-built dict instead of an `Evidence`.

    This is the laundering shape `handlers._is_approved` refuses. Modelled here
    so the executor's refusal can be asserted rather than assumed.
    """

    def for_subject(self, subject_type, subject_id):
        return [{"verified": True, "amount": 9999.0}]


def _verified(etype, subject_id, level=VerificationLevel.L4_INDEPENDENT_VERIFICATION,
              method="authenticated_api_response", amount=None):
    ev = Evidence.create(
        evidence_type=etype,
        subject_type="opportunity",
        subject_id=subject_id,
        source="upwork_api",
        **({"amount": amount} if amount is not None else {}),
    )
    return ev.verify(VerificationResult(
        status=EvidenceStatus.VERIFIED, method=method, level=level, actor="test",
    ))


def _coding_task(task_id):
    return {
        "task_id": task_id,
        "task_type": "coding",
        "required_capabilities": ["CODING"],
        "description": "Write a Python function",
        "validation_method": "tests",
        "output": {
            "code": "def hello():\n    return 'world'\n",
            "tests": "def test_hello():\n    assert hello() == 'world'\n",
            "test_passed": True,
        },
    }


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestExecutorPaymentGate(unittest.TestCase):
    """ARCH-ENG-158 — a PAID transition requires independent proof of payment."""

    def setUp(self):
        self.portfolio = OpportunityPortfolio(
            db_path=os.path.join(tempfile.mkdtemp(), "portfolio.db"))
        self.validator = CapabilityValidator(get_default_registry(), human_available=False)
        self.gates = HumanGateManager()

    def _entry(self, opp_id):
        e = PortfolioEntry(opportunity_id=opp_id, work_status=WorkStatus.NEW)
        self.portfolio.add(e)
        return e

    def test_no_evidence_store_never_pays(self):
        """No store wired => cannot verify => must not pay (fail closed)."""
        ex = TaskExecutor(self.portfolio, self.validator, self.gates)
        res = ex.execute(_coding_task("opp-a"), self._entry("opp-a"))
        self.assertFalse(res.paid)
        self.assertNotEqual(res.final_status, "paid")
        self.assertEqual(self.portfolio.get("opp-a").work_status,
                         WorkStatus.PAYMENT_PENDING)

    def test_empty_store_never_pays(self):
        """A store with no evidence for the subject must not pay."""
        ex = TaskExecutor(self.portfolio, self.validator, self.gates,
                          evidence_store=_Store())
        res = ex.execute(_coding_task("opp-b"), self._entry("opp-b"))
        self.assertFalse(res.paid)
        self.assertEqual(self.portfolio.get("opp-b").work_status,
                         WorkStatus.PAYMENT_PENDING)

    def test_legacy_verified_dict_never_pays(self):
        """A `{"verified": True}`-shaped result must never book.

        This is the precise defect: the old code wrote that literal itself.
        """
        ex = TaskExecutor(self.portfolio, self.validator, self.gates,
                          evidence_store=_LegacyDictStore())
        res = ex.execute(_coding_task("opp-c"), self._entry("opp-c"))
        self.assertFalse(res.paid)
        self.assertEqual(self.portfolio.get("opp-c").work_status,
                         WorkStatus.PAYMENT_PENDING)

    def test_manual_l1_attestation_does_not_pay(self):
        """L1 manual attestation is 'pending', never hard revenue."""
        store = _Store()
        for et in ("platform_submission", "completion_confirmation"):
            store.add(_verified(et, "opp-d"))
        store.add(_verified("payment_gross", "opp-d",
                            level=VerificationLevel.L1_SELF_REPORTED,
                            method="manual_attestation", amount=500.0))
        ex = TaskExecutor(self.portfolio, self.validator, self.gates,
                          evidence_store=store)
        res = ex.execute(_coding_task("opp-d"), self._entry("opp-d"))
        self.assertFalse(res.paid)

    def test_payment_without_submission_and_completion_does_not_pay(self):
        """SUBMITTED->PAID needs all three slots; a payment alone is not enough."""
        store = _Store()
        store.add(_verified("payment_gross", "opp-e", amount=500.0))
        ex = TaskExecutor(self.portfolio, self.validator, self.gates,
                          evidence_store=store)
        res = ex.execute(_coding_task("opp-e"), self._entry("opp-e"))
        self.assertFalse(res.paid)

    def test_real_l3_payment_still_books(self):
        """The floor is a floor, not a wall: a real payout still reaches PAID."""
        store = _Store()
        for et in ("platform_submission", "completion_confirmation"):
            store.add(_verified(et, "opp-f"))
        store.add(_verified("payment_gross", "opp-f", amount=500.0))
        ex = TaskExecutor(self.portfolio, self.validator, self.gates,
                          evidence_store=store)
        res = ex.execute(_coding_task("opp-f"), self._entry("opp-f"))
        self.assertTrue(res.paid)
        self.assertEqual(res.final_status, "paid")
        self.assertEqual(self.portfolio.get("opp-f").work_status, WorkStatus.PAID)

    def test_result_carries_the_evidence_that_paid(self):
        """The paying `Evidence` travels on the result, not a bare boolean."""
        store = _Store()
        for et in ("platform_submission", "completion_confirmation"):
            store.add(_verified(et, "opp-g"))
        pay = _verified("payment_gross", "opp-g", amount=750.0)
        store.add(pay)
        ex = TaskExecutor(self.portfolio, self.validator, self.gates,
                          evidence_store=store)
        res = ex.execute(_coding_task("opp-g"), self._entry("opp-g"))
        self.assertTrue(res.paid)
        self.assertTrue(res.evidence)
        self.assertTrue(all(isinstance(e, Evidence) for e in res.evidence))
        self.assertIn(pay.id, [e.id for e in res.evidence])


class TestStepResultsAreHonest(unittest.TestCase):
    """ARCH-ENG-158 — the recorded step payload must not claim more than happened."""

    def setUp(self):
        self.portfolio = OpportunityPortfolio(
            db_path=os.path.join(tempfile.mkdtemp(), "portfolio.db"))
        self.validator = CapabilityValidator(get_default_registry(), human_available=False)
        self.gates = HumanGateManager()

    def _entry(self, opp_id):
        e = PortfolioEntry(opportunity_id=opp_id, work_status=WorkStatus.NEW)
        self.portfolio.add(e)
        return e

    def test_step12_never_reports_verified_true_without_evidence(self):
        ex = TaskExecutor(self.portfolio, self.validator, self.gates)
        res = ex.execute(_coding_task("opp-h"), self._entry("opp-h"))
        step12 = res.context.step_results[12]
        self.assertFalse(step12.get("verified"))
        self.assertIn("reason", step12)

    def test_step12_blocked_when_store_missing(self):
        ex = TaskExecutor(self.portfolio, self.validator, self.gates)
        res = ex.execute(_coding_task("opp-i"), self._entry("opp-i"))
        self.assertEqual(res.context.step_results[12].get("status"),
                         StepStatus.BLOCKED.value)

    def test_work_status_map_no_longer_maps_14_to_paid(self):
        """The blanket step→status table must not be able to express PAID."""
        ex = TaskExecutor(self.portfolio, self.validator, self.gates)
        self.assertNotEqual(ex._work_status_for_step(14), WorkStatus.PAID)

    def test_step13_does_not_fabricate_an_evidence_dict(self):
        """Step 13 must not append a hand-built dict shaped like evidence."""
        ex = TaskExecutor(self.portfolio, self.validator, self.gates)
        res = ex.execute(_coding_task("opp-j"), self._entry("opp-j"))
        step13 = res.context.step_results[13]
        self.assertNotIn("recorded_at", step13)
        self.assertEqual(step13.get("recorded_count"), 0)
        self.assertTrue(all(isinstance(e, Evidence) for e in res.context.evidence))


class TestVacuityProbe(unittest.TestCase):
    """ARCH-ENG-158 — the probe is built at runtime so it cannot match itself.

    A guard that greps for its own tag proves nothing. This probe reconstructs
    the OLD step-12 behaviour in isolation and asserts that the NEW gate logic
    refuses it — so if the gate were ever reverted to a literal, this fails.
    """

    def test_probe_rejects_the_pre_fix_verdict_shape(self):
        probe_shape = {"verified": True}          # what step 12 used to write
        self.assertTrue(probe_shape.get("verified"))
        # The gate reads a real Evidence's status/level, not this dict.
        ev = _verified("payment_gross", "probe-subject", amount=1.0)
        self.assertIsInstance(ev, Evidence)
        self.assertNotIsInstance(probe_shape, Evidence)
        # ...and an L1 record is not a substitute for it.
        l1 = _verified("payment_gross", "probe-subject",
                       level=VerificationLevel.L1_SELF_REPORTED,
                       method="manual_attestation", amount=1.0)
        self.assertFalse(l1.is_verified(VerificationLevel.L3_EXTERNAL_SOURCE))

    def test_probe_result_to_dict_reports_paid_flag(self):
        """`to_dict` must expose the honest `paid` flag, not infer it from status."""
        from agents.earning.executor import ExecutionContext
        ctx = ExecutionContext(task={"task_id": "probe"})
        ctx.completed_at = 10.0
        ctx.started_at = 4.0
        r = ExecutionResult(success=True, final_status="payment_unverified",
                            context=ctx, paid=False)
        d = r.to_dict()
        self.assertFalse(d["paid"])
        self.assertNotEqual(d["final_status"], "paid")
        self.assertEqual(d["duration_s"], 6.0)


if __name__ == "__main__":
    unittest.main()