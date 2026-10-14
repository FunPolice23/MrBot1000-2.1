"""A real crypto send requires a RECORDED, SCOPED human approval (ARCH-ENG-130).

`RealCryptoOperator.confirm_and_send` used to call `try_real_payment` directly;
the only thing gating a real send was the static `human_approval_required=True`
constructor flag on `CryptoPayments`. A method named "confirm" confirmed
nothing — if that flag were ever flipped to enable real sends, any caller could
move real funds with no recorded human decision.

The fix binds `confirm_and_send` to a real, scoped approval via the ARCH-ENG-129
`assert_approval_covers` contract: an APPROVED queue item whose scope names
`crypto_send` and the exact destination/amount/currency/chain the human
reviewed. It must fail CLOSED on every miss.

The crypto layer is stubbed so `try_real_payment` records whether it was
reached: that isolates the approval GATE from the constructor flag, and a test
that only checked the return value could not tell a gate refusal from the
flag's own block. Each case asserts BOTH the result and whether the send was
actually attempted.

No network, no wallet, no filesystem: the queue is the in-memory pytest queue
and `crypto` is a recording stub.
"""
import os
import sys
import unittest

sys.path.insert(0, r"D:\MrBot1000_2.0")

from agents.integrations.wallet import Chain
from agents.earning.real_crypto_operator import RealCryptoOperator
from agents.safety.approval import (
    ApprovalItem,
    ApprovalKind,
    ApprovalStatus,
    HumanApprovalQueue,
)


class _Chainless:
    pass


class _StubRequest:
    def __init__(self):
        self.request_id = "req-1"
        self.from_address = "0xfrom"
        self.to_address = "0xto"
        self.amount = 5.0
        self.currency = "USDC"
        self.chain = Chain.ETHEREUM
        self.status = "pending"
        self.tx_hash = ""
        self.confirmations = 0

    def to_dict(self):
        return {"request_id": self.request_id, "to": self.to_address,
                "amount": self.amount, "currency": self.currency}


class _StubCrypto:
    """Records whether the real-send path was reached. Returns ok so the
    approval GATE is the only thing that can block a send in these tests."""

    def __init__(self):
        self.calls = []
        self._requests = {"req-1": _StubRequest()}

    def get_request(self, request_id):
        return self._requests.get(request_id)

    def create_payment(self, frm, to, amount, currency, chain, memo=""):
        return self._requests["req-1"]

    def simulate_payment(self, request):
        return {"ok": True, "note": "simulated"}

    def try_real_payment(self, request, rpc_url="", private_key=""):
        self.calls.append(("try_real_payment", request.request_id))
        return {"ok": True, "tx_hash": "0xtx"}

    def confirm_payment(self, request_id):
        self.calls.append(("confirm_payment", request_id))
        return {"confirmations": 3}


class _StubGuard:
    """A safety guard that always flags the action for approval."""

    class _Result:
        action = "flag"
        reasons = ["high-value send"]
        blocked = False

    def check(self, action):
        return self._Result()


def _scoped_approval(amount=5.0, to="0xto", currency="USDC",
                     chain="ethereum", tool="crypto_send", request_id="req-1"):
    item = ApprovalItem(
        kind=ApprovalKind.PAYMENT,
        title="Crypto payment",
        description="d",
        details={"tool": tool, "arguments": {
            "request_id": request_id, "to": to, "amount": amount,
            "currency": currency, "chain": chain}},
    )
    return item


class ConfirmAndSendApprovalGateTest(unittest.TestCase):
    def setUp(self):
        HumanApprovalQueue.reset_singleton()
        self.queue = HumanApprovalQueue.instance()
        # Bypass __init__ so the real CryptoPayments (and its SDK checks / the
        # human_approval_required flag) never runs; the gate under test is in
        # confirm_and_send, and crypto is the recording stub.
        self.op = RealCryptoOperator.__new__(RealCryptoOperator)
        self.op.crypto = _StubCrypto()
        self.op.safety_guard = None

    def _enqueue_and_approve(self, item):
        self.queue.enqueue(item)
        self.assertTrue(self.queue.approve(item.id))
        return item.id

    # ── fail-closed: no send reached ──────────────────────────────────────
    def test_no_approval_id_blocks_and_never_sends(self):
        res = self.op.confirm_and_send("req-1")
        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "blocked")
        self.assertIn("approval_id", res["error"])
        self.assertEqual(self.op.crypto.calls, [],
                         "confirm_and_send must NOT reach try_real_payment "
                         "without a recorded approval")

    def test_unknown_approval_id_blocks_and_never_sends(self):
        res = self.op.confirm_and_send("req-1", approval_id="does-not-exist")
        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "blocked")
        self.assertEqual(self.op.crypto.calls, [])

    def test_amount_mismatch_blocks_and_never_sends(self):
        # Human approved $999; the persisted request is $5. A different amount
        # is a different action and must not be sent against this approval.
        aid = self._enqueue_and_approve(_scoped_approval(amount=999.0))
        res = self.op.confirm_and_send("req-1", approval_id=aid)
        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "blocked")
        self.assertEqual(self.op.crypto.calls, [])

    def test_wrong_tool_approval_blocks_and_never_sends(self):
        # A record_payment approval replayed as the crypto-send gate (the
        # ARCH-ENG-129 F2 class): the scope names a different tool.
        aid = self._enqueue_and_approve(_scoped_approval(tool="record_payment"))
        res = self.op.confirm_and_send("req-1", approval_id=aid)
        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "blocked")
        self.assertEqual(self.op.crypto.calls, [])

    def test_pending_approval_blocks_and_never_sends(self):
        # Enqueued but NOT yet decided: authorizes nothing.
        item = _scoped_approval()
        self.queue.enqueue(item)
        res = self.op.confirm_and_send("req-1", approval_id=item.id)
        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "blocked")
        self.assertEqual(self.op.crypto.calls, [])

    # ── the only path that sends: a correct, scoped, APPROVED item ─────────
    def test_correct_scoped_approval_proceeds_to_send(self):
        aid = self._enqueue_and_approve(_scoped_approval())
        res = self.op.confirm_and_send("req-1", approval_id=aid)
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "confirmed")
        self.assertIn(("try_real_payment", "req-1"), self.op.crypto.calls,
                      "a correct scoped approval MUST reach the real send")

    # ── propose_payment enqueues the scoped approval the gate requires ─────
    def test_propose_payment_enqueues_scoped_approval(self):
        self.op.safety_guard = _StubGuard()
        res = self.op.propose_payment(
            "0xfrom", "0xto", 5.0, "USDC", Chain.ETHEREUM, memo="test")
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "awaiting_approval")
        approval_id = res.get("approval_id")
        self.assertTrue(approval_id, "propose_payment must return an approval_id")
        # The enqueued item must be the one confirm_and_send accepts.
        pending = self.queue.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].id, approval_id)
        # And confirming against that id (once approved) reaches the send.
        self.queue.approve(approval_id)
        confirmed = self.op.confirm_and_send("req-1", approval_id=approval_id)
        self.assertTrue(confirmed["ok"])
        self.assertEqual(confirmed["status"], "confirmed")


if __name__ == "__main__":
    unittest.main()
