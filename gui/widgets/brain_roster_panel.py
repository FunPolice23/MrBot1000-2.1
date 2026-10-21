"""Phase 4 N-brain roster UI — per-tier brain count + per-slot config.

A self-contained panel: per tier (Big/Small) a count spinner (1..MAX) and one
configurable row per active slot (provider / model / device / enable). Reads the
initial state from ``BrainRoster.load()`` and writes every edit back through
``BrainRoster.save()`` (which merges via ``merge_settings_file``, ARCH-ENG-070).

The panel is deliberately constructible without a full MainWindow (optional
``root`` / ``devices`` / ``models``) so it is unit-testable headless and a
detection failure can never take the tab down.
"""
from __future__ import annotations

from typing import Any, List, Optional

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel, QSpinBox,
    QVBoxLayout, QWidget,
)

from agents.runtime.brain_roster import (
    MAX_BIG, MAX_SMALL, BrainRoster, BrainSlot, LOCAL_PROVIDERS,
)

# Cloud providers the roster dropdown may offer. The runtime authority is
# SUPPORTED_PROVIDERS (dual_brain): BrainConfig.__post_init__ silently coerces
# any provider NOT in that set to llamacpp, which would point the brain at a
# local server that is not running the cloud model — a guaranteed failure with
# no error. So the dropdown only offers providers the runtime can actually
# drive (never offer what the runtime will discard). Falls back to a known-good
# list if the import fails, so the panel never renders empty.
try:
    from agents.runtime.dual_brain import (
        SUPPORTED_PROVIDERS as _SUPPORTED,
        LOCAL_PROVIDERS as _RT_LOCAL,
    )
    _CLOUD_SAMPLES = sorted(_SUPPORTED - _RT_LOCAL)
except Exception:
    _CLOUD_SAMPLES = ["openai", "groq", "openrouter", "together"]


class _SlotRow(QWidget):
    """One brain slot's config: provider / model / device / enable."""

    changed = Signal()

    def __init__(self, index: int, tier: str, devices: Optional[List[Any]] = None,
                 models: Optional[List[str]] = None, slot: Optional[BrainSlot] = None):
        super().__init__()
        self.index = index
        self.tier = tier
        self.slot = slot or BrainSlot(tier=tier)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        # Seed widgets with signals BLOCKED so construction never emits
        # `changed` (which would persist to settings.json). Only a real operator
        # edit persists — otherwise building the panel inside any test that
        # constructs DualBrainControl would pollute the real settings.json.
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(sorted(LOCAL_PROVIDERS) + _CLOUD_SAMPLES)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.device_combo = QComboBox()
        self.enable_cb = QCheckBox("Enabled")
        for w in (self.provider_combo, self.model_combo, self.device_combo, self.enable_cb):
            w.blockSignals(True)
        try:
            if self.slot.provider:
                self.provider_combo.setCurrentText(self.slot.provider)
            for m in (models or []):
                self.model_combo.addItem(str(m))
            if self.slot.model:
                self.model_combo.setCurrentText(self.slot.model)
            self.device_combo.addItem("Auto", "")
            for d in (devices or []):
                label = d.label() if hasattr(d, "label") else str(getattr(d, "id", d))
                self.device_combo.addItem(label, getattr(d, "id", ""))
            if self.slot.device_id:
                idx = self.device_combo.findData(self.slot.device_id)
                if idx >= 0:
                    self.device_combo.setCurrentIndex(idx)
            self.enable_cb.setChecked(self.slot.enabled)
        finally:
            for w in (self.provider_combo, self.model_combo, self.device_combo, self.enable_cb):
                w.blockSignals(False)

        self.provider_combo.currentTextChanged.connect(lambda _: self.changed.emit())
        lay.addWidget(QLabel("Provider:"))
        lay.addWidget(self.provider_combo)

        self.model_combo.currentTextChanged.connect(lambda _: self.changed.emit())
        lay.addWidget(QLabel("Model:"))
        lay.addWidget(self.model_combo, 1)

        self.device_combo.currentIndexChanged.connect(lambda _: self.changed.emit())
        lay.addWidget(QLabel("Device:"))
        lay.addWidget(self.device_combo)

        self.enable_cb.stateChanged.connect(lambda _: self.changed.emit())
        lay.addWidget(self.enable_cb)

    def to_slot(self) -> BrainSlot:
        return BrainSlot(
            tier=self.tier,
            enabled=self.enable_cb.isChecked(),
            provider=self.provider_combo.currentText().strip(),
            model=self.model_combo.currentText().strip(),
            device_id=self.device_combo.currentData() or "",
            port=0,
        )


