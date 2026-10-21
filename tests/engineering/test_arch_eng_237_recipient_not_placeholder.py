"""ARCH-ENG-237 / BB-01 -- a payment may only be proposed to a real recipient.

The finding
-----------
`EarningTab._on_propose_payment` fabricated its recipient:
`to_address = "0x" + "A" * 40` (comment: "payment fields collected from UI
controls in future iteration"). That address flowed into
`RealCryptoOperator.propose_payment`, whose scoped approval (ARCH-ENG-130) then
presented the human with a fully-formed, human-readable authorisation request:
"Send {amount} {currency} on {chain} to 0xAAAA…". The tab even HAD the missing
input -- a "To address" line edit -- but it was a throwaway local, never stored,
never read. There were zero recipient-validation sites in the entire tree.

Why the boundary, not just the call site
----------------------------------------
ARCH-ENG-130's scoping guarantees the operator reviews *precisely what was
requested*; it cannot notice that what was requested should never have been
requested. The correct mechanism faithfully delivered the operator to an
authorization for a transfer to a nonsense address. Per the sweep's lesson
(`11t` `_step12_verify`, `11w` `_stated_usd`): validate content at the boundary
where it ENTERS, not only where it is USED.

The fix
-------
1. The tab reads `self.pay_recipient` (the field that always existed) and
   refuses honestly when it is empty; a placeholder is never substituted.
2. `RealCryptoOperator.propose_payment` validates the recipient BEFORE creating
   a request or enqueueing an approval: chain-aware shape (EVM / Solana
   base58) and the all-identical-digit dummy class -- no real key ever lands on
   42 identical characters, and on a payment surface a burned recipient does
   not get substituted input either. Rejections return
   `{"ok": False, "status": "invalid_recipient"}` and create nothing.

Vacuity probes: against the pre-fix sources, the operator tests pass a
*bypassed* guard at `propose_payment` that did not exist (AttributeError) and
the tab-level tests reach a fabricated approval instead of a refusal -- both
falsify.
"""

import os
import sys
import unittest
from unittest import mock

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.integrations.wallet import Chain
from agents.earning.real_crypto_operator import RealCryptoOperator, _recipient_rejection
from agents.safety.approval import HumanApprovalQueue


VALID_EVM = "0x" + "ab12" * 10            # 40 mixed hex chars
PLACEHOLDER_EVM = "0x" + "A" * 40         # the exact string the tab used to send
ALL_IDENTICAL_EVM = "0x" + "3" * 40       # the same class, different digit


class _StubRequest:
    def __init__(self, to_address):
        self.request_id = "req-237"
        self.from_address = "0xfrom"
        self.to_address = to_address
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
    """create_payment is the boundary under test; the send path is a nameplate."""

    def __init__(self):
        self.created = []

    def create_payment(self, frm, to, amount, currency, chain, memo=""):
        self.created.append(to)
        return _StubRequest(to)

    def simulate_payment(self, request):
        return {"ok": True, "note": "simulated"}


class _StubGuard:
    """Always flags — same shape as the ARCH-ENG-130 fixture's guard."""

    class _Result:
        action = "flag"
        reasons = ["high-value send"]
        blocked = False

    def check(self, action):
        return self._Result()


def _operator():
    op = RealCryptoOperator.__new__(RealCryptoOperator)
    op.crypto = _StubCrypto()
    op.safety_guard = _StubGuard()
    return op


class RecipientValidationUnit(unittest.TestCase):
    """The pure content check, chain-aware."""

    def test_empty_recipient_is_refused(self):
        self.assertTrue(_recipient_rejection(Chain.ETHEREUM, ""))
        self.assertTrue(_recipient_rejection(Chain.ETHEREUM, None))

    def test_evm_shape_required(self):
        self.assertTrue(_recipient_rejection(Chain.ETHEREUM, "0x123"))
        self.assertTrue(_recipient_rejection(Chain.POLYGON, "not-an-address"))
        self.assertIsNone(_recipient_rejection(Chain.POLYGON, VALID_EVM))

    def test_solana_shape_required(self):
        self.assertTrue(_recipient_rejection(Chain.SOLANA, PLACEHOLDER_EVM),
                        "an EVM placeholder must not pass as a Solana address")
        self.assertIsNone(
            _recipient_rejection(
                Chain.SOLANA, "4Nd1mBQtrMJVYVfKf2PJy9NZUZdTAsj7DtfX9e25qSF9"))

    def test_identical_character_recipient_is_refused(self):
        self.assertTrue(_recipient_rejection(Chain.ETHEREUM, PLACEHOLDER_EVM))
        self.assertTrue(_recipient_rejection(Chain.ETHEREUM, ALL_IDENTICAL_EVM))


