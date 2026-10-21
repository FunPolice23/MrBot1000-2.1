# ═══════════════════════════════════════════════════════════════════════════
# DUAL BRAIN CONTROL PANEL — v2.5 (llama-server both brains)
# ═══════════════════════════════════════════════════════════════════════════
# PURPOSE: One-click orchestrator for dual-GPU inference setup.
#          Small Brain (llama-server on 1660S, port 1235)
#          Big Brain (llama-server on 5060Ti, port 1234)
#
# TO REMOVE THIS FEATURE:
#   1. Delete this file (gui/dual_brain_control.py)
#   2. Remove create_dual_brain_tab() from gui/tab_builders.py
#   3. Remove ("Dual Brain", self.create_dual_brain_tab) from main.py tab_specs
#   4. Remove agents/big_brain.py and agents/small_brain.py (if no longer needed)
#   5. Remove prompts/big_brain.txt and prompts/small_brain.txt
#
# GPU ALLOCATION:
#   - GPU 0 (5060 Ti 16GB): Big Brain via llama-server (device 0, port 1234)
#   - GPU 1 (1660 Super 6GB): Small Brain via llama-server (device 1, port 1235)
#   - Both can overflow to system RAM
#   - Hardware-level isolation via CUDA contexts
# ═══════════════════════════════════════════════════════════════════════════

import json
import os
import subprocess
import tempfile
import threading
import time
import traceback
import urllib.request
from datetime import datetime
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, QThread, QTimer, Signal, QObject
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from agents.providers.provider_lifecycle import ProviderStatusChecker
from gui.workers.brain_launch_worker import BrainLaunchWorker
from gui.workers.provider_lifecycle_backend import ProviderLifecycleBackend
from gui.workers.provider_workers import ProviderProbeWorker, ProviderStopWorker


# Shared compact QSS for the llama.cpp customization spins/combos (v2.1).
SMALL_SPIN_QSS = """
    QSpinBox, QComboBox {
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
BIG_SPIN_QSS = """
    QSpinBox, QComboBox {
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
        selection-background-color: #bb86fc;
    }