class BrainRosterPanel(QWidget):
    """Per-tier brain count + one configurable row per slot; persists the roster."""

    def __init__(self, parent: Optional[QWidget] = None, *,
                 roster: Optional[BrainRoster] = None,
                 devices: Optional[List[Any]] = None,
                 models: Optional[List[str]] = None,
                 root: Optional[str] = None):
        super().__init__(parent)
        self._root = root
        self._devices = list(devices) if devices is not None else self._detect_devices()
        self._models = list(models) if models is not None else []
        self.roster = roster if roster is not None else BrainRoster.load(root=root)
        # Debounce saves: an editable model field fires currentTextChanged per
        # keystroke, and each save is a full merge_settings_file (tmp+fsync+
        # os.replace) on the shared settings.json — a keystroke storm widens the
        # WinError lock-race window. Coalesce edits into one save after a short
        # idle; save_roster_from / the save handlers force an immediate flush.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self._flush_save)

        lay = QVBoxLayout(self)
        self._tier_widgets = {}
        for tier, max_n in (("big", MAX_BIG), ("small", MAX_SMALL)):
            grp = QGroupBox(f"{'Big' if tier == 'big' else 'Small'} Brains")
            gl = QVBoxLayout(grp)
            hl = QHBoxLayout()
            hl.addWidget(QLabel("Count:"))
            spin = QSpinBox()
            spin.setRange(1, max_n)
            existing = self.roster.big if tier == "big" else self.roster.small
            spin.setValue(max(1, len(existing)))
            spin.valueChanged.connect(lambda v, t=tier: self._rebuild_tier(t, v))
            hl.addWidget(spin)
            hl.addStretch(1)
            gl.addLayout(hl)
            rows_box = QVBoxLayout()
            gl.addLayout(rows_box)
            lay.addWidget(grp)
            self._tier_widgets[tier] = {"spin": spin, "rows": rows_box}
            self._rebuild_tier(tier, spin.value())

    def _detect_devices(self) -> List[Any]:
        try:
            from agents.runtime.device_registry import detect_devices
            return detect_devices(include_cpu=False)
        except Exception:
            return []

    def _rebuild_tier(self, tier: str, count: int) -> None:
        info = self._tier_widgets[tier]
        existing = self.roster.big if tier == "big" else self.roster.small
        while info["rows"].count() > count:
            item = info["rows"].takeAt(info["rows"].count() - 1)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        while info["rows"].count() < count:
            i = info["rows"].count()
            slot = existing[i] if i < len(existing) else BrainSlot(tier=tier)
            row = _SlotRow(i, tier, self._devices, self._models, slot)
            row.changed.connect(self._on_changed)
            info["rows"].addWidget(row)

    def _on_changed(self) -> None:
        for tier, info in self._tier_widgets.items():
            slots = []
            for i in range(info["rows"].count()):
                w = info["rows"].itemAt(i).widget()
                if isinstance(w, _SlotRow):
                    slots.append(w.to_slot())
            setattr(self.roster, tier, slots)
        # Debounce: collect now, persist after a short idle (see __init__).
        self._save_timer.start()

    def _flush_save(self) -> None:
        """Persist the roster now (debounce target / forced flush)."""
        try:
            self.roster.save(root=self._root)
        except Exception:
            pass


def save_roster_from(panel: Optional["BrainRosterPanel"] = None,
                     root: Optional[str] = None) -> Optional[BrainRoster]:
    """Shared two-handler entry point: persist a BrainRosterPanel's roster.

    Called from BOTH save handlers (``dual_brain_control._snapshot_settings_values``
    and ``main.save_settings``) per the two-handler rule. Returns the saved
    roster, or ``None`` on failure — never raises, so a failed roster write
    cannot abort the ``.env`` write that follows.
    """
    try:
        if panel is not None and hasattr(panel, "roster"):
            panel._on_changed()  # collect current rows into panel.roster
            panel._flush_save()  # force immediate persist (save-handler path)
            return panel.roster
        roster = BrainRoster.load(root=root)
        roster.save(root=root)
        return roster
    except Exception:
        return None


def flush_pending_roster_edit(panel: Optional["BrainRosterPanel"] = None) -> None:
    """Flush a debounced roster edit to disk BEFORE anything reads it back.

    ARCH-ENG-153. ``_on_changed`` now coalesces writes behind a 400 ms timer,
    but the launch path reads the roster from ``settings.json``
    (``DualBrainRuntime.from_settings()`` -> ``BrainRoster.load_or_none``) and
    reaches none of the save handlers. So an edit followed by Start inside the
    window launched the PREVIOUS model, with no error and no log line.

    Called on the READ side by every path that builds a runtime from the
    persisted roster. Unlike ``save_roster_from`` this writes nothing when
    there is no pending edit, so it is safe to call unconditionally on hot
    paths. Never raises: a failed flush must not abort a brain start, and the
    pre-debounce behaviour (write-on-keystroke) is what it falls back to being.
    """
    if panel is None or not hasattr(panel, "_flush_save"):
        return
    try:
        timer = getattr(panel, "_save_timer", None)
        if timer is not None and timer.isActive():
            panel._flush_save()
            timer.stop()
    except Exception:
        pass
