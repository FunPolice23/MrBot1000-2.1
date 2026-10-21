"""ARCH-ENG-154 — every wallet surface in the Earnings tab was dead, and fixing
the wiring would have booked a wallet BALANCE as revenue.

Three linked defects, all reproduced by execution against the real tabs.

1. `EarningTab._get_wallet_manager()` guarded
   `hasattr(self.main_window, "payments_tab")`. `create_payments_tab()`
   (gui/builders/tab_feature_builders.py) stores the tab as
   `self._payments_tab`, and `MainWindow` exposes no `payments_tab` attribute or
   property anywhere in the repo. OBSERVED on the real MainWindow shape:
   `hasattr(main, "payments_tab")` -> False, `hasattr(main, "_payments_tab")` ->
   True. The guard was permanently False, so the method always returned None and
   ALL FIVE call sites were dead: Add Wallet raised
   "'NoneType' object has no attribute 'add_wallet'", Propose Payment raised
   "'NoneType' object has no attribute 'get_wallet'" (the operator was also
   constructed with `None` as its wallet manager), the crypto wallets table
   stayed at 0 rows, and get_summary()'s wallet contribution never ran.

2. `PaymentsTab.wallet_manager` was hardcoded `None` and never assigned, so even
   a correct attribute read would have handed back None.

3. (2nd pass) `get_summary()` added every USD wallet BALANCE to `earned`.
   Unreachable while (1) held — and ACTIVATING it by fixing (1) is a
   fabrication: one wallet with `currency="USD", balance=500.0` and ZERO
   verified payments returned `earned=500.0`, rendered as
   "💰 Earned: $500.00" by the Insights panel. A balance is not revenue (a
   transfer in, an airdrop, an operator top-up all inflate it). Removed; the
   honest source is verified payment evidence, which this tab cannot reach.
"""

from __future__ import annotations

import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget


def _qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _SilencedDialogs:
    """Offscreen QMessageBox.exec() blocks with nobody to click it."""

    def __enter__(self):
        self._shown = []
        self._saved = (QMessageBox.critical, QMessageBox.information, QMessageBox.warning)
        QMessageBox.critical = staticmethod(lambda *a, **k: self._shown.append(("critical", a[-1] if a else "")))
        QMessageBox.information = staticmethod(lambda *a, **k: self._shown.append(("info", a[-1] if a else "")))
        QMessageBox.warning = staticmethod(lambda *a, **k: self._shown.append(("warning", a[-1] if a else "")))
        return self._shown

    def __exit__(self, *exc):
        QMessageBox.critical, QMessageBox.information, QMessageBox.warning = self._saved
        return False


class _FakeMainWindow(QWidget):
    """The real MainWindow shape: `create_payments_tab` sets `_payments_tab`."""

    def __init__(self, payments_tab):
        super().__init__()
        self._payments_tab = payments_tab


class _IsolatedWalletStore:
    """Point the shared store at a temp file and restore it afterwards.

    Without this the tests write the operator's real
    `~/.mrbot1000/wallets.json` — observed: the file did not exist before the
    first run and 11 fake wallets were written into it, one of them with
    `currency="USD", balance=500.0`, which the Payments tab then rendered as
    "Total Balance: USD: 500.0000". A GUI test must never mutate operator state.
    """

    def __enter__(self):
        import tempfile
        from agents.integrations.wallet import WalletManager
        self._cls = WalletManager
        # Shape-tolerant so the pre-fix class (no `_SHARED`) is exercised for
        # BEHAVIOUR, not an AttributeError in the fixture. A negative control
        # that dies in setUp proves nothing about the defect.
        self._saved = getattr(WalletManager, "_SHARED", "<absent>")
        self._dir = tempfile.TemporaryDirectory()
        WalletManager._SHARED = WalletManager(
            os.path.join(self._dir.name, "wallets.json"))
        return WalletManager._SHARED

    def __exit__(self, *exc):
        if self._saved == "<absent>":
            if hasattr(self._cls, "_SHARED"):
                del self._cls._SHARED
        else:
            self._cls._SHARED = self._saved
        self._dir.cleanup()
        return False