class ProposePaymentRefusesBeforeAnythingIsCreated(unittest.TestCase):
    """The refusal must happen BEFORE create_payment and BEFORE any approval."""

    def setUp(self):
        HumanApprovalQueue.reset_singleton()
        self.queue = HumanApprovalQueue.instance()
        # ARCH-ENG-281 (D-01): opt in past the new crypto feature boundary so
        # this suite still tests recipient validation at content entry.
        self._crypto_flag = mock.patch.dict(
            os.environ, {"MRBOT_ENABLE_CRYPTO": "1"})
        self._crypto_flag.start()
        self.addCleanup(self._crypto_flag.stop)
        self.op = _operator()

    def test_placeholder_address_creates_nothing_and_enqueues_nothing(self):
        before = len(self.queue.all())
        res = self.op.propose_payment(
            "0x" + "9" * 40, PLACEHOLDER_EVM, 5.0, "ETH", Chain.ETHEREUM)
        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "invalid_recipient")
        self.assertEqual(self.op.crypto.created, [],
                         "create_payment must not run for a dummy recipient")
        self.assertEqual(len(self.queue.all()), before,
                         "no approval may be enqueued for a dummy recipient")

    def test_bad_solana_shape_creates_nothing(self):
        res = self.op.propose_payment(
            "4Nd1mBQtrMJVYVfKf2PJy9NZUZdTAsj7DtfX9e25qSF9", VALID_EVM,
            2.0, "SOL", Chain.SOLANA)
        self.assertFalse(res["ok"])
        self.assertIn("Solana", res["error"])
        self.assertEqual(self.op.crypto.created, [])

    def test_valid_recipient_still_reaches_the_scoped_approval(self):
        """The positive control: real recipients suffer no new strictness."""
        res = self.op.propose_payment(
            "0x" + "9" * 40, VALID_EVM, 5.0, "ETH", Chain.ETHEREUM)
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "awaiting_approval")
        self.assertTrue(res["approval_id"], "the scoped approval id must exist")
        self.assertEqual(self.op.crypto.created, [VALID_EVM])


class TabRefusesWithoutARecipient(unittest.TestCase):
    """The earning tab must never substitute a placeholder for the field."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from agents.safety.approval import HumanApprovalQueue as Q
        Q.reset_singleton()
        self.queue = Q.instance()

    def test_empty_recipient_field_is_an_honest_refusal(self):
        from PySide6.QtWidgets import QMessageBox
        from gui.tabs.earning_tab import EarningTab
        saved = QMessageBox.warning
        captured = []
        QMessageBox.warning = staticmethod(
            lambda *a, **k: captured.append((a[-2] if len(a) > 2 else "", a[-1] if a else "")))
        from agents.integrations.wallet import WalletManager
        wm = WalletManager.shared()
        try:
            addr = "0x" + "76ab" * 8 + "0x0"
            # Use the shared funded wallet (stable across runs).
            sender = "0x" + "5" * 40
            if wm.get_wallet(sender) is None:
                wm.add_wallet(sender, Chain.ETHEREUM)
            wm.update_balance(sender, 100.0)
            tab = EarningTab()
            tab.wallet_address_input.setText(sender)
            tab.pay_send_amount.setValue(5.0)
            tab.pay_currency.setCurrentText("ETH")
            before = len(self.queue.all())
            tab._on_propose_payment()
            self.assertEqual(
                [d[0] for d in captured if d[1]], ["Error"],
                f"the empty recipient must produce the honest refusal, got {captured}")
            self.assertIn("Recipient address required", " ".join(d[1] for d in captured))
            self.assertEqual(len(self.queue.all()), before,
                             "no approval may be enqueued without a recipient")
            self.assertNotIn("AAAA", "" .join(d[1] for d in captured))
        finally:
            QMessageBox.warning = saved

    def test_tab_stores_the_recipient_field_it_always_had(self):
        from gui.tabs.earning_tab import EarningTab
        tab = EarningTab()
        self.assertTrue(
            hasattr(tab, "pay_recipient"),
            "the 'To address' field must be kept, not remain a throwaway local")
        self.assertEqual(tab.pay_recipient.placeholderText(), "To address")


if __name__ == "__main__":
    unittest.main()
