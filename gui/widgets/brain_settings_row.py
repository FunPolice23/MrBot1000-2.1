"""gui/widgets/brain_settings_row.py — editable llama.cpp settings for one brain.

A ``BrainSettingsRow`` renders one brain's editable launch parameters (context,
GPU layers, threads, batch, KV cache, split mode, temperature) and emits a
slot-keyed ``changed`` signal. This gives EVERY enabled device — including the
CPU/RAM pool and extra GPUs (slots 2+) — the same editable settings the two role
brains have, closing the N-brain gap where only Big/Small had controls.

Nothing here assumes exactly two brains. ``bind(config)`` seeds it from a
``BrainConfig``; the parent panel reads the values back on save.
"""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QSpinBox, QDoubleSpinBox, QWidget,
)

# Role → (emoji, accent color). Matches the Provider Control convention.
_ROLE_STYLE = {
    "big": ("🧠", "#bb86fc"),
    "small": ("🤖", "#03dac6"),
}

# Phase G (ARCH-ENG-094): mouse-hover help for each advanced setting.
def _help(key: str) -> str:
    try:
        from agents.knowledge.llama_setting_help import tooltip
        return tooltip(key)
    except Exception:
        return ""

_SPIN_QSS = """
    QSpinBox, QDoubleSpinBox {
        background: #1a1a1a; color: #e0e0e0;
        border: 1px solid #333; border-radius: 4px; padding: 3px;
        font-size: 11px;
    }
"""

_COMBO_QSS = """
    QComboBox {
        background: #1a1a1a; color: #e0e0e0;
        border: 1px solid #333; border-radius: 4px; padding: 3px;
        font-size: 11px;
    }
    QComboBox::drop-down { border: none; }
    QComboBox QAbstractItemView {
        background: #1a1a1a; color: #e0e0e0;
        selection-background-color: #9c27b0;
    }
"""


