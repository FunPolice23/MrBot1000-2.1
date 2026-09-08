"""tests/test_earning_capability.py — First real earning capability (v2.1 Phase 4).

Offline/mock-first: producer is a fake, so the whole human-gated fulfillment
path is verified with no network/model/Qt. Uses real TaskWorkspace, deterministic
validators, HumanGateManager, EvidenceStore, and OpportunityPortfolio.
"""

import os
import tempfile
import unittest

from agents.earning_capability import EarningCapabilityExecutor, EarningCapabilityResult
from agents.human_gates import HumanGateManager, HumanGateType
from agents.opportunity_portfolio import OpportunityPortfolio, PortfolioEntry, WorkStatus


def _opp(opp_id="opp-1", platform="TestPlatform", task_type="writing",
         title="Write a report", description="Produce a short report",
         required_skills=None, amount=50.0, payment_currency="usd",
         payment_conditions=None):
    return type("Opp", (), {
        "id": opp_id, "opportunity_id": opp_id, "platform": platform,
        "task_type": task_type, "type": task_type, "title": title,
        "description": description,
        "required_skills": required_skills or ["deliverable"],
        "advertised_amount": amount, "payment_currency": payment_currency,
        "external_id": f"ext-{opp_id}", "payment_conditions": payment_conditions or {},
    })()


def _producer(opp, requirements):
    # Simple, short sentences score high on the DocumentScanner Flesch readability
    # gate, so the deterministic QA check passes (quality >= 0.7).
    return (
        "# Deliverable\n\n"
        "This report looks at the freelance market for data work.\n\n"
        "Demand for data help is high and still growing. Many small firms need "
        "people who can clean spreadsheets, build charts, and explain numbers. "
        "They pay well for clear, on-time work.\n\n"
        "A person with basic skills can do this from home. You set your own "
        "hours. You pick the jobs that fit. Good reviews bring more jobs. Over "
        "time this becomes a steady income.\n\n"
        "The plan is simple. Find jobs. Do good work. Deliver on time. Reply "
        "to clients fast. Ask for a review. Repeat.\n\n"
        "This is a realistic and safe way to earn money online."
    )


