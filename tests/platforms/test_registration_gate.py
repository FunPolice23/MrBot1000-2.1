"""Gated registration service (Phase B, agents/platforms/registration.py).

Locks in the safety contract:
- propose() fetches the playbook QUARANTINED (trusted=False) and executes nothing.
- register() is REFUSED without a recorded, APPROVED create_account approval.
- register() REFUSES to invent a value for any field the caller didn't supply.
- An untrusted instruction can never authorize registration.

No network: the instruction gate, approval queue, and WebEyes are mocked.
"""
import os
import sys
import unittest
from unittest import mock

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.platforms.registration import RegistrationService, RegistrationPlan


def _fake_gate(content="STEP 1: go to signup. STEP 2: enter email."):
    gate = mock.Mock()
    qi = mock.Mock()
    qi.status = "pending"
    qi.trusted = False
    qi.content = content
    gate.fetch_instruction.return_value = qi
    return gate


def _fake_queue(status="approved", item_id="appr_1"):
    from agents.safety.approval import ApprovalStatus
    q = mock.Mock()
    item = mock.Mock()
    item.status = ApprovalStatus.APPROVED if status == "approved" else ApprovalStatus.PENDING
    item.id = item_id
    q.find_by_id.return_value = item
    return q


class TestPropose(unittest.TestCase):
    def test_propose_quarantines_playbook_and_executes_nothing(self):
        svc = RegistrationService(instruction_gate=_fake_gate())
        with mock.patch("agents.integrations.web_eyes.get_web_eyes") as eyes:
            eyes.return_value.read_page.return_value = {
                "title": "Sign up", "text": "Enter your email and password to register"}
            out = svc.propose("uGig", "https://ugig.net/signup",
                              instruction_url="https://ugig.net/skill.md")
        self.assertTrue(out["ok"])
        plan = out["plan"]
        self.assertIsInstance(plan, RegistrationPlan)
        self.assertFalse(plan.instruction_trusted)        # quarantined
        self.assertEqual(plan.instruction_status, "pending")
        self.assertIn("email", plan.detected_fields)       # detected from page
        self.assertIn("password", plan.detected_fields)
        # Nothing was submitted — read_page only, no fill_form.
        eyes.return_value.fill_form.assert_not_called()
        # Warnings tell the human it's untrusted + high-trust.
        self.assertTrue(any("UNTRUSTED" in w for w in plan.warnings))
        self.assertTrue(any("HIGH-TRUST" in w for w in plan.warnings))


class TestRegisterRefusals(unittest.TestCase):
    def _svc(self, queue=None):
        return RegistrationService(instruction_gate=_fake_gate(),
                                   approval_queue=queue or _fake_queue())

    def test_refused_without_approval_id(self):
        svc = self._svc()
        out = svc.register("uGig", "https://ugig.net/signup",
                           {"email": "#email"}, {"email": "a@b.com"})
        self.assertFalse(out["ok"])
        self.assertIn("HIGH-TRUST", out["reason"])

    def test_refused_when_approval_not_approved(self):
        svc = self._svc(_fake_queue(status="pending"))
        out = svc.register("uGig", "https://ugig.net/signup",
                           {"email": "#email"}, {"email": "a@b.com"},
                           approval_id="appr_1")
        self.assertFalse(out["ok"])
        self.assertIn("not approved", out["reason"])

    def test_refused_when_approval_unknown(self):
        q = _fake_queue()
        q.find_by_id.return_value = None
        svc = self._svc(q)
        out = svc.register("uGig", "https://ugig.net/signup",
                           {"email": "#email"}, {"email": "a@b.com"},
                           approval_id="nope")
        self.assertFalse(out["ok"])
        self.assertIn("not found", out["reason"])

    def test_refuses_to_invent_missing_value(self):
        """A field with no supplied value is never fabricated."""
        svc = self._svc()
        out = svc.register("uGig", "https://ugig.net/signup",
                           {"email": "#email", "password": "#pw"},
                           {"email": "a@b.com"},          # password missing
                           approval_id="appr_1")
        self.assertFalse(out["ok"])
        self.assertIn("never invents", out["reason"])
        self.assertIn("password", out["reason"])

    def test_approved_registration_forwards_to_fill_form(self):
        svc = self._svc(_fake_queue(status="approved"))
        def _fake_run(coro):
            coro.close()
            return {"url": "x", "title": "Welcome"}
        with mock.patch("agents.integrations.web_eyes.get_web_eyes") as eyes, \
             mock.patch("asyncio.run", side_effect=_fake_run):
            out = svc.register("uGig", "https://ugig.net/signup",
                               {"email": "#email"}, {"email": "a@b.com"},
                               approval_id="appr_1")
        self.assertTrue(out["ok"])
        self.assertIn("evidence", out)
        # fill_form was reached with the caller's selector->value mapping.
        self.assertTrue(eyes.return_value.fill_form.called)

    def test_register_with_vault_refuses_without_stored_creds(self):
        """register_with_vault fails closed when the vault has nothing for the
        platform — it never falls back to inventing a credential."""
        svc = self._svc(_fake_queue(status="approved"))
        fake_vault = mock.Mock()
        fake_vault.has_platform.return_value = False
        out = svc.register_with_vault("uGig", "https://ugig.net/signup",
                                      {"email": "#email", "password": "#pw"},
                                      approval_id="appr_1", vault=fake_vault)
        self.assertFalse(out["ok"])
        self.assertIn("no credentials stored", out["reason"])

    def test_register_with_vault_uses_stored_secret(self):
        """With creds in the vault, register_with_vault reads them and fills."""
        svc = self._svc(_fake_queue(status="approved"))
        fake_vault = mock.Mock()
        fake_vault.has_platform.return_value = True
        fake_vault.get_all.return_value = {"email": "a@b.com", "password": "pw"}
        with mock.patch("agents.integrations.web_eyes.get_web_eyes") as eyes, \
             mock.patch("asyncio.run", side_effect=lambda c: (c.close(), {"url": "x"})[1]):
            out = svc.register_with_vault("uGig", "https://ugig.net/signup",
                                          {"email": "#email", "password": "#pw"},
                                          approval_id="appr_1", vault=fake_vault)
        self.assertTrue(out["ok"])
        self.assertTrue(eyes.return_value.fill_form.called)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