"""


HARDWARE_PRESETS = {
    "Safe / low VRAM": {
        "small": (8192, 512, 4, -1, "q8_0"),
        "big": (16384, 1024, 6, -1, "q8_0"),
        "help": "Fits modest GPUs more easily: smaller context and batches use less VRAM, with a small quality/speed tradeoff.",
    },
    "Balanced": {
        "small": (16384, 1024, 4, -1, "f16"),
        "big": (32768, 2048, 8, -1, "f16"),
        "help": "A practical starting point for a single mid-range GPU or the current dual-GPU setup.",
    },
    "CPU only": {
        "small": (4096, 256, 4, 0, "q8_0"),
        "big": (8192, 512, 6, 0, "q8_0"),
        "help": "Disables GPU layers and reduces memory pressure. Expect slower generation, but it should run without CUDA.",
    },
    "Quality / high VRAM": {
        "small": (32768, 2048, 6, -1, "f16"),
        "big": (65536, 4096, 10, -1, "f16"),
        "help": "For systems with plenty of VRAM. Larger context and batches can improve throughput but consume substantially more memory.",
    },
}


# ═══════════════════════════════════════════════════════════════════════════
# GPU STATUS WORKER — runs nvidia-smi in background to avoid GUI freeze
# ═══════════════════════════════════════════════════════════════════════════
class GPUStatusWorker(QThread):
    """Background worker that polls GPU status."""
    status_updated = Signal(list)  # List of dicts with GPU info
    
    def __init__(self, interval_ms=2000):
        super().__init__()
        self.interval_ms = interval_ms
        self.running = True
    
    def run(self):
        """Poll GPU status every interval."""
        while self.running and not self.isInterruptionRequested():
            try:
                gpus = self._get_gpu_status()
                self.status_updated.emit(gpus)
            except Exception:
                pass  # GPU polling is best-effort; don't crash the thread
            if self.running and not self.isInterruptionRequested():
                self.msleep(self.interval_ms)

    def stop(self):
        """Request the polling loop to exit so shutdown can join the thread."""
        self.running = False
        self.requestInterruption()
    
    def _get_gpu_status(self):
        """Get GPU status via nvidia-smi.

        ARCH-ENG-183 — TWO DEFECTS HERE.

        1. `subprocess.run(..., capture_output=True)` IS THE BROKEN FORM.
           ARCH-ENG-116 established that it raises
           `OSError(22, 'The request is not supported')` / WinError 50 on
           Windows whenever the parent's stdout is a reconfigured pipe, which is
           what `pytest --capture=fd` does. Combined with the blanket
           `except Exception: pass` below, the GPU panel silently froze on its
           last values with nothing anywhere. Now it uses the one hardened
           nvidia-smi invocation (ARCH-ENG-116/166).

        2. ONE BAD ROW ABORTED THE WHOLE POLL. `int(parts[4])` raises
           ValueError when utilization reads `N/A` — which nvidia-smi does emit
           routinely for idle/unsupported fields — and that exception was caught
           by the outer handler, so the function returned an EMPTY list and EVERY
           GPU vanished from the panel. Row parsing is now per-row: a bad row is
           skipped and the rest are reported.

        A third `stop()` definition also existed below this one, shadowed by the
        first; it is removed, because a duplicated teardown method is a trap for
        the next reader.
        """
        gpus = []
        query = "index,name,memory.used,memory.total,utilization.gpu"
        try:
            from agents.runtime.device_registry import _run_nvidia_smi
            stdout = _run_nvidia_smi(query)
        except Exception:
            return gpus          # best-effort; no GPU data is a valid answer
        for line in str(stdout or "").strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 5:
                continue
            # ARCH-ENG-183: per-row tolerance. `N/A` is routine in nvidia-smi
            # output and must not cost us every OTHER gpu.
            try:
                gpus.append({
                    "index": int(parts[0]),
                    "name": parts[1],
                    "memory_used_mb": int(float(parts[2])),
                    "memory_total_mb": int(float(parts[3])),
                    "utilization": int(float(parts[4])) if parts[4] != "N/A" else 0,
                })
            except (ValueError, TypeError):
                continue
        return gpus


# ═══════════════════════════════════════════════════════════════════════════
# PROVIDER STATUS CHECKER — Detects running llama-server instances
# ═══════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════
# DUAL BRAIN CONTROL PANEL — Main Widget
# ═══════════════════════════════════════════════════════════════════════════
class _WheelEventFilter(QObject):
    """Event filter that blocks wheel scroll on QComboBox while dropdown is closed.
    
    This prevents accidental model changes when the user scrolls over the
    combo box. The user must click to open the dropdown before scrolling
    to change the selection.
    """
    def __init__(self, combo, parent=None):
        super().__init__(parent)
        self.combo = combo
    
class _ModelLabelAdapter:
    """Legacy shim: lets the backend call ``sb_model_label.setText(name)``.

    BrainControlRow exposes a model dropdown, not a label. ``setText`` selects
    the matching model in the row's dropdown (so the running model shows up);
    ``text()`` returns the current model's basename for any reader. Transitional
    — new code should call ``row.set_model()`` / ``row.current_model()``.
    """

    def __init__(self, row):
        self._row = row

    def setText(self, name: str):
        try:
            if not name:
                return
            # "Model: —" or a bare basename/path -> select it in the dropdown.
            cleaned = name.replace("Model:", "").strip()
            if cleaned and cleaned != "—":
                self._row.set_model(cleaned)
        except Exception:
            pass

    def text(self) -> str:
        try:
            model = self._row.current_model()
            return f"Model: {os.path.basename(model)}" if model else "Model: —"
        except Exception:
            return "Model: —"


class _NullWidget:
    """Null-object standing in for a disabled brain's legacy alias widgets.

    v2.1.53 (ARCH-ENG-053): when a brain is disabled (single-GPU box, CPU
    unchecked) its row is not rendered, so the legacy sb_*/bb_* aliases have no
    real widget. Pointing them here makes every downstream setText / setStyleSheet
    / setEnabled a harmless no-op instead of an AttributeError that aborts the
    start flow. Any attribute access that isn't a known setter returns a no-op
    callable, so it tolerates the full range of legacy call patterns.
    """

    def setText(self, *a, **k):
        pass

    def setStyleSheet(self, *a, **k):
        pass

    def setEnabled(self, *a, **k):
        pass

    def text(self, *a, **k):
        return ""

    def isEnabled(self, *a, **k):
        return False

    def __getattr__(self, name):
        # Any other method/attribute the legacy code might poke -> no-op callable.
        def _noop(*a, **k):
            return None
        return _noop


class DualBrainControl(ProviderLifecycleBackend, QWidget):
    """Control panel for dual-brain GPU orchestration."""

    _restart_ready = Signal(bool)
    _external_lifecycle_finished = Signal(bool, bool, str)
    _vram_estimate_ready = Signal(int, str, object)
    # ARCH-ENG-182: marshals a "clear the Loading state" request from a raw
    # worker thread onto the GUI thread. `_do_restart` runs on a
    # `threading.Thread`, which has NO Qt event loop, so a
    # `QTimer.singleShot` from there never fires and the brain row stays stuck
    # at "Loading...". Emitting to a slot on this QObject is queued instead.
    _loading_clear_requested = Signal(bool)
    # Background threads (model restart, VRAM estimate) must not touch QWidgets
    # directly — that is undefined behaviour in Qt and shows up as random freezes
    # and access violations. They emit this instead; the slot runs on the GUI
    # thread.
    _log_requested = Signal(str)

    # ARCH-ENG-057: >0 while `_apply_runtime` is programmatically filling the
    # per-device settings controls. Seeding must never be treated as an operator
    # edit, because each row's valueChanged is wired directly to
    # `_on_brain_settings_changed` -> `save_policy()`, and firing there persisted
    # hardcoded constructor defaults over the operator's saved per-device model +
    # llama.cpp settings. A counter (not a bool) so nested/recursive seeding
    # paths cannot clear it early. Class-level default so the attribute exists
    # even on instances built via `__new__` (tests do this to reach methods
    # without paying for full widget construction).
    _seeding_settings = 0
    
    # Signals emitted when model changes
    small_brain_model_changed = Signal(str)  # model_name
    big_brain_model_changed = Signal(str)    # model_name
    provider_probed = Signal(object)         # dict from background provider probe
    provider_detection_ready = Signal(object)
    vram_warning_requested = Signal(bool, str, float, float, object)
    
    def __init__(self, parent=None, runtime=None):
        super().__init__(parent)

        # Expand to fill available space in scroll areas / layouts
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(400)

        # v2.1 Phase 5: canonical runtime is the single source of truth for
        # endpoint/model/device config. Optional; the widget still works with
        # its own defaults when no runtime is injected (back-compat).
        self.runtime = runtime
        self._restart_ready.connect(self._continue_model_restart)
        self._external_lifecycle_finished.connect(self._finish_external_lifecycle)
        self._log_requested.connect(self._append_log_line)

        # Provider checkers
        self.provider_checker = ProviderStatusChecker()
        self.vram_warning_requested.connect(self._show_vram_warning)
        
        # Initialize provider manager for dynamic provider/GPU detection
        from agents.providers.provider_manager import ProviderManager
        self.provider_manager = ProviderManager.instance()
        self._hardware_tensor_types = {}
        self.provider_detection_ready.connect(self._on_provider_detection_ready)
        
        # Track which providers we started (vs already running)
        self.we_started_small = False
        self.we_started_big = False
        self._closing = False
        self._provider_probe_thread = None
        self._vram_estimates = {}
        self._vram_estimate_inflight = set()
        self._vram_estimate_ready.connect(self._on_vram_estimate_ready)
        # ARCH-ENG-182: queued onto the GUI thread by Qt, which is what a
        # `QTimer.singleShot` from a raw `threading.Thread` could not do.
        self._loading_clear_requested.connect(self._on_loading_clear_requested)

        # Guard against auto-restart loops from probe-triggered combo changes
        self._suppress_model_change_restart = False

        # ARCH-ENG-057: >0 while `_apply_runtime` is programmatically filling the
        # per-device settings controls. Seeding must never be treated as an
        # operator edit, because the row's valueChanged is wired directly to
        # `_on_brain_settings_changed` -> `save_policy()`, and firing there
        # persisted hardcoded constructor defaults over the operator's saved
        # per-device settings. A counter (not a bool) so nested/recursive
        # seeding paths cannot clear it early.
        self._seeding_settings = 0

        # GPU status worker (background thread)
        self.gpu_worker = GPUStatusWorker(interval_ms=2000)
        self.gpu_worker.status_updated.connect(self._on_gpu_status_updated)
        
        # Track last user-selected model to prevent auto-restart loops
        self._last_small_model = None
        self._last_big_model = None
        
        # Build the UI — widget construction only; signal wiring deferred
        # to _wire_all_signals via QTimer to avoid AttributeError on methods
        # defined later in the class body.
        self.setup_ui()
        self._apply_hardware_tensor_options()

        # Defer all signal/slot connections to the next event-loop cycle so
        # every handler method (defined later in the class body) is guaranteed
        # to exist before we try to connect to it.
        QTimer.singleShot(0, self._wire_all_signals)
        
        # Provider probe runs on a background thread; apply results on the GUI
        # thread via this signal (v2.1 tab-switch freeze fix).
        self.provider_probed.connect(self._safe_apply_provider_status)

        # Seed ctx/endpoint labels from the canonical runtime when injected.
        self._apply_runtime()
        
        # Start GPU monitoring thread (non-blocking)
        self.gpu_worker.start()
        
        # Defer provider status refresh to next event loop cycle so the widget
        # paints first without blocking on HTTP calls to llama-server ports.
        QTimer.singleShot(0, self._refresh_provider_status)

        # v2.1.60 (ARCH-ENG-073): a llama-server can die on its own (OOM, GPU
        # contention, mmproj mismatch abort) with the app still alive. Without a
        # periodic re-probe the status row froze at "● Running" and the operator
        # was misled into thinking the brain was still loaded when its process
        # was gone (e.g. the big brain on port 1234 dying while the GUI showed
        # Running). _refresh_provider_status already runs the probe on a
        # background thread and applies results via a queued signal, so a slow
        # or dead port never blocks the GUI. Poll every 4s while the panel is
        # open; cleanup() stops it.
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(4000)
        self._status_timer.timeout.connect(self._refresh_provider_status)
        self._status_timer.start()
        
        # Build dynamic provider panels after detection. Provider discovery
        # performs GPU and endpoint probes, so it must not run on the Qt thread.
        if getattr(self.provider_manager, "_detected", False):
            self._on_provider_detection_ready(self.provider_manager.get_providers())
        else:
            self._start_provider_detection()

    def _start_provider_detection(self):
        """Detect providers without blocking construction or tab painting."""
        if getattr(self, "_provider_detection_thread", None) is not None:
            if self._provider_detection_thread.is_alive():
                return

        def detect():
            try:
                # Route through _detect_once so a concurrent warm_up() (kicked
                # off at app launch) and this widget never run detect_providers()
                # at the same time — the lock serialises them and the second
                # caller just returns the already-populated cache.
                providers = self.provider_manager._detect_once()
            except Exception:
                providers = {}
            if not getattr(self, "_closing", False):
                self.provider_detection_ready.emit(providers)

        self._provider_detection_thread = threading.Thread(
            target=detect,
            name="provider-detection",
            daemon=True,
        )
        self._provider_detection_thread.start()

    def _on_provider_detection_ready(self, _providers):
        """Apply background provider discovery results on the Qt thread."""
        if getattr(self, "_closing", False):
            return
        self._apply_hardware_tensor_options()
        self._apply_runtime()
        # The subtitle/provider summary were rendered from an empty cache during
        # construction; refresh them now that detection has populated it.
        self._update_gpu_subtitle()
        # ARCH-ENG-140: _build_provider_panels was deliberately REMOVED. It built
        # 12+ QFrames, never parented or added them to any layout, and discarded
        # them on every detection-ready callback. Its controls were nonetheless
        # live: _on_model_changed fired on currentTextChanged and wrote BOTH
        # BIG_BRAIN_MODEL and SMALL_BRAIN_MODEL to .env — so picking one item in
        # an invisible panel rewrote persisted config for both roles. The live
        # path is ProviderConfigWidget (tab_feature_builders.py:1910).

    def _update_gpu_subtitle(self):
        """Render the GPU-count subtitle from the current detection cache."""
        label = getattr(self, "_gpu_subtitle_label", None)
        if label is None:
            return
        try:
            gpus = self.provider_manager.get_gpus(detect=False)
            if len(gpus) >= 2:
                text = f"GPU-Isolated Inference: {gpus[0].name} (Big) + {gpus[1].name} (Small)"
            elif len(gpus) == 1:
                text = f"Single GPU: {gpus[0].name} (Cloud fallback available)"
            else:
                text = "Cloud-Only Mode (No local GPUs detected)"
            label.setText(text)
        except Exception:
            pass

    def _wire_start_stop_buttons(self):
        """Wire up start/stop buttons after class body is fully defined.

        The handler methods (_on_start_small_brain, _on_stop_small_brain,
        _on_start_big_brain, _on_stop_big_brain) are defined later in the
        class body. During __init__ -> setup_ui(), they don't exist yet.
        Defer wiring to the next event-loop cycle where they're guaranteed
        to be available.

        N-brain (Phase 3): when Provider Control renders BrainControlRow widgets,
        each row's own ``start_clicked``/``stop_clicked`` already routes to the
        right handler via ``_on_provider_row_start/stop``. Connecting the legacy
        ``.clicked`` here too would fire the handler TWICE, so we skip it when
        the buttons belong to a row (they always do once rows are built).
        """
        if getattr(self, "_provider_rows", None):
            return  # rows self-wire via slot-keyed signals
        # ARCH-ENG-128: a disabled brain's row is not rendered, so its legacy
        # alias is a _NullWidget. _NullWidget.__getattr__ answers EVERY name
        # (returning a no-op function), so `hasattr(self, "sb_start_btn")` is
        # always True and `sb_start_btn.clicked` resolves to that no-op
        # FUNCTION — calling `.connect` on it raises
        # "AttributeError: 'function' object has no attribute 'connect'".
        # Skip null-object aliases; only a REAL button has a .clicked.connect.
        def _real_btn(w):
            return w if (w is not None and not isinstance(w, _NullWidget)) else None
        for _attr, _handler in (
            ("sb_start_btn", self._on_start_small_brain),
            ("sb_stop_btn", self._on_stop_small_brain),
            ("bb_start_btn", self._on_start_big_brain),
            ("bb_stop_btn", self._on_stop_big_brain),
        ):
            _b = _real_btn(getattr(self, _attr, None))
            if _b is not None:
                _b.clicked.connect(_handler)

    def _wire_refresh_buttons(self):
        """Wire up refresh/model buttons after class body is fully defined.

        ARCH-ENG-128: same null-object guard as _wire_start_stop_buttons — a
        _NullWidget alias answers every attribute with a no-op function, so
        `.clicked.connect` would raise. Only real buttons are wired.
        """
        def _real_btn(w):
            return w if (w is not None and not isinstance(w, _NullWidget)) else None
        for _attr, _handler in (
            ("sb_refresh_models_btn", self._refresh_small_brain_models),
            ("bb_refresh_models_btn", self._refresh_big_brain_models),
        ):
            _b = _real_btn(getattr(self, _attr, None))
            if _b is not None:
                _b.clicked.connect(_handler)

    def _apply_hardware_preset(self):
        """Apply the selected preset to the chosen hardware target."""
        from agents.runtime.dual_brain import BrainRole, DualBrainRuntime

        preset = HARDWARE_PRESETS[self.hardware_preset_combo.currentText()]
        runtime = self.runtime or DualBrainRuntime.from_env()
        gpus = {gpu.index: gpu for gpu in self.provider_manager.get_gpus(detect=False)}
        targets = {
            "Small Brain / GPU 1": (("sb", BrainRole.SMALL),),
            "Big Brain / GPU 0": (("bb", BrainRole.BIG),),
            "Both brains": (("sb", BrainRole.SMALL), ("bb", BrainRole.BIG)),
        }.get(self.hardware_preset_target_combo.currentText(), ())
        for prefix, role in targets:
            config = runtime.config(role)
            values = self._adapt_preset_for_hardware(
                preset["big"], gpus.get(config.device),
                cpu_only=config.gpu_layers == 0 or config.device not in gpus)
            ctx, batch, threads, gpu_layers, kv = values
            getattr(self, f"{prefix}_ctx_spin").setValue(ctx)
            getattr(self, f"{prefix}_batch_spin").setValue(batch)
            getattr(self, f"{prefix}_threads_spin").setValue(threads)
            getattr(self, f"{prefix}_gpu_layers_spin").setValue(gpu_layers)
            getattr(self, f"{prefix}_kv_combo").setCurrentText(kv)
        self.hardware_preset_help.setText(
            preset["help"] + " Click Save to write these values.")

    @staticmethod
    def _adapt_preset_for_hardware(values, gpu=None, cpu_only=False):
        """Adapt a shared preset to device memory and supported KV types."""
        context, batch, threads, gpu_layers, kv = values
        if cpu_only:
            return min(context, 8192), min(batch, 512), min(threads, 6), 0, "q8_0"

        supported = set(gpu.tensor_types if gpu else ())
        if gpu and gpu.memory_total_mb <= 8192:
            context = min(context, 16384)
            batch = min(batch, 1024)
            threads = min(threads, 6)
        if kv not in supported:
            kv = "q8_0" if "q8_0" in supported else (next(iter(supported), "f16"))
        return context, batch, threads, gpu_layers, kv

    def _apply_hardware_tensor_options(self):
        """Limit KV choices to the assigned GPU's supported tensor profile.

        ARCH-ENG-194: `__init__` calls this immediately after `setup_ui()`
        (line 375), but the `sb_kv_combo` / `bb_kv_combo` it reads are not
        created by `setup_ui` itself -- they are assigned later by
        `_alias_legacy_settings_attrs`, which runs when the brain rows are built.
        So whether these attributes exist at construction time depends on
        whether device detection produced brain rows at all.

        On a machine with no detected GPU rows, that made construction raise
        `AttributeError: 'DualBrainControl' object has no attribute
        'sb_kv_combo'` -- a crash in `__init__`, not a degraded panel. Found by
        the new mixin-contract guard, which constructs the widget directly.

        A method called from `__init__` must not assume later-initialised state
        exists, so the combos are resolved defensively and a missing one is
        skipped. This is also the honest behaviour: with no row there is no
        combo to constrain.
        """
        from agents.providers.provider_manager import supported_tensor_types
        from agents.runtime.dual_brain import BrainRole, DualBrainRuntime

        gpus = {gpu.index: gpu for gpu in self.provider_manager.get_gpus(detect=False)}
        for small, name in ((True, "sb_kv_combo"), (False, "bb_kv_combo")):
            combo = getattr(self, name, None)
            if combo is None:
                # The brain rows have not been built yet (or never will be).
                # `_apply_hardware_tensor_options` is also called again at
                # line 446 once detection completes, so nothing is lost.
                continue
            role = BrainRole.SMALL if small else BrainRole.BIG
            runtime = self.runtime or DualBrainRuntime.from_env()
            device = runtime.config(role).device
            gpu = gpus.get(device)
            options = gpu.tensor_types if gpu else supported_tensor_types(cpu=True)
            if not options:
                # An empty option list would make `options[0]` raise below.
                continue
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(options)
            combo.setCurrentText(current if current in options else options[0])
            combo.blockSignals(False)
            hardware = gpu.name if gpu else "CPU / system RAM"
            capability = f" SM {gpu.compute_capability}" if gpu and gpu.compute_capability else ""
            combo.setToolTip(
                f"Supported KV/tensor types for {hardware}{capability}: "
                + ", ".join(options))
            self._hardware_tensor_types[small] = options
            label = getattr(self, "sb_kv_label" if small else "bb_kv_label", None)
            if label is not None:
                label.setText("Small KV Cache:" if small else "Big KV Cache:")
                label.setToolTip(
                    f"{hardware}{capability}. Available KV/tensor types: {', '.join(options)}")
        profiles = []
        runtime = self.runtime or DualBrainRuntime.from_env()
        for small in (True, False):
            role = BrainRole.SMALL if small else BrainRole.BIG
            device = runtime.config(role).device
            gpu = gpus.get(device)
            # ARCH-ENG-194: `.get`, not `[...]`. The loop above now skips a brain
            # whose combo does not exist yet, so a direct index raised KeyError
            # here -- the same latent assumption, one level down. The summary line
            # is a convenience; a missing profile must not take down the panel.
            options = self._hardware_tensor_types.get(small)
            if not options:
                continue
            if gpu:
                sm = f"SM {gpu.compute_capability}" if gpu.compute_capability else "SM unknown"
                profiles.append(f"{'Small' if small else 'Big'}: {gpu.name} ({sm}) -> {', '.join(options)}")
            else:
                profiles.append(f"{'Small' if small else 'Big'}: CPU / system RAM -> {', '.join(options)}")
        if profiles:
            self.tensor_profile_label.setText(
                "Hardware tensor/KV profiles: " + " | ".join(profiles))
        self.tensor_profile_label.setText("Hardware tensor/KV profiles: " + " | ".join(profiles))
        self._sync_gpu_hardware_controls()

    def _sync_gpu_hardware_controls(self):
        """Mirror live brain KV values in the detected-GPU summary rows."""
        for index, control in getattr(self, "gpu_hardware_controls", {}).items():
            role = control.get("role")
            if role == "Big Brain":
                combo = control["kv_combo"]
                combo.blockSignals(True)
                combo.setCurrentText(self.bb_kv_combo.currentText())
                combo.blockSignals(False)
            elif role == "Small Brain":
                combo = control["kv_combo"]
                combo.blockSignals(True)
                combo.setCurrentText(self.sb_kv_combo.currentText())
                combo.blockSignals(False)

    def _wire_settings_signals(self):
        """Wire up settings spinbox/combo signals after class body is fully defined.

        The signal handlers (_on_context_changed, _on_small_brain_model_changed,
        _on_big_brain_model_changed, _on_start_all, _on_stop_all,
        _refresh_provider_status, _persist_settings) are defined later in the
        class body. Defer wiring to the next event-loop cycle.
        """
        try:
            if hasattr(self, "sb_ctx_spin"):
                self.sb_ctx_spin.valueChanged.connect(lambda: self._on_context_changed(False))
            if hasattr(self, "bb_ctx_spin"):
                self.bb_ctx_spin.valueChanged.connect(lambda: self._on_context_changed(True))
            if hasattr(self, "sb_model_combo"):
                self.sb_model_combo.currentTextChanged.connect(self._on_small_brain_model_changed)
            if hasattr(self, "bb_model_combo"):
                self.bb_model_combo.currentTextChanged.connect(self._on_big_brain_model_changed)
            if hasattr(self, "start_all_btn"):
                self.start_all_btn.clicked.connect(self._on_start_all)
            if hasattr(self, "stop_all_btn"):
                self.stop_all_btn.clicked.connect(self._on_stop_all)
            if hasattr(self, "refresh_btn"):
                self.refresh_btn.clicked.connect(self._refresh_provider_status)
            if hasattr(self, "save_settings_btn"):
                self.save_settings_btn.clicked.connect(self._persist_settings)
            # Temperature spinbox signals.
            if hasattr(self, "sb_temp_spin"):
                self.sb_temp_spin.valueChanged.connect(self._persist_settings)
            if hasattr(self, "bb_temp_spin"):
                self.bb_temp_spin.valueChanged.connect(self._persist_settings)
            # Auto-start toggle persists its choice to .env (AUTO_START_SERVERS).
            if hasattr(self, "auto_start_check"):
                self.auto_start_check.stateChanged.connect(self._persist_settings)
            if hasattr(self, "show_server_consoles_check"):
                self.show_server_consoles_check.stateChanged.connect(self._persist_settings)
        except RuntimeError:
            # The widget may be in teardown while the delayed singleShot callback
            # is still running; do not crash the parent app during rebuilds.
            pass

    def _wire_all_signals(self):
        """Wire all deferred signals in one shot — called once via QTimer after
        setup_ui() completes, when every handler method is guaranteed to exist."""
        self._wire_start_stop_buttons()
        self._wire_refresh_buttons()
        self._wire_settings_signals()

    def _apply_plan_device_assignment(self, small, big):
        """Assign role→device from the device registry (detection + policy).

        The registry detects every GPU (by stable UUID) and the CPU/RAM pool,
        classifies each by VRAM/RAM, and applies the operator's persisted
        enable/disable + role choices. Big maps to the first big-class enabled
        device, Small to the first small-class enabled device — GPUs preferred
        over CPU within a class. A device the operator pinned via <ROLE>_DEVICE
        (a value differing from the role default) is left untouched.

        N-brain (Phase 1): the same placements are fed to ``runtime.sync_slots``
        so the runtime grows/shrinks its slot list to match every enabled device
        (slots 2+ are built automatically). Only touches llamacpp roles. Never
        raises.
        """
        try:
            from agents.runtime import device_registry as dr

            def _pinned(prefix, default_idx):
                raw = (os.getenv(f"{prefix}_DEVICE", "") or "").strip()
                if raw == "":
                    return False
                try:
                    return int(raw) != default_idx
                except ValueError:
                    return False

            big_pinned = _pinned("BIG_BRAIN", 0)
            small_pinned = _pinned("SMALL_BRAIN", 1)
            if big_pinned and small_pinned:
                return
            devices = dr.detect_devices(include_cpu=True)
            policy = dr.load_policy()
            assignments = dr.resolve_assignments(devices, policy)
            placements = dr.brain_placements(assignments)
            # Grow/shrink the runtime's N-brain slot list to match enabled
            # devices BEFORE re-seeding slots 0/1 below (sync_slots does both).
            if self.runtime is not None:
                try:
                    self.runtime.sync_slots(placements)
                except Exception:
                    pass
            first_big = next((p for p in placements if p["role"] == "big"), None)
            first_small = next((p for p in placements if p["role"] == "small"), None)
            # Only GPUs drive the llamacpp --device; a CPU placement means the
            # role runs on system RAM (gpu_layers=0), handled by the caller.
            if (not big_pinned and first_big and first_big["kind"] == "gpu"
                    and big.provider == "llamacpp" and big.device != first_big["index"]):
                big.device = first_big["index"]
            if (not small_pinned and first_small and first_small["kind"] == "gpu"
                    and small.provider == "llamacpp" and small.device != first_small["index"]):
                small.device = first_small["index"]
        except Exception:
            pass  # registry is best-effort; never break runtime seeding

    def _build_device_panel(self, parent_layout):
        """Build the Compute Devices panel: one row per detected device with an
        enable checkbox and a role selector (Auto/Big/Small). Reads + persists
        the device registry policy. Never raises — a detection failure just
        renders an informational label.
        """
        try:
            from PySide6.QtWidgets import QVBoxLayout
            from agents.runtime import device_registry as dr

            group = QGroupBox("🖥️  Compute Devices (enable / assign per device)")
            group.setStyleSheet("""
                QGroupBox {
                    color: #bb86fc; font-weight: bold;
                    border: 2px solid #bb86fc; border-radius: 8px;
                    margin-top: 10px; padding-top: 15px;
                }
                QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            """)
            v = QVBoxLayout(group)
            hint = QLabel(
                "Each detected GPU and the CPU/RAM pool can be enabled and assigned. "
                "≥12 GB = Big Brain, 4–12 GB = Small Brain; CPU/RAM depends on cores + RAM. "
                "Disable a device to keep it idle. Changes apply on the next Start.")
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #888; font-size: 11px;")
            v.addWidget(hint)

            devices = dr.detect_devices(include_cpu=True)
            # B1: surface a lost-GPU / detection diagnostic in the device panel
            # AND the Live Log, so a dropped GPU is explained (with a reboot
            # hint) instead of silently missing from the list.
            detect_error = getattr(dr, "_LAST_DETECT_ERROR", "") or ""
            if detect_error:
                warn = QLabel("⚠️ " + detect_error)
                warn.setWordWrap(True)
                warn.setStyleSheet(
                    "color: #ffb300; font-size: 11px; padding: 4px;")
                v.addWidget(warn)
                try:
                    self._log("⚠️ GPU detection: " + detect_error)
                except Exception:
                    pass
            policy = dr.load_policy()
            self._device_rows = {}
            if not devices:
                v.addWidget(QLabel("No compute devices detected."))
            for dev in devices:
                row = QHBoxLayout()
                enabled_cb = QCheckBox()
                enabled_cb.setChecked(policy.is_enabled(dev))
                enabled_cb.setToolTip(f"Use {dev.label()} for inference")
                enabled_cb.stateChanged.connect(
                    lambda _s, d=dev: self._on_device_toggled(d))
                cap = dev.capability_class()
                cap_txt = {"big": "Big-capable", "small": "Small-capable",
                           "none": "insufficient memory"}[cap]
                name_lbl = QLabel(dev.label())
                name_lbl.setMinimumWidth(320)
                role_combo = QComboBox()
                role_combo.addItems(["Auto", "Big Brain", "Small Brain"])
                override = policy.role_override(dev)
                role_combo.setCurrentText(
                    {"big": "Big Brain", "small": "Small Brain"}.get(override, "Auto"))
                # A device that cannot host 'big' shouldn't offer it.
                if cap == "small":
                    role_combo.removeItem(role_combo.findText("Big Brain"))
                if cap == "none":
                    role_combo.clear()
                    role_combo.addItem("Unavailable")
                    role_combo.setEnabled(False)
                role_combo.currentTextChanged.connect(
                    lambda _t, d=dev: self._on_device_role_changed(d))
                cap_lbl = QLabel(cap_txt)
                cap_lbl.setStyleSheet(
                    "color: #4caf50;" if cap == "big" else
                    ("color: #ffb74d;" if cap == "small" else "color: #f44336;"))
                row.addWidget(enabled_cb)
                row.addWidget(name_lbl)
                row.addWidget(QLabel("Role:"))
                row.addWidget(role_combo)
                row.addWidget(cap_lbl)
                row.addStretch(1)
                v.addLayout(row)
                self._device_rows[dev.id] = {
                    "device": dev, "enable": enabled_cb, "role": role_combo}
            parent_layout.addWidget(group)
        except Exception as exc:
            try:
                self.log_signal.emit(f"[GUI] Compute-device panel skipped: {exc}")
            except Exception:
                pass

    def _on_device_toggled(self, dev):
        """Persist a device enable/disable change and re-apply the assignment.

        N-brain (Phase 6): if the operator disables a device that currently
        hosts a RUNNING brain, that brain is stopped so we never orphan a server
        on hardware the operator has taken out of use.
        """
        try:
            from agents.runtime import device_registry as dr
            policy = dr.load_policy()
            row = self._device_rows.get(dev.id)
            now_enabled = bool(row["enable"].isChecked()) if row else True
            policy.enabled[dev.id] = now_enabled
            dr.save_policy(policy)
            if not now_enabled:
                self._stop_brain_on_disabled_device(dev.id)
            # v2.1.47 (ARCH-ENG-046): the per-device toggle is the SINGLE source
            # of truth for whether a brain runs. Persist it to the runtime's own
            # <ROLE>_ENABLED env key too, so a disabled brain's provider adapter
            # is never registered (worker_provider_mixin gate) and its settings
            # block disappears — closing the gap where the device was off in
            # settings.json but BIG_BRAIN_ENABLED stayed true in .env.
            self._sync_role_enabled_to_env(dev, now_enabled)
            self._reapply_device_assignment()
        except Exception as exc:
            try:
                self.log_signal.emit(f"[GUI] Device toggle failed: {exc}")
            except Exception:
                pass

    def _sync_role_enabled_to_env(self, dev, now_enabled: bool) -> None:
        """Write <ROLE>_ENABLED for the role bound to `dev` (never raises).

        Keeps the runtime env flag in lockstep with the per-device enable toggle.
        """
        try:
            if self.runtime is None:
                return
            cfg = self.runtime.slot_for_device(dev.id)
            if cfg is None:
                return
            slot = getattr(cfg, "slot", -1)
            key = {0: "BIG_BRAIN_ENABLED", 1: "SMALL_BRAIN_ENABLED"}.get(slot)
            if not key:
                return  # slots 2+ are governed by the device policy only
            value = "true" if now_enabled else "false"
            # Import FIRST, then write os.environ. `main` runs
            # `load_dotenv(override=True)` at module level (main.py:201), so a
            # lazy first import re-reads .env and silently clobbers any
            # os.environ value set beforehand — the toggle appeared to do
            # nothing in-process (ARCH-ENG-048). Importing before the write
            # makes the assignment authoritative.
            try:
                from main import set_env_values
            except Exception:
                set_env_values = None
            os.environ[key] = value
            if set_env_values is not None:
                try:
                    set_env_values({key: value})
                except Exception:
                    pass
            self.log_signal.emit(
                f"[GUI] {key}={value} (device '{dev.label()}' "
                f"{'enabled' if now_enabled else 'disabled'})"
            )
        except Exception:
            pass

    def _stop_brain_on_disabled_device(self, device_id: str):
        """Stop any brain bound to a now-disabled device (never raises)."""
        try:
            if self.runtime is None:
                return
            cfg = self.runtime.slot_for_device(device_id)
            if cfg is None:
                return
            slot = getattr(cfg, "slot", -1)
            if slot == 0:
                self._on_stop_big_brain()
            elif slot == 1:
                self._on_stop_small_brain()
            elif slot >= 2:
                self._stop_slot(slot)
        except Exception:
            pass

    def _on_device_role_changed(self, dev):
        """Persist a device role override (Auto/Big/Small) and re-apply."""
        try:
            from agents.runtime import device_registry as dr
            policy = dr.load_policy()
            row = self._device_rows.get(dev.id)
            text = row["role"].currentText() if row else "Auto"
            policy.role[dev.id] = {"Big Brain": "big", "Small Brain": "small"}.get(text, "")
            dr.save_policy(policy)
            self._reapply_device_assignment()
        except Exception as exc:
            try:
                self.log_signal.emit(f"[GUI] Device role change failed: {exc}")
            except Exception:
                pass

    def _reapply_device_assignment(self):
        """Re-run device→role assignment and refresh the labels/subtitle so the
        GUI reflects the new enable/role policy immediately."""
        try:
            if self.runtime is not None:
                from agents.runtime.dual_brain import BrainRole
                self._apply_plan_device_assignment(
                    self.runtime.config(BrainRole.SMALL),
                    self.runtime.config(BrainRole.BIG))
            self._apply_runtime()
            # v2.1.54 (ARCH-ENG-054): _apply_plan_device_assignment grows/shrinks
            # runtime.slots() to match enabled devices, but the Provider Control
            # ROWS are built once and were never rebuilt here — so enabling the
            # CPU/RAM device updated the runtime to 2 slots while the panel still
            # showed only the Big brain row (and disabling left a stale row).
            # Rebuild the rows so the panel always matches the runtime's slots.
            self._rebuild_provider_rows()
        except Exception:
            pass

    def _build_provider_rows(self, provider_layout):
        """Build one BrainControlRow per runtime slot into ``provider_layout``.

        Slots 0/1 are the Big/Small brains; slots 2+ render automatically when
        more devices are enabled. Legacy ``sb_*``/``bb_*`` attribute names are
        aliased to slots 0/1's sub-widgets so the existing backend wiring keeps
        working. Start/Stop emit slot-keyed signals routed to the existing
        per-role handlers for slots 0/1, and to a slot handler for slots 2+.
        """
        from gui.widgets.brain_control_row import BrainControlRow
        # Clear any previously-built rows (rebuild on device-policy change).
        for row in getattr(self, "_provider_rows", []):
            row.setParent(None)
        self._provider_rows = []

        slots = self.runtime.slots() if self.runtime is not None else []
        if len(slots) < 2:
            # No runtime (or degraded) -> synthesize the two role rows so the
            # panel is never empty; _apply_runtime fills real values later.
            slots = [None, None]

        # v2.1.47 (ARCH-ENG-046): a slot whose role config is DISABLED is not a
        # live brain — BIG_BRAIN_ENABLED/SMALL_BRAIN_ENABLED (and the per-device
        # enable toggle, which writes the same flag) is the single source of
        # truth. Render a settings row ONLY for enabled slots, so the llama.cpp
        # settings/options block disappears when that backend is disabled instead
        # of showing controls for a brain that will never run. A disabled slot is
        # skipped entirely (no row, no Start/Stop, no model dropdown).
        render_slots = []
        for i, cfg in enumerate(slots):
            if cfg is not None and not getattr(cfg, "enabled", True):
                continue
            render_slots.append(cfg)

        for i in range(len(render_slots)):
            cfg = render_slots[i] if render_slots[i] is not None else None
            if cfg is not None:
                role = cfg.role.value if hasattr(cfg.role, "value") else str(cfg.role)
                label = cfg.gpu_label or ""
            else:
                role = "big" if i == 0 else "small"
                label = ""
            # slot index passed to the row is its ORIGINAL position so start/stop
            # routing (which keys on slot 0/1) still targets the right brain.
            original_index = slots.index(cfg) if cfg in slots else i
            row = BrainControlRow(slot=original_index, role=role, device_label=label)
            provider_layout.addWidget(row, i, 0, 1, -1)
            row.start_clicked.connect(self._on_provider_row_start)
            row.stop_clicked.connect(self._on_provider_row_stop)
            row.model_changed.connect(self._on_provider_row_model_changed)
            row.mtp_changed.connect(self._on_provider_row_mtp_changed)
            self._provider_rows.append(row)

        # Fill every row's model dropdown from discovered local .gguf files and
        # pre-select the slot's configured model (if any). This is what makes
        # model selection work for ALL devices, not just the two role brains.
        try:
            discovered = self._discover_gguf_models()
        except Exception:
            discovered = []
        for row in self._provider_rows:
            cfg = None
            if self.runtime is not None:
                cfg = self.runtime.slot_config(row.slot)
            selected = getattr(cfg, "model", "") or "" if cfg else ""
            row.set_models(discovered, selected)

        # Alias legacy attribute names to slots 0/1 so the backend (which reads
        # self.sb_status, self.bb_start_btn, etc.) keeps working unchanged.
        self._alias_legacy_provider_attrs()

    def _alias_legacy_provider_attrs(self):
        """Point sb_*/bb_* at the sub-widgets of provider rows 0/1.

        The backend writes the running-model name via ``sb_model_label.setText()``.
        BrainControlRow exposes a model dropdown (``model_combo``) rather than a
        label, so we wrap it in a tiny adapter whose ``setText`` selects that
        model in the dropdown — keeping the backend's setText calls working.

        v2.1.53 (ARCH-ENG-053): ALWAYS create every alias, even when a brain is
        disabled and its row is not rendered (single-GPU box, CPU unchecked).
        Previously ``len(rows) < 2`` returned early, leaving sb_status/bb_status
        (and the start/stop buttons, model labels) UNDEFINED — so any backend or
        GUI code that touched them raised AttributeError and aborted the start
        flow. Now a missing brain's aliases point at a null-object that swallows
        setText/setStyleSheet/setEnabled, so status updates for the live brain
        still work and the disabled brain is a harmless no-op.
        """
        rows = getattr(self, "_provider_rows", [])
        # slot 0 = Big, slot 1 = Small. Find each by slot (rows may be a subset
        # when a brain is disabled).
        big_row = next((r for r in rows if getattr(r, "slot", None) == 0), None)
        small_row = next((r for r in rows if getattr(r, "slot", None) == 1), None)

        def _status(row):
            return row.status if row is not None else _NullWidget()

        def _label(row):
            return _ModelLabelAdapter(row) if row is not None else _NullWidget()

        def _btn(row, which):
            if row is None:
                return _NullWidget()
            return row.start_btn if which == "start" else row.stop_btn

        # Small Brain legacy aliases
        self.sb_status = _status(small_row)
        self.sb_model_label = _label(small_row)
        self.sb_start_btn = _btn(small_row, "start")
        self.sb_stop_btn = _btn(small_row, "stop")
        self._sb_control_label = small_row.header if small_row is not None else _NullWidget()
        # Big Brain legacy aliases
        self.bb_status = _status(big_row)
        self.bb_model_label = _label(big_row)
        self.bb_start_btn = _btn(big_row, "start")
        self.bb_stop_btn = _btn(big_row, "stop")
        self._bb_control_label = big_row.header if big_row is not None else _NullWidget()

    def _on_provider_row_start(self, slot: int):
        """Route a row's Start click to the right brain handler by slot."""
        if slot == 0:
            self._on_start_big_brain()
        elif slot == 1:
            self._on_start_small_brain()
        else:
            # Slots 2+ launch via the generalized slot path (Phase 5).
            self._start_slot(slot)

    def _on_provider_row_stop(self, slot: int):
        """Route a row's Stop click to the right brain handler by slot."""
        if slot == 0:
            self._on_stop_big_brain()
        elif slot == 1:
            self._on_stop_small_brain()
        else:
            self._stop_slot(slot)

    def _on_provider_row_model_changed(self, slot: int, model_path: str):
        """A row's model dropdown changed: set the slot config's model.

        Slots 0/1 map to the BIG/SMALL role configs (so the existing dialogue /
        launch path sees the choice); slots 2+ set their slot config directly.
        The choice is persisted to the device policy (settings.json) keyed by
        device id so EVERY enabled device remembers its model across restarts
        (slots 0/1 additionally keep their .env BIG/SMALL_BRAIN_MODEL). Never
        raises.
        """
        try:
            if self.runtime is None:
                return
            cfg = self.runtime.slot_config(slot)
            if cfg is None:
                return
            cfg.model = model_path or ""
            # Keep the hidden Settings model combo in sync for slots 0/1 so
            # _snapshot_settings_values (which reads the combo) persists the
            # same choice. Slots 2+ have no Settings combo.
            try:
                if slot == 0:
                    self._set_settings_combo_model(False, model_path)
                elif slot == 1:
                    self._set_settings_combo_model(True, model_path)
            except Exception:
                pass
            # Persist the per-device model choice to the device policy.
            try:
                from agents.runtime import device_registry as dr
                if cfg.device_id:
                    policy = dr.load_policy()
                    if model_path:
                        policy.models[cfg.device_id] = model_path
                    else:
                        policy.models.pop(cfg.device_id, None)
                    dr.save_policy(policy)
            except Exception:
                pass
            # Persist .env off-thread so a dropdown change never blocks the GUI
            # (covers slots 0/1 via BIG/SMALL_BRAIN_MODEL).
            persist = getattr(self, "_persist_settings_async", None)
            if persist is not None:
                persist()
            else:
                self._persist_settings()
        except Exception:
            pass

    def _on_provider_row_mtp_changed(self, slot: int, enabled: bool):
        """A row's MTP toggle changed: set the slot config's spec_type (Phase G).

        Only ever called with enabled=True when the model supports MTP (the row
        greys the box otherwise), so this simply maps the checkbox onto
        ``spec_type``. Persists via the device policy + .env like the model
        choice. Never raises.
        """
        try:
            if self.runtime is None:
                return
            cfg = self.runtime.slot_config(slot)
            if cfg is None:
                return
            cfg.spec_type = "draft-mtp" if enabled else ""
            if enabled and getattr(cfg, "spec_draft_n_max", None) in (None, 0):
                cfg.spec_draft_n_max = 3  # llama.cpp default
            # Persist to the device policy so the choice survives restarts.
            try:
                from agents.runtime import device_registry as dr
                if cfg.device_id:
                    policy = dr.load_policy()
                    settings = policy.settings.setdefault(cfg.device_id, {})
                    if enabled:
                        settings["spec_type"] = "draft-mtp"
                        settings["spec_draft_n_max"] = cfg.spec_draft_n_max
                    else:
                        settings.pop("spec_type", None)
                        settings.pop("spec_draft_n_max", None)
                    dr.save_policy(policy)
            except Exception:
                pass
            persist = getattr(self, "_persist_settings_async", None)
            if persist is not None:
                persist()
            else:
                self._persist_settings()
        except Exception:
            pass

    def _show_advanced_settings_help(self):
        """Show a concise reference for the advanced llama.cpp settings (Phase G).

        Renders the same text as the per-control mouse-hover tooltips so the "?"
        button and the hovers never disagree.
        """
        try:
            from agents.knowledge.llama_setting_help import LLAMA_SETTING_HELP
            _TITLES = {
                "ctx": "Context (Ctx)", "gpu_layers": "GPU Layers",
                "threads": "Threads", "batch": "Batch", "kv_cache": "KV cache",
                "split_mode": "Split mode", "temperature": "Temperature",
                "flash_attn": "FlashAttention", "cache_reuse": "Cache reuse",
                "context_shift": "Context shift",
                "ctx_checkpoints": "Context checkpoints",
                "mtp": "MTP (multi-token prediction)",
                "spec_draft_n_max": "MTP draft tokens",
                "mmproj": "Vision projector (mmproj)",
            }
            lines = ["Advanced llama.cpp settings — what they do:\n"]
            for key in ("ctx", "gpu_layers", "threads", "batch", "kv_cache",
                        "split_mode", "temperature", "flash_attn",
                        "cache_reuse", "context_shift", "ctx_checkpoints",
                        "mtp", "spec_draft_n_max", "mmproj"):
                text = LLAMA_SETTING_HELP.get(key)
                if text:
                    lines.append(f"• {_TITLES.get(key, key)}: {text}")
            QMessageBox.information(self, "Advanced llama.cpp settings",
                                    "\n\n".join(lines))
        except Exception:
            pass

    def _rebuild_provider_rows(self):
        """Rebuild the Provider Control rows after a device-policy change."""
        group = getattr(self, "provider_control_group", None)
        layout = group.layout() if group is not None else None
        if layout is not None:
            self._build_provider_rows(layout)

    def _build_detected_brains_summary(self, settings_layout):
        """Build the per-device editable settings section into the Settings grid.

        Renders one ``BrainSettingsRow`` per runtime slot so EVERY enabled device
        (GPU or CPU/RAM, slots 2+ included) has editable context / gpu-layers /
        threads / batch / KV / split / temperature — closing the N-brain gap
        where only the two role brains had controls. Refreshed live by
        ``_update_detected_brains_summary``.
        """
        row = 1
        header = QLabel("🖥️ Per-Device Settings (all enabled devices)")
        header.setFont(QFont("Segoe UI", 10, QFont.Bold))
        header.setStyleSheet("color: #9c27b0;")
        settings_layout.addWidget(header, row, 0, 1, 4)
        row += 1
        hint = QLabel("Edit any device's launch parameters here; they apply on the "
                      "next brain start. CPU/RAM runs system-RAM only (GPU layers locked to 0).")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 10px;")
        settings_layout.addWidget(hint, row, 0, 1, 4)
        row += 1
        # A vertical container we repopulate on each refresh.
        self._detected_brains_container = QVBoxLayout()
        settings_layout.addLayout(self._detected_brains_container, row, 0, 1, 4)
        self._settings_rows = []
        self._update_detected_brains_summary()

    def _update_detected_brains_summary(self):
        """Rebuild the per-device editable settings rows from the slot list.

        After building the rows, the legacy ``sb_*``/``bb_*`` widget attribute
        names are aliased to slots 1/0's controls respectively (Small=slot1,
        Big=slot0) so the launch snapshot, ``_snapshot_settings_values``,
        temperature presets, and hardware presets — all of which read those
        attributes — keep working against the unified per-device rows.
        """
        container = getattr(self, "_detected_brains_container", None)
        if container is None:
            return
        # Clear existing rows.
        while container.count():
            item = container.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        self._settings_rows = []
        slots = self.runtime.slots() if self.runtime is not None else []
        from gui.widgets.brain_settings_row import BrainSettingsRow
        for i, cfg in enumerate(slots):
            role = cfg.role.value if hasattr(cfg.role, "value") else str(cfg.role)
            is_cpu = bool(getattr(cfg, "device_id", "") == "cpu") or cfg.gpu_layers == 0
            label = cfg.gpu_label or ""
            srow = BrainSettingsRow(slot=i, role=role, device_label=label,
                                    is_cpu=is_cpu)
            srow.bind(cfg)
            srow.changed.connect(self._on_brain_settings_changed)
            container.addWidget(srow)
            self._settings_rows.append(srow)
        # Alias legacy sb_*/bb_* attribute names to slots 1/0 so existing
        # launch/snapshot/preset wiring keeps working (Small=slot1, Big=slot0).
        self._alias_legacy_settings_attrs()
        # v2.1.38 (ARCH-ENG-045): seed temperature from the persisted env keys
        # the brains actually read (big_brain/small_brain read BIG/SMALL_BRAIN_
        # TEMPERATURE at construction). The BrainSettingsRow hardcodes 0.5 at
        # creation and was never re-seeded, so a saved temperature reverted to
        # 0.50 in the widget on every rebuild even though the save itself was
        # correct. Seed HERE (after the rows are built) so the value survives
        # every rebuild — _apply_runtime calls this method, so seeding in
        # _apply_runtime would be immediately overwritten by this rebuild.
        # Block signals while seeding so the setValue doesn't fire valueChanged
        # -> _persist_settings.
        for _slot, _pfx in ((0, "BIG"), (1, "SMALL")):
            if _slot >= len(self._settings_rows):
                continue
            _tspin = getattr(self._settings_rows[_slot], "temp_spin", None)
            if _tspin is None:
                continue
            try:
                _saved_t = float(os.getenv(f"{_pfx}_BRAIN_TEMPERATURE", "0.5") or 0.5)
            except (TypeError, ValueError):
                _saved_t = 0.5
            _tspin.blockSignals(True)
            try:
                _tspin.setValue(_saved_t)
            finally:
                _tspin.blockSignals(False)

    def _alias_legacy_settings_attrs(self):
        """Point sb_*/bb_* settings attributes at slots 1/0's BrainSettingsRow
        controls (Small=slot1, Big=slot0). No-op when fewer than 2 rows."""
        rows = getattr(self, "_settings_rows", [])
        if len(rows) < 2:
            return
        small, big = rows[1], rows[0]
        # Small Brain
        self.sb_ctx_spin = small.ctx_spin
        self.sb_gpu_layers_spin = small.gpu_layers_spin
        self.sb_split_combo = small.split_combo
        self.sb_threads_spin = small.threads_spin
        self.sb_batch_spin = small.batch_spin
        self.sb_kv_combo = small.kv_combo
        self.sb_temp_spin = small.temp_spin
        # Big Brain
        self.bb_ctx_spin = big.ctx_spin
        self.bb_gpu_layers_spin = big.gpu_layers_spin
        self.bb_split_combo = big.split_combo
        self.bb_threads_spin = big.threads_spin
        self.bb_batch_spin = big.batch_spin
        self.bb_kv_combo = big.kv_combo
        self.bb_temp_spin = big.temp_spin

    def _on_brain_settings_changed(self, slot: int):
        """A per-device settings control changed: apply to the slot config +
        persist (off-thread). Slots 0/1 persist via .env; slots 2+ persist to the
        device policy (settings.json → devices.settings). Never raises."""
        try:
            # ARCH-ENG-057: a programmatic fill (see `_seeding_settings`) is not
            # an operator edit. Persisting it wrote the row's unbound defaults
            # over the operator's saved per-device settings.
            if getattr(self, "_seeding_settings", 0) > 0:
                return
            if self.runtime is None:
                # ARCH-ENG-197: DO NOT SILENTLY DISCARD THE EDIT.
                #
                # This used to `return` here, BEFORE `apply_to(cfg)` and before
                # `_persist_settings_async()`. So any ctx / threads / batch /
                # gpu-layers / kv edit made before device detection finished was
                # dropped completely: not applied, not written, and not logged.
                #
                # That window is not exotic. Detection runs on a background
                # thread and the panel is interactive as soon as it paints, so
                # the first few seconds of a session are exactly when an operator
                # is most likely to reach for a spinner.
                #
                # `_snapshot_settings_values()` reads only widgets and needs no
                # runtime, so the PERSIST half of the work can always be done. Only
                # the in-memory `apply_to(cfg)` genuinely needs a config object, so
                # that is what gets deferred: the slot is recorded, and
                # `_apply_runtime` replays it once a runtime exists.
                #
                # Previously the setting survived neither the session nor the
                # restart, and the operator had no way to know.
                try:
                    pending = getattr(self, "_pending_slot_applies", None)
                    if pending is None:
                        pending = set()
                        self._pending_slot_applies = pending
                    pending.add(int(slot))
                    persist = getattr(self, "_persist_settings_async", None)
                    if persist is not None:
                        persist()
                    self._log(
                        "Settings saved to file; applying to the running server "
                        "once device detection finishes."
                    )
                except Exception:
                    pass
                return
            rows = getattr(self, "_settings_rows", [])
            if not (0 <= slot < len(rows)):
                return
            cfg = self.runtime.slot_config(slot)
            if cfg is None:
                return
            rows[slot].apply_to(cfg)
            # Persist per-device settings. Slots 2+ always need the device
            # policy (they have no .env keys). A slot 0/1 whose device is the
            # CPU/RAM pool (or an extra device) ALSO needs it — .env only holds
            # the GPU role keys, so without this a CPU-pool context/threads edit
            # applied in-session but silently reverted on restart (ARCH-ENG-049).
            try:
                from agents.runtime import device_registry as dr
                if cfg.device_id and (slot >= 2 or cfg.device_id == "cpu"):
                    policy = dr.load_policy()
                    policy.settings[cfg.device_id] = rows[slot].values()
                    dr.save_policy(policy)
            except Exception:
                pass
            persist = getattr(self, "_persist_settings_async", None)
            if persist is not None:
                persist()
        except Exception:
            pass


    def _replay_pending_slot_applies(self):
        """ARCH-ENG-197: apply edits made before a runtime existed.

        `_on_brain_settings_changed` persists immediately but defers the
        in-memory `apply_to(cfg)` when `self.runtime` is None, recording the slot
        here. This replays those edits once detection has produced a runtime, so
        "saved to file, applied when detection finishes" is a promise the panel
        actually keeps.

        Runs AFTER `_apply_runtime`'s own seeding, so the operator's value wins
        over the detected default -- which is the correct order: an explicit edit
        should not be overwritten by a fallback that ran later.
        """
        pending = sorted(getattr(self, "_pending_slot_applies", None) or set())
        if not pending or self.runtime is None:
            return
        rows = getattr(self, "_settings_rows", [])
        for slot in pending:
            try:
                if not (0 <= slot < len(rows)):
                    continue
                cfg = self.runtime.slot_config(slot)
                if cfg is None:
                    continue
                rows[slot].apply_to(cfg)
            except Exception:
                continue
        try:
            self._pending_slot_applies.clear()
        except Exception:
            self._pending_slot_applies = set()

    def _apply_runtime(self):
        """Seed ctx spins + endpoint labels from the canonical runtime (if any)."""
        if self.runtime is None:
            return
        from agents.runtime.dual_brain import BrainRole, apply_hardware_fallback
        try:
            small = self.runtime.config(BrainRole.SMALL)
            big = self.runtime.config(BrainRole.BIG)
            detected_gpu_indexes = {
                gpu.index for gpu in self.provider_manager.get_gpus(detect=False)}
            apply_hardware_fallback(small, detected_gpu_indexes)
            active_local = self.provider_manager.resolve_enabled_provider(local=True)
            local_settings = getattr(self, "local_settings_group", None)
            if local_settings is not None:
                supported_local = {
                    "llamacpp", "ollama", "lmstudio", "vllm", "koboldcpp"
                }
                has_local_brain = any(
                    cfg.enabled and cfg.provider in supported_local
                    for cfg in (small, big))
                local_settings.setVisible(has_local_brain)
                local_settings.setTitle(
                    f"⚙️ {active_local or 'Local Provider'} Settings (per brain)")
            detected_gpus = {
                gpu.index: gpu.name for gpu in self.provider_manager.get_gpus(detect=False)
            }
            # VRAM-based device assignment: the plan ranks GPUs by VRAM, so the
            # biggest hosts Big and the next hosts Small — independent of PCI
            # index order. Only applies when the operator has NOT pinned a
            # device via <ROLE>_DEVICE (an explicit value wins).
            self._apply_plan_device_assignment(small, big)
            if small.device in detected_gpus:
                small.gpu_label = detected_gpus[small.device]
            elif small.provider == "llamacpp":
                # A stale dual-GPU default must not make a single-GPU machine
                # try CUDA1. Auto-fall back to CPU/system RAM until the user
                # explicitly selects a GPU-layer count.
                small.gpu_layers = 0
            if big.device in detected_gpus:
                big.gpu_label = detected_gpus[big.device]
            if small.gpu_layers == 0:
                small.gpu_label = "CPU / System RAM"
            elif active_local and active_local != "llamacpp":
                small.gpu_label = "External provider"
                big.gpu_label = big.gpu_label or "External provider"
            sb_spin = getattr(self, "sb_ctx_spin", None)
            bb_spin = getattr(self, "bb_ctx_spin", None)
            # ARCH-ENG-057: seeding a control is NOT an operator edit, but these
            # `setValue` calls land on the BrainSettingsRow spins whose
            # `valueChanged` is wired straight to `_on_brain_settings_changed` ->
            # `save_policy()`. Firing during seeding persisted the row's
            # unbound/hardcoded defaults over the operator's saved per-device
            # model + llama.cpp settings — reproduced by merely constructing the
            # widget (context/threads/batch/kv/split/temperature all reverted to
            # the BrainSettingsRow constructor defaults). Hold the guard for the
            # whole seeding block so no programmatic fill can persist.
            self._seeding_settings += 1
            try:
                if sb_spin is not None:
                    sb_spin.setValue(small.context)
                if bb_spin is not None:
                    bb_spin.setValue(big.context)
                # Seed the llama.cpp customization widgets (v2.1).
                try:
                    if getattr(self, "sb_threads_spin", None) is not None:
                        self.sb_threads_spin.setValue(small.threads)
                    if getattr(self, "bb_threads_spin", None) is not None:
                        self.bb_threads_spin.setValue(big.threads)
                    if getattr(self, "sb_batch_spin", None) is not None:
                        self.sb_batch_spin.setValue(small.batch)
                    if getattr(self, "bb_batch_spin", None) is not None:
                        self.bb_batch_spin.setValue(big.batch)
                    if getattr(self, "sb_split_combo", None) is not None:
                        self.sb_split_combo.setCurrentText(small.split_mode)
                    if getattr(self, "bb_split_combo", None) is not None:
                        self.bb_split_combo.setCurrentText(big.split_mode)
                    if getattr(self, "sb_kv_combo", None) is not None:
                        self.sb_kv_combo.setCurrentText(small.kv_cache)
                    if getattr(self, "bb_kv_combo", None) is not None:
                        self.bb_kv_combo.setCurrentText(big.kv_cache)
                    if getattr(self, "sb_gpu_layers_spin", None) is not None:
                        self.sb_gpu_layers_spin.setValue(
                            small.gpu_layers if small.gpu_layers is not None else -1)
                    if getattr(self, "bb_gpu_layers_spin", None) is not None:
                        self.bb_gpu_layers_spin.setValue(
                            big.gpu_layers if big.gpu_layers is not None else -1)
                    # NOTE (v2.1.38, ARCH-ENG-045): temperature is NOT seeded here.
                    # This method rebuilds the per-device settings rows via
                    # _update_detected_brains_summary() further down, which recreates
                    # every BrainSettingsRow at its hardcoded 0.5 — so any temp seeded
                    # here would be immediately overwritten. Temperature is seeded
                    # inside _update_detected_brains_summary, AFTER the rows are built.
                except Exception:
                    pass
            finally:
                self._seeding_settings -= 1
            # Refresh the port labels to match the canonical contract.
            provider_names = {
                "llamacpp": "llama.cpp",
                "lmstudio": "LM Studio",
                "ollama": "Ollama",
                "vllm": "vLLM",
            }
            small_provider_name = provider_names.get(small.provider, small.provider)
            big_provider_name = provider_names.get(big.provider, big.provider)
            sb_label = getattr(self, "sb_settings_label", None)
            bb_label = getattr(self, "bb_settings_label", None)
            if sb_label is not None:
                sb_label.setText(
                    f"🤖 Small Brain · {small_provider_name} · "
                    f"{small.gpu_label} · port {small.port}")
            if bb_label is not None:
                bb_label.setText(
                    f"🧠 Big Brain · {big_provider_name} · "
                    f"{big.gpu_label} · port {big.port}")
            # Provider Control row headers: show the assigned device so the
            # one-click-launch rows match the Compute Devices panel.
            sb_ctrl = getattr(self, "_sb_control_label", None)
            bb_ctrl = getattr(self, "_bb_control_label", None)
            if sb_ctrl is not None:
                sb_ctrl.setText(f"🤖 Small Brain · {small.gpu_label}")
            if bb_ctrl is not None:
                bb_ctrl.setText(f"🧠 Big Brain · {big.gpu_label}")
            # Route + GPU-contention guidance (v2.1): state which provider serves
            # which role and flag broken isolation so the operator can disable a
            # provider or split main/chat across GPUs.
            try:
                active_cloud = os.getenv("ACTIVE_CLOUD_PROVIDER", "").strip()
                if active_local:
                    route_provider_name = provider_names.get(active_local, active_local)
                    route = (
                        f"Route: Edward → {route_provider_name} / "
                        f"{big.model or 'auto model'} / {big.gpu_label} · "
                        f"Jacob → {route_provider_name} / "
                        f"{small.model or 'auto model'} / {small.gpu_label}"
                    )
                elif active_cloud and active_cloud.lower() != "auto":
                    route = f"Route: {active_cloud} cloud provider · no local provider enabled"
                else:
                    route = "Route: no local or cloud provider enabled"
                if hasattr(self.runtime, "validate_isolation"):
                    iso = self.runtime.validate_isolation()
                    if not active_local:
                        route += " · local hardware idle"
                    elif iso.get("isolated"):
                        route += " · GPUs isolated ✓"
                    else:
                        route += " · ⚠ GPU isolation broken — give each brain its own GPU or disable one provider"
                rl = getattr(self, "route_label", None)
                if rl is not None:
                    rl.setText(route)
            except Exception:
                pass
            # N-brain (Phase 3): the runtime may have grown/shrunk its slot list
            # during device sync above. Rebuild the Provider Control rows only
            # when the count actually changed so we don't reset button state on
            # every refresh.
            try:
                n_slots = len(self.runtime.slots())
                if n_slots != len(getattr(self, "_provider_rows", [])):
                    self._rebuild_provider_rows()
                self._update_detected_brains_summary()
            except Exception:
                pass
        except Exception:
            pass  # runtime seeding is best-effort; never break the panel
        # ARCH-ENG-197: last, so an edit made before detection finished is applied
        # AFTER the detected defaults -- an explicit operator choice must not be
        # overwritten by a fallback that happened to run later.
        try:
            self._replay_pending_slot_applies()
        except Exception:
            pass

    def _snapshot_settings_values(self) -> dict:
        """Build the llama.cpp settings dict from the current widget state.

        MUST run on the GUI thread (reads QWidget .value()/.currentText()).
        Returns the plain ``values`` dict; the caller decides whether to write
        it synchronously (_persist_settings) or off-thread
        (_persist_settings_async). Never raises — returns {} on any error.
        """
        try:
            values = {
                "SMALL_BRAIN_MODEL": self._current_model_path(True),
                "BIG_BRAIN_MODEL": self._current_model_path(False),
                "SMALL_BRAIN_CONTEXT": str(self.sb_ctx_spin.value()),
                "BIG_BRAIN_CONTEXT": str(self.bb_ctx_spin.value()),
                "SMALL_BRAIN_GPU_LAYERS": str(self.sb_gpu_layers_spin.value()),
                "BIG_BRAIN_GPU_LAYERS": str(self.bb_gpu_layers_spin.value()),
                "SMALL_BRAIN_SPLIT_MODE": self.sb_split_combo.currentText() or "none",
                "BIG_BRAIN_SPLIT_MODE": self.bb_split_combo.currentText() or "none",
                "SMALL_BRAIN_THREADS": str(self.sb_threads_spin.value()),
                "BIG_BRAIN_THREADS": str(self.bb_threads_spin.value()),
                "SMALL_BRAIN_BATCH": str(self.sb_batch_spin.value()),
                "BIG_BRAIN_BATCH": str(self.bb_batch_spin.value()),
                "SMALL_BRAIN_KV_CACHE": self.sb_kv_combo.currentText() or "f16",
                "BIG_BRAIN_KV_CACHE": self.bb_kv_combo.currentText() or "f16",
                "SMALL_BRAIN_TEMPERATURE": str(self.sb_temp_spin.value()),
                "BIG_BRAIN_TEMPERATURE": str(self.bb_temp_spin.value()),
                "AUTO_START_SERVERS": "1" if self.auto_start_check.isChecked() else "0",
                "SHOW_BRAIN_CONSOLES": "1" if self.show_server_consoles_check.isChecked() else "0",
            }
            # v2.1.37 (ARCH-ENG-044): persist the per-brain ENABLE state so the
            # "Save Local Provider Settings" button captures enable/disable, not
            # just hardware flags. The checkboxes live on the Settings tab; read
            # them defensively (this widget may be saved before that tab is built)
            # and fall back to the current env value so we never clobber a choice.
            for _role, _attr in (("BIG", "llamacpp_big_enabled"),
                                 ("SMALL", "llamacpp_small_enabled")):
                _cb = getattr(self, _attr, None)
                try:
                    if _cb is not None:
                        values[f"{_role}_BRAIN_ENABLED"] = str(bool(_cb.isChecked()))
                    else:
                        values[f"{_role}_BRAIN_ENABLED"] = os.getenv(
                            f"{_role}_BRAIN_ENABLED", "true")
                except RuntimeError:
                    values[f"{_role}_BRAIN_ENABLED"] = os.getenv(
                        f"{_role}_BRAIN_ENABLED", "true")
            # v2.1.9: advanced llama.cpp flags (per brain). ARCH-ENG-314: a
            # control at its "not set" sentinel yields no value AND names its
            # stale key for removal, so un-setting a control finally persists.
            self._stale_env_keys = set()
            for _grp in ("sb_adv_group", "bb_adv_group"):
                _controls = getattr(self, _grp, None)
                if not _controls:
                    continue
                _prefix = "SMALL_BRAIN" if _grp.startswith("sb_") else "BIG_BRAIN"
                _vals, _stale = self._llama_flag_values(_prefix, _controls)
                values.update(_vals)
                self._stale_env_keys.update(_stale)
            # N-brain roster (Phase 4): the roster lives in settings.json, not
            # .env, so it is persisted here as a side effect rather than as an
            # entry in `values`. BOTH save handlers own this write (the
            # two-handler rule) — this one and main.py:save_settings.
            self._persist_brain_roster()
            return values
        except Exception as e:
            self._log(f"Failed to snapshot llama.cpp settings: {e}")
            return {}

    def _persist_brain_roster(self) -> None:
        """Persist the N-brain roster to settings.json (Phase 4).

        The roster lives in settings.json (not .env), so it is written as a side
        effect of the settings snapshot rather than as an entry in `values`.
        Called from BOTH save handlers (this one and main.py:save_settings) per
        the two-handler rule. Never raises — a failed roster write must not
        abort the .env write that follows.
        """
        try:
            from gui.widgets.brain_roster_panel import save_roster_from
            panel = getattr(self, "brain_roster_panel", None)
            if save_roster_from(panel) is None:
                self._log("⚠️ Brain roster not persisted (save failed).")
        except Exception as exc:
            self._log(f"⚠️ Brain roster not persisted: {exc}")

    def _persist_settings(self):
        """Persist the llama.cpp customization values to `.env` (v2.1).

        Writes the per-brain ctx / gpu-layers / split / threads / batch / kv-cache
        keys so the runtime and next launch pick them up. Uses the lock-resilient
        set_env_values from main.py when available; never raises.

        The widget snapshot is split out (_snapshot_settings_values) so the
        launch path can persist off-thread via _persist_settings_async without
        blocking the GUI on the ~350ms atomic .env rewrite.
        """
        try:
            values = self._snapshot_settings_values()
            if not values:
                return
            import pathlib
            try:
                from main import EnvWriteRefused, set_env_values
            except Exception:
                self._log("⚠️ Settings not persisted: set_env_values unavailable.")
                return
            try:
                set_env_values(
                    values,
                    remove_keys=getattr(self, "_stale_env_keys", None))
            except EnvWriteRefused as refusal:
                # Test isolation: a test run must never rewrite operator config.
                self._log(f"⚠️ Settings not persisted: {refusal}")
                return
            except Exception:
                # Fallback: use the SAME atomic writer with the repo path spelled
                # out. Never own a second, non-atomic write of the credentials
                # file — an interrupted write_text can truncate .env.
                repo_env = pathlib.Path(__file__).resolve().parents[2] / ".env"
                try:
                    set_env_values(
                        values,
                        path=repo_env,
                        remove_keys=getattr(self, "_stale_env_keys", None))
                except Exception as exc:
                    self._log(f"⚠️ Settings could not be persisted: {exc}")
                    return
            os.environ["SMALL_BRAIN_MODEL"] = values["SMALL_BRAIN_MODEL"]
            os.environ["BIG_BRAIN_MODEL"] = values["BIG_BRAIN_MODEL"]
            os.environ["SHOW_BRAIN_CONSOLES"] = values["SHOW_BRAIN_CONSOLES"]
            # v2.1.38 (ARCH-ENG-045): keep the in-process env in sync with the
            # just-saved temperature so a later _apply_runtime re-seed reads the
            # fresh value (otherwise the widget would show a stale temperature
            # after a rebuild because os.environ only updates on a full reload).
            for _tk in ("SMALL_BRAIN_TEMPERATURE", "BIG_BRAIN_TEMPERATURE"):
                if _tk in values:
                    os.environ[_tk] = values[_tk]
            self._log("💾 llama.cpp settings and model defaults saved to .env")
        except Exception as e:
            self._log(f"Failed to persist llama.cpp settings: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # ADVANCED llama.cpp FLAGS (v2.1.9)
    # ═══════════════════════════════════════════════════════════════════════
    def _build_llama_flag_group(self, parent_layout, brain_label, prefix, spin_qss):
        """Build one brain's advanced llama-server flag group.

        Every control maps to exactly one llama-server flag. A control left at
        its "not set" sentinel writes no env key, so `build_llama_command`
        omits the flag and llama.cpp keeps its own default — the launch command
        for an untouched config is unchanged.

        The MoE controls matter most on this hardware: a large MoE model (e.g.
        the 35B-A3B) can park expert weights in system RAM to fit a 16GB card.
        DRY/XTC are the anti-repetition samplers that suppress the loops the
        Dialogue tab used to fall into.
        """
        from PySide6.QtWidgets import (QGroupBox as _GB, QGridLayout as _GL,
                                       QLabel as _QL, QSpinBox as _SP,
                                       QDoubleSpinBox as _DSP, QComboBox as _CB,
                                       QCheckBox as _CKB)
        group = _GB(f"🧩 Advanced llama.cpp Flags — {brain_label}")
        group.setStyleSheet("""
            QGroupBox {
                color: #4caf50;
                font-weight: bold;
                border: 2px solid #4caf50;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        grid = _GL(group)
        controls = {}

        def _label(text, tip="", row=0, col=0):
            lbl = _QL(text)
            lbl.setStyleSheet("color: #888; font-size: 11px;")
            if tip:
                lbl.setToolTip(tip)
            grid.addWidget(lbl, row, col)
            return lbl

        def _spin(key, lo, hi, default, tip, row, col, special=None, suffix="",
                  unset=None):
            sp = _SP()
            sp.setRange(lo, hi)
            sp.setValue(int(os.getenv(f"{prefix}_{key}", str(default)) or default))
            sp.setFixedWidth(90)
            sp.setStyleSheet(spin_qss)
            if suffix:
                sp.setSuffix(suffix)
            if special is not None:
                sp.setSpecialValueText(special)
            if unset is None:
                # ARCH-ENG-314: the per-control "this value means UNSET"
                # predicate. Default: a sentinel floor ("(default)" at the
                # minimum) or the conventional 0/-1 "off" value.
                if special is not None:
                    unset = lambda v, minv=lo: v == minv  # noqa: E731
                else:
                    unset = lambda v: v <= 0  # noqa: E731
            sp._flag_unset = unset
            sp.setToolTip(tip)
            grid.addWidget(sp, row, col)
            controls[key] = sp
            return sp

        def _dspin(key, lo, hi, default, tip, row, col, step=0.05, decimals=2,
                   unset=None):
            sp = _DSP()
            sp.setRange(lo, hi)
            sp.setSingleStep(step)
            sp.setDecimals(decimals)
            sp.setValue(float(os.getenv(f"{prefix}_{key}", str(default)) or default))
            sp.setFixedWidth(90)
            sp.setStyleSheet(spin_qss)
            if unset is None:
                # Float flags here all use 0.0 == off/not set.
                unset = lambda v: v <= 0.0  # noqa: E731
            sp._flag_unset = unset
            sp.setToolTip(tip)
            grid.addWidget(sp, row, col)
            controls[key] = sp
            return sp

        def _combo(key, items, tip, row, col, width=110):
            cb = _CB()
            cb.addItems(items)
            cur = os.getenv(f"{prefix}_{key}", items[0])
            if cur in items:
                cb.setCurrentText(cur)
            cb.setFixedWidth(width)
            cb.setStyleSheet(spin_qss)
            cb.setToolTip(tip)
            grid.addWidget(cb, row, col)
            controls[key] = cb
            return cb

        def _check(key, text, tip, row, col):
            ckb = _CKB(text)
            ckb.setChecked(os.getenv(f"{prefix}_{key}", "false").lower() == "true")
            ckb.setStyleSheet("color: #ccc; font-size: 11px;")
            ckb.setToolTip(tip)
            grid.addWidget(ckb, row, col)
            controls[key] = ckb
            return ckb

        # ── Performance (VRAM / speed) ──────────────────────────────────────
        _label("— Performance —", "", 0, 0)
        _label("Flash Attn:", "Fast attention kernel: big speed + VRAM win on "
                              "supported cards. 'auto' lets llama.cpp decide.", 1, 0)
        _combo("FLASH_ATTN", ["(default)", "auto", "on", "off"],
               "Maps to --flash-attn. '(default)' omits the flag.", 1, 1)

        _label("Cache Reuse:", "Min chunk size to reuse a KV prefix across turns "
                               "(needs prompt caching). 0 = off. Large win in "
                               "Dialogue, where every turn resends a long prefix. "
                               "Ignored by llama.cpp when an mmproj (vision) model "
                               "is loaded.", 1, 2)
        _spin("CACHE_REUSE", 0, 4096, 0,
              "Maps to --cache-reuse N. 0 omits the flag. Try 256.", 1, 3)

        _label("Ctx Checkpoints:", "Max context checkpoints per slot. Helps long "
                                   "conversations stay coherent; higher uses more RAM.",
               2, 0)
        _spin("CTX_CHECKPOINTS", -1, 256, -1,
              "Maps to --ctx-checkpoints N. -1 omits the flag.", 2, 1, special="(default)")

        _check("KV_OFFLOAD", "Keep KV cache in system RAM",
               "Checked = KV cache stays in system RAM (--no-kv-offload), freeing "
               "VRAM for weights. Useful when the model barely fits.", 2, 2)
        controls["KV_OFFLOAD"].setChecked(
            os.getenv(f"{prefix}_KV_OFFLOAD", "false").lower() == "true")
        controls["KV_OFFLOAD"].setToolTip(
            "Checked = pass --no-kv-offload (KV cache in system RAM).\n"
            "Unchecked = omit the flag (llama.cpp keeps KV offload enabled).")

        # ── MoE expert placement (the big lever on 16GB) ────────────────────
        _label("— MoE / CPU Offload —", "", 3, 0)
        _label("MoE Layers on CPU:", "Keep the MoE expert weights of the first N "
                                     "layers in system RAM. This is how a big MoE "
                                     "model fits a small card. 0 = off.", 4, 0)
        _spin("N_CPU_MOE", 0, 200, 0,
              "Maps to --n-cpu-moe N. 0 omits the flag. Start ~half the layer count.",
              4, 1)

        _label("Dense FFN on CPU:", "Keep the dense FFN weights of the first N layers "
                                    "in system RAM (non-MoE layers). 0 = off.", 4, 2)
        _spin("N_CPU_FFN", 0, 200, 0,
              "Maps to --n-cpu-ffn N. 0 omits the flag.", 4, 3)

        _check("CPU_MOE", "All MoE weights on CPU",
               "Checked = --cpu-moe (every expert weight in system RAM). "
               "Slowest but smallest VRAM footprint.", 5, 0)

        # ── Samplers / anti-repetition ──────────────────────────────────────
        _label("— Sampling & Anti-Repetition —", "", 6, 0)
        _label("Top-K:", "Top-K sampling. 0 = disabled (llama.cpp default 40).", 7, 0)
        _spin("TOP_K", -1, 500, -1,
              "Maps to --top-k N. -1 omits the flag.", 7, 1, special="(default)")

        _label("Top-P:", "Nucleus sampling (default 0.95). 1.0 = disabled.", 7, 2)
        _dspin("TOP_P", 0.0, 1.0, 0.0,
               "Maps to --top-p N. 0 omits the flag.", 7, 3)

        _label("Min-P:", "Min-P sampling (default 0.05). Prunes unlikely tokens; "
                         "good quality/creativity balance. 0 = disabled.", 8, 0)
        _dspin("MIN_P", 0.0, 1.0, 0.0,
               "Maps to --min-p N. 0 omits the flag. Try 0.05.", 8, 1)

        _label("Repeat Penalty:", "Penalise repeated token sequences (default 1.0 = off).",
               8, 2)
        _dspin("REPEAT_PENALTY", 0.0, 2.0, 0.0,
               "Maps to --repeat-penalty N. 0 omits the flag. Try 1.05-1.15.", 8, 3)

        _label("Presence Penalty:", "Repeat alpha presence penalty (default 0 = off).",
               9, 0)
        _dspin("PRESENCE_PENALTY", 0.0, 2.0, 0.0,
               "Maps to --presence-penalty N. 0 omits the flag.", 9, 1)

        _label("Frequency Penalty:", "Repeat alpha frequency penalty (default 0 = off).",
               9, 2)
        _dspin("FREQUENCY_PENALTY", 0.0, 2.0, 0.0,
               "Maps to --frequency-penalty N. 0 omits the flag.", 9, 3)

        # DRY — purpose-built to kill repeated text
        _label("DRY Multiplier:", "DRY sampler: directly suppresses repeated "
                                  "sequences. 0 = off. Try 0.8.", 10, 0)
        _dspin("DRY_MULTIPLIER", 0.0, 5.0, 0.0,
               "Maps to --dry-multiplier N. 0 omits the flag (and its sub-flags).",
               10, 1)
        _label("DRY Base:", "DRY base value (llama.cpp default 1.75).", 10, 2)
        _dspin("DRY_BASE", 0.0, 3.0, 0.0,
               "Maps to --dry-base N. Only emitted when DRY Multiplier > 0.", 10, 3)
        _label("DRY Allowed Len:", "Allowed repeat length before DRY penalises "
                                   "(default 2).", 11, 0)
        _spin("DRY_ALLOWED_LENGTH", -1, 32, -1,
              "Maps to --dry-allowed-length N. -1 omits it.", 11, 1, special="(default)")
        _label("DRY Penalty Last-N:", "Tokens considered by DRY (default 64).", 11, 2)
        _spin("DRY_PENALTY_LAST_N", -1, 2048, -1,
              "Maps to --dry-penalty-last-n N. -1 omits it.", 11, 3, special="(default)")

        # XTC — remove boring tokens
        _label("XTC Probability:", "XTC sampler: removes 'boring' tokens to raise "
                                   "variety. 0 = off. Try 0.5.", 12, 0)
        _dspin("XTC_PROBABILITY", 0.0, 1.0, 0.0,
               "Maps to --xtc-probability N. 0 omits the flag.", 12, 1)
        _label("XTC Threshold:", "XTC threshold (default 0.1; 1.0 = disabled).", 12, 2)
        _dspin("XTC_THRESHOLD", 0.0, 1.0, 0.0,
               "Maps to --xtc-threshold N. Only emitted when XTC Probability > 0.",
               12, 3)

        # ── Reasoning ───────────────────────────────────────────────────────
        _label("— Reasoning —", "", 13, 0)
        _label("Reasoning Budget:", "Token budget for thinking: -1 unrestricted, "
                                    "0 immediate end, N = cap. -2 = leave default.",
               14, 0)
        _spin("REASONING_BUDGET", -2, 65536, -2,
              "Maps to --reasoning-budget N. -2 omits the flag.", 14, 1, special="(default)")
        _label("Reasoning Format:", "How thought tags are parsed/returned.", 14, 2)
        _combo("REASONING_FORMAT",
               ["(default)", "none", "auto", "deepseek", "deepseek-legacy"],
               "Maps to --reasoning-format. '(default)' omits the flag.", 14, 3,
               width=130)

        # ── Multimodal projector ────────────────────────────────────────────
        _label("— Vision (mmproj) —", "", 15, 0)
        _label("Projector (mmproj):", "Companion mmproj-*.gguf for vision. Leave "
                                      "empty if the model has vision built in or is "
                                      "text-only.", 16, 0)
        from PySide6.QtWidgets import QLineEdit as _LE, QPushButton as _PB, QHBoxLayout as _HL, QWidget as _W
        proj_row = _W()
        proj_lay = _HL(proj_row)
        proj_lay.setContentsMargins(0, 0, 0, 0)
        proj_edit = _LE()
        proj_edit.setText(os.getenv(f"{prefix}_MMPROJ", ""))
        proj_edit.setPlaceholderText("(none — text-only or built-in vision)")
        proj_edit.setStyleSheet(spin_qss)
        proj_edit.setToolTip(
            "Path to an mmproj-*.gguf projector (maps to --mmproj).\n"
            "Empty omits the flag: llama.cpp then uses a projector embedded in the "
            "GGUF if present, else runs text-only.")
        proj_lay.addWidget(proj_edit, 1)
        auto_btn = _PB("Auto")
        auto_btn.setFixedWidth(52)
        auto_btn.setToolTip("Find an mmproj-*.gguf next to the selected model.")
        auto_btn.clicked.connect(lambda _=False, p=prefix, e=proj_edit: self._auto_detect_mmproj(p, e))
        proj_lay.addWidget(auto_btn)
        grid.addWidget(proj_row, 16, 1, 1, 3)
        controls["MMPROJ"] = proj_edit

        _check("MMPROJ_OFFLOAD", "Keep projector on CPU",
               "Checked = --no-mmproj-offload (projector stays in system RAM).",
               17, 0)

        hint = _QL("Unset controls add no flag — llama.cpp keeps its own default. "
                   "Values apply on the next brain restart.")
        hint.setStyleSheet("color: #666; font-size: 10px;")
        hint.setWordWrap(True)
        grid.addWidget(hint, 18, 0, 1, 3)

        # Help button — opens the same in-app help dialog as the Dialogue tab,
        # pre-filtered to this brain's flags.
        help_btn = QPushButton("❓ Help")
        help_btn.setFixedWidth(90)
        help_btn.setToolTip("Explain every flag here (opens the in-app feature help).")
        help_btn.clicked.connect(
            lambda _=False: self._open_llama_flags_help(brain_label))
        grid.addWidget(help_btn, 18, 3)

        parent_layout.addWidget(group)
        return controls

    def _open_llama_flags_help(self, brain_label: str = "") -> None:
        """Open the in-app help dialog filtered to the advanced llama.cpp flags."""
        try:
            from gui.panels.help_dialog import show_help_dialog
            show_help_dialog(self, keyword="Flag:")
        except Exception as exc:
            try:
                self._log(f"Help dialog unavailable: {exc}")
            except Exception:
                pass

    @staticmethod
    def _mmproj_core(stem: str) -> str:
        """Reduce a model or projector filename to its shared 'core' identity.

        Strips a leading ``mmproj-`` and any trailing quant/format token
        (``Q4_K_M``, ``BF16``, ``F16``, ``Q3_K_XL``, ``.Q6_K`` …) so that a
        model and its projector collapse to the same string, e.g.::

            gemma-4-26B-A4B-it-Q4_K_M      ->  gemma-4-26B-A4B-it
            mmproj-gemma-4-26B-A4B-it-BF16 ->  gemma-4-26B-A4B-it
        """
        import re
        s = stem
        if s.lower().startswith("mmproj-"):
            s = s[len("mmproj-"):]
        # Repeatedly peel a trailing quant/format token (separated by - or .).
        while True:
            m = re.match(
                r"^(.*?)[._-](?:Q\d[\w.]*|F\d+|BF\d+|IQ\d[\w.]*|QAT|BF16|F16|F32)$",
                s, re.IGNORECASE)
            if not m or not m.group(1):
                return s
            s = m.group(1)

    def _auto_detect_mmproj(self, prefix: str, edit) -> None:
        """Fill the mmproj field with the projector that matches the model.

        Matches by core identity (see ``_mmproj_core``) — NOT by folder order.
        If the selected model has no matching projector (text-only, or its
        vision projector simply isn't installed), the field is left EMPTY and a
        clear note is logged; we never grab an unrelated model's projector
        (which llama.cpp rejects at startup, killing the visible console).
        """
        try:
            import pathlib
            small = prefix.startswith("SMALL")
            model_path = self._current_model_path(small)
            if not model_path:
                self._log("⚠️ Select a model first, then Auto-detect mmproj.")
                return
            folder = pathlib.Path(model_path).parent
            model_stem = pathlib.Path(model_path).stem
            model_core = self._mmproj_core(model_stem)
            model_tokens = model_core.split("-")

            found = sorted(folder.glob("mmproj*.gguf"))
            if not found:
                edit.setText("")
                self._log(f"ℹ️ No mmproj-*.gguf next to {pathlib.Path(model_path).name} "
                          f"(model is text-only or has vision built in).")
                return

            # Score each candidate against the selected model's core identity.
            # exact == the cores are identical; related == one token list is a
            # prefix or suffix of the other (handles a -QAT/-it tag on the
            # projector, or a brand prefix like "Ternary-" on the model).
            best, best_score = None, 0
            for cand in found:
                cand_core = self._mmproj_core(cand.stem)
                if cand_core == model_core:
                    score = 2
                elif self._token_related(model_tokens, cand_core.split("-")):
                    score = 1
                else:
                    continue
                if score > best_score:
                    best, best_score = cand, score

            if best is None:
                edit.setText("")
                names = ", ".join(c.name for c in found[:3])
                more = f" (+{len(found) - 3} more)" if len(found) > 3 else ""
                self._log(f"ℹ️ No projector matches {model_stem} "
                          f"(found: {names}{more} — none belong to this model). "
                          f"Left blank; this model runs text-only.")
                return

            edit.setText(str(best))
            self._log(f"✅ Projector for {model_stem}: {best.name}")
        except Exception as exc:
            self._log(f"mmproj auto-detect failed: {exc}")

    @staticmethod
    def _token_prefix(a: list, b: list) -> bool:
        """True if one token list is a prefix of the other (token-wise)."""
        n = min(len(a), len(b))
        if n == 0:
            return False
        return [t.lower() for t in a[:n]] == [t.lower() for t in b[:n]]

    @staticmethod
    def _token_suffix(a: list, b: list) -> bool:
        """True if one token list is a suffix of the other (token-wise)."""
        n = min(len(a), len(b))
        if n == 0:
            return False
        return [t.lower() for t in a[-n:]] == [t.lower() for t in b[-n:]]

    @staticmethod
    def _token_related(a: list, b: list) -> bool:
        """Model↔projector cores are related if one is a prefix or suffix of
        the other — the projector name is the model name minus a quant/format
        tag, possibly with a brand prefix (``Ternary-Bonsai`` vs ``Bonsai``)."""
        return DualBrainControl._token_prefix(a, b) or DualBrainControl._token_suffix(a, b)

    def _llama_flag_values(self, prefix: str, controls: dict) -> tuple:
        """Convert one group's controls into env key/value pairs and stale keys.

        Returns ``(values, stale_keys)``. A control at its "not set" sentinel
        produces NO value — instead it names its ``{prefix}_{key}`` for
        REMOVAL, because a leftover line from a previous state must not
        resurrect the flag (ARCH-ENG-314: unchecking/“(default)”-ing/clearing
        a control used to leave the old line in .env forever, so the operator's
        change was silently reverted on every rebuild).
        """
        values = {}
        stale = []
        try:
            from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit
        except Exception:
            return values, stale

        def _put(key, value):
            values[f"{prefix}_{key}"] = str(value)

        for key, widget in controls.items():
            try:
                if isinstance(widget, QComboBox):
                    text = widget.currentText().strip()
                    if text.startswith("("):
                        stale.append(f"{prefix}_{key}")  # "(default)" -> unset
                        continue
                    _put(key, text)
                elif isinstance(widget, QLineEdit):
                    text = widget.text().strip()
                    if text:
                        _put(key, text)
                    else:
                        stale.append(f"{prefix}_{key}")
                elif isinstance(widget, QCheckBox):
                    # A CHECKED box writes "true" — for the "keep X in system
                    # RAM" checkboxes the parser maps this to the --no-…-offload
                    # form (ARCH-ENG-315). An UNCHECKED box means "not set": the
                    # key must be REMOVED so the operator's change persists;
                    # writing nothing (the old behaviour) left the previous
                    # value in .env and re-checked the box on every reload.
                    if widget.isChecked():
                        _put(key, "true")
                    else:
                        stale.append(f"{prefix}_{key}")
                else:
                    # Spin boxes: unset metadata decides (per-control lambdas
                    # attached in _build_llama_flag_group), falling back to the
                    # historic out-of-range sentinel rules.
                    val = widget.value()
                    unset_test = getattr(widget, "_flag_unset", None)
                    special = widget.specialValueText()
                    if special and val == widget.minimum():
                        stale.append(f"{prefix}_{key}")
                    elif unset_test is not None and unset_test(val):
                        stale.append(f"{prefix}_{key}")
                    elif isinstance(val, float):
                        _put(key, f"{val:g}")
                    else:
                        _put(key, val)
            except RuntimeError:
                # Widget's C++ side is gone (tab rebuilt); skip it.
                continue
        return values, stale

    def setup_ui(self):
        """Build the control panel UI with dynamic provider and GPU detection."""
        layout = QVBoxLayout(self)
        
        # ── Header ──────────────────────────────────────────────────────
        header = QLabel("🧠 Dual Brain Orchestrator")
        header.setFont(QFont("Segoe UI", 18, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("color: #bb86fc; padding: 10px;")
        layout.addWidget(header)
        
        # Dynamic subtitle based on detected configuration. Uses the current
        # cache (detect=False) so building this tab never blocks on the ~2s of
        # endpoint probes; _update_gpu_subtitle() re-renders it once the
        # background warm-up/detection fills the cache.
        gpus = self.provider_manager.get_gpus(detect=False)
        providers = self.provider_manager.get_running_providers(detect=False)
        
        subtitle = QLabel()
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #888; font-size: 12px; padding-bottom: 10px;")
        layout.addWidget(subtitle)
        self._gpu_subtitle_label = subtitle
        self._update_gpu_subtitle()

        # Provider status summary
        provider_names = ", ".join([f"{p.name}: {p.status}" for p in providers.values()]) or "None detected"
        self.route_label = QLabel(f"Providers: {provider_names}")
        self.route_label.setAlignment(Qt.AlignCenter)
        self.route_label.setWordWrap(True)
        self.route_label.setStyleSheet("color: #4fc3f7; font-size: 11px; padding-bottom: 6px;")
        layout.addWidget(self.route_label)

        # ── GPU Status Panel ───────────────────────────────────────────
        gpu_group = QGroupBox("📊 GPU Status (Auto-Refreshing)")
        gpu_group.setStyleSheet("""
            QGroupBox {
                color: #03dac6;
                font-weight: bold;
                border: 2px solid #03dac6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        gpu_layout = QHBoxLayout(gpu_group)

        # Dynamic GPU widgets based on detected GPUs
        self.gpu_widgets = {}
        colors = ["#bb86fc", "#03dac6", "#ff9800", "#4caf50", "#e91e63", "#9c27b0"]
        # ARCH-ENG-161: dedupe by index and skip unusable rows before rendering.
        # nvidia-smi can transiently report a phantom row (empty name / 0 MB) or a
        # repeated index right after a GPU is recovered; rendering those produced
        # empty placeholder panels that looked like duplicate devices.
        # `gpu_widgets` is keyed by index, so a duplicate also silently orphaned
        # the real one. Fixed in v2.1.112; tagged ARCH-ENG-161 so the
        # ARCH-ENG-150 guard can verify the release record against HEAD.
        seen_gpu_indexes: set = set()
        shown = 0
        for gpu in gpus:
            idx = getattr(gpu, "index", -1)
            name = (getattr(gpu, "name", "") or "").strip()
            mem = getattr(gpu, "memory_total_mb", 0) or 0
            if idx < 0 or not name or mem <= 0 or idx in seen_gpu_indexes:
                continue
            seen_gpu_indexes.add(idx)
            color = colors[shown % len(colors)]
            shown += 1
            widget = self._create_gpu_widget(idx, name, color)
            gpu_layout.addWidget(widget)
            self.gpu_widgets[idx] = widget
        
        # If no GPUs detected, show a label
        if not gpus:
            no_gpu_label = QLabel("No GPUs detected. Using cloud providers only.")
            no_gpu_label.setAlignment(Qt.AlignCenter)
            no_gpu_label.setStyleSheet("color: #ff9800; font-size: 12px; padding: 20px;")
            gpu_layout.addWidget(no_gpu_label)

        layout.addWidget(gpu_group)

        # ── Compute Devices (enable/disable per detected device) ──────────
        # Device-centric brain allocation: every detected GPU (by stable UUID)
        # and the CPU/RAM pool is listed with an enable checkbox and a role
        # selector (Auto / Big / Small). Choices persist to settings.json and
        # drive which devices host which brain. Nothing is hardcoded — a new
        # GPU appears here automatically on the next detection.
        self._build_device_panel(layout)

        # ── N-Brain Roster panel removed (ARCH-ENG-309) ────────────────────
        # This slot between Compute Devices and Provider Control held the
        # per-tier count spinners (Big/Small Brains) and one editable
        # provider/model/device row per slot — a second model-selection
        # surface that could disagree with Provider Control, which is the
        # single place model selection and per-slot settings are edited.
        # The roster DATA (settings.json) still drives extra slots at
        # launch; only this editing surface is gone.
        # Kept on purpose: cleanup() still calls flush_pending_roster_edit
        # (a safe no-op with no panel) because ARCH-ENG-153 pins that flush
        # structurally, and brain_roster_panel.py keeps its standalone
        # unit tests.

        # ── Provider Control Panel ──────────────────────────────────────
        provider_group = QGroupBox("🎛️ Provider Control (One-Click Launch)")
        self.provider_control_group = provider_group
        provider_group.setStyleSheet("""
            QGroupBox {
                color: #ffb300;
                font-weight: bold;
                border: 2px solid #ffb300;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        provider_layout = QGridLayout(provider_group)

        # N-brain rows (Phase 3): one BrainControlRow per runtime slot. Slots
        # 0/1 are the Big/Small brains; slots 2+ appear automatically when more
        # devices are enabled in the Compute Devices panel. The legacy sb_*/bb_*
        # attribute names are ALIASED to slots 0/1's sub-widgets so the entire
        # existing backend wiring (start/stop/status/model) keeps working
        # unchanged. Rebuilt by _rebuild_provider_rows() on device-policy change.
        self._provider_rows: list = []
        self._build_provider_rows(provider_layout)

        # Phase G (ARCH-ENG-094): a "?" button that explains the advanced
        # llama.cpp settings (the same text as the per-control mouse-hover tips).
        help_btn = QPushButton("❓ Advanced settings help")
        help_btn.setToolTip(
            "What each advanced llama.cpp setting does and when to change it.")
        help_btn.setStyleSheet(
            "QPushButton { background:#333; color:#ffb300; border:1px solid #ffb300;"
            " border-radius:4px; padding:4px 10px; }"
            "QPushButton:hover { background:#3a3a3a; }")
        help_btn.clicked.connect(self._show_advanced_settings_help)
        provider_layout.addWidget(help_btn, len(self._provider_rows), 0)

        layout.addWidget(provider_group)

        # ── llama.cpp Settings Panel ─────────────────────────────────────
        settings_group = QGroupBox("⚙️ Local Provider Settings (per brain)")
        self.local_settings_group = settings_group
        settings_group.setStyleSheet("""
            QGroupBox {
                color: #9c27b0;
                font-weight: bold;
                border: 2px solid #9c27b0;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        settings_layout = QGridLayout(settings_group)

        # ── Per-device settings are rendered by _build_detected_brains_summary
        # below (one BrainSettingsRow per enabled device, incl. CPU/extra GPUs).
        # The legacy sb_*/bb_* widget attributes are aliased to those rows'
        # controls there, so the launch snapshot, _snapshot_settings_values,
        # temperature presets, and hardware presets all keep working unchanged.
        # The old hardcoded two-brain editor grid was removed in v2.1.17 — the
        # unified per-device rows replace it.

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Hardware preset:"))
        self.hardware_preset_combo = QComboBox()
        self.hardware_preset_combo.addItems(list(HARDWARE_PRESETS))
        self.hardware_preset_combo.setCurrentText("Balanced")
        self.hardware_preset_combo.setToolTip(
            "Choose a starting point for VRAM, context, batch size, and CPU/GPU use. "
            "Save and restart both servers after applying a preset.")
        preset_row.addWidget(self.hardware_preset_combo)
        preset_row.addWidget(QLabel("Target:"))
        self.hardware_preset_target_combo = QComboBox()
        self.hardware_preset_target_combo.addItems([
            "Big Brain / GPU 0",
            "Small Brain / GPU 1",
            "Both brains",
        ])
        self.hardware_preset_target_combo.setCurrentText("Big Brain / GPU 0")
        self.hardware_preset_target_combo.setToolTip(
            "Choose which runtime GPU/brain receives the preset values.")
        preset_row.addWidget(self.hardware_preset_target_combo)
        self.apply_hardware_preset_btn = QPushButton("Apply")
        self.apply_hardware_preset_btn.setToolTip(
            "Fill the selected brain's local-provider controls with the hardware preset.")
        self.apply_hardware_preset_btn.clicked.connect(self._apply_hardware_preset)
        preset_row.addWidget(self.apply_hardware_preset_btn)
        preset_row.addStretch(1)
        self.hardware_preset_help = QLabel(HARDWARE_PRESETS["Balanced"]["help"])
        self.hardware_preset_help.setWordWrap(True)
        self.hardware_preset_help.setStyleSheet("color: #888; font-size: 10px;")
        self.hardware_preset_combo.currentTextChanged.connect(
            lambda name: self.hardware_preset_help.setText(HARDWARE_PRESETS[name]["help"]))
        preset_row.addWidget(self.hardware_preset_help, 2)
        self.tensor_profile_label = QLabel()
        self.tensor_profile_label.setWordWrap(True)
        self.tensor_profile_label.setStyleSheet("color: #888; font-size: 10px;")
        preset_row.addWidget(self.tensor_profile_label, 3)
        settings_layout.addLayout(preset_row, 0, 0, 1, 4)

        # ── Per-device settings (N-brain): one editable BrainSettingsRow per
        # enabled device, incl. CPU/RAM and extra GPUs. The legacy sb_*/bb_*
        # widget attributes are aliased to these rows' controls there.
        self._build_detected_brains_summary(settings_layout)

        layout.addWidget(settings_group)

        # ── Advanced llama.cpp flags (v2.1.9) ──────────────────────────────
        # Two self-contained groups (one per brain) so the existing per-brain
        # settings grid above keeps its row numbering untouched. Every control
        # maps 1:1 to a llama-server flag and is only emitted when the operator
        # sets it, so defaults stay byte-identical to the previous behaviour.
        self.sb_adv_group = self._build_llama_flag_group(
            layout, "Small Brain", "SMALL_BRAIN", SMALL_SPIN_QSS)
        self.bb_adv_group = self._build_llama_flag_group(
            layout, "Big Brain", "BIG_BRAIN", BIG_SPIN_QSS)

        # ── Provider Control Panel ──────────────────────────────────────
        
        # ── Quick Actions ───────────────────────────────────────────────
        quick_group = QGroupBox("⚡ Quick Actions")
        quick_group.setObjectName("quickActionsGroup")
        quick_group.setStyleSheet("""
            QGroupBox {
                color: #4caf50;
                font-weight: bold;
                border: 2px solid #4caf50;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        quick_layout = QHBoxLayout(quick_group)
        
        self.start_all_btn = QPushButton("🚀 Start All Brains")
        self.start_all_btn.setObjectName("startAllBrainsButton")
        self.start_all_btn.setToolTip("Start Small Brain and Big Brain together")
        self.start_all_btn.setStyleSheet("""
            QPushButton {
                background: #4caf50;
                color: white;
                font-weight: bold;
                font-size: 14px;
                border: none;
                border-radius: 6px;
                padding: 12px 24px;
            }
            QPushButton:hover { background: #45a049; }
        """)
        quick_layout.addWidget(self.start_all_btn)

        self.stop_all_btn = QPushButton("🛑 Stop All Brains")
        self.stop_all_btn.setObjectName("stopAllBrainsButton")
        self.stop_all_btn.setToolTip("Stop Small Brain and Big Brain together")
        self.stop_all_btn.setStyleSheet("""
            QPushButton {
                background: #f44336;
                color: white;
                font-weight: bold;
                font-size: 14px;
                border: none;
                border-radius: 6px;
                padding: 12px 24px;
            }
            QPushButton:hover { background: #da190b; }
        """)
        quick_layout.addWidget(self.stop_all_btn)

        self.refresh_btn = QPushButton("🔄 Refresh Status")
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background: #2196f3;
                color: white;
                font-weight: bold;
                font-size: 14px;
                border: none;
                border-radius: 6px;
                padding: 12px 24px;
            }
            QPushButton:hover { background: #1976d2; }
        """)
        self.refresh_btn.clicked.connect(self._refresh_provider_status)
        quick_layout.addWidget(self.refresh_btn)

        # Auto-start both llama-server instances when MrBot1000 launches
        self.auto_start_check = QCheckBox(
            "Start both servers automatically at launch")
        self.auto_start_check.setObjectName("autoStartCheck")
        self.auto_start_check.setToolTip(
            "When enabled, MrBot1000 launches both llama-server instances "
            "(big=1234, small=1235) automatically when the program starts, "
            "using the per-brain settings configured here. Disable to start "
            "the servers manually with Start All Brains.")
        self.auto_start_check.setChecked(
            os.getenv("AUTO_START_SERVERS", "1").strip().lower()
            in ("1", "true", "yes", "on"))
        quick_layout.addWidget(self.auto_start_check)

        self.show_server_consoles_check = QCheckBox(
            "Show llama-server console windows")
        self.show_server_consoles_check.setObjectName("showServerConsolesCheck")
        self.show_server_consoles_check.setToolTip(
            "Open a visible console for each locally launched brain. "
            "Disable to keep consoles hidden and write output to the temporary logs.")
        self.show_server_consoles_check.setChecked(
            os.getenv("SHOW_BRAIN_CONSOLES", "1").strip().lower()
            in ("1", "true", "yes", "on"))
        quick_layout.addWidget(self.show_server_consoles_check)

        # Save llama.cpp customization to .env (v2.1)
        self.save_settings_btn = QPushButton("💾 Save Local Provider Settings")
        self.save_settings_btn.setStyleSheet("""
            QPushButton {
                background: #ff9800;
                color: #000;
                font-weight: bold;
                font-size: 13px;
                border: none;
                border-radius: 6px;
                padding: 12px 18px;
            }
            QPushButton:hover { background: #fb8c00; }
        """)
        quick_layout.addWidget(self.save_settings_btn)
        layout.addWidget(quick_group)
        
        # ── Status Log ──────────────────────────────────────────────────
        log_group = QGroupBox("📝 Event Log")
        log_group.setStyleSheet("""
            QGroupBox {
                color: #aaaaaa;
                font-weight: bold;
                border: 1px solid #555;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        log_layout = QVBoxLayout(log_group)
        
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setMaximumHeight(150)
        self.log_display.setStyleSheet("""
            QTextEdit {
                background: #0a0a0a;
                color: #00ff00;
                border: 1px solid #333;
                border-radius: 4px;
                font-family: Consolas, monospace;
                font-size: 11px;
            }
        """)
        log_layout.addWidget(self.log_display)
        
        layout.addWidget(log_group)
        
        # ── Configuration Info ──────────────────────────────────────────
        config_label = QLabel(
            "Config: Small Brain = active provider / CPU or available GPU | "
            "Big Brain = active provider / available primary GPU"
        )
        config_label.setAlignment(Qt.AlignCenter)
        config_label.setStyleSheet("color: #666; font-size: 10px; padding: 5px;")
        layout.addWidget(config_label)
    
    def _create_gpu_widget(self, index, name, color):
        """Create a GPU status display widget with estimated + actual bars,
        color-coded safety zones, KV cache bar, and per-component tooltip."""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background: #1a1a1a;
                border: 2px solid {color};
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        layout = QVBoxLayout(frame)
        layout.setSpacing(4)

        # GPU name + assigned brain
        brain_name = f"Edward (Big Brain)" if index == 0 else f"Jacob (Small Brain)"
        name_label = QLabel(f"GPU {index}: {name} — {brain_name}")
        name_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        name_label.setStyleSheet(f"color: {color};")
        layout.addWidget(name_label)

        # Model info label
        model_label = QLabel("Model: —")
        model_label.setStyleSheet("color: #aaa; font-size: 10px;")
        layout.addWidget(model_label)

        # Context info
        ctx_label = QLabel("Context: —")
        ctx_label.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(ctx_label)

        # ── Estimated VRAM bar ─────────────────────────────────────────
        est_label = QLabel("Estimated:")
        est_label.setStyleSheet("color: #ccc; font-size: 10px;")
        layout.addWidget(est_label)

        est_bar = QProgressBar()
        est_bar.setMaximum(100)
        est_bar.setValue(0)
        est_bar.setTextVisible(True)
        est_bar.setFormat("%v%")
        est_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid #444;
                border-radius: 4px;
                text-align: center;
                color: white;
                min-height: 18px;
            }}
            QProgressBar::chunk {{
                background: {color};
                border-radius: 4px;
            }}
        """)
        est_bar.setProperty("base_stylesheet", f"""
            QProgressBar {{
                border: 1px solid #444;
                border-radius: 4px;
                text-align: center;
                color: white;
                min-height: 18px;
            }}
            QProgressBar::chunk {{
                background: {{CHUNK_COLOR}};
                border-radius: 4px;
            }}
        """)
        layout.addWidget(est_bar)

        est_detail = QLabel("Weights: —  KV: —  Overhead: —")
        est_detail.setStyleSheet("color: #888; font-size: 9px;")
        layout.addWidget(est_detail)

        # ── Actual VRAM bar (nvidia-smi) ───────────────────────────────
        act_label = QLabel("Actual (nvidia-smi):")
        act_label.setStyleSheet("color: #ccc; font-size: 10px; padding-top: 4px;")
        layout.addWidget(act_label)

        act_bar = QProgressBar()
        act_bar.setMaximum(100)
        act_bar.setValue(0)
        act_bar.setTextVisible(True)
        act_bar.setFormat("%v%")
        act_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #444;
                border-radius: 4px;
                text-align: center;
                color: white;
                min-height: 18px;
            }
            QProgressBar::chunk {
                background: #4caf50;
                border-radius: 4px;
            }
        """)
        layout.addWidget(act_bar)

        act_detail = QLabel("— GB / — GB")
        act_detail.setStyleSheet("color: #888; font-size: 9px;")
        layout.addWidget(act_detail)

        # ── KV Cache bar ───────────────────────────────────────────────
        kv_label = QLabel("KV Cache (allocated):")
        kv_label.setStyleSheet("color: #ccc; font-size: 10px; padding-top: 4px;")
        layout.addWidget(kv_label)

        kv_bar = QProgressBar()
        kv_bar.setMaximum(100)
        kv_bar.setValue(0)
        kv_bar.setTextVisible(True)
        kv_bar.setFormat("%v%")
        kv_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #444;
                border-radius: 4px;
                text-align: center;
                color: white;
                min-height: 14px;
            }
            QProgressBar::chunk {
                background: #ff9800;
                border-radius: 4px;
            }
        """)
        layout.addWidget(kv_bar)

        kv_detail = QLabel("— GB / — GB allocated")
        kv_detail.setStyleSheet("color: #888; font-size: 9px;")
        layout.addWidget(kv_detail)

        # ── Status line ────────────────────────────────────────────────
        status_label = QLabel("—")
        status_label.setStyleSheet("color: #4caf50; font-size: 10px; font-weight: bold; padding-top: 4px;")
        layout.addWidget(status_label)

        # ── Live generation progress bar ───────────────────────────────
        progress_label = QLabel("Generation:")
        progress_label.setStyleSheet("color: #ccc; font-size: 10px; padding-top: 4px;")
        layout.addWidget(progress_label)

        progress_bar = QProgressBar()
        progress_bar.setMaximum(100)
        progress_bar.setValue(0)
        progress_bar.setTextVisible(True)
        progress_bar.setFormat("— tok/s")
        progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #444;
                border-radius: 4px;
                text-align: center;
                color: white;
                min-height: 14px;
            }
            QProgressBar::chunk {
                background: #00bcd4;
                border-radius: 4px;
            }
        """)
        layout.addWidget(progress_bar)

        tok_speed_label = QLabel("— tok/s  |  — tok generated  |  — elapsed")
        tok_speed_label.setStyleSheet("color: #888; font-size: 9px;")
        layout.addWidget(tok_speed_label)

        # Store references.
        #
        # ARCH-ENG-177: this was `if index == 0: ... else: ...`, so EVERY
        # non-zero index assigned the `gpu1_*` names. On a 3-GPU box GPU 2's
        # creation overwrote GPU 1's references, and no `gpu2_*` attribute was
        # ever created. Every `update_gpu_*` / `_set_gpu_*` call for index >= 1
        # then wrote GPU N's telemetry onto GPU 1's labels — GPU 1 showed wrong
        # numbers and GPU 2 showed none at all.
        #
        # That directly contradicts the premise of the whole app: one brain
        # server per detected GPU, each with its own telemetry.
        #
        # Now every index gets its own names, and `gpu0_*` / `gpu1_*` are kept
        # as ALIASES for indices 0 and 1 because a lot of existing code reads
        # those attributes directly by name.
        refs = {
            "est_bar": est_bar, "act_bar": act_bar, "kv_bar": kv_bar,
            "label": name_label, "model_label": model_label,
            "ctx_label": ctx_label, "est_detail": est_detail,
            "act_detail": act_detail, "kv_detail": kv_detail,
            "status": status_label, "progress": progress_bar,
            "tok_speed": tok_speed_label,
        }
        for suffix, widget in refs.items():
            setattr(self, f"gpu{index}_{suffix}", widget)
        # Registry the setters can consult for ANY index, not just 0/1.
        registry = getattr(self, "_gpu_widget_refs", None)
        if registry is None:
            registry = {}
            self._gpu_widget_refs = registry
        registry[int(index)] = refs
        # Live generation progress state (updated from dialogue).
        self._gpu_gen_start = {}
        self._gpu_tok_count = {}
        self._gpu_tok_running = {}
        return frame
    
    # ═══════════════════════════════════════════════════════════════════
    # GPU STATUS UPDATES
    # ═══════════════════════════════════════════════════════════════════
    def pause_background(self):
        """Reduce polling while the tab is hidden.

        ARCH-ENG-230: THIS ONLY SLOWED THE GPU WORKER. THE 4 s STATUS TIMER RAN
        ANYWAY.

        `pause_background` exists to cut background cost for a hidden tab, and
        `tab_lifecycle` calls it on every tab switch away. But it only set
        `gpu_worker.interval_ms = 15000`. The `_status_timer` at :405 -- a 4 s
        `QTimer` driving `_refresh_provider_status` -- kept firing for the life
        of the process, hidden or not.

        Each tick spawned a probe thread, and `_probe_with_deadline` expands that
        into one extra thread per visible GPU row, each doing `urlopen(timeout=2)`
        serially, plus a `settings.json` read from `_runtime_from_settings`. So
        a hidden Providers & GPU tab was still doing N+1 thread spawns and a
        disk read every four seconds.

        The provider liveness check is genuinely worth keeping while hidden: it
        is what makes a brain that died on its own show as stopped rather than
        frozen at "Running" (ARCH-ENG-073). So this slows the timer rather than
        stopping it -- the guarantee survives, the cost does not.
        """
        try:
            w = getattr(self, "gpu_worker", None)
            if w is not None:
                w.interval_ms = 15000
        except Exception:
            pass
        try:
            timer = getattr(self, "_status_timer", None)
            if timer is not None:
                timer.setInterval(20000)
        except Exception:
            pass


    def resume_background(self):
        """Restore fast nvidia-smi polling when the tab is shown again."""
        try:
            w = getattr(self, "gpu_worker", None)
            if w is not None:
                w.interval_ms = 2000
                if not w.isRunning():
                    w.start()
        except Exception:
            pass
        # ARCH-ENG-230: also restore the status-timer interval that
        # `pause_background` slowed. Without this the tab stays at the
        # hidden 20 s cadence for the rest of the session.
        try:
            timer = getattr(self, "_status_timer", None)
            if timer is not None:
                timer.setInterval(4000)
        except Exception:
            pass

    def _on_gpu_status_updated(self, gpus):
        """Handle GPU status update from background worker. Updates estimated
        (from GGUF metadata) and actual (from nvidia-smi) bars side-by-side,
        color-coded safety zones, KV cache bar, and status line."""
        for gpu in gpus:
            idx = gpu["index"]
            mem_used_gb = gpu["memory_used_mb"] / 1024
            mem_total_gb = gpu["memory_total_mb"] / 1024
            
            # Calculate model VRAM breakdown (estimated need from GGUF metadata)
            model_info = self._get_model_vram_for_gpu(idx)
            model_vram_gb = model_info.get("total_gb", 0)
            weights_gb = model_info.get("weights_gb", 0)
            kv_gb = model_info.get("kv_gb", 0)
            overhead_gb = round(model_vram_gb - weights_gb - kv_gb, 2) if model_vram_gb > 0 else 0
            
            # Get context for this GPU
            ctx = self._get_context_for_gpu(idx)
            
            # Get model name
            model_name = self._get_model_name_for_gpu(idx)
            
            # ── Estimated bar ────────────────────────────────────────────
            if model_vram_gb > 0:
                gpu_pct = min(100, int((model_vram_gb / mem_total_gb) * 100))
                
                # Color-coded safety zones
                if gpu_pct < 80:
                    zone_color = "#4caf50"  # Green — fits comfortably
                    status_text = "✅ Fits in VRAM"
                elif gpu_pct < 100:
                    zone_color = "#ff9800"  # Orange — fits but close to limit
                    status_text = "⚠️ Close to limit"
                else:
                    zone_color = "#ff9800"  # Orange — spills to RAM but works
                    overflow = model_vram_gb - mem_total_gb
                    status_text = f"⚠️ {overflow:.1f} GB spills to RAM"
                
                # Update estimated bar
                self._set_gpu_bar(idx, "est", gpu_pct, zone_color)
                self._set_gpu_detail(idx, "est", f"Weights: {weights_gb:.1f}GB  KV: {kv_gb:.1f}GB  Overhead: {overhead_gb:.1f}GB")
                self._set_gpu_model(idx, model_name)
                self._set_gpu_ctx(idx, f"Context: {ctx:,} tokens")
                self._set_gpu_status(idx, status_text)
                
                # ── Actual bar ───────────────────────────────────────────
                mem_pct = min(100, int((mem_used_gb / mem_total_gb) * 100))
                self._set_gpu_bar(idx, "act", mem_pct, "#4caf50")
                self._set_gpu_detail(idx, "act", f"{mem_used_gb:.1f} GB / {mem_total_gb:.1f} GB")
                
                # ── KV Cache bar ────────────────────────────────────────
                # Estimate KV usage as a fraction of total estimated VRAM,
                # applied to actual VRAM usage (handles RAM spill correctly)
                kv_fraction = kv_gb / model_vram_gb if model_vram_gb > 0 else 0
                kv_used_gb = mem_used_gb * kv_fraction
                kv_pct = min(100, int((kv_used_gb / mem_total_gb) * 100)) if mem_total_gb > 0 else 0
                self._set_gpu_bar(idx, "kv", kv_pct, "#ff9800")
                kv_type = model_info.get("kv_type", "f16")
                self._set_gpu_detail(
                    idx, "kv", f"{kv_used_gb:.1f} GB / {kv_gb:.1f} GB allocated ({kv_type})")
                
            else:
                # No model selected — show actual nvidia-smi usage only
                mem_pct = int((mem_used_gb / mem_total_gb) * 100)
                self._set_gpu_bar(idx, "est", 0, "#666")
                self._set_gpu_bar(idx, "act", mem_pct, "#4caf50")
                self._set_gpu_bar(idx, "kv", 0, "#666")
                self._set_gpu_detail(idx, "est", "(no model selected)")
                self._set_gpu_detail(idx, "act", f"{mem_used_gb:.1f} GB / {mem_total_gb:.1f} GB")
                self._set_gpu_detail(idx, "kv", "—")
                self._set_gpu_model(idx, "—")
                self._set_gpu_ctx(idx, "—")
                self._set_gpu_status(idx, "—")

    def _gpu_ref(self, idx: int, suffix: str):
        """The widget registered for GPU `idx`, for ANY index.

        ARCH-ENG-177. Every setter below used
        `... if idx == 0 else gpu1_...`, which sent every index >= 1 to GPU 1's
        widgets. `gpu2`, `gpu3`, ... never existed as attributes, so on a 3+ GPU
        box GPU 2's telemetry overwrote GPU 1's panel and GPU 2's own panel never
        updated.

        Resolution order:
          1. the per-index registry built in `_create_gpu_widget`
          2. the `gpu{idx}_{suffix}` attribute (set for every index now)
          3. None -- the caller does nothing, which is correct for an index with
             no panel.

        Deliberately NOT falling back to `gpu1_*`: silently writing one device's
        numbers onto another device's panel is worse than showing nothing.
        """
        try:
            i = int(idx)
        except (TypeError, ValueError):
            return None
        registry = getattr(self, "_gpu_widget_refs", None) or {}
        refs = registry.get(i)
        if refs is not None:
            return refs.get(suffix)
        return getattr(self, f"gpu{i}_{suffix}", None)

    def _set_gpu_bar(self, idx, bar_type, pct, color):
        """Set a GPU bar value and color.

        ARCH-ENG-230: THE STYLESHEET IS ONLY REBUILT WHEN IT CHANGED.

        This runs for three bars per GPU every 2 s (15 s when hidden), from
        `_on_gpu_status_updated`. `QProgressBar.setStyleSheet` is not a plain
        assignment: it invalidates the widget style, re-runs the polish and
        relayouts the bar and its ancestors. Four repolish cycles per GPU per
        tick, writing the same colour almost every time because VRAM zones
        change rarely.
        """
        bar = self._gpu_ref(idx, f"{bar_type}_bar")
        if bar:
            bar.setValue(pct)
            base = bar.property("base_stylesheet")
            if base:
                css = base.replace("{CHUNK_COLOR}", color)
                if bar.styleSheet() != css:
                    bar.setStyleSheet(css)

    def _set_gpu_detail(self, idx, detail_type, text):
        """Set a GPU detail label. detail_type: 'est', 'act', 'kv'."""
        label = self._gpu_ref(idx, f"{detail_type}_detail")
        if label:
            label.setText(text)

    def _set_gpu_model(self, idx, text):
        """Set the model name label."""
        label = self._gpu_ref(idx, "model_label")
        if label:
            label.setText(f"Model: {text}")

    def _set_gpu_ctx(self, idx, text):
        """Set the context label."""
        label = self._gpu_ref(idx, "ctx_label")
        if label:
            label.setText(text)

    def _set_gpu_status(self, idx, text):
        """Set the status line with color.

        ARCH-ENG-230: same re-polish problem as `_set_gpu_bar` -- the colour is
        one of three values and changes far less often than this runs.
        """
        label = self._gpu_ref(idx, "status")
        if label:
            color = "#4caf50" if "✅" in text else "#ff9800" if "⚠️" in text else "#888"
            css = f"color: {color}; font-size: 10px; font-weight: bold; padding-top: 4px;"
            if label.styleSheet() != css:
                label.setStyleSheet(css)
            label.setText(text)

    def clear_gpu_progress(self, slot: int = 0):
        """Reset the generation progress bar after generation completes.

        v2.1.80 (ARCH-ENG-101): ``slot`` is the runtime slot index (0=Big,
        1=Small, 2+=extra device), NOT a persona name — the N-brain roster has
        no fixed Edward/Jacob pair, so callers resolve the active device's slot.
        """
        idx = int(slot)
        bar = getattr(self, f"gpu{idx}_progress", None)
        speed_label = getattr(self, f"gpu{idx}_tok_speed", None)
        if bar is not None:
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setFormat("— tok/s")
        if speed_label is not None:
            speed_label.setText("— tok/s  |  — tok generated  |  — elapsed")

    def update_gpu_progress(self, slot: int, tok_count: int, elapsed_s: float):
        """Update the live generation progress bar for a device slot.

        v2.1.80 (ARCH-ENG-101): device/slot-keyed. ``slot`` 0=Big, 1=Small,
        2+=extra. ``tok_count``/``elapsed_s`` come from the streaming brain
        (accumulated chars//4 and wall time since first token).
        """
        idx = int(slot)
        bar = getattr(self, f"gpu{idx}_progress", None)
        speed_label = getattr(self, f"gpu{idx}_tok_speed", None)
        if bar is None:
            return
        tps = tok_count / elapsed_s if elapsed_s > 0 else 0.0
        bar.setRange(0, 0)
        bar.setFormat(f"● {tps:.1f} tok/s")
        if speed_label is not None:
            speed_label.setText(
                f"{tps:.1f} tok/s  |  ~{tok_count} tok  |  {elapsed_s:.1f}s")

    def _get_context_for_gpu(self, idx):
        """Get the configured context size for a GPU."""
        try:
            if idx == 0:
                return self.bb_ctx_spin.value()
            else:
                return self.sb_ctx_spin.value()
        except Exception:
            return 32768

    def _get_model_name_for_gpu(self, idx):
        """Get the model name for a GPU."""
        try:
            from agents.runtime.dual_brain import BrainRole, DualBrainRuntime
            role = BrainRole.BIG if idx == 0 else BrainRole.SMALL
            model_path = self._current_model_path(role == BrainRole.SMALL)
            if model_path:
                # External providers use IDs such as ``qwen/qwen3.5-9b``;
                # only local filesystem selections should be reduced to a
                # filename.
                return os.path.basename(model_path) if os.path.exists(model_path) else model_path
            runtime = self.runtime or DualBrainRuntime.from_env()
            configured = runtime.config(role).model
            if configured:
                return configured
            return "—"
        except Exception:
            return "—"

    def _get_model_vram_for_gpu(self, gpu_index: int) -> dict:
        """Get VRAM estimate for the model assigned to a GPU."""
        try:
            small = gpu_index != 0
            ctx = self.sb_ctx_spin.value() if small else self.bb_ctx_spin.value()
            model_path = self._current_model_path(small)
            if not model_path:
                return {}
            kv_name = (self.sb_kv_combo.currentText() if small else self.bb_kv_combo.currentText()) or "f16"
            key = f"{model_path}|{ctx}|{kv_name}"
            cached = self._vram_estimates.get(key)
            if cached is not None:
                return cached
            if key not in self._vram_estimate_inflight:
                self._vram_estimate_inflight.add(key)
                threading.Thread(
                    target=self._estimate_vram_background,
                    args=(gpu_index, key, model_path, ctx, kv_name),
                    daemon=True,
                ).start()
            return {}
        except Exception:
            return {}

    def _estimate_vram_background(self, gpu_index, key, model_path, context, kv_name):
        """Estimate GGUF memory without reading model metadata on the GUI thread."""
        try:
            from agents.providers.gguf_meta import estimate_vram_gb
            kv_type_bytes = {"f32": 4, "f16": 2, "q8_0": 1,
                             "q4_0": 0.5, "auto": 2}.get(kv_name, 2)
            estimate = estimate_vram_gb(
                model_path, context=context, kv_type_bytes=kv_type_bytes)
            estimate["kv_type"] = kv_name
        except Exception:
            estimate = {}
        self._vram_estimate_ready.emit(gpu_index, key, estimate)

    def _on_vram_estimate_ready(self, gpu_index, key, estimate):
        self._vram_estimate_inflight.discard(key)
        if estimate:
            self._vram_estimates[key] = estimate
            self._render_vram_estimate(gpu_index, estimate)

    def _render_vram_estimate(self, gpu_index, estimate):
        """Update VRAM widgets from an already-computed background result."""
        is_big = gpu_index == 0
        model_vram_gb = estimate.get("total_gb", 0)
        weights_gb = estimate.get("weights_gb", 0)
        kv_gb = estimate.get("kv_gb", 0)
        gpu_total = 14.8 if is_big else 6.0
        if model_vram_gb <= 0:
            return
        gpu_pct = min(100, int((model_vram_gb / gpu_total) * 100))
        if gpu_pct < 80:
            zone_color = "#4caf50"
            status = "✅ Fits in VRAM"
        elif gpu_pct < 95:
            zone_color = "#ff9800"
            status = "⚠️ Close to limit"
        else:
            zone_color = "#ff5252"
            overflow = model_vram_gb - gpu_total
            status = f"⚠️ {overflow:.1f} GB spills to RAM"
        self._set_gpu_bar(gpu_index, "est", gpu_pct, zone_color)
        self._set_gpu_detail(
            gpu_index,
            "est",
            f"Weights: {weights_gb:.1f}GB  KV: {kv_gb:.1f}GB  Total: {model_vram_gb:.1f}GB",
        )
        self._set_gpu_status(gpu_index, status)
        context = self.bb_ctx_spin.value() if is_big else self.sb_ctx_spin.value()
        self._set_gpu_ctx(gpu_index, f"Context: {context:,} tokens")

    def _on_context_changed(self, is_big: bool):
        """Queue VRAM estimation without blocking the Qt thread."""
        try:
            idx = 0 if is_big else 1
            small = not is_big
            estimate = self._get_model_vram_for_gpu(idx)
            if estimate:
                self._render_vram_estimate(idx, estimate)
        except Exception:
            pass
    
    # ═══════════════════════════════════════════════════════════════════
    # PROVIDER CONTROL HANDLERS
    # ═══════════════════════════════════════════════════════════════════
    # ═══════════════════════════════════════════════════════════════════
    # MODEL DROPDOWN REFRESH — query llama-server for available models
    # ═══════════════════════════════════════════════════════════════════
    def _brain_port(self, small: bool) -> int:
        """Resolve the ACTUAL configured port for a brain from the runtime
        (or .env fallback), so the panel never hardcodes 1234/1235 when the
        operator runs llama.cpp on another endpoint/port (v2.1 review fix)."""
        try:
            from agents.runtime.dual_brain import BrainRole
            if self.runtime is not None:
                return int(self.runtime.config(BrainRole.SMALL if small else BrainRole.BIG).port)
            cfg = DualBrainRuntime.from_env().config(BrainRole.SMALL if small else BrainRole.BIG)
            return int(cfg.port)
        except Exception:
            return 1235 if small else 1234

    _PLACEHOLDER_MARKERS = ("⚠️", "Error", "No models found")

    def _resolve_model_path(self, small: bool, combo_text: str) -> str:
        """Return a real .gguf path to launch for a brain, or '' if none.

                Resolution order (first non-placeholder, existing file wins):
          1. combo text IF it is a real model id/path (not a placeholder)
          2. env BIG/SMALL_BRAIN_MODEL
                    3. '' (caller aborts launch with a clear log)
        """
        cands = []
        if combo_text and not combo_text.startswith(self._PLACEHOLDER_MARKERS):
            cands.append(combo_text)
        env_key = "SMALL_BRAIN_MODEL" if small else "BIG_BRAIN_MODEL"
        env_model = os.getenv(env_key, "").strip()
        if env_model:
            cands.append(env_model)
        for c in cands:
            if os.path.exists(c):
                return c
        return ""

    # ── Local .gguf discovery + model dropdown (v2.1) ──────────────────────
    # The model dropdowns previously listed ONLY what the running llama-server
    # reported via /v1/models, which (single-model mode) is just the ONE model
    # currently loaded — so the dropdown never showed the other .gguf files on
    # disk and the user could not switch to them. Now we scan the local model
    # directories for every .gguf and present all of them, storing the full
    # path per item while showing a friendly name.
    _GGUF_SEARCH_DIRS = (r"D:/LMStudio/models", r"D:/llama.cpp")

    @staticmethod
    def _norm_path(p: str) -> str:
        return (p or "").replace("\\", "/").lower()

    def _discover_gguf_models(self) -> list:
        """Scan the local model dirs for standalone .gguf files (skip mmproj).

        Returns full .gguf paths (forward slashes), de-duplicated + sorted.
        mmproj-* files are vision projector companion files, not standalone
        chat models, so they are excluded.
        """
        found = {}
        extra = os.getenv("GGUF_MODELS_DIR", "").strip()
        search = list(self._GGUF_SEARCH_DIRS)
        if extra:
            search.insert(0, extra)
        library_dirs = os.getenv("MODEL_LIBRARY_DIR", "").strip()
        if library_dirs:
            search[0:0] = [item for item in library_dirs.split(os.pathsep) if item]
        for base_str in search:
            base = os.path.abspath(base_str)
            if not os.path.isdir(base):
                continue
            for root, _dirs, files in os.walk(base):
                for fn in files:
                    if not fn.lower().endswith(".gguf"):
                        continue
                    if fn.lower().startswith("mmproj"):
                        continue  # vision projector, not standalone
                    full = os.path.join(root, fn).replace("\\", "/")
                    found[full] = True
        return sorted(found)

    def _model_combo(self, small: bool):
        """The Settings model combo for a role, or None when it doesn't exist.

        Model selection moved to Provider Control (one place for all devices),
        so the old per-role Settings combo may be absent. Callers must handle
        None (see _current_model_path, which falls back to the runtime config).
        """
        return getattr(self, "sb_model_combo" if small else "bb_model_combo", None)

    def _current_model_path(self, small: bool) -> str:
        """Full .gguf path behind the dropdown's current item (UserRole).

        Falls back to the runtime config's model when the Settings combo is
        absent (model selection now lives in Provider Control)."""
        combo = self._model_combo(small)
        if combo is not None and combo.count() > 0:
            data = combo.itemData(combo.currentIndex())
            if data:
                return str(data)
            return combo.currentText()
        # No Settings combo: read the model from the runtime config.
        try:
            from agents.runtime.dual_brain import BrainRole, DualBrainRuntime
            runtime = self.runtime or DualBrainRuntime.from_env()
            cfg = runtime.config(BrainRole.SMALL if small else BrainRole.BIG)
            return cfg.model or ""
        except Exception:
            return ""

    def _set_settings_combo_model(self, small: bool, model_path: str):
        """Select ``model_path`` in the hidden Settings model combo (slots 0/1).

        Adds it if missing and selects it, blocking signals so we don't fire the
        model-change handler (which would re-persist / restart). Keeps the hidden
        backing store in sync with the Provider Control selection so
        _snapshot_settings_values persists the same choice.
        """
        combo = self._model_combo(small)
        if combo is None:
            return
        combo.blockSignals(True)
        try:
            target_norm = self._norm_path(model_path)
            # Find or add the item.
            idx = -1
            for i in range(combo.count()):
                if self._norm_path(combo.itemData(i) or "") == target_norm:
                    idx = i
                    break
            if idx < 0 and model_path:
                import os
                combo.addItem(os.path.basename(model_path), model_path)
                idx = combo.count() - 1
            if idx >= 0:
                combo.setCurrentIndex(idx)
            elif not model_path:
                combo.setCurrentIndex(0)  # "Select a model..."
        finally:
            combo.blockSignals(False)

    def _repopulate_model_combo(self, small: bool, loaded_path: str = "", models=None):
        """Fill a brain's dropdown with ALL local .gguf (display name, full path
        in item data).

        Selection policy: GUI combo is the SOURCE OF TRUTH. A role remains
        unselected until the user chooses a model or an explicit saved value
        selects one. A running model is shown in the list but never silently
        becomes the next launch selection.
        """
        combo = self._model_combo(small)
        if combo is None:
            # Settings model combo removed (model selection lives in Provider
            # Control). Nothing to repopulate here.
            return
        prev = self._current_model_path(small)  # what the user has selected (may be "")
        prev_norm = self._norm_path(prev)
        from agents.runtime.dual_brain import BrainRole, DualBrainRuntime
        runtime = self.runtime or DualBrainRuntime.from_env()
        cfg = runtime.config(BrainRole.SMALL if small else BrainRole.BIG)
        external = cfg.provider != "llamacpp"
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem("Select a model...", "")
            paths = list(models or []) if external else self._discover_gguf_models()
            if cfg.model and cfg.model not in paths:
                paths.insert(0, cfg.model)
            if loaded_path and self._norm_path(loaded_path) not in {self._norm_path(p) for p in paths}:
                paths.insert(0, loaded_path)  # running model not under scanned dirs
            # Keep an existing user selection or explicit saved model only.
            target_norm = ""
            if prev_norm and prev_norm in {self._norm_path(p) for p in paths}:
                target_norm = prev_norm
            elif cfg.model and self._norm_path(cfg.model) in {self._norm_path(p) for p in paths}:
                target_norm = self._norm_path(cfg.model)
            select = -1
            for i, p in enumerate(paths):
                combo.addItem(p if external else os.path.basename(p), p)
                if self._norm_path(p) == target_norm:
                    select = i + 1
            if target_norm:
                # Suppress model-change auto-restart during programmatic selection
                self._suppress_model_change_restart = True
                combo.setCurrentIndex(select)
                self._suppress_model_change_restart = False
            else:
                combo.setCurrentIndex(0)
        finally:
            combo.blockSignals(False)

    def _restart_brain_with(self, small: bool, model_path: str):
        """Stop a running brain (force) and relaunch it with the given model.

        The combo is already pointing at ``model_path`` (user selection), so we
        only force-stop and restart; guards against recursion on the model-changed
        signal by not mutating the combo here.

        v2.1 fix: runs on a background thread so the GUI never blocks while
        the model loads into VRAM/RAM. Shows a loading indicator instead.
        """
        label = "Small Brain" if small else "Big Brain"
        port = self._brain_port(small)

        # Show loading indicator
        self._set_loading(small, True, model_path)
        self._log(f"♻️ Switching {label} model to {os.path.basename(model_path)}...")

        # Run restart on background thread
        import threading
        t = threading.Thread(
            target=self._do_restart,
            args=(small, model_path, port, label),
            daemon=True,
        )
        t.start()

    def _do_restart(self, small: bool, model_path: str, port: int, label: str):
        """Background restart logic."""
        try:
            self._force_stop_brain(small)
            # Wait until the port is actually free
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                running, _ = self.provider_checker.check_llama_server(port, timeout=1)
                if not running:
                    break
                time.sleep(0.3)
            # All Qt widget and QThread operations must happen on the GUI
            # thread. The worker only stops the old process and waits for the
            # port to become available.
            self._restart_ready.emit(small)
        except Exception as e:
            self._log(f"❌ Failed to switch {label} model: {e}")

            # ARCH-ENG-182: THIS RAN ON A RAW `threading.Thread`, NOT ON THE QT
            # THREAD. `_do_restart` is started with `threading.Thread` (see
            # `_restart_brain_with`), so it has NO Qt event loop.
            # `QTimer.singleShot(0, ...)` from such a thread posts a timer event
            # to a loop that does not exist: the callback may never run, and the
            # brain row is left stuck at "Loading…" with no error anywhere — the
            # operator's model switch silently did nothing.
            #
            # The fix marshals the GUI update through a Qt signal, which Qt
            # queues onto the GUI thread for us, instead of calling a widget
            # method (or a timer) directly from a worker.
            self._clear_loading_on_gui_thread(small)

    def _on_loading_clear_requested(self, small: bool) -> None:
        """ARCH-ENG-182: GUI-thread handler for a worker's loading-clear request.

        Runs on the Qt thread because the signal is emitted from a worker and
        this object's thread affinity is the GUI thread, so the connection is
        queued. Guarded because the widget can be mid-teardown.
        """
        if getattr(self, "_closing", False):
            return
        try:
            self._set_loading(bool(small), False, "")
        except RuntimeError:
            pass

    def _clear_loading_on_gui_thread(self, small: bool) -> None:
        """Clear a brain row's Loading state, always on the Qt thread.

        ARCH-ENG-182. Safe to call from a worker thread, from the GUI thread, or
        mid-teardown: it only emits a signal connected to a plain Qt slot, so Qt
        performs the queued hand-off. Emitting from a non-GUI thread to a slot on
        a GUI object is a queued connection, which is exactly the required
        behaviour — unlike `QTimer.singleShot` from the same thread.
        """
        try:
            self._loading_clear_requested.emit(bool(small))
        except RuntimeError:
            pass          # the underlying C++ object is gone; nothing to do

    def _continue_model_restart(self, small: bool):
        """Continue a model restart on the Qt GUI thread."""
        if small:
            self._on_start_small_brain()
        else:
            self._on_start_big_brain()

    def _row_for_slot(self, slot: int):
        """Return the BrainControlRow for *slot*, or None if not rendered.

        v2.1.53 (ARCH-ENG-053): with a brain disabled (e.g. CPU unchecked on a
        single-GPU box) only the enabled brain's row exists, so the legacy
        sb_*/bb_* aliases are absent. Callers that update a brain's status must
        resolve the row by slot and no-op when it isn't rendered, instead of
        touching a missing alias and raising AttributeError (which aborted the
        start flow).
        """
        for row in getattr(self, "_provider_rows", []) or []:
            if getattr(row, "slot", None) == slot:
                return row
        return None

    def _set_loading(self, small: bool, loading: bool, model_path: str):
        """Show/hide loading indicator for a brain."""
        label = "Small Brain" if small else "Big Brain"
        slot = 1 if small else 0
        idx = 0 if small else 1  # GPU-card detail index (unchanged legacy mapping)
        if loading:
            self._log(f"⏳ {label}: loading {os.path.basename(model_path)} into VRAM...")
            # Update the brain's row status to show loading. Resolve by slot so a
            # disabled/missing brain is a no-op instead of an AttributeError.
            row = self._row_for_slot(slot)
            if row is not None:
                row.status.setText("● Loading...")
                row.status.setStyleSheet("color: #ffb300; font-weight: bold;")
                row.start_btn.setEnabled(False)
                row.stop_btn.setEnabled(False)

            # Do not parse GGUF metadata here. Large model files can make that
            # operation expensive, and this method runs on the Qt thread.
            # GPUStatusWorker will update actual usage while the server loads.
            self._set_gpu_detail(idx, "est", f"Loading {os.path.basename(model_path)}...")
            self._set_gpu_detail(idx, "act", "Loading...")
            self._set_gpu_detail(idx, "kv", "Loading...")
        else:
            row = self._row_for_slot(slot)
            if row is not None:
                row.status.setText("● Checking...")
                row.status.setStyleSheet("color: #ffb300; font-weight: bold;")
            # Refresh status on the Qt event loop. A threading.Timer would call
            # QWidget methods from a Python worker thread and can leave the
            # visible state stuck at Loading even after llama-server is ready.
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1000, self._refresh_provider_status)

    def _force_stop_brain(self, small: bool):
        """Terminate a brain's server process regardless of who started it.

        Stops the exact child we spawned if we have a live handle; otherwise (server
        was started outside this panel, e.g. a previous run / scripts) it kills the
        process listening on the brain's port. We never rely on WINDOWTITLE matching,
        which fails for CREATE_NO_WINDOW servers (v2.0.36s fix).
        """
        attr = "_small_server_process" if small else "_big_server_process"
        flag = "we_started_small" if small else "we_started_big"
        proc = getattr(self, attr, None)
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
            except Exception:
                pass
        # ALWAYS sweep the port too: a duplicate llama-server (SO_REUSEADDR lets
        # two bind one port) or a stale server from a prior run can share it, and
        # killing only the tracked child left the extra one listening — the "one
        # server stays open after Stop" bug. _kill_llama_on_port kills every PID
        # bound to the port.
        self._kill_llama_on_port(self._brain_port(small))
        setattr(self, attr, None)
        setattr(self, flag, False)

    def _pids_on_port(self, port: int):
        """Every PID LISTENING on `port`, de-duplicated.

        ARCH-ENG-187: delegates to the ONE shared implementation in
        `device_registry`. This copy and `check_llama_process` each had their own
        version, and they had already drifted apart — one filtered for
        `llama-server.exe`, the other for `llama.exe`, so each was wrong about a
        case the other got right. A port's occupancy is a system fact; it does
        not need to be re-derived per caller.
        """
        from agents.runtime.device_registry import pids_listening_on
        return pids_listening_on(port)

    def _process_image_name(self, pid: int) -> str:
        """Lower-cased executable name for `pid`, or "" if it cannot be read.

        ARCH-ENG-171/187: used to decide whether a PID bound to a brain port is
        one of OUR llama-server processes and may therefore be killed.
        """
        from agents.runtime.device_registry import process_image_name
        return process_image_name(pid)

    @staticmethod
    def _is_llama_image(image_name: str) -> bool:
        """True only for a llama.cpp server image.

        ARCH-ENG-171/187: delegates to the shared predicate. Deliberately
        narrow — the app spawns `llama-server.exe`, `llama.exe` is the legacy
        alias some launcher scripts produce, and nothing else is accepted. The
        whole point is that a port alone does not identify a process we own.
        """
        from agents.runtime.device_registry import is_llama_server_image
        return is_llama_server_image(image_name)

    def _kill_llama_on_port(self, port: int):
        """Kill every LLAMA-SERVER process listening on 127.0.0.1:<port>.

        Works for servers this panel started (CREATE_NO_WINDOW servers have no
        matching window title) AND removes duplicate/stale instances that share
        the port — a single-PID kill left the extra server running, which is
        why "Stop" appeared to leave one open.

        ARCH-ENG-171: THIS USED TO KILL *ANY* PROCESS ON THE PORT.

        There was no image-name verification, so the port was treated as proof
        of ownership. That is not true here: `ProviderManager._detect_lm_studio`
        defaults to `http://127.0.0.1:1234/v1`, and 1234 IS the Big Brain port
        (`agents/runtime/dual_brain.py` ROLE_DEFAULTS). An operator running LM
        Studio — or anything else that grabbed 1234 first — had it force-killed
        by pressing Stop on a brain, with no warning and no way to tell why.

        It was also called for servers this app explicitly ADOPTED and promised
        not to manage (`brain_launch_worker` sets `we_started_* = False` for
        those, precisely so Stop would leave them alone).

        Now: a PID is killed only if its image name is a llama.cpp server. An
        unrecognised listener is reported and left running, because destroying
        a stranger's process is far worse than leaving a port occupied — and the
        message tells the operator which PID is in the way.

        `netstat` also reports a listener twice for some addresses (`0.0.0.0:`
        and `[::]:` on v4+v6), so PIDs are de-duplicated before any kill; a
        repeated kill of the same PID is both wasteful and can race.
        """
        killed = []
        skipped = []
        seen = set()
        for pid in self._pids_on_port(port):
            if pid in seen:
                continue          # netstat reports v4 and v6 rows for one socket
            seen.add(pid)
            image = self._process_image_name(pid)
            if not self._is_llama_image(image):
                skipped.append((pid, image or "unknown"))
                continue
            try:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True, text=True, timeout=5,
                    encoding="utf-8", errors="replace",
                    creationflags=subprocess.CREATE_NO_WINDOW)
                killed.append(pid)
            except Exception:
                pass
        if skipped:
            detail = ", ".join(f"PID {p} ({i})" for p, i in skipped)
            self._log(
                f"Port {port} is held by a process that is not a llama-server: "
                f"{detail}. Left running — press Stop again once the port is "
                f"free, or stop that process yourself."
            )
        return killed

    def _brain_models_url(self, small: bool) -> str:
        """Full /v1/models URL for a brain, from the configured endpoint."""
        try:
            from agents.runtime.dual_brain import BrainRole
            if self.runtime is not None:
                mpath = self.runtime.config(BrainRole.SMALL if small else BrainRole.BIG).models_path
                return mpath if mpath else f"http://127.0.0.1:{self._brain_port(small)}/v1/models"
            cfg = DualBrainRuntime.from_env().config(BrainRole.SMALL if small else BrainRole.BIG)
            return cfg.models_path or f"http://127.0.0.1:{self._brain_port(small)}/v1/models"
        except Exception:
            return f"http://127.0.0.1:{self._brain_port(small)}/v1/models"

    def _log(self, message):
        """Append a timestamped message to the provider event log.

        Safe to call from any thread: when invoked off the GUI thread the widget
        update is marshalled through `_log_requested` so it happens on the GUI
        thread (touching a QWidget from another thread is undefined behaviour and
        caused intermittent freezes / access violations).
        """
        if QThread.currentThread() is self.thread():
            self._append_log_line(message)
        else:
            self._log_requested.emit(str(message))

    def _append_log_line(self, message):
        """GUI-thread slot: append one line and keep the view scrolled to the end."""
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_display.append(f"[{ts}] {message}")
        scrollbar = self.log_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _record_start_failure(self, phase: str, error: Exception):
        """Persist start failures when Qt cannot deliver the visible log entry."""
        try:
            path = os.path.join(tempfile.gettempdir(), "mrbot-dual-brain-crash.log")
            with open(path, "a", encoding="utf-8", errors="replace") as report:
                report.write(f"\n[{datetime.now().isoformat()}] {phase}: {error!r}\n")
                report.write(traceback.format_exc())
        except Exception:
            pass

    def cleanup(self):
        """Stop and join provider workers before this control is destroyed."""
        self._closing = True
        # ARCH-ENG-153: flush any debounced roster edit before teardown. The
        # panel's only writer is a 400 ms single-shot timer, and closing the
        # window stops the event loop before it fires — so an edit made in the
        # last moments was silently discarded on every exit.
        try:
            from gui.widgets.brain_roster_panel import flush_pending_roster_edit
            flush_pending_roster_edit(getattr(self, "brain_roster_panel", None))
        except Exception:
            pass
        # v2.1.60 (ARCH-ENG-073): stop the periodic provider-status poller so it
        # doesn't fire after teardown (probing dead ports on a destroyed widget).
        status_timer = getattr(self, "_status_timer", None)
        if status_timer is not None:
            try:
                status_timer.stop()
            except RuntimeError:
                pass
        probe_thread = getattr(self, "_provider_probe_thread", None)
        if probe_thread is not None and probe_thread.is_alive():
            probe_thread.join(3000)
        # Stop every GPU polling thread, not just the current reference: a model
        # restart can replace self.gpu_worker while an older instance keeps
        # running, and a QThread still alive at interpreter teardown aborts the
        # process (access violation / exit 139).
        for worker in self._all_gpu_workers():
            try:
                if worker.isRunning():
                    worker.stop()
                    worker.wait(7000)
            except RuntimeError:
                pass
        for name in (
            "_small_probe_worker", "_big_probe_worker",
            "_small_stop_worker", "_big_stop_worker",
            "_small_launch_worker", "_big_launch_worker",
            # ARCH-ENG-181: the prep workers were missing from this list. They
            # are QThreads that do GGUF inspection before a launch, so one left
            # running at teardown aborts the process with the access-violation /
            # exit-139 class this method exists to prevent.
            "_small_prep_worker", "_big_prep_worker",
            # ...and so are the per-slot launch workers for extra devices
            # (slots 2+ in the N-brain roster), which had no teardown at all.
            *self._slot_launch_worker_names(),
        ):
            worker = getattr(self, name, None)
            try:
                if worker is not None and worker.isRunning():
                    if hasattr(worker, "stop"):
                        worker.stop()
                    worker.wait(3000)
            except RuntimeError:
                pass

        # ARCH-ENG-181: CALL THE BACKEND'S cleanup.
        #
        # `DualBrainControl(ProviderLifecycleBackend, QWidget)` mixes the backend
        # in as a base class, and `ProviderLifecycleBackend.cleanup` holds the
        # carefully-ordered teardown (closing flag FIRST so callbacks stop
        # re-arming, probe-thread join, then every worker). This override
        # shadowed it and never called `super()`, so NONE of that ran for the
        # widget — the one case that matters. The base class docstring is
        # explicit about the failure it prevents: "letting that escape would
        # abort teardown and leave the remaining threads running".
        #
        # Ordering: this method's own work runs first (it stops the widget's
        # poller and flushes the roster edit), then the base class performs the
        # full worker teardown. `_closing` is already set above, so the base
        # class's re-set is idempotent.
        try:
            super().cleanup()
        except Exception:
            pass

    def _all_gpu_workers(self):
        """Return every live GPUStatusWorker this control has ever started.

        Tracked in a WeakSet so replaced pollers are still stopped (they would
        otherwise outlive the widget and crash Qt at exit) without leaking.
        """
        import weakref
        workers = getattr(self, "_gpu_workers", None)
        if workers is None:
            workers = weakref.WeakSet()
            self._gpu_workers = workers
        current = getattr(self, "gpu_worker", None)
        if current is not None:
            workers.add(current)
        return list(workers)

    def _slot_launch_worker_names(self):
        """ARCH-ENG-181: attribute names of every per-slot LAUNCH worker.

        The N-brain roster stores extra devices' launchers as
        `_slot_{n}_launch_worker` (set in `ProviderLifecycleBackend._launch_slot`).
        Those QThreads had NO teardown at all, so an extra brain's launcher could
        still be running when Qt destroyed the widget — the "QThread: Destroyed
        while thread is still running" abort this method exists to prevent.

        Discovered by scanning instance attributes rather than a fixed list, so a
        slot added later is covered automatically.
        """
        import re as _re
        try:
            names = list(vars(self))
        except TypeError:
            return []
        return [n for n in names
                if _re.fullmatch(r"_slot_\d+_launch_worker", n)]


# Preserve the historical test/import surface while callers migrate to the
# explicit facade methods. This compatibility assignment can be removed after
# usage-ledger and import-boundary checks show no legacy access.
for _compat_name in (
    "_persist_role_model",
    "_on_small_brain_model_changed",
    "_on_big_brain_model_changed",
):
    setattr(BrainLaunchWorker, _compat_name,
            getattr(ProviderLifecycleBackend, _compat_name))


# ═══════════════════════════════════════════════════════════════════════════
# REMOVAL INSTRUCTIONS
# ═══════════════════════════════════════════════════════════════════════════
# To completely remove the Dual Brain feature:
#
# 1. DELETE: gui/dual_brain_control.py
# 2. DELETE: gui/chat_tab.py, gui/dialogue_tab.py
# 3. DELETE: agents/big_brain.py, agents/small_brain.py
# 4. DELETE: prompts/big_brain.txt, prompts/small_brain.txt
# 5. DELETE: scripts/start_small_brain_llamacpp.ps1, scripts/start_big_brain_llamacpp.ps1
# 6. EDIT: gui/tab_builders.py — remove create_dual_brain_tab(),
#          create_chat_tab(), create_dialogue_tab()
# 7. EDIT: main.py — remove "Chat" and "Dialogue" from tab_specs
# 8. EDIT: settings.json — remove lm_studio provider (optional)
# 9. EDIT: .env — remove dual brain env vars (optional)
# ═══════════════════════════════════════════════════════════════════════════
