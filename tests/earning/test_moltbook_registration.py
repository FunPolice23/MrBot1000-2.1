"""Phase F1 — agent-driven Moltbook registration + human-claim handoff (ARCH-ENG-089).

The agent registers ITSELF via the API (behind a human approval that authorizes
that call), stores the api_key in the encrypted vault (never logged), and hands
the human claim instructions. The agent cannot claim itself.
"""
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, r"D:\MrBot1000_2.0")


class _Resp:
    def __init__(self, payload):
        self._p = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _Client:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return _Resp(self.payload)

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return _Resp(self.payload)


class _NullGate:
    def fetch_instruction(self, *a, **k):
        class _QI:
            status = "allowed"
            trusted = True
            content = "skill"
        return _QI()


class TestAgentDrivenRegistration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        # Point the vault's default dir at a temp dir so we never touch the
        # real vault. Patch the module-level _default_dir it falls back to.
        import agents.platforms.credential_vault as cv
        self._orig_default = cv._default_dir
        cv._default_dir = lambda: Path(self._tmp)

    def tearDown(self):
        import agents.platforms.credential_vault as cv
        cv._default_dir = self._orig_default

    def _register(self):
        from agents.earning.moltbook_agent import MoltbookAgentCapability
        payload = {"agent": {"api_key": "moltbook_SECRET",
                             "claim_url": "https://www.moltbook.com/claim/abc",
                             "verification_code": "reef-X4B2"}}
        cap = MoltbookAgentCapability(_NullGate(), http_client=_Client(payload))
        plan = cap.plan_registration("MrBot", "earning agent",
                                     skill_status="allowed")
        return cap.register(plan, capability_approved=True)

    def test_register_returns_claim_and_instructions(self):
        out = self._register()
        self.assertTrue(out["ok"])
        self.assertEqual(out["claim_status"], "pending_claim")
        self.assertEqual(out["claim_url"], "https://www.moltbook.com/claim/abc")
        self.assertEqual(out["verification_code"], "reef-X4B2")
        self.assertIn("reef-X4B2", out["human_instructions"])
        self.assertIn("claim/abc", out["human_instructions"])

    def test_register_stores_key_in_vault_not_logged(self):
        # Capture anything logged during registration.
        logs = []
        handler = logging.Handler()
        handler.emit = lambda r: logs.append(r.getMessage())
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            out = self._register()
        finally:
            root.removeHandler(handler)
        self.assertTrue(out["api_key_stored_in_vault"])
        # The secret must never appear in any log line.
        self.assertFalse(any("moltbook_SECRET" in m for m in logs))
        # And it must be retrievable from the vault.
        from agents.platforms.credential_vault import CredentialVault
        self.assertEqual(CredentialVault().get("moltbook", "api_key"),
                         "moltbook_SECRET")

    def test_register_requires_approval(self):
        from agents.earning.moltbook_agent import MoltbookAgentCapability
        cap = MoltbookAgentCapability(_NullGate(), http_client=_Client({}))
        plan = cap.plan_registration("MrBot", "earning agent",
                                     skill_status="allowed")
        out = cap.register(plan, capability_approved=False)
        self.assertEqual(out["status"], "awaiting_approval")

    def test_claim_status_maps_states(self):
        from agents.earning.moltbook_agent import MoltbookAgentCapability
        # Seed the vault so claim_status has a key.
        from agents.platforms.credential_vault import CredentialVault
        CredentialVault().set("moltbook", "api_key", "k")
        for raw, expected in (("pending_claim", "pending_claim"),
                              ("claimed", "claimed"),
                              ("weird", "unknown")):
            cap = MoltbookAgentCapability(_NullGate(),
                                          http_client=_Client({"status": raw}))
            out = cap.claim_status()
            self.assertEqual(out["claim_status"], expected)

    def test_claim_status_no_key(self):
        from agents.earning.moltbook_agent import MoltbookAgentCapability
        cap = MoltbookAgentCapability(_NullGate(), http_client=_Client({}))
        out = cap.claim_status()
        self.assertFalse(out["ok"])
        self.assertEqual(out["claim_status"], "unknown")

    def test_request_human_claim_enqueues_pending(self):
        from agents.earning.moltbook_agent import MoltbookAgentCapability
        from agents.safety.approval import HumanApprovalQueue, ApprovalStatus
        cap = MoltbookAgentCapability(_NullGate(), http_client=_Client({}))
        plan = cap.plan_registration("MrBot", "earning agent",
                                     skill_status="allowed")
        out = cap.request_human_claim(
            plan, claim_url="https://www.moltbook.com/claim/abc",
            verification_code="reef-X4B2")
        self.assertTrue(out["ok"])
        self.assertEqual(out["status"], "awaiting_human_claim")
        item = HumanApprovalQueue.instance().find_by_id(out["approval_id"])
        self.assertIsNotNone(item)
        self.assertEqual(item.status, ApprovalStatus.PENDING)
        self.assertIn("reef-X4B2", out["human_instructions"])


if __name__ == "__main__":
    raise SystemExit(unittest.main())
