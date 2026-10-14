"""Regression: wiring start/stop/refresh buttons must not crash when a brain's
row is a _NullWidget alias (ARCH-ENG-128).

A disabled/missing brain's row is not rendered, so its legacy sb_*/bb_* alias
is a _NullWidget. _NullWidget.__getattr__ answers EVERY attribute name with a
no-op FUNCTION, so `hasattr(self, "sb_start_btn")` is always True and
`self.sb_start_btn.clicked` resolves to that function — calling `.connect` on it
raised `AttributeError: 'function' object has no attribute 'connect'` during
_wire_start_stop_buttons, crashing the Providers & GPU tab on a single-GPU box
(the 2nd GPU in a "GPU is lost" driver state reproduces this exactly).
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

_qapp = QApplication.instance() or QApplication([])

from gui.widgets.dual_brain_control import DualBrainControl, _NullWidget
from agents.runtime.dual_brain import DualBrainRuntime


def _make_control_with_null_small_row():
    """Build a control, then force the small-brain aliases to _NullWidget to
    emulate a box where the small brain's row was not rendered (single GPU)."""
    rt = DualBrainRuntime.from_env()
    w = DualBrainControl(parent=None, runtime=rt)
    # Emulate "small brain row missing": replace the small aliases with the
    # null-object exactly as _alias_legacy_settings_attrs would when no row.
    w.sb_start_btn = _NullWidget()
    w.sb_stop_btn = _NullWidget()
    w.sb_refresh_models_btn = _NullWidget()
    # Clear the provider-rows short-circuit so the wiring path actually runs.
    w._provider_rows = []
    return w


def test_wire_start_stop_buttons_tolerates_null_widget_alias():
    w = _make_control_with_null_small_row()
    # Must NOT raise AttributeError: 'function' object has no attribute 'connect'
    w._wire_start_stop_buttons()


def test_wire_refresh_buttons_tolerates_null_widget_alias():
    w = _make_control_with_null_small_row()
    w._wire_refresh_buttons()


def test_null_widget_clicked_is_a_function_not_a_signal():
    """Prove the mechanism: _NullWidget.clicked is a plain function (no .connect)."""
    nw = _NullWidget()
    assert callable(nw.clicked)
    assert not hasattr(nw.clicked, "connect")


def test_all_slots_disabled_reaches_the_crash_precondition():
    """Realistic end-to-end precondition, not a hand-set alias.

    The crash needs `_provider_rows` EMPTY at the moment the deferred
    `_wire_all_signals()` timer fires. That is exactly the configuration where
    NO brain slot renders at all: every slot disabled (both role brains off, no
    CPU fallback). Build that runtime for real and assert the precondition,
    then run the production wiring path.
    """
    env = dict(os.environ)
    env["BIG_BRAIN_ENABLED"] = "false"
    env["SMALL_BRAIN_ENABLED"] = "false"

    rt = DualBrainRuntime.from_env(env)
    rt.sync_slots = lambda placements: rt.slots()  # no extra device renders
    for cfg in rt.slots():
        cfg.enabled = False

    w = DualBrainControl(parent=None, runtime=rt)
    assert not (getattr(w, "_provider_rows", None) or []), (
        "precondition unmet: a row rendered, so wiring early-returns")
    assert isinstance(w.sb_start_btn, _NullWidget)

    # Production path: _wire_all_signals -> both wiring methods.
    w._wire_start_stop_buttons()
    w._wire_refresh_buttons()
