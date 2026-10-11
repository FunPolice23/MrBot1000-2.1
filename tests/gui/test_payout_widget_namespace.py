"""tests/gui/test_payout_widget_namespace.py

ARCH-ENG-047 (v2.1.47): guard against a tab widget-attribute collision that
broke the Management payout verifier.

ManagementTab owns `self.pay_amount` (a QLineEdit) on the MainWindow parent, and
main.py's `_verify_and_mark_paid` / `_on_management_verify_paid` read and write
it via `.text()` / `.setText()`. The Earnings EarningTab is built LATER on the
same parent (main.py:1428 vs Management at 1419). When the Earnings tab also
named its crypto "Propose Payment" spinbox `self.pay_amount`, the later-built
QDoubleSpinBox clobbered the Management QLineEdit on the shared parent:
  - `_on_management_verify_paid` -> `.setText()` -> AttributeError, and
  - `_verify_and_mark_paid` -> `.text()` returned the spinbox's (empty) text,
    so a typed amount could silently verify as $0.

The Earnings spinbox is now `pay_send_amount`; these tests pin the namespace so
a future same-name reintroduction fails here instead of in production.
"""
import sys
sys.path.insert(0, ".")

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit, QDoubleSpinBox


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_earning_tab_payment_spinbox_does_not_shadow_pay_amount(qt_app):
    """The Earnings crypto-payment spinbox must not be named `pay_amount`."""
    from gui.tabs.earning_tab import EarningTab
    tab = EarningTab()
    assert not hasattr(tab, "pay_amount"), (
        "EarningTab re-introduced `pay_amount`; it collides with ManagementTab's "
        "payout QLineEdit on the shared parent and breaks the payout verifier. "
        "Use `pay_send_amount` (see ARCH-ENG-047)."
    )
    assert isinstance(tab.pay_send_amount, QDoubleSpinBox)


def test_management_and_earnings_tabs_share_parent_without_collision(qt_app):
    """Building both tabs on one parent must leave `pay_amount` as the
    Management QLineEdit (the one the payout verifier uses)."""
    from PySide6.QtWidgets import QWidget
    from gui.tabs.earning_tab import EarningTab

    parent = QWidget()
    # Mirror the real build order: Management (main.py:1419) then Earnings (1428).
    parent.pay_amount = QLineEdit()          # stands in for ManagementTab's field
    parent.pay_amount.setText("250")
    EarningTab(parent=parent)                # built second, on the same parent

    assert isinstance(parent.pay_amount, QLineEdit)
    # The verifier's write path must still work.
    parent.pay_amount.setText("400")
    assert parent.pay_amount.text().strip() == "400"