class TestWalletWiringReachesAStore(unittest.TestCase):
    """Defects 1 + 2: the wallet surfaces actually resolve a store."""

    @classmethod
    def setUpClass(cls):
        cls.app = _qt_app()

    def setUp(self):
        # The tabs call WalletManager.shared() in __init__, so the isolation
        # must be installed before any tab is constructed.
        self._iso = _IsolatedWalletStore()
        self._iso.__enter__()
        self.addCleanup(self._iso.__exit__)

    def _tab(self, main=None):
        from gui.tabs.earning_tab import EarningTab
        tab = EarningTab()
        if main is not None:
            tab.main_window = main
        return tab

    def test_main_window_shape_really_has_no_public_payments_tab(self):
        """The guard's premise, asserted against the real shape."""
        from gui.tabs.payments_tab import PaymentsTab
        main = _FakeMainWindow(PaymentsTab())
        self.assertFalse(
            hasattr(main, "payments_tab"),
            "if MainWindow ever grows a public payments_tab, this test's "
            "reproduction is stale — re-check the fix is still needed")
        self.assertTrue(hasattr(main, "_payments_tab"))

    def test_wallet_manager_resolves_through_the_real_main_shape(self):
        from gui.tabs.payments_tab import PaymentsTab
        tab = self._tab(_FakeMainWindow(PaymentsTab()))
        self.assertIsNotNone(
            tab._get_wallet_manager(),
            "the real MainWindow shape must still yield a wallet store")

    def test_payments_tab_holds_a_real_wallet_manager(self):
        from gui.tabs.payments_tab import PaymentsTab
        self.assertIsNotNone(
            PaymentsTab().wallet_manager,
            "PaymentsTab.wallet_manager was hardcoded None")

    def test_crypto_operator_has_a_wallet_manager(self):
        """Propose Payment's second dead link: the operator itself was None-backed."""
        from gui.tabs.earning_tab import EarningTab
        self.assertIsNotNone(EarningTab().crypto_operator.crypto.wallets)

    def test_both_tabs_share_one_wallet_store(self):
        """A wallet added on one surface must be visible on the other."""
        from agents.integrations.wallet import WalletManager
        from gui.tabs.payments_tab import PaymentsTab
        tab = self._tab(_FakeMainWindow(PaymentsTab()))
        self.assertIs(tab._get_wallet_manager(), WalletManager.shared())

    def test_add_wallet_reaches_the_store(self):
        from agents.integrations.wallet import Chain, WalletManager
        wm = WalletManager.shared()
        # Unique per run: the store is a real on-disk file and survives the
        # process, so a fixed address is already present on a second run.
        addr = "0x" + ("9" * 8 + f"{os.getpid():032x}")[:40].ljust(40, "7")
        before = {w.address for w in wm.list_wallets()}
        self.assertNotIn(addr, before, "test address must be fresh")
        tab = self._tab()
        tab.wallet_address_input.setText(addr)
        tab.wallet_chain_combo.setCurrentText("ETH")
        with _SilencedDialogs() as shown:
            tab._on_add_wallet()
        self.assertEqual(
            shown, [], f"Add Wallet must not error; got {shown}")
        self.assertIn(addr, {w.address for w in wm.list_wallets()} - before)

    def test_propose_payment_reaches_the_safety_gate(self):
        """Pre-fix: "'NoneType' object has no attribute 'get_wallet'".

        Post-fix the request is CREATED and routed into the human-approval queue
        (or simulated) — it must never raise, and never silently vanish.
        (ARCH-ENG-237: and post-237 the payment needs a real recipient from the
        'To address' field — the old hardcoded 0xA*40 placeholder is refused.)
        """
        from gui.tabs.earning_tab import EarningTab
        tab = EarningTab()
        wm = tab._get_wallet_manager()
        addr = "0x" + "2" * 40
        if wm.get_wallet(addr) is None:
            from agents.integrations.wallet import Chain
            wm.add_wallet(addr, Chain.ETHEREUM)
        wm.update_balance(addr, 100.0)   # fund it; the balance rule is legitimate
        tab.wallet_address_input.setText(addr)
        tab.pay_recipient.setText("0x" + "ab12" * 10)
        tab.pay_send_amount.setValue(5.0)
        tab.pay_currency.setCurrentText("ETH")
        with _SilencedDialogs() as shown:
            tab._on_propose_payment()
        # Reaching the gate IS success: the operator creates the request and
        # routes it to the human-approval queue rather than raising. A
        # `critical` dialog is the pre-fix signature ("'NoneType' object has no
        # attribute 'get_wallet'") and must never appear.
        self.assertFalse(
            [d for d in shown if d[0] == "critical"],
            f"Propose Payment must reach the gate, not raise: {shown}")
        self.assertTrue(
            any("awaiting_approval" in d[1] for d in shown if d[0] == "info"),
            f"the payment must be queued for human approval: {shown}")

    def test_crypto_wallets_table_populates(self):
        from agents.integrations.wallet import Chain, WalletManager
        wm = WalletManager.shared()
        addr = "0x" + "3" * 40
        if wm.get_wallet(addr) is None:
            wm.add_wallet(addr, Chain.ETHEREUM)
        tab = self._tab()
        tab._refresh_crypto_wallets()
        self.assertGreater(
            tab.crypto_wallets_table.rowCount(), 0,
            "the crypto wallets table must render the store, not stay empty")


class TestWalletBalanceIsNeverRevenue(unittest.TestCase):
    """Defect 3: a balance is not earnings."""

    @classmethod
    def setUpClass(cls):
        cls.app = _qt_app()

    def setUp(self):
        self._iso = _IsolatedWalletStore()
        self._iso.__enter__()
        self.addCleanup(self._iso.__exit__)

    def test_a_usd_wallet_balance_does_not_become_earned(self):
        from agents.integrations.wallet import Chain, WalletManager
        from gui.tabs.earning_tab import EarningTab

        wm = WalletManager.shared()
        addr = "0x" + "4" * 40
        if wm.get_wallet(addr) is None:
            wm.add_wallet(addr, Chain.ETHEREUM)
        w = wm.get_wallet(addr)
        w.currency = "USD"
        w.balance = 500.0
        wm._save()

        tab = EarningTab()
        # The store IS reachable — the wiring works — and still must not book.
        self.assertIs(tab._get_wallet_manager(), wm)
        self.assertEqual(
            tab.get_summary()["earned"], 0.0,
            "a $500 wallet balance with zero verified payments must not report "
            "$500 earned")

    def test_get_summary_source_has_no_wallet_contribution(self):
        """Pin the removal so the loop cannot be reintroduced silently."""
        import inspect
        from gui.tabs import earning_tab
        src = inspect.getsource(earning_tab.EarningTab.get_summary)
        self.assertNotIn("w.balance", src)
        self.assertNotIn("earned +=", src)


if __name__ == "__main__":
    unittest.main()
