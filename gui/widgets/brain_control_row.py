"""gui/widgets/brain_control_row.py — one brain's one-click-launch controls.

A ``BrainControlRow`` renders a single brain's launch controls (header with
role + device, status dot, running-model label, Start/Stop buttons) and emits
**slot-keyed** signals so the parent panel can wire N rows to a slot-indexed
handler without knowing anything about BIG/SMALL. This is the reusable building
block for the N-brain Provider Control panel (Phases 2–3 of the N-brain
migration). Nothing here assumes exactly two brains.
"""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget,
)


# Role → (emoji, accent color). Roles are the BrainRole string values
# ("big"/"small"); the color matches the existing Provider Control convention.
_ROLE_STYLE = {
    "big": ("🧠", "#bb86fc"),
    "small": ("🤖", "#03dac6"),
}

_COMBO_QSS = """
    QComboBox {
        background: #1a1a1a;
        color: #e0e0e0;
        border: 1px solid #333;
        border-radius: 4px;
        padding: 4px;
        font-size: 11px;
    }
    QComboBox::drop-down { border: none; }
    QComboBox QAbstractItemView {
        background: #1a1a1a;
        color: #e0e0e0;
        selection-background-color: #03dac6;
    }
"""


class BrainControlRow(QWidget):
    """One brain's launch controls. Emits slot-keyed start/stop/model signals."""

    # slot is the 0-based ordinal in the runtime's slot list.
    start_clicked = Signal(int)
    stop_clicked = Signal(int)
    model_changed = Signal(int, str)  # slot, full model path ("" = unselected)
    mtp_changed = Signal(int, bool)   # slot, enabled (Phase G, ARCH-ENG-093)

    def __init__(self, slot: int, role: str, device_label: str = "",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.slot = slot
        self.role = role
        emoji, accent = _ROLE_STYLE.get(role, ("🧠", "#bb86fc"))
        role_name = "Big Brain" if role == "big" else "Small Brain"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        # Header: emoji + role + device (updated live from the registry).
        self.header = QLabel(f"{emoji} {role_name}")
        self.header.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.header.setStyleSheet(f"color: {accent};")
        layout.addWidget(self.header)

        self.status = QLabel("● Stopped")
        self.status.setStyleSheet("color: #ff5252; font-weight: bold;")
        layout.addWidget(self.status)

        # Model picker: a real dropdown so EVERY slot (including extra devices)
        # can choose a model, not just the two role brains. Full path stored in
        # item data; the visible text is the basename.
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(220)
        self.model_combo.setStyleSheet(_COMBO_QSS)
        self.model_combo.setToolTip(
            "Select the model this brain runs (auto-detected local .gguf files)")
        self.model_combo.currentIndexChanged.connect(self._emit_model_changed)
        layout.addWidget(self.model_combo, 1)

        # MTP (multi-token prediction) toggle — Phase G, ARCH-ENG-093. Enabled
        # only when the selected model carries an MTP head; otherwise greyed out
        # with a plain-language tooltip so it can't be turned on for a model that
        # would no-op or error. Re-evaluated on every model change.
        self.mtp_check = QCheckBox("MTP")
        self.mtp_check.setToolTip(
            "Multi-Token Prediction: faster generation on models with an MTP head.")
        self.mtp_check.setEnabled(False)
        self.mtp_check.stateChanged.connect(self._emit_mtp_changed)
        layout.addWidget(self.mtp_check)

        self.start_btn = QPushButton(f"▶ Start {role_name}")
        self.start_btn.setStyleSheet(f"""
            QPushButton {{
                background: {accent};
                color: #000;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }}
            QPushButton:hover {{ background: {accent}cc; }}
            QPushButton:disabled {{ background: #444; color: #888; }}
        """)
        self.start_btn.clicked.connect(lambda: self.start_clicked.emit(self.slot))
        layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("⏹ Stop")
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background: #ff5252;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }
            QPushButton:hover { background: #ff5252cc; }
            QPushButton:disabled { background: #444; color: #888; }
        """)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(lambda: self.stop_clicked.emit(self.slot))
        layout.addWidget(self.stop_btn)

        if device_label:
            self.set_device_label(device_label)

    # ── Model picker ─────────────────────────────────────────────────────────
    def set_models(self, paths, selected: str = ""):
        """Fill the model dropdown with discovered .gguf paths.

        ``selected`` is a full path (or basename) to pre-select; kept if present.
        Blocks signals during the programmatic fill so we don't emit a spurious
        model_changed.
        """
        paths = list(paths or [])
        self.model_combo.blockSignals(True)
        try:
            self.model_combo.clear()
            self.model_combo.addItem("Select a model...", "")
            select = 0
            sel_norm = _norm(selected)
            for i, p in enumerate(paths):
                self.model_combo.addItem(os.path.basename(p), p)
                if sel_norm and _norm(p) == sel_norm:
                    select = i + 1
            self.model_combo.setCurrentIndex(select)
        finally:
            self.model_combo.blockSignals(False)
        self._refresh_mtp_availability()

    def current_model(self) -> str:
        """Full path behind the dropdown's current item ("" if unselected)."""
        data = self.model_combo.currentData()
        return str(data) if data else ""

    def _emit_model_changed(self, _index):
        self._refresh_mtp_availability()
        self.model_changed.emit(self.slot, self.current_model())

    # ── MTP availability (Phase G, ARCH-ENG-093) ─────────────────────────────
    def _refresh_mtp_availability(self) -> None:
        """Enable the MTP checkbox only when the selected model supports it.

        Greys it out (with a reason) otherwise, so the operator can never turn on
        a flag that would no-op or error on a model without an MTP head.
        """
        model = self.current_model()
        supported = False
        reason = "select a model to check MTP support"
        if model:
            try:
                from agents.providers.model_capabilities import detect_mtp
                info = detect_mtp(model)
                supported = bool(info.get("supported"))
                reason = info.get("reason") or reason
            except Exception as exc:
                reason = f"could not check MTP support: {exc}"
        self.mtp_check.blockSignals(True)
        try:
            self.mtp_check.setEnabled(supported)
            if not supported:
                self.mtp_check.setChecked(False)
            tip = ("MTP available — predicts multiple tokens per pass for faster "
                   "generation on this model." if supported else reason)
            self.mtp_check.setToolTip(tip)
        finally:
            self.mtp_check.blockSignals(False)

    def _emit_mtp_changed(self, _state):
        self.mtp_changed.emit(self.slot, self.mtp_check.isChecked())

    def mtp_enabled(self) -> bool:
        """True only if the box is both enabled (model supports MTP) and checked."""
        return self.mtp_check.isEnabled() and self.mtp_check.isChecked()

    # ── Live updates (called by the parent panel) ────────────────────────────
    def set_device_label(self, label: str) -> None:
        """Update the header to show which device this brain runs on."""
        emoji, accent = _ROLE_STYLE.get(self.role, ("🧠", "#bb86fc"))
        role_name = "Big Brain" if self.role == "big" else "Small Brain"
        suffix = f" · {label}" if label else ""
        self.header.setText(f"{emoji} {role_name}{suffix}")
        self.header.setStyleSheet(f"color: {accent};")

    def set_status(self, text: str, color: str = "#ffb300") -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color}; font-weight: bold;")

    def set_model(self, model_name: str) -> None:
        """Select ``model_name`` (full path or basename) in the dropdown if
        present; otherwise leave the current selection untouched.

        v2.1.79 (ARCH-ENG-098): the status tick calls this every ~4s with the
        same model. Re-selecting an already-selected index re-runs the MTP
        probe, which parses the GGUF header on the GUI thread — a multi-second
        freeze on a 9B+ model. Skip the whole block (including the MTP refresh)
        when the target index is already current, so a steady state costs
        nothing.
        """
        if not model_name:
            return
        sel_norm = _norm(model_name)
        sel_base = _norm(os.path.basename(model_name))
        for i in range(self.model_combo.count()):
            data = self.model_combo.itemData(i)
            if not data:
                continue
            d = str(data)
            if _norm(d) == sel_norm or _norm(os.path.basename(d)) == sel_base:
                if self.model_combo.currentIndex() == i:
                    return  # already selected — no MTP re-probe, no freeze
                self.model_combo.blockSignals(True)
                try:
                    self.model_combo.setCurrentIndex(i)
                finally:
                    self.model_combo.blockSignals(False)
                self._refresh_mtp_availability()
                return

    def set_running(self, running: bool) -> None:
        """Toggle button availability for the running/stopped state."""
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)

    def bind(self, config) -> None:
        """Seed the row from a ``BrainConfig`` (role, device label, model)."""
        try:
            self.role = config.role.value if hasattr(config.role, "value") else str(config.role)
            self.set_device_label(getattr(config, "gpu_label", "") or "")
            self.set_model(getattr(config, "model", "") or "")
        except Exception:
            pass  # bind is best-effort; never break row construction


def _norm(p: str) -> str:
    """Normalize a path for comparison (backslashes, case)."""
    return str(p or "").strip().replace("\\", "/").casefold()


__all__ = ["BrainControlRow"]