class BrainSettingsRow(QWidget):
    """Editable llama.cpp settings for one brain slot. Emits slot-keyed changes."""

    changed = Signal(int)  # slot

    def __init__(self, slot: int, role: str, device_label: str = "",
                 is_cpu: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.slot = slot
        self.role = role
        self.is_cpu = is_cpu
        emoji, accent = _ROLE_STYLE.get(role, ("🧠", "#bb86fc"))
        role_name = "Big Brain" if role == "big" else "Small Brain"

        outer = QHBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(10)

        # Header: emoji + role + device.
        self.header = QLabel(f"{emoji} {role_name} · {device_label}" if device_label
                             else f"{emoji} {role_name}")
        self.header.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.header.setStyleSheet(f"color: {accent};")
        self.header.setMinimumWidth(220)
        outer.addWidget(self.header)

        # Context size.
        outer.addWidget(self._lbl("Ctx:"))
        self.ctx_spin = QSpinBox()
        self.ctx_spin.setRange(2048, 524288)
        self.ctx_spin.setValue(32768)
        self.ctx_spin.setSuffix(" tok")
        self.ctx_spin.setFixedWidth(110)
        self.ctx_spin.setStyleSheet(_SPIN_QSS)
        self.ctx_spin.setToolTip(_help("ctx"))
        self.ctx_spin.valueChanged.connect(lambda: self.changed.emit(self.slot))
        outer.addWidget(self.ctx_spin)

        # GPU layers (only meaningful for GPU devices; CPU is system-RAM only).
        outer.addWidget(self._lbl("GPU Layers:"))
        self.gpu_layers_spin = QSpinBox()
        self.gpu_layers_spin.setRange(-1, 999)
        self.gpu_layers_spin.setValue(-1)  # -1 = Auto
        self.gpu_layers_spin.setToolTip(_help("gpu_layers"))
        self.gpu_layers_spin.setFixedWidth(70)
        self.gpu_layers_spin.setStyleSheet(_SPIN_QSS)
        self.gpu_layers_spin.valueChanged.connect(lambda: self.changed.emit(self.slot))
        outer.addWidget(self.gpu_layers_spin)
        if is_cpu:
            # CPU pool: force 0 (system RAM), disable the control.
            self.gpu_layers_spin.setValue(0)
            self.gpu_layers_spin.setEnabled(False)

        # Threads.
        outer.addWidget(self._lbl("Threads:"))
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 256)
        self.threads_spin.setValue(8 if role == "big" else 4)
        self.threads_spin.setFixedWidth(60)
        self.threads_spin.setStyleSheet(_SPIN_QSS)
        self.threads_spin.setToolTip(_help("threads"))
        self.threads_spin.valueChanged.connect(lambda: self.changed.emit(self.slot))
        outer.addWidget(self.threads_spin)

        # Batch.
        outer.addWidget(self._lbl("Batch:"))
        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(32, 8192)
        self.batch_spin.setValue(2048)
        self.batch_spin.setFixedWidth(80)
        self.batch_spin.setStyleSheet(_SPIN_QSS)
        self.batch_spin.setToolTip(_help("batch"))
        self.batch_spin.valueChanged.connect(lambda: self.changed.emit(self.slot))
        outer.addWidget(self.batch_spin)

        # KV cache type.
        outer.addWidget(self._lbl("KV:"))
        self.kv_combo = QComboBox()
        self.kv_combo.addItems(["auto", "f16", "q8_0", "q4_0", "q5_1", "q5_0", "q4_1"])
        self.kv_combo.setCurrentText("f16")
        self.kv_combo.setFixedWidth(80)
        self.kv_combo.setStyleSheet(_COMBO_QSS)
        self.kv_combo.setToolTip(_help("kv_cache"))
        self.kv_combo.currentTextChanged.connect(lambda: self.changed.emit(self.slot))
        outer.addWidget(self.kv_combo)

        # Split mode.
        outer.addWidget(self._lbl("Split:"))
        self.split_combo = QComboBox()
        self.split_combo.addItems(["none", "layer", "row"])
        self.split_combo.setCurrentText("none")
        self.split_combo.setFixedWidth(80)
        self.split_combo.setStyleSheet(_COMBO_QSS)
        self.split_combo.setToolTip(_help("split_mode"))
        self.split_combo.currentTextChanged.connect(lambda: self.changed.emit(self.slot))
        outer.addWidget(self.split_combo)

        # Temperature.
        outer.addWidget(self._lbl("Temp:"))
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.05)
        self.temp_spin.setValue(0.5)
        self.temp_spin.setFixedWidth(70)
        self.temp_spin.setStyleSheet(_SPIN_QSS)
        self.temp_spin.setToolTip(_help("temperature"))
        self.temp_spin.valueChanged.connect(lambda: self.changed.emit(self.slot))
        outer.addWidget(self.temp_spin)

        outer.addStretch(1)

    @staticmethod
    def _lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #888; font-size: 11px;")
        return lbl

    # ── Seed / read back ─────────────────────────────────────────────────────
    def bind(self, config) -> None:
        """Seed the controls from a ``BrainConfig`` (blocks signals during fill)."""
        try:
            self.role = config.role.value if hasattr(config.role, "value") else str(config.role)
            # ARCH-ENG-298 (L-01): surface the per-model llama.cpp guidance
            # that was previously dead data. The operator sees it on the row
            # they are editing; nothing is applied without their action.
            try:
                model = getattr(config, "model", "") or ""
                if model:
                    from agents.providers.model_recommendations import summary
                    self.header.setToolTip(summary(model))
            except Exception:
                pass
            for w in (self.ctx_spin, self.gpu_layers_spin, self.threads_spin,
                      self.batch_spin, self.kv_combo, self.split_combo, self.temp_spin):
                w.blockSignals(True)
            try:
                if getattr(config, "context", None):
                    self.ctx_spin.setValue(int(config.context))
                gl = config.gpu_layers
                if not self.is_cpu and gl is not None:
                    self.gpu_layers_spin.setValue(int(gl))
                if getattr(config, "threads", None):
                    self.threads_spin.setValue(int(config.threads))
                if getattr(config, "batch", None):
                    self.batch_spin.setValue(int(config.batch))
                if getattr(config, "kv_cache", ""):
                    self.kv_combo.setCurrentText(config.kv_cache)
                if getattr(config, "split_mode", ""):
                    self.split_combo.setCurrentText(config.split_mode)
            finally:
                for w in (self.ctx_spin, self.gpu_layers_spin, self.threads_spin,
                          self.batch_spin, self.kv_combo, self.split_combo, self.temp_spin):
                    w.blockSignals(False)
        except Exception:
            pass  # bind is best-effort

    def apply_to(self, config) -> None:
        """Write the current control values back into a ``BrainConfig``."""
        try:
            config.context = self.ctx_spin.value()
            if not self.is_cpu:
                v = self.gpu_layers_spin.value()
                config.gpu_layers = None if v < 0 else int(v)
            else:
                config.gpu_layers = 0
            config.threads = self.threads_spin.value()
            config.batch = self.batch_spin.value()
            config.kv_cache = self.kv_combo.currentText() or "f16"
            config.split_mode = self.split_combo.currentText() or "none"
        except Exception:
            pass

    def values(self) -> dict:
        """Current control values as a plain dict (for persistence)."""
        return {
            "context": self.ctx_spin.value(),
            "gpu_layers": (0 if self.is_cpu else
                           (None if self.gpu_layers_spin.value() < 0
                            else int(self.gpu_layers_spin.value()))),
            "threads": self.threads_spin.value(),
            "batch": self.batch_spin.value(),
            "kv_cache": self.kv_combo.currentText() or "f16",
            "split_mode": self.split_combo.currentText() or "none",
            "temperature": self.temp_spin.value(),
        }


__all__ = ["BrainSettingsRow"]