class TestFulfillApproved(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="hermes-cap-")
        from database import AgentDB
        from agents.evidence_store import EvidenceStore
        self._db_path = os.path.join(self._tmp, "ep.db")
        self.evidence_store = EvidenceStore(AgentDB(self._db_path))
        self.portfolio = OpportunityPortfolio(
            os.path.join(self._tmp, "port.db"))
        self.lifecycle = type("LC", (), {
            "mark_submitted": lambda self, oid, note="": None,
            "mark_queued": lambda self, oid, note="": None,
        })()
        self.executor = EarningCapabilityExecutor(
            portfolio=self.portfolio,
            lifecycle=self.lifecycle,
            evidence_store=self.evidence_store,
            human_gates=HumanGateManager(),
            root_folder=os.path.join(self._tmp, "root"),
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_simple_writing_task_approved_no_payment(self):
        opp = _opp()
        # Pre-seed a portfolio entry so the sync path finds it.
        self.portfolio.add(PortfolioEntry(opportunity_id="opp-1", platform="TestPlatform"))
        result = self.executor.fulfill(opp, _producer)
        self.assertIsInstance(result, EarningCapabilityResult)
        self.assertTrue(result.is_approved, result.error)
        self.assertEqual(result.status, "approved")
        self.assertEqual(result.lifecycle_stage, "submitted")
        # A real deliverable exists.
        self.assertTrue(result.files)
        # Submission is LOCAL packaging; never "paid".
        self.assertTrue(result.submission_package.get("status") == "submitted")
        # Evidence recorded is a submission record (L1), not payment.
        self.assertTrue(result.evidence_id)
        self.assertEqual(result.gates, [])

    def test_portfolio_entry_moved_to_waiting_external(self):
        self.portfolio.add(PortfolioEntry(opportunity_id="opp-1", platform="TestPlatform"))
        self.executor.fulfill(_opp(), _producer)
        entry = self.portfolio.get("opp-1")
        self.assertEqual(entry.work_status, WorkStatus.WAITING_EXTERNAL)

    def test_evidence_is_submission_not_payment(self):
        self.portfolio.add(PortfolioEntry(opportunity_id="opp-1", platform="TestPlatform"))
        result = self.executor.fulfill(_opp(), _producer)
        ev = self.evidence_store.get(result.evidence_id)
        self.assertIsNotNone(ev)
        self.assertEqual(ev.evidence_type, "platform_submission")
        # L1 self-reported local record — must NOT be treated as verified payment.
        self.assertNotEqual(ev.evidence_type, "payment_gross")


class TestHumanGateBlocksSubmission(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="hermes-cap-")
        from database import AgentDB
        from agents.evidence_store import EvidenceStore
        self.evidence_store = EvidenceStore(AgentDB(os.path.join(self._tmp, "ep.db")))
        self.portfolio = OpportunityPortfolio(os.path.join(self._tmp, "port.db"))
        self.executor = EarningCapabilityExecutor(
            portfolio=self.portfolio,
            evidence_store=self.evidence_store,
            human_gates=HumanGateManager(),
            root_folder=os.path.join(self._tmp, "root"),
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_payment_task_requires_approval(self):
        # payment_conditions set -> PAYMENTS gate -> awaiting approval.
        opp = _opp(payment_conditions={"requires_payment": True})
        self.portfolio.add(PortfolioEntry(opportunity_id="opp-1", platform="TestPlatform"))
        result = self.executor.fulfill(opp, _producer)
        self.assertEqual(result.status, "await_approval")
        self.assertFalse(result.is_approved)
        self.assertTrue(any(g["gate_type"] == HumanGateType.PAYMENTS.value
                            for g in result.gates))
        # Must NOT produce a submission package when blocked.
        self.assertEqual(result.submission_package, {})

    def test_portfolio_entry_awaiting_approval_when_gated(self):
        opp = _opp(payment_conditions={"requires_payment": True})
        self.portfolio.add(PortfolioEntry(opportunity_id="opp-1", platform="TestPlatform"))
        self.executor.fulfill(opp, _producer)
        entry = self.portfolio.get("opp-1")
        self.assertEqual(entry.work_status, WorkStatus.AWAITING_APPROVAL)
        self.assertTrue(entry.blocked_reason)

    def test_explicit_clear_gate_allows_submission(self):
        opp = _opp(payment_conditions={"requires_payment": True})
        self.portfolio.add(PortfolioEntry(opportunity_id="opp-1", platform="TestPlatform"))
        # Human approves the PAYMENTS gate for this call.
        result = self.executor.fulfill(opp, _producer,
                                       clear_gates=[HumanGateType.PAYMENTS.value])
        self.assertTrue(result.is_approved, result.error)
        self.assertEqual(result.status, "approved")


class TestValidationFailure(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="hermes-cap-")
        from database import AgentDB
        from agents.evidence_store import EvidenceStore
        self.evidence_store = EvidenceStore(AgentDB(os.path.join(self._tmp, "ep.db")))
        self.portfolio = OpportunityPortfolio(os.path.join(self._tmp, "port.db"))
        self.executor = EarningCapabilityExecutor(
            portfolio=self.portfolio,
            evidence_store=self.evidence_store,
            human_gates=HumanGateManager(),
            root_folder=os.path.join(self._tmp, "root"),
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_empty_producer_fails(self):
        result = self.executor.fulfill(_opp(), lambda opp, reqs: "")
        self.assertEqual(result.status, "failed")
        self.assertIn("empty", result.error)


class TestNoFabricatedPayment(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="hermes-cap-")
        from database import AgentDB
        from agents.evidence_store import EvidenceStore
        self.evidence_store = EvidenceStore(AgentDB(os.path.join(self._tmp, "ep.db")))
        self.executor = EarningCapabilityExecutor(
            portfolio=None, evidence_store=self.evidence_store,
            human_gates=HumanGateManager(),
            root_folder=os.path.join(self._tmp, "root"),
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_never_records_payment(self):
        result = self.executor.fulfill(_opp(amount=5000.0), _producer)
        self.assertTrue(result.is_approved)
        # No verified payment evidence ever recorded by the capability.
        from agents.evidence import EvidenceStatus
        ev = self.evidence_store.get(result.evidence_id)
        self.assertNotEqual(ev.evidence_type, "payment_gross")
        self.assertNotEqual(ev.status, EvidenceStatus.VERIFIED)


if __name__ == "__main__":
    unittest.main()
