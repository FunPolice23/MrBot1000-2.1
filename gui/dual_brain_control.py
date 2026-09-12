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
    QComboBox,
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
    
    def _get_gpu_status(self):
        """Get GPU status via nvidia-smi."""
        gpus = []
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 5:
                        gpus.append({
                            "index": int(parts[0]),
                            "name": parts[1],
                            "memory_used_mb": int(parts[2]),
                            "memory_total_mb": int(parts[3]),
                            "utilization": int(parts[4])
                        })
        except Exception:
            pass  # parsing is best-effort; return empty list on any error
        return gpus
    
    def stop(self):
        """Stop the polling loop."""
        self.running = False
        self.requestInterruption()


# ═══════════════════════════════════════════════════════════════════════════
# PROVIDER STATUS CHECKER — Detects running llama-server instances
# ═══════════════════════════════════════════════════════════════════════════
class ProviderStatusChecker:
    """Check if llama-server instances are running."""

    _cache = {}
    _cache_lock = threading.Lock()
    _cache_ttl = float(os.getenv("DUAL_BRAIN_PROBE_CACHE_S", "2"))
    
    @staticmethod
    def check_llama_server(port=1234, timeout=10, refresh=False):
        """Check if llama-server is running on the given port."""
        now = time.monotonic()
        if not refresh:
            with ProviderStatusChecker._cache_lock:
                cached = ProviderStatusChecker._cache.get(port)
            if cached and now - cached[0] < ProviderStatusChecker._cache_ttl:
                return cached[1]
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/models")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
                # llama.cpp releases have returned either OpenAI-compatible
                # ``data`` or a ``models`` list (some versions include both).
                # Accept both so a healthy server is not shown as offline merely
                # because its response shape changed.
                result = True, ProviderStatusChecker.extract_model_ids(data)
        except Exception:
            result = False, []  # network check is best-effort
        with ProviderStatusChecker._cache_lock:
            ProviderStatusChecker._cache[port] = (time.monotonic(), result)
        return result

    @staticmethod
    def check_endpoint(url, timeout=10):
        """Check an OpenAI-compatible provider endpoint and return its models."""
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
            return True, ProviderStatusChecker.extract_model_ids(data)
        except Exception:
            return False, []

    @staticmethod
    def _provider_root(endpoint):
        return str(endpoint or "").rstrip("/").removesuffix("/v1")

    @classmethod
    def check_loaded_provider(cls, provider, endpoint, timeout=5):
        """Return (server_available, loaded_models) for controllable providers."""
        root = cls._provider_root(endpoint)
        try:
            if provider == "lmstudio":
                url = f"{root}/api/v1/models"
                with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as resp:
                    data = json.loads(resp.read().decode())
                loaded = []
                for model in data.get("models", []):
                    key = model.get("key", "")
                    if key and model.get("loaded_instances"):
                        loaded.append(key)
                return True, loaded
            if provider == "ollama":
                url = f"{root}/api/ps"
                with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as resp:
                    data = json.loads(resp.read().decode())
                return True, [m.get("name") or m.get("model", "") for m in data.get("models", [])]
        except Exception:
            return False, []
        return False, []

    @classmethod
    def load_provider_model(cls, provider, endpoint, model, timeout=30):
        root = cls._provider_root(endpoint)
        if provider == "lmstudio":
            url, body = f"{root}/api/v1/models/load", {"model": model}
        elif provider == "ollama":
            url, body = f"{root}/api/generate", {"model": model, "stream": False}
        else:
            return False, f"{provider} does not expose a model-load API"
        return cls._post_json(url, body, timeout)

    @classmethod
    def unload_provider_model(cls, provider, endpoint, model="", timeout=30):
        root = cls._provider_root(endpoint)
        if provider == "lmstudio":
            loaded_ok, loaded = cls.check_loaded_provider(provider, endpoint, timeout=5)
            if not loaded_ok:
                return False, "LM Studio loaded-model list is unavailable"
            for instance_id in loaded:
                if not model or instance_id == model:
                    ok, message = cls._post_json(
                        f"{root}/api/v1/models/unload", {"instance_id": instance_id}, timeout)
                    if not ok:
                        return False, message
            return True, "unloaded"
        if provider == "ollama":
            if not model:
                return False, "Ollama requires a model name to unload"
            return cls._post_json(
                f"{root}/api/generate", {"model": model, "keep_alive": 0}, timeout)
        return False, f"{provider} does not expose a model-unload API"

    @staticmethod
    def _post_json(url, body, timeout):
        try:
            payload = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(
                url, data=payload, method="POST",
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return True, resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def clear_cache(port=None):
        """Invalidate one port or all cached provider probes."""
        with ProviderStatusChecker._cache_lock:
            if port is None:
                ProviderStatusChecker._cache.clear()
            else:
                ProviderStatusChecker._cache.pop(port, None)

    @staticmethod
    def extract_model_ids(data):
        """Normalize llama.cpp model-list variants to displayable IDs."""
        if isinstance(data.get("result"), str) and data["result"]:
            return [data["result"]]
        raw_models = data.get("data") or data.get("models") or []
        result = []
        for item in raw_models:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                result.append(item.get("id") or item.get("name") or item.get("model") or "unknown")
        return result
    
    @staticmethod
    def check_llama_process(port=None):
        """Check if llama-server process is running."""
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq llama.exe", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return "llama.exe" in result.stdout
        except Exception:
            return False


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
    
    def eventFilter(self, obj, event):
        # Block wheel events when dropdown is not open
        if event.type() == event.Type.Wheel and not self.combo.view().isVisible():
            return True  # Event handled — block it
        return False  # Pass through


class DualBrainControl(QWidget):
    """Control panel for dual-brain GPU orchestration."""

    _restart_ready = Signal(bool)
    
    # Signals emitted when model changes
    small_brain_model_changed = Signal(str)  # model_name
    big_brain_model_changed = Signal(str)    # model_name
    provider_probed = Signal(object)         # dict from background provider probe
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

        # Provider checkers
        self.provider_checker = ProviderStatusChecker()
        self.vram_warning_requested.connect(self._show_vram_warning)
        
        # Initialize provider manager for dynamic provider/GPU detection
        from agents.provider_manager import ProviderManager
        self.provider_manager = ProviderManager.instance()
        self.provider_manager.detect_providers()
        
        # Track which providers we started (vs already running)
        self.we_started_small = False
        self.we_started_big = False
        self._closing = False
        self._provider_probe_thread = None

        # Guard against auto-restart loops from probe-triggered combo changes
        self._suppress_model_change_restart = False

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
        
        # Build dynamic provider panels
        self._build_provider_panels()

    def _build_provider_panels(self):
        """Build provider-specific configuration panels with failover support."""
        from agents.provider_manager import ProviderManager, ProviderStatus
        
        pm = self.provider_manager
        providers = pm.get_providers()
        gpus = pm.get_gpus()
        
        # Create provider selection panel
        if hasattr(self, 'provider_group'):
            # Clear existing widgets
                pass
        
        # Build provider selection UI
        self.provider_panels = {}
        
        for name, provider in providers.items():
            panel = self._create_provider_panel(name, provider, gpus)
            self.provider_panels[name] = panel
    
    def _create_provider_panel(self, name, provider, gpus):
        """Create a configuration panel for a specific provider."""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background: #1a1a1a;
                border: 2px solid #333;
                border-radius: 8px;
                padding: 8px;
            }}
        """)
        layout = QVBoxLayout(frame)
        
        # Provider header
        header = QHBoxLayout()
        status_color = "#4caf50" if provider.status == "running" else "#ff5252" if provider.status == "stopped" else "#ff9800"
        status_label = QLabel(f"● {provider.name}")
        status_label.setStyleSheet(f"color: {status_color}; font-weight: bold; font-size: 12px;")
        header.addWidget(status_label)
        
        header.addStretch()
        
        # GPU assignment
        if provider.is_local and gpus:
            gpu_combo = QComboBox()
            gpu_combo.addItem("Auto", -1)
            for gpu in gpus:
                gpu_combo.addItem(f"GPU {gpu.index}: {gpu.name}", gpu.index)
            gpu_combo.setCurrentIndex(provider.gpu_index + 1)
            gpu_combo.currentIndexChanged.connect(lambda idx, n=name: self._on_gpu_assignment_changed(n, idx - 1))
            header.addWidget(QLabel("GPU:"))
            header.addWidget(gpu_combo)
        
        layout.addLayout(header)
        
        # Model selection
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("Model:"))
        model_combo = QComboBox()
        model_combo.setEditable(True)
        if provider.models:
            model_combo.addItems(provider.models)
        if provider.selected_model:
            model_combo.setCurrentText(provider.selected_model)
        model_combo.currentTextChanged.connect(lambda text, n=name: self._on_model_changed(n, text))
        model_layout.addWidget(model_combo, stretch=1)
        layout.addLayout(model_layout)
        
        # Provider-specific settings
        if provider.is_cloud:
            # Cloud provider settings
            settings_layout = QHBoxLayout()
            settings_layout.addWidget(QLabel("Context:"))
            ctx_spin = QSpinBox()
            ctx_spin.setRange(1048576, 1048576)
            ctx_spin.setValue(provider.context_size)
            ctx_spin.valueChanged.connect(lambda val, n=name: self._on_context_changed(n, val))
            settings_layout.addWidget(ctx_spin)
            layout.addLayout(settings_layout)
        else:
            # Local provider settings
            settings_layout = QGridLayout()
            settings_layout.addWidget(QLabel("Context:"), 0, 0)
            ctx_spin = QSpinBox()
            ctx_spin.setRange(2048, 524288)
            ctx_spin.setValue(provider.context_size)
            ctx_spin.valueChanged.connect(lambda val, n=name: self._on_context_changed(n, val))
            settings_layout.addWidget(ctx_spin, 0, 1)
            layout.addLayout(settings_layout)
        
        return frame
    
    def _on_gpu_assignment_changed(self, provider_name, gpu_index):
        """Handle GPU assignment change."""
        self.provider_manager.assign_provider_to_gpu(provider_name, gpu_index)
        self._log(f"Assigned {provider_name} to GPU {gpu_index}")
    
    def _on_model_changed(self, provider_name, model_name):
        """Handle model selection change."""
        provider = self.provider_manager.get_provider(provider_name)
        if provider:
            provider.selected_model = model_name
            values = {
                "BIG_BRAIN_MODEL": model_name,
                "SMALL_BRAIN_MODEL": model_name,
            }
            os.environ.update(values)
            try:
                from main import set_env_values
                set_env_values(values)
            except Exception:
                pass
            self._log(f"Selected model {model_name} for {provider_name}")
    
    def _on_context_changed(self, provider_name, context_size):
        """Handle context size change."""
        provider = self.provider_manager.get_provider(provider_name)
        if provider:
            provider.context_size = context_size

    def _wire_start_stop_buttons(self):
        """Wire up start/stop buttons after class body is fully defined.

        The handler methods (_on_start_small_brain, _on_stop_small_brain,
        _on_start_big_brain, _on_stop_big_brain) are defined later in the
        class body. During __init__ -> setup_ui(), they don't exist yet.
        Defer wiring to the next event-loop cycle where they're guaranteed
        to be available.
        """
        if hasattr(self, "sb_start_btn"):
            self.sb_start_btn.clicked.connect(self._on_start_small_brain)
        if hasattr(self, "sb_stop_btn"):
            self.sb_stop_btn.clicked.connect(self._on_stop_small_brain)
        if hasattr(self, "bb_start_btn"):
            self.bb_start_btn.clicked.connect(self._on_start_big_brain)
        if hasattr(self, "bb_stop_btn"):
            self.bb_stop_btn.clicked.connect(self._on_stop_big_brain)

    def _wire_refresh_buttons(self):
        """Wire up refresh/model buttons after class body is fully defined."""
        if hasattr(self, "sb_refresh_models_btn"):
            self.sb_refresh_models_btn.clicked.connect(self._refresh_small_brain_models)
        if hasattr(self, "bb_refresh_models_btn"):
            self.bb_refresh_models_btn.clicked.connect(self._refresh_big_brain_models)

    def _apply_hardware_preset(self):
        """Apply editable values for the selected hardware tier."""
        preset = HARDWARE_PRESETS[self.hardware_preset_combo.currentText()]
        for prefix, values in (("sb", preset["small"]), ("bb", preset["big"])):
            ctx, batch, threads, gpu_layers, kv = values
            getattr(self, f"{prefix}_ctx_spin").setValue(ctx)
            getattr(self, f"{prefix}_batch_spin").setValue(batch)
            getattr(self, f"{prefix}_threads_spin").setValue(threads)
            getattr(self, f"{prefix}_gpu_layers_spin").setValue(gpu_layers)
            getattr(self, f"{prefix}_kv_combo").setCurrentText(kv)
        self.hardware_preset_help.setText(
            preset["help"] + " Click Save to write these values.")

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

    def _get_fallback_provider(self, exclude_provider=None):
        """Get a fallback provider for failover."""
        from agents.provider_manager import ProviderStatus
        
        providers = self.provider_manager.get_providers()
        
        # Priority: local running > cloud running > local stopped
        for name, provider in providers.items():
            if name == exclude_provider:
                continue
            if provider.status == ProviderStatus.RUNNING:
                return name
        
        # Try cloud providers
        for name, provider in providers.items():
            if name == exclude_provider:
                continue
            if provider.is_cloud and provider.status == ProviderStatus.RUNNING:
                return name
        
        return None
    
    def _failover_to_cloud(self, failed_provider):
        """Failover from failed local provider to cloud."""
        fallback = self._get_fallback_provider(failed_provider)
        if fallback:
            self._log(f"⚠️ {failed_provider} failed, failing over to {fallback}")
            # Update UI to reflect failover
            self._apply_provider_status({
                f"{failed_provider}_running": False,
                f"{fallback}_running": True,
            })
        else:
            self._log(f"❌ {failed_provider} failed, no fallback available!")

    def _apply_runtime(self):
        """Seed ctx spins + endpoint labels from the canonical runtime (if any)."""
        if self.runtime is None:
            return
        from agents.dual_brain_runtime import BrainRole
        try:
            small = self.runtime.config(BrainRole.SMALL)
            big = self.runtime.config(BrainRole.BIG)
            active_local = self.provider_manager.resolve_enabled_provider(local=True)
            local_settings = getattr(self, "local_settings_group", None)
            if local_settings is not None:
                is_llamacpp = active_local == "llamacpp"
                local_settings.setVisible(is_llamacpp and any(
                    cfg.enabled and cfg.provider == "llamacpp" for cfg in (small, big)))
                local_settings.setTitle(
                    "⚙️ llama.cpp Settings (per brain)" if is_llamacpp
                    else f"⚙️ {active_local or 'No local provider'} Settings")
            detected_gpus = {
                gpu.index: gpu.name for gpu in self.provider_manager.get_gpus()
            }
            if small.device in detected_gpus:
                small.gpu_label = detected_gpus[small.device]
            elif small.provider == "llamacpp" and small.gpu_layers is None:
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
                    self.sb_gpu_layers_spin.setValue(small.gpu_layers if small.gpu_layers is not None else -1)
                if getattr(self, "bb_gpu_layers_spin", None) is not None:
                    self.bb_gpu_layers_spin.setValue(big.gpu_layers if big.gpu_layers is not None else -1)
            except Exception:
                pass
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
            # Route + GPU-contention guidance (v2.1): state which provider serves
            # which role and flag broken isolation so the operator can disable a
            # provider or split main/chat across GPUs.
            try:
                active_cloud = os.getenv("ACTIVE_CLOUD_PROVIDER", "").strip()
                if active_local:
                    route_provider_name = provider_names.get(active_local, active_local)
                    route = (
                        f"Route: Marcus → {route_provider_name} / "
                        f"{big.model or 'auto model'} / {big.gpu_label} · "
                        f"Alex → {route_provider_name} / "
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
        except Exception:
            pass  # runtime seeding is best-effort; never break the panel

    def _persist_settings(self):
        """Persist the llama.cpp customization values to `.env` (v2.1).

        Writes the per-brain ctx / gpu-layers / split / threads / batch / kv-cache
        keys so the runtime and next launch pick them up. Uses the lock-resilient
        set_env_values from main.py when available; never raises.
        """
        try:
            def _spin(name, default="0"):
                w = getattr(self, name, None)
                return str(w.value()) if w is not None else os.getenv(name.upper().replace("sb_", "SMALL_BRAIN_").replace("bb_", "BIG_BRAIN_").replace("_spin", "").replace("_combo", ""), default)

            values = {
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
            }
            try:
                from main import set_env_values
                set_env_values(values)
            except Exception:
                # Fallback: write directly to .env lines (idempotent).
                import pathlib
                env_path = pathlib.Path(__file__).resolve().parent.parent / ".env"
                lines = []
                existing = {}
                if env_path.exists():
                    for ln in env_path.read_text(encoding="utf-8").splitlines():
                        if "=" in ln and not ln.strip().startswith("#"):
                            k, _ = ln.split("=", 1)
                            existing[k.strip()] = ln
                        else:
                            lines.append(ln)
                for k, v in values.items():
                    lines = [l for l in lines if not l.startswith(f"{k}=")]
                    lines.append(f"{k}={v}")
                env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self._log("💾 llama.cpp settings saved to .env")
        except Exception as e:
            self._log(f"Failed to persist llama.cpp settings: {e}")

    def setup_ui(self):
        """Build the control panel UI with dynamic provider and GPU detection."""
        layout = QVBoxLayout(self)
        
        # ── Header ──────────────────────────────────────────────────────
        header = QLabel("🧠 Dual Brain Orchestrator")
        header.setFont(QFont("Segoe UI", 18, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("color: #bb86fc; padding: 10px;")
        layout.addWidget(header)
        
        # Dynamic subtitle based on detected configuration
        gpus = self.provider_manager.get_gpus()
        providers = self.provider_manager.get_running_providers()
        
        if len(gpus) >= 2:
            subtitle_text = f"GPU-Isolated Inference: {gpus[0].name} (Big) + {gpus[1].name} (Small)"
        elif len(gpus) == 1:
            subtitle_text = f"Single GPU: {gpus[0].name} (Cloud fallback available)"
        else:
            subtitle_text = "Cloud-Only Mode (No local GPUs detected)"
        
        subtitle = QLabel(subtitle_text)
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #888; font-size: 12px; padding-bottom: 10px;")
        layout.addWidget(subtitle)

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
        for i, gpu in enumerate(gpus):
            color = colors[i % len(colors)]
            widget = self._create_gpu_widget(gpu.index, gpu.name, color)
            gpu_layout.addWidget(widget)
            self.gpu_widgets[gpu.index] = widget
        
        # If no GPUs detected, show a label
        if not gpus:
            no_gpu_label = QLabel("No GPUs detected. Using cloud providers only.")
            no_gpu_label.setAlignment(Qt.AlignCenter)
            no_gpu_label.setStyleSheet("color: #ff9800; font-size: 12px; padding: 20px;")
            gpu_layout.addWidget(no_gpu_label)

        layout.addWidget(gpu_group)

        # ── Provider Control Panel ──────────────────────────────────────
        provider_group = QGroupBox("🎛️ Provider Control (One-Click Launch)")
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
        
        # Labels are updated from the canonical runtime after the controls exist.
        sb_label = QLabel("🤖 Small Brain")
        sb_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        sb_label.setStyleSheet("color: #03dac6;")
        provider_layout.addWidget(sb_label, 0, 0)
        
        self.sb_status = QLabel("● Checking...")
        self.sb_status.setStyleSheet("color: #ffb300; font-weight: bold;")
        provider_layout.addWidget(self.sb_status, 0, 1)
        
        self.sb_model_label = QLabel("Model: —")
        self.sb_model_label.setStyleSheet("color: #888;")
        provider_layout.addWidget(self.sb_model_label, 0, 2)
        
        self.sb_start_btn = QPushButton("▶ Start Small Brain")
        self.sb_start_btn.setStyleSheet("""
            QPushButton {
                background: #03dac6;
                color: #000;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }
            QPushButton:hover { background: #03dac6cc; }
        """)
        provider_layout.addWidget(self.sb_start_btn, 0, 3)
        
        self.sb_stop_btn = QPushButton("⏹ Stop")
        self.sb_stop_btn.setStyleSheet("""
            QPushButton {
                background: #ff5252;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }
            QPushButton:hover { background: #ff5252cc; }
        """)
        self.sb_stop_btn.setEnabled(False)
        provider_layout.addWidget(self.sb_stop_btn, 0, 4)
        
        bb_label = QLabel("🧠 Big Brain")
        bb_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        bb_label.setStyleSheet("color: #bb86fc;")
        provider_layout.addWidget(bb_label, 1, 0)
        
        self.bb_status = QLabel("● Checking...")
        self.bb_status.setStyleSheet("color: #ffb300; font-weight: bold;")
        provider_layout.addWidget(self.bb_status, 1, 1)
        
        self.bb_model_label = QLabel("Model: —")
        self.bb_model_label.setStyleSheet("color: #888;")
        provider_layout.addWidget(self.bb_model_label, 1, 2)
        
        self.bb_start_btn = QPushButton("▶ Start Big Brain")
        self.bb_start_btn.setStyleSheet("""
            QPushButton {
                background: #bb86fc;
                color: #000;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }
            QPushButton:hover { background: #bb86fc88; }
        """)
        provider_layout.addWidget(self.bb_start_btn, 1, 3)
        
        self.bb_stop_btn = QPushButton("⏹ Stop")
        self.bb_stop_btn.setStyleSheet("""
            QPushButton {
                background: #ff5252;
                color: white;
                font-weight: bold;
                border: none,
                border-radius: 4px;
                padding: 8px 16px;
            }
            QPushButton:hover { background: #ff5252cc; }
        """)
        self.bb_stop_btn.setEnabled(False)
        provider_layout.addWidget(self.bb_stop_btn, 1, 4)
        
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

        # ── Small Brain Settings ──
        self.sb_settings_label = QLabel("🤖 Small Brain (CPU / System RAM, port 1235)")
        self.sb_settings_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.sb_settings_label.setStyleSheet("color: #03dac6;")
        settings_layout.addWidget(self.sb_settings_label, 0, 0, 1, 4)

        self.sb_model_combo = QComboBox()
        self.sb_model_combo.setMinimumWidth(250)
        self.sb_model_combo.installEventFilter(_WheelEventFilter(self.sb_model_combo))
        self.sb_model_combo.setStyleSheet("""
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
        """)
        self.sb_model_combo.setToolTip("Select model for Small Brain (auto-detected from llama-server)")
        settings_layout.addWidget(self.sb_model_combo, 1, 0)

        self.sb_refresh_models_btn = QPushButton("🔄 Refresh")
        self.sb_refresh_models_btn.setFixedWidth(80)
        self.sb_refresh_models_btn.setStyleSheet("""
            QPushButton {
                background: #03dac6;
                color: #000;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 10px;
            }
            QPushButton:hover { background: #03dac6cc; }
        """)
        settings_layout.addWidget(self.sb_refresh_models_btn, 1, 1)

        self.sb_ctx_label = QLabel("Ctx Size:")
        self.sb_ctx_label.setStyleSheet("color: #888; font-size: 11px;")
        settings_layout.addWidget(self.sb_ctx_label, 1, 2)

        self.sb_ctx_spin = QSpinBox()
        self.sb_ctx_spin.setRange(2048, 524288)
        self.sb_ctx_spin.setValue(32768)
        self.sb_ctx_spin.setSuffix(" tok")
        self.sb_ctx_spin.setFixedWidth(100)
        self.sb_ctx_spin.setStyleSheet("""
            QSpinBox {
                background: #1a1a1a;
                color: #e0e0e0;
                border: 1px solid #333;
                border-radius: 4px;
                padding: 4px;
                font-size: 11px;
            }
        """)
        self.sb_ctx_spin.valueChanged.connect(lambda: self._on_context_changed(False))
        settings_layout.addWidget(self.sb_ctx_spin, 1, 3)

        # ── Small Brain advanced llama.cpp settings (row 2) ────────────────
        sb_adv_label = QLabel("GPU Layers / Split / Threads / KV:")
        sb_adv_label.setStyleSheet("color: #888; font-size: 11px;")
        settings_layout.addWidget(sb_adv_label, 2, 0)

        self.sb_gpu_layers_spin = QSpinBox()
        self.sb_gpu_layers_spin.setRange(-1, 999)
        self.sb_gpu_layers_spin.setValue(int(os.getenv("SMALL_BRAIN_GPU_LAYERS", "-1") or -1))
        self.sb_gpu_layers_spin.setSpecialValueText("Auto")
        self.sb_gpu_layers_spin.setToolTip("GPU layers (-1=auto, 0=CPU only, N=offload N layers to GPU)")
        self.sb_gpu_layers_spin.setFixedWidth(80)
        self.sb_gpu_layers_spin.setStyleSheet(SMALL_SPIN_QSS)
        settings_layout.addWidget(self.sb_gpu_layers_spin, 2, 1)

        self.sb_split_combo = QComboBox()
        self.sb_split_combo.addItems(["none", "layer", "row"])
        self.sb_split_combo.setCurrentText(os.getenv("SMALL_BRAIN_SPLIT_MODE", "none"))
        self.sb_split_combo.setToolTip("Split mode: none=1 GPU, layer=per-layer across GPUs, row=row-wise")
        self.sb_split_combo.setFixedWidth(90)
        self.sb_split_combo.setStyleSheet(SMALL_SPIN_QSS)
        settings_layout.addWidget(self.sb_split_combo, 2, 2)

        self.sb_threads_spin = QSpinBox()
        self.sb_threads_spin.setRange(1, 32)
        self.sb_threads_spin.setValue(int(os.getenv("SMALL_BRAIN_THREADS", "4") or 4))
        self.sb_threads_spin.setSuffix(" t")
        self.sb_threads_spin.setFixedWidth(70)
        self.sb_threads_spin.setStyleSheet(SMALL_SPIN_QSS)
        settings_layout.addWidget(self.sb_threads_spin, 2, 3)

        # ── Big Brain Settings ──
        bb_settings_label = QLabel("🧠 Big Brain (5060 Ti, port 1234)")
        self.bb_settings_label = bb_settings_label
        bb_settings_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        bb_settings_label.setStyleSheet("color: #bb86fc;")
        settings_layout.addWidget(bb_settings_label, 3, 0, 1, 4)

        self.bb_model_combo = QComboBox()
        self.bb_model_combo.setMinimumWidth(250)
        self.bb_model_combo.installEventFilter(_WheelEventFilter(self.bb_model_combo))
        self.bb_model_combo.setStyleSheet("""
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
                selection-background-color: #bb86fc;
            }
        """)
        self.bb_model_combo.setToolTip("Select model for Big Brain (auto-detected from llama-server)")
        settings_layout.addWidget(self.bb_model_combo, 4, 0)

        self.bb_refresh_models_btn = QPushButton("🔄 Refresh")
        self.bb_refresh_models_btn.setFixedWidth(80)
        self.bb_refresh_models_btn.setStyleSheet("""
            QPushButton {
                background: #bb86fc;
                color: #000;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 10px;
            }
            QPushButton:hover { background: #bb86fc88; }
        """)
        settings_layout.addWidget(self.bb_refresh_models_btn, 4, 1)

        self.bb_ctx_label = QLabel("Ctx Size:")
        self.bb_ctx_label.setStyleSheet("color: #888; font-size: 11px;")
        settings_layout.addWidget(self.bb_ctx_label, 4, 2)

        self.bb_ctx_spin = QSpinBox()
        self.bb_ctx_spin.setRange(2048, 524288)
        self.bb_ctx_spin.setValue(32768)
        self.bb_ctx_spin.setSuffix(" tok")
        self.bb_ctx_spin.setFixedWidth(100)
        self.bb_ctx_spin.setStyleSheet("""
            QSpinBox {
                background: #1a1a1a;
                color: #e0e0e0;
                border: 1px solid #333;
                border-radius: 4px;
                padding: 4px;
                font-size: 11px;
            }
        """)
        self.bb_ctx_spin.valueChanged.connect(lambda: self._on_context_changed(True))
        settings_layout.addWidget(self.bb_ctx_spin, 4, 3)

        bb_adv_label = QLabel("GPU Layers / Split / Threads / KV:")
        bb_adv_label.setStyleSheet("color: #888; font-size: 11px;")
        settings_layout.addWidget(bb_adv_label, 5, 0)

        self.bb_gpu_layers_spin = QSpinBox()
        self.bb_gpu_layers_spin.setRange(-1, 999)
        self.bb_gpu_layers_spin.setValue(int(os.getenv("BIG_BRAIN_GPU_LAYERS", "-1") or -1))
        self.bb_gpu_layers_spin.setSpecialValueText("Auto")
        self.bb_gpu_layers_spin.setToolTip("GPU layers (-1=auto, 0=CPU only, N=offload N layers to GPU)")
        self.bb_gpu_layers_spin.setFixedWidth(80)
        self.bb_gpu_layers_spin.setStyleSheet(BIG_SPIN_QSS)
        settings_layout.addWidget(self.bb_gpu_layers_spin, 5, 1)

        self.bb_split_combo = QComboBox()
        self.bb_split_combo.addItems(["none", "layer", "row"])
        self.bb_split_combo.setCurrentText(os.getenv("BIG_BRAIN_SPLIT_MODE", "none"))
        self.bb_split_combo.setToolTip("Split mode: none=1 GPU, layer=per-layer across GPUs, row=row-wise")
        self.bb_split_combo.setFixedWidth(90)
        self.bb_split_combo.setStyleSheet(BIG_SPIN_QSS)
        settings_layout.addWidget(self.bb_split_combo, 5, 2)

        self.bb_threads_spin = QSpinBox()
        self.bb_threads_spin.setRange(1, 32)
        self.bb_threads_spin.setValue(int(os.getenv("BIG_BRAIN_THREADS", "8") or 8))
        self.bb_threads_spin.setSuffix(" t")
        self.bb_threads_spin.setFixedWidth(70)
        self.bb_threads_spin.setStyleSheet(BIG_SPIN_QSS)
        settings_layout.addWidget(self.bb_threads_spin, 5, 3)

        # ── KV cache type + batch (shared row across both brains) ──────────
        kv_label = QLabel("KV Cache:")
        kv_label.setStyleSheet("color: #888; font-size: 11px;")
        settings_layout.addWidget(kv_label, 6, 0)
        self.sb_kv_combo = QComboBox()
        self.sb_kv_combo.addItems(["f16", "f32", "q8_0", "q4_0", "auto"])
        self.sb_kv_combo.setCurrentText(os.getenv("SMALL_BRAIN_KV_CACHE", "f16"))
        self.sb_kv_combo.setToolTip("KV cache quantization: f16=default, q8_0/q4_0=saves VRAM, f32=max accuracy")
        self.sb_kv_combo.setFixedWidth(90)
        self.sb_kv_combo.setStyleSheet(SMALL_SPIN_QSS)
        settings_layout.addWidget(self.sb_kv_combo, 6, 1)
        bb_kv_label = QLabel("Big KV Cache:")
        bb_kv_label.setStyleSheet("color: #888; font-size: 11px;")
        settings_layout.addWidget(bb_kv_label, 6, 2)
        self.bb_kv_combo = QComboBox()
        self.bb_kv_combo.addItems(["f16", "f32", "q8_0", "q4_0", "auto"])
        self.bb_kv_combo.setCurrentText(os.getenv("BIG_BRAIN_KV_CACHE", "f16"))
        self.bb_kv_combo.setToolTip("KV cache quantization: f16=default, q8_0/q4_0=saves VRAM, f32=max accuracy")
        self.bb_kv_combo.setFixedWidth(90)
        self.bb_kv_combo.setStyleSheet(BIG_SPIN_QSS)
        settings_layout.addWidget(self.bb_kv_combo, 6, 3)

        # ── Batch size (row 7) ─────────────────────────────────────────────
        batch_label = QLabel("Batch Size:")
        batch_label.setStyleSheet("color: #888; font-size: 11px;")
        settings_layout.addWidget(batch_label, 7, 0)
        self.sb_batch_spin = QSpinBox()
        self.sb_batch_spin.setRange(128, 8192)
        self.sb_batch_spin.setValue(int(os.getenv("SMALL_BRAIN_BATCH", "2048") or 2048))
        self.sb_batch_spin.setToolTip("Prompt/eval batch size (tokens). Lower uses less VRAM.")
        self.sb_batch_spin.setFixedWidth(90)
        self.sb_batch_spin.setStyleSheet(SMALL_SPIN_QSS)
        settings_layout.addWidget(self.sb_batch_spin, 7, 1)
        bb_batch_label = QLabel("Big Batch Size:")
        bb_batch_label.setStyleSheet("color: #888; font-size: 11px;")
        settings_layout.addWidget(bb_batch_label, 7, 2)
        self.bb_batch_spin = QSpinBox()
        self.bb_batch_spin.setRange(128, 8192)
        self.bb_batch_spin.setValue(int(os.getenv("BIG_BRAIN_BATCH", "2048") or 2048))
        self.bb_batch_spin.setToolTip("Prompt/eval batch size (tokens). Lower uses less VRAM.")
        self.bb_batch_spin.setFixedWidth(90)
        self.bb_batch_spin.setStyleSheet(BIG_SPIN_QSS)
        settings_layout.addWidget(self.bb_batch_spin, 7, 3)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Hardware preset:"))
        self.hardware_preset_combo = QComboBox()
        self.hardware_preset_combo.addItems(list(HARDWARE_PRESETS))
        self.hardware_preset_combo.setCurrentText("Balanced")
        self.hardware_preset_combo.setToolTip(
            "Choose a starting point for VRAM, context, batch size, and CPU/GPU use. "
            "Save and restart both servers after applying a preset.")
        preset_row.addWidget(self.hardware_preset_combo)
        self.apply_hardware_preset_btn = QPushButton("Apply")
        self.apply_hardware_preset_btn.setToolTip(
            "Fill the llama.cpp controls with the selected hardware preset.")
        self.apply_hardware_preset_btn.clicked.connect(self._apply_hardware_preset)
        preset_row.addWidget(self.apply_hardware_preset_btn)
        preset_row.addStretch(1)
        self.hardware_preset_help = QLabel(HARDWARE_PRESETS["Balanced"]["help"])
        self.hardware_preset_help.setWordWrap(True)
        self.hardware_preset_help.setStyleSheet("color: #888; font-size: 10px;")
        self.hardware_preset_combo.currentTextChanged.connect(
            lambda name: self.hardware_preset_help.setText(HARDWARE_PRESETS[name]["help"]))
        preset_row.addWidget(self.hardware_preset_help, 2)
        settings_layout.addLayout(preset_row, 8, 0, 1, 4)

        layout.addWidget(settings_group)

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

        # Save llama.cpp customization to .env (v2.1)
        self.save_settings_btn = QPushButton("💾 Save llama.cpp Settings")
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
        brain_name = "Marcus (Big Brain)" if index == 0 else "Alex (Small Brain)"
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

        # Store references
        if index == 0:
            self.gpu0_est_bar = est_bar
            self.gpu0_act_bar = act_bar
            self.gpu0_kv_bar = kv_bar
            self.gpu0_label = name_label
            self.gpu0_model_label = model_label
            self.gpu0_ctx_label = ctx_label
            self.gpu0_est_detail = est_detail
            self.gpu0_act_detail = act_detail
            self.gpu0_kv_detail = kv_detail
            self.gpu0_status = status_label
        else:
            self.gpu1_est_bar = est_bar
            self.gpu1_act_bar = act_bar
            self.gpu1_kv_bar = kv_bar
            self.gpu1_label = name_label
            self.gpu1_model_label = model_label
            self.gpu1_ctx_label = ctx_label
            self.gpu1_est_detail = est_detail
            self.gpu1_act_detail = act_detail
            self.gpu1_kv_detail = kv_detail
            self.gpu1_status = status_label

        return frame
    
    # ═══════════════════════════════════════════════════════════════════
    # GPU STATUS UPDATES
    # ═══════════════════════════════════════════════════════════════════
    def pause_background(self):
        """Stop the nvidia-smi polling worker when the tab is hidden (GUI perf)."""
        try:
            w = getattr(self, "gpu_worker", None)
            if w is not None:
                w.stop()
        except Exception:
            pass

    def resume_background(self):
        """Restart the nvidia-smi polling worker when the tab is shown again."""
        try:
            w = getattr(self, "gpu_worker", None)
            if w is not None and not w.isRunning():
                w.start()
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

    def _set_gpu_bar(self, idx, bar_type, pct, color):
        """Set a GPU bar value and color."""
        if idx == 0:
            bar = getattr(self, f"gpu0_{bar_type}_bar", None)
        else:
            bar = getattr(self, f"gpu1_{bar_type}_bar", None)
        if bar:
            bar.setValue(pct)
            # Rebuild the stylesheet with the new chunk color
            base = bar.property("base_stylesheet")
            if base:
                bar.setStyleSheet(base.replace("{CHUNK_COLOR}", color))

    def _set_gpu_detail(self, idx, detail_type, text):
        """Set a GPU detail label. detail_type: 'est', 'act', 'kv'."""
        label = getattr(self, f"gpu0_{detail_type}_detail", None) if idx == 0 else getattr(self, f"gpu1_{detail_type}_detail", None)
        if label:
            label.setText(text)

    def _set_gpu_model(self, idx, text):
        """Set the model name label."""
        label = getattr(self, f"gpu0_model_label", None) if idx == 0 else getattr(self, f"gpu1_model_label", None)
        if label:
            label.setText(f"Model: {text}")

    def _set_gpu_ctx(self, idx, text):
        """Set the context label."""
        label = getattr(self, f"gpu0_ctx_label", None) if idx == 0 else getattr(self, f"gpu1_ctx_label", None)
        if label:
            label.setText(text)

    def _set_gpu_status(self, idx, text):
        """Set the status line with color."""
        label = getattr(self, f"gpu0_status", None) if idx == 0 else getattr(self, f"gpu1_status", None)
        if label:
            color = "#4caf50" if "✅" in text else "#ff9800" if "⚠️" in text else "#888"
            label.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: bold; padding-top: 4px;")
            label.setText(text)

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
            from agents.dual_brain_runtime import BrainRole
            role = BrainRole.BIG if idx == 0 else BrainRole.SMALL
            model_path = self._current_model_path(role == BrainRole.SMALL)
            if model_path:
                return os.path.basename(model_path)
            return "—"
        except Exception:
            return "—"

    def _get_model_vram_for_gpu(self, gpu_index: int) -> dict:
        """Get VRAM estimate for the model assigned to a GPU."""
        try:
            from agents.dual_brain_runtime import BrainRole
            from agents.gguf_meta import estimate_vram_gb
            
            # Determine which brain maps to this GPU
            if gpu_index == 0:
                role = BrainRole.BIG
                ctx = self.bb_ctx_spin.value()
            else:
                role = BrainRole.SMALL
                ctx = self.sb_ctx_spin.value()
            
            # Get the model path from the combo
            small = (role == BrainRole.SMALL)
            model_path = self._current_model_path(small)
            if not model_path:
                return {}
            
            kv_name = (self.sb_kv_combo.currentText() if small else self.bb_kv_combo.currentText()) or "f16"
            kv_type_bytes = {"f32": 4, "f16": 2, "q8_0": 1, "q4_0": 0.5, "auto": 2}.get(kv_name, 2)
            # Estimate VRAM using the selected cache precision.
            est = estimate_vram_gb(model_path, context=ctx, kv_type_bytes=kv_type_bytes)
            est["kv_type"] = kv_name
            return est
        except Exception:
            return {}

    def _on_context_changed(self, is_big: bool):
        """Live preview: update the estimated VRAM bar when context spinbox changes."""
        try:
            from agents.gguf_meta import estimate_vram_gb
            
            idx = 0 if is_big else 1
            ctx = self.bb_ctx_spin.value() if is_big else self.sb_ctx_spin.value()
            
            # Get model path
            small = not is_big
            model_path = self._current_model_path(small)
            if not model_path:
                return
            
            kv_name = (self.bb_kv_combo.currentText() if is_big else self.sb_kv_combo.currentText()) or "f16"
            kv_type_bytes = {"f32": 4, "f16": 2, "q8_0": 1, "q4_0": 0.5, "auto": 2}.get(kv_name, 2)
            # Estimate VRAM using the selected cache precision.
            est = estimate_vram_gb(model_path, context=ctx, kv_type_bytes=kv_type_bytes)
            model_vram_gb = est.get("total_gb", 0)
            weights_gb = est.get("weights_gb", 0)
            kv_gb = est.get("kv_gb", 0)
            
            # Get GPU total
            gpu_total = 14.8 if is_big else 6.0
            
            if model_vram_gb > 0:
                gpu_pct = min(100, int((model_vram_gb / gpu_total) * 100))
                
                # Color-coded safety zones
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
                
                self._set_gpu_bar(idx, "est", gpu_pct, zone_color)
                self._set_gpu_detail(idx, "est", f"Weights: {weights_gb:.1f}GB  KV: {kv_gb:.1f}GB  Total: {model_vram_gb:.1f}GB")
                self._set_gpu_status(idx, status)
                self._set_gpu_ctx(idx, f"Context: {ctx:,} tokens")
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
            from agents.dual_brain_runtime import BrainRole
            if self.runtime is not None:
                return int(self.runtime.config(BrainRole.SMALL if small else BrainRole.BIG).port)
            cfg = DualBrainRuntime.from_env().config(BrainRole.SMALL if small else BrainRole.BIG)
            return int(cfg.port)
        except Exception:
            return 1235 if small else 1234

    # Default .gguf model paths — mirror the start_*_brain.ps1 scripts so a
    # launched server always gets a REAL model file, never a placeholder/UI
    # string (v2.1 fix: Start was passing "⚠️ llama-server offline…" as --model).
    _DEFAULT_MODEL_PATHS = {
        True: "D:/LMStudio/models/lmstudio-community/Qwen3-4B-Thinking-2507-GGUF/Qwen3-4B-Thinking-2507-Q6_K.gguf",
        False: "D:/LMStudio/models/lmstudio-community/Qwen3.8-27B-GGUF/Qwen3.8-27B-Q4_K_M.gguf",
    }
    _PLACEHOLDER_MARKERS = ("⚠️", "Error", "No models found")

    def _resolve_model_path(self, small: bool, combo_text: str) -> str:
        """Return a real .gguf path to launch for a brain, or '' if none.

        Resolution order (first non-placeholder, existing file wins):
          1. combo text IF it is a real model id/path (not a placeholder)
          2. env BIG/SMALL_BRAIN_MODEL
          3. the default .gguf path from the start scripts
          4. '' (caller aborts launch with a clear log)
        """
        cands = []
        if combo_text and not combo_text.startswith(self._PLACEHOLDER_MARKERS):
            cands.append(combo_text)
        env_key = "SMALL_BRAIN_MODEL" if small else "BIG_BRAIN_MODEL"
        env_model = os.getenv(env_key, "").strip()
        if env_model:
            cands.append(env_model)
        cands.append(self._DEFAULT_MODEL_PATHS[small])
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
        return self.sb_model_combo if small else self.bb_model_combo

    def _current_model_path(self, small: bool) -> str:
        """Full .gguf path behind the dropdown's current item (UserRole)."""
        combo = self._model_combo(small)
        if combo.count() == 0:
            return ""
        data = combo.itemData(combo.currentIndex())
        if data:
            return str(data)
        return combo.currentText()

    def _repopulate_model_combo(self, small: bool, loaded_path: str = "", models=None):
        """Fill a brain's dropdown with ALL local .gguf (display name, full path
        in item data).

        Selection policy: GUI combo is the SOURCE OF TRUTH. The user's selection
        is NEVER overridden by what the server reports as loaded. The only time
        we auto-select the loaded model is on first population when the user
        hasn't made a selection yet.
        """
        combo = self._model_combo(small)
        prev = self._current_model_path(small)  # what the user has selected (may be "")
        prev_norm = self._norm_path(prev)
        from agents.dual_brain_runtime import BrainRole, DualBrainRuntime
        runtime = self.runtime or DualBrainRuntime.from_env()
        cfg = runtime.config(BrainRole.SMALL if small else BrainRole.BIG)
        external = cfg.provider != "llamacpp"
        combo.blockSignals(True)
        try:
            combo.clear()
            paths = list(models or []) if external else self._discover_gguf_models()
            if external and cfg.model and cfg.model not in paths:
                paths.insert(0, cfg.model)
            if loaded_path and self._norm_path(loaded_path) not in {self._norm_path(p) for p in paths}:
                paths.insert(0, loaded_path)  # running model not under scanned dirs
            # Decide the target selection:
            #   1. ALWAYS keep the user's previous valid selection if it exists in the list;
            #   2. else auto-select the loaded model (first-time population only);
            #   3. else first entry.
            target_norm = ""
            if prev_norm and prev_norm in {self._norm_path(p) for p in paths}:
                target_norm = prev_norm
            elif loaded_path and not prev_norm:
                target_norm = self._norm_path(loaded_path)
            select = 0
            for i, p in enumerate(paths):
                combo.addItem(p if external else os.path.basename(p), p)
                if self._norm_path(p) == target_norm:
                    select = i
            if paths:
                # Suppress model-change auto-restart during programmatic selection
                self._suppress_model_change_restart = True
                combo.setCurrentIndex(select)
                self._suppress_model_change_restart = False
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

            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._set_loading(small, False, ""))

    def _continue_model_restart(self, small: bool):
        """Continue a model restart on the Qt GUI thread."""
        if small:
            self._on_start_small_brain()
        else:
            self._on_start_big_brain()

    def _set_loading(self, small: bool, loading: bool, model_path: str):
        """Show/hide loading indicator for a brain."""
        label = "Small Brain" if small else "Big Brain"
        idx = 0 if small else 1
        if loading:
            self._log(f"⏳ {label}: loading {os.path.basename(model_path)} into VRAM...")
            # Update status to show loading
            if small:
                self.sb_status.setText("● Loading...")
                self.sb_status.setStyleSheet("color: #ffb300; font-weight: bold;")
                self.sb_start_btn.setEnabled(False)
                self.sb_stop_btn.setEnabled(False)
            else:
                self.bb_status.setText("● Loading...")
                self.bb_status.setStyleSheet("color: #ffb300; font-weight: bold;")
                self.bb_start_btn.setEnabled(False)
                self.bb_stop_btn.setEnabled(False)
            
            # Update GPU bars to show loading state
            model_info = self._get_model_vram_for_gpu(idx)
            model_vram_gb = model_info.get("total_gb", 0)
            if model_vram_gb > 0:
                # Show estimated bar at 100% (model is being loaded)
                self._set_gpu_bar(idx, "est", 100, "#ffb300")
                self._set_gpu_detail(idx, "est", f"Loading {os.path.basename(model_path)}...")
                # Show actual bar at 0% (will be updated by nvidia-smi polling)
                self._set_gpu_bar(idx, "act", 0, "#4caf50")
                self._set_gpu_detail(idx, "act", "Loading...")
                # Show KV bar at 0%
                self._set_gpu_bar(idx, "kv", 0, "#ff9800")
                self._set_gpu_detail(idx, "kv", "Loading...")
        else:
            if small:
                self.sb_status.setText("● Checking...")
                self.sb_status.setStyleSheet("color: #ffb300; font-weight: bold;")
            else:
                self.bb_status.setText("● Checking...")
                self.bb_status.setStyleSheet("color: #ffb300; font-weight: bold;")
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
        else:
            self._kill_llama_on_port(self._brain_port(small))
        setattr(self, attr, None)
        setattr(self, flag, False)

    def _pid_on_port(self, port: int):
        """Return the PID bound to 127.0.0.1:<port> (listening), or None."""
        try:
            out = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW).stdout
        except Exception:
            return None
        for ln in out.splitlines():
            parts = ln.split()
            if len(parts) >= 5 and parts[0] == "TCP":
                local = parts[1]
                state = parts[3] if len(parts) >= 5 else ""
                pid = parts[4]
                if state == "LISTENING" and local.endswith(f":{port}") and pid.isdigit():
                    return int(pid)
        return None

    def _kill_llama_on_port(self, port: int):
        """Kill the process listening on 127.0.0.1:<port> (works for servers started
        outside this panel; CREATE_NO_WINDOW servers have no matching window title)."""
        pid = self._pid_on_port(port)
        if pid is not None:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True, text=True, timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception:
                pass

    def _brain_models_url(self, small: bool) -> str:
        """Full /v1/models URL for a brain, from the configured endpoint."""
        try:
            from agents.dual_brain_runtime import BrainRole
            if self.runtime is not None:
                mpath = self.runtime.config(BrainRole.SMALL if small else BrainRole.BIG).models_path
                return mpath if mpath else f"http://127.0.0.1:{self._brain_port(small)}/v1/models"
            cfg = DualBrainRuntime.from_env().config(BrainRole.SMALL if small else BrainRole.BIG)
            return cfg.models_path or f"http://127.0.0.1:{self._brain_port(small)}/v1/models"
        except Exception:
            return f"http://127.0.0.1:{self._brain_port(small)}/v1/models"

    def _launch_and_wait(self, role_name: str, cmd, port: int):
        """Launch a server, then prove its endpoint is ready before reporting success."""
        log_path = os.path.join(tempfile.gettempdir(), f"mrbot-{role_name.lower()}-llama-server.log")
        try:
            log_file = open(log_path, "w", encoding="utf-8", errors="replace")
            proc = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            raise

        deadline = time.monotonic() + 120.0
        last_error = "server did not answer"
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                log_file.close()
                try:
                    with open(log_path, encoding="utf-8", errors="replace") as f:
                        tail = f.read()[-1200:].strip()
                except OSError:
                    tail = ""
                raise RuntimeError(f"process exited with code {proc.returncode}; log={log_path}\n{tail}")
            running, models = self.provider_checker.check_llama_server(port, timeout=2)
            if running:
                log_file.close()
                return proc, log_path, models
            last_error = f"no response on :{port}"
            time.sleep(1.0)

        log_file.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        raise RuntimeError(f"{last_error} after 15s; log={log_path}")

    def _log(self, message):
        """Append a timestamped message to the provider event log."""
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
        """Stop the GPU polling thread before the control is destroyed."""
        self._closing = True
        probe_thread = getattr(self, "_provider_probe_thread", None)
        if probe_thread is not None and probe_thread.is_alive():
            probe_thread.join(3000)
        worker = getattr(self, "gpu_worker", None)
        if worker is not None and worker.isRunning():
            worker.stop()
            worker.wait(7000)
        for name in (
            "_small_probe_worker", "_big_probe_worker",
            "_small_stop_worker", "_big_stop_worker",
            "_small_launch_worker", "_big_launch_worker",
        ):
            worker = getattr(self, name, None)
            try:
                if worker is not None and worker.isRunning():
                    if hasattr(worker, "stop"):
                        worker.stop()
                    worker.wait(3000)
            except RuntimeError:
                # Finished workers may already have processed deleteLater().
                pass


class BrainLaunchWorker(QThread):
    """Background worker for launching llama-server - prevents GUI freeze."""

    launch_finished = Signal(bool, str, object)  # success, message, process

    def __init__(self, role_name: str, cmd: list, port: int, check_fn=None):
        super().__init__()
        self.role_name = role_name
        self.cmd = cmd
        self.port = port
        self.check_fn = check_fn or self._default_check
        self._proc = None
        self._stop_requested = False

    def stop(self):
        """Request cancellation and terminate a process already launched."""
        self._stop_requested = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    def _default_check(self, port):
        try:
            import urllib.request
            req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/models")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return True
        except Exception:
            return False

    def run(self):
        """Launch server and wait for it to be ready."""
        import time
        log_path = os.path.join(tempfile.gettempdir(), f"mrbot-{self.role_name.lower()}-llama-server.log")
        try:
            log_file = open(log_path, "w", encoding="utf-8", errors="replace")
            self._proc = subprocess.Popen(
                self.cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as e:
            self._record_failure(f"Popen failed: {e}")
            self.launch_finished.emit(False, f"Failed to start {self.role_name}: {e}", None)
            return

        self._log_file = log_file
        self._log_path = log_path

        try:
            deadline = time.monotonic() + 120.0
            while time.monotonic() < deadline and not self._stop_requested:
                if self._proc.poll() is not None:
                    log_file.close()
                    try:
                        with open(log_path, encoding="utf-8", errors="replace") as f:
                            tail = f.read()[-1200:].strip()
                    except OSError:
                        tail = ""
                    self.launch_finished.emit(False, f"Process exited with code {self._proc.returncode}\n{tail}", None)
                    return
                if self.check_fn(self.port):
                    log_file.close()
                    self.launch_finished.emit(True, f"{self.role_name} ready on :{self.port}", self._proc)
                    return
                time.sleep(1.0)

            log_file.close()
            if self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            message = "Launch cancelled" if self._stop_requested else "Server did not respond after 120s"
            self.launch_finished.emit(False, message, None)
        except Exception as e:
            self._record_failure(f"worker run failed: {e}")
            try:
                if self._proc is not None and self._proc.poll() is None:
                    self._proc.terminate()
            except Exception:
                pass
            self.launch_finished.emit(False, f"Launcher error: {e}", None)

    def _record_failure(self, message: str):
        try:
            path = os.path.join(tempfile.gettempdir(), "mrbot-dual-brain-crash.log")
            with open(path, "a", encoding="utf-8", errors="replace") as report:
                report.write(f"\n[{datetime.now().isoformat()}] {self.role_name}: {message}\n")
                report.write(f"command={self.cmd!r}\n")
        except Exception:
            pass


    def _refresh_small_brain_models(self):
        """Populate the Small Brain dropdown with ALL local .gguf, selecting the
        currently-loaded model if the server is up."""
        loaded = ""
        try:
            req = urllib.request.Request(self._brain_models_url(True))
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                models = ProviderStatusChecker.extract_model_ids(data)
                if models:
                    loaded = models[0]
        except Exception as e:
            self._log(f"Small Brain model refresh (server offline): {type(e).__name__}")
        self._repopulate_model_combo(True, loaded)

    def _refresh_big_brain_models(self):
        """Populate the Big Brain dropdown with ALL local .gguf, selecting the
        currently-loaded model if the server is up."""
        loaded = ""
        try:
            req = urllib.request.Request(self._brain_models_url(False))
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                models = ProviderStatusChecker.extract_model_ids(data)
                if models:
                    loaded = models[0]
        except Exception as e:
            self._log(f"Big Brain model refresh (server offline): {type(e).__name__}")
        self._repopulate_model_combo(False, loaded)

    def _get_llama_model(self, port: int, prefer: str = "") -> str:
        """Get model name from llama-server API. Returns prefer if available, else first model."""
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/models")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                models = ProviderStatusChecker.extract_model_ids(data)
                if prefer and prefer in models:
                    return prefer
                if models:
                    return models[0]
        except Exception:
            pass  # best-effort model fallback
        return ""

    # ═══════════════════════════════════════════════════════════════════
    # VRAM-AFFINITY GUARD (warn-but-allow, v2.0.37c)
    # ═══════════════════════════════════════════════════════════════════
    # Policy (binding, user): 5060 Ti (Big Brain) never overflows onto the 1660
    # Super; the 1660 Super (Small Brain, 6 GB) is only for tiny models. Overflow
    # beyond a GPU's VRAM may go to SYSTEM RAM, never across PCIe to the other
    # card. Cross-GPU spill is already structurally impossible (each brain is its
    # own llama-server pinned to ONE device with --split-mode none), so the guard
    # only warns when a model's estimated VRAM need exceeds the target GPU's free
    # VRAM, letting the user confirm a system-RAM spill is intended.
    def _gpu_free_vram_gb(self, device_index: int) -> Optional[float]:
        """Free VRAM (GB) for a CUDA device via nvidia-smi; None if unavailable.
        
        v2.1: Added timeout to prevent GUI freeze when nvidia-smi is slow.
        """
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,memory.free", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW)
            if r.returncode != 0:
                return None
            for line in r.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2 and parts[0] == str(device_index):
                    try:
                        return float(parts[1]) / 1024.0  # MiB -> GB
                    except ValueError:
                        return None
        except subprocess.TimeoutExpired:
            return None  # nvidia-smi timed out -> skip check
        except Exception:
            return None
        return None

    def _model_vram_need_gb(self, small: bool, model_path: str) -> Dict[str, Any]:
        """Estimate a model's total VRAM need (weights + KV @ configured ctx).

        Returns {estimate_gb, complete, kv_gb, weights_gb}. Bounded; never raises.
        Falls back to weights+margin when metadata is unreadable.
        """
        ctx = self.sb_ctx_spin.value() if small else self.bb_ctx_spin.value()
        kv_name = (self.sb_kv_combo.currentText() if small else self.bb_kv_combo.currentText()) or "f16"
        kv_type_bytes = {
            "f32": 4,
            "f16": 2,
            "q8_0": 1,
            "q4_0": 0.5,
            "auto": 2,
        }.get(kv_name, 2)
        try:
            from agents.gguf_meta import estimate_vram_gb
            estimate = estimate_vram_gb(
                model_path, context=ctx, kv_type_bytes=kv_type_bytes)
            estimate["kv_type"] = kv_name
            return estimate
        except Exception:
            try:
                import os as _os
                wgb = _os.path.getsize(model_path) / 1e9
            except Exception:
                wgb = 0.0
            return {"estimate_gb": wgb * 1.05 + 0.3, "complete": False,
                    "kv_gb": 0.0, "weights_gb": round(wgb, 2)}

    def _check_vram_affinity(self, small: bool, model_path: str) -> bool:
        """Warn-but-allow VRAM check before starting a brain.

        Returns True to proceed, False to abort. Queries the target GPU's free
        VRAM; if the model's estimated total need clearly exceeds it, asks the
        user to confirm an overflow-to-system-RAM spill is intended. Never routes
        to the other GPU (structurally impossible). Skips the prompt when VRAM
        can't be queried or the model is small enough.
        
        v2.1: Run VRAM check on background thread to prevent GUI freeze.
        """
        import threading
        
        result = {"value": True, "done": False}
        
        def _check():
            try:
                est = self._model_vram_need_gb(small, model_path)
                need = est.get("total_gb") or est.get("estimate_gb") or 0.0
                free = self._gpu_free_vram_gb(1 if small else 0)
                if free is None or need <= 0:
                    result["value"] = True
                elif need <= free:
                    result["value"] = True
                else:
                    # Need exceeds free VRAM -> ask user on GUI thread
                    # Emit from the worker thread; Qt delivers this QWidget
                    # slot on the GUI thread through the queued connection.
                    self.vram_warning_requested.emit(small, model_path, need, free, result)
                    return
            except Exception:
                result["value"] = True
            result["done"] = True
        
        t = threading.Thread(target=_check, daemon=True)
        t.start()
        
        # Wait for result (with timeout to prevent infinite freeze)
        # Never hold the GUI thread for the full VRAM probe. If nvidia-smi or
        # metadata parsing is slow, the launch path continues with its loading
        # state instead of freezing the window.
        t.join(timeout=0.25)
        if not result["done"]:
            return True  # timeout -> proceed
        
        return result["value"]
    
    def _show_vram_warning(self, small: bool, model_path: str, need: float, free: float, result: dict):
        """Show VRAM warning dialog on GUI thread."""
        if small:
            role = "Small Brain target GPU"
        else:
            role = "Big Brain target GPU"
        mb = QMessageBox(self)
        mb.setWindowTitle("Model larger than GPU VRAM")
        mb.setIcon(QMessageBox.Icon.Warning)
        mb.setText(
            f"'{os.path.basename(model_path)}' needs an estimated ~{need:.1f} GB "
            f"of VRAM (weights + KV cache), but {role} has ~{free:.1f} GB free.\n\n"
            f"The overflow will run from SYSTEM RAM (slower), NOT the other GPU "
            f"(cross-GPU spill is disabled). Continue with the system-RAM overflow?")
        yes = mb.addButton("Start anyway (overflow to RAM)", QMessageBox.ButtonRole.AcceptRole)
        no = mb.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        mb.setDefaultButton(no)
        mb.exec()
        result["value"] = mb.clickedButton() is yes
        result["done"] = True

    # ═══════════════════════════════════════════════════════════════════
    # STOP HANDLERS
    # ═══════════════════════════════════════════════════════════════════
    def _on_stop_small_brain(self):
        """Stop the Small Brain server on its configured port.

        Stops whatever is listening on the Small Brain port whether this panel
        started it or not (it may be a leftover from a prior run / scripts). The
        panel owns that port, so Stop always acts on it (v2.0.36s fix).
        """
        self._begin_stop_brain(True)

    def _begin_stop_brain(self, small: bool):
        label = "Small Brain" if small else "Big Brain"
        from agents.dual_brain_runtime import BrainRole, DualBrainRuntime
        runtime = self.runtime or DualBrainRuntime.from_env()
        cfg = runtime.config(BrainRole.SMALL if small else BrainRole.BIG)
        if cfg.provider != "llamacpp":
            model = cfg.model
            self._log(f"Stopping {label} model {model or '(selected provider model)'}...")
            threading.Thread(
                target=self._unload_external_model,
                args=(small, cfg.provider, cfg.endpoint, model, label),
                daemon=True,
            ).start()
            return
        self._log(f"Stopping {label}...")
        worker = ProviderStopWorker(self, small)
        setattr(self, "_small_stop_worker" if small else "_big_stop_worker", worker)
        worker.stop_finished.connect(lambda: self._on_brain_stopped(small))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_brain_stopped(self, small: bool):
        label = "Small Brain" if small else "Big Brain"
        self._log(f"✅ {label} stopped")
        self._refresh_provider_status()

    # ═══════════════════════════════════════════════════════════════════
    # START HANDLERS
    # ═══════════════════════════════════════════════════════════════════
    def _on_start_small_brain(self):
        self._probe_before_start(True)

    def _probe_before_start(self, small: bool):
        label = "Small Brain" if small else "Big Brain"
        try:
            from agents.dual_brain_runtime import BrainRole, DualBrainRuntime
            runtime = DualBrainRuntime.from_env()
            cfg = runtime.config(BrainRole.SMALL if small else BrainRole.BIG)
            self._log(f"Checking {label}...")
            worker = ProviderProbeWorker(
                self.provider_checker,
                self._brain_port(small) if cfg.provider == "llamacpp" else cfg.models_path,
                endpoint=cfg.provider != "llamacpp",
                provider=cfg.provider,
                model=cfg.model,
            )
            setattr(self, "_small_probe_worker" if small else "_big_probe_worker", worker)
            worker.probe_finished.connect(
                lambda running, models: self._on_provider_probe_done(small, running, models)
            )
            worker.finished.connect(worker.deleteLater)
            worker.start()
        except Exception as exc:
            self._log(f"❌ {label} start check failed: {exc}")
            self._record_start_failure(f"{label.lower()} probe", exc)

    def _on_provider_probe_done(self, small: bool, running: bool, models):
        try:
            if running:
                self._log(f"{'Small' if small else 'Big'} Brain provider is reachable")
                self._refresh_provider_status()
                return
            if small:
                self._start_small_brain_after_probe()
            else:
                self._start_big_brain_after_probe()
        except Exception as exc:
            self._log(f"❌ {'Small' if small else 'Big'} Brain start failed: {exc}")
            self._set_loading(small, False, "")

    def _start_small_brain_after_probe(self):
        """Start Small Brain on its configured local hardware/provider."""
        try:
            from agents.dual_brain_runtime import BrainRole, DualBrainRuntime
            rt = DualBrainRuntime.from_env()
            cfg = rt.config(BrainRole.SMALL)
            if not cfg.enabled:
                self._log("ℹ️ Small Brain is disabled in Settings; no local server started.")
                self._set_loading(True, False, "")
                return
            active_local = self.provider_manager.resolve_enabled_provider(local=True)
            if active_local != cfg.provider:
                self._log(f"ℹ️ Small Brain has no active {cfg.provider} route; select or enable a provider in Settings.")
                self._set_loading(True, False, "")
                return
            if cfg.provider != "llamacpp":
                self._start_external_brain(True, cfg)
                return
            detected_gpu_indexes = {gpu.index for gpu in self.provider_manager.get_gpus()}
            if cfg.gpu_layers is None and cfg.device not in detected_gpu_indexes:
                # The persisted dual-GPU default cannot be used on a
                # single-GPU machine. Apply the fallback at the final command
                # construction point so the GUI cannot overwrite it with Auto.
                cfg.gpu_layers = 0
                if getattr(self, "sb_gpu_layers_spin", None) is not None:
                    self.sb_gpu_layers_spin.setValue(0)
                cfg.gpu_label = "CPU / System RAM"
                self._log("Small Brain: secondary GPU unavailable; using CPU/system RAM.")
            else:
                self._log("Starting Small Brain (llama-server)...")

            model = self._resolve_model_path(True, self._current_model_path(True))
            if not model:
                self._log("❌ Small Brain: no model found. Set SMALL_BRAIN_MODEL in .env or pick a real model, then Start.")
                self._set_loading(True, False, "")
                return
            # Show feedback before metadata/VRAM checks so the GUI never looks
            # idle while launch preparation is in progress.
            self._set_loading(True, True, model)
            # VRAM-affinity guard (warn-but-allow) before launching.
            if not self._check_vram_affinity(True, model):
                self._log("⛔ Small Brain start cancelled — model exceeds the target GPU VRAM (would spill to RAM).")
                self._set_loading(True, False, "")
                return
            
            # Apply GUI overrides onto the canonical config.
            cfg.context = self.sb_ctx_spin.value()
            cfg.threads = self.sb_threads_spin.value()
            cfg.batch = self.sb_batch_spin.value()
            cfg.split_mode = self.sb_split_combo.currentText() or "none"
            cfg.kv_cache = self.sb_kv_combo.currentText() or "f16"
            self._persist_settings()
            gpu_l = self.sb_gpu_layers_spin.value()
            cfg.gpu_layers = None if gpu_l < 0 else int(gpu_l)
            if not detected_gpu_indexes or cfg.device not in detected_gpu_indexes:
                cfg.gpu_layers = 0
            cfg.model = model
            cmd = cfg.build_llama_command(model_path=model)
            
            # Launch asynchronously to prevent GUI freeze
            self._small_launch_worker = BrainLaunchWorker(
                "small", cmd, self._brain_port(True))
            self._small_launch_worker.launch_finished.connect(self._on_small_brain_launched)
            self._small_launch_worker.finished.connect(self._small_launch_worker.deleteLater)
            self._small_launch_worker.start()
            
        except Exception as e:
            self._log(f"❌ Failed to start Small Brain: {e}")
            self._record_start_failure("small launch setup", e)
            self._set_loading(True, False, "")

    def _on_small_brain_launched(self, success: bool, message: str, proc):
        """Handle small brain launch completion."""
        try:
            if success:
                self._small_server_process = proc
                self.we_started_small = True
                self._log(f"✅ {message}")
                self._refresh_provider_status()
            else:
                self._log(f"❌ {message}")
                self.we_started_small = False
            self._set_loading(True, False, "")
        except Exception as exc:
            self._record_start_failure("small completion", exc)

    def _on_start_big_brain(self):
        self._probe_before_start(False)

    def _start_big_brain_after_probe(self):
        """Start Big Brain (llama-server on 5060 Ti, port 1234)."""
        try:
            from agents.dual_brain_runtime import BrainRole, DualBrainRuntime
            rt = DualBrainRuntime.from_env()
            cfg = rt.config(BrainRole.BIG)
            if not cfg.enabled:
                self._log("ℹ️ Big Brain is disabled in Settings; no local server started.")
                self._set_loading(False, False, "")
                return
            active_local = self.provider_manager.resolve_enabled_provider(local=True)
            if active_local != cfg.provider:
                self._log(f"ℹ️ Big Brain has no active {cfg.provider} route; select or enable a provider in Settings.")
                self._set_loading(False, False, "")
                return
            if cfg.provider != "llamacpp":
                self._start_external_brain(False, cfg)
                return
            self._log("Starting Big Brain (llama-server on 5060 Ti)...")

            model = self._resolve_model_path(False, self._current_model_path(False))
            if not model:
                self._log("❌ Big Brain: no model found. Set BIG_BRAIN_MODEL in .env or pick a real model, then Start.")
                self._set_loading(False, False, "")
                return
            # Show feedback before metadata/VRAM checks so the GUI never looks
            # idle while launch preparation is in progress.
            self._set_loading(False, True, model)
            # VRAM-affinity guard (warn-but-allow) before launching.
            if not self._check_vram_affinity(False, model):
                self._log("⛔ Big Brain start cancelled — model exceeds the 5060 Ti's free VRAM (would spill to RAM).")
                self._set_loading(False, False, "")
                return
            
            cfg.context = self.bb_ctx_spin.value()
            cfg.threads = self.bb_threads_spin.value()
            cfg.batch = self.bb_batch_spin.value()
            cfg.split_mode = self.bb_split_combo.currentText() or "none"
            cfg.kv_cache = self.bb_kv_combo.currentText() or "f16"
            self._persist_settings()
            gpu_l = self.bb_gpu_layers_spin.value()
            cfg.gpu_layers = None if gpu_l < 0 else int(gpu_l)
            cfg.model = model
            cmd = cfg.build_llama_command(model_path=model)
            
            # Launch asynchronously to prevent GUI freeze
            self._big_launch_worker = BrainLaunchWorker(
                "big", cmd, self._brain_port(False))
            self._big_launch_worker.launch_finished.connect(self._on_big_brain_launched)
            self._big_launch_worker.finished.connect(self._big_launch_worker.deleteLater)
            self._big_launch_worker.start()
            
        except Exception as e:
            self.we_started_big = False
            self._log(f"❌ Failed to start Big Brain: {e}")
            self._record_start_failure("big launch setup", e)
            self._set_loading(False, False, "")

    def _start_external_brain(self, small: bool, cfg):
        """Load the configured role model for a shared external provider."""
        label = "Small Brain" if small else "Big Brain"
        model = (cfg.model or "").strip()
        if not model:
            self._log(f"❌ {label}: no {cfg.provider} model is configured.")
            self._set_loading(small, False, "")
            return
        self._set_loading(small, True, model)
        self._log(f"Loading {label} model {model} through {cfg.provider}...")
        threading.Thread(
            target=self._load_external_model,
            args=(small, cfg.provider, cfg.endpoint, model, label),
            daemon=True,
        ).start()

    def _on_big_brain_launched(self, success: bool, message: str, proc):
        """Handle big brain launch completion."""
        try:
            if success:
                self._big_server_process = proc
                self.we_started_big = True
                self._log(f"✅ {message}")
                self._refresh_provider_status()
            else:
                self._log(f"❌ {message}")
                self.we_started_big = False
            self._set_loading(False, False, "")
        except Exception as exc:
            self._record_start_failure("big completion", exc)


    
    def _on_stop_big_brain(self):
        """Stop the Big Brain server on its configured port.

        Stops whatever is listening on the Big Brain port whether this panel
        started it or not (it may be a leftover from a prior run / scripts). The
        panel owns that port, so Stop always acts on it (v2.0.36s fix).
        """
        self._begin_stop_brain(False)

    # ═══════════════════════════════════════════════════════════════════
    # STOP ALL HANDLER
    # ═══════════════════════════════════════════════════════════════════
    def _on_stop_all(self):
        """Stop both Small Brain and Big Brain using port-specific filters."""
        self._log("Stopping all providers...")
        self._on_stop_small_brain()
        self._on_stop_big_brain()

    def _unload_external_model(self, small, provider, endpoint, model, label):
        ok, message = self.provider_checker.unload_provider_model(
            provider, endpoint, model)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._finish_external_lifecycle(
            small, ok, f"{label} {message}"))

    def _load_external_model(self, small, provider, endpoint, model, label):
        ok, message = self.provider_checker.load_provider_model(
            provider, endpoint, model)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._finish_external_lifecycle(
            small, ok, f"{label} {message}"))

    def _finish_external_lifecycle(self, small, ok, message):
        prefix = "✅" if ok else "❌"
        self._log(f"{prefix} {message}")
        self._refresh_provider_status()

    # ═══════════════════════════════════════════════════════════════════
    # MODEL SWITCH HANDLERS
    # ═══════════════════════════════════════════════════════════════════
    def _sync_adapter_model(self, small: bool):
        """Sync the selected model to the corresponding adapter."""
        model_path = self._current_model_path(small)
        if not model_path:
            return
        
        # Try to get the actual model name from the running server first
        model_name = os.path.basename(model_path)
        try:
            port = self._brain_port(small)
            running, models = self.provider_checker.check_llama_server(port, timeout=2)
            if running and models:
                # Find the model that matches our selected file (fuzzy match)
                path_base = os.path.basename(model_path).lower().replace('.gguf', '').replace('-gguf', '')
                for m in models:
                    model_base = m.lower().replace('.gguf', '').replace('-gguf', '')
                    if path_base in model_base or model_base in path_base:
                        model_name = m
                        break
        except Exception:
            pass
        
        if small:
            if self.small_brain is not None:
                self.small_brain.model = model_name
        else:
            if self.big_brain is not None:
                self.big_brain.model = model_name

    def _on_small_brain_model_changed(self, model_name: str):
        """Handle Small Brain model change — restart the brain with the new
        model when it is running, else just record the selection for next Start."""
        # Guard against placeholder/error items (v2.1).
        if not model_name or model_name.startswith(self._PLACEHOLDER_MARKERS):
            return
        from agents.dual_brain_runtime import BrainRole, DualBrainRuntime
        runtime = DualBrainRuntime.from_env()
        cfg = runtime.config(BrainRole.SMALL)
        if cfg.provider != "llamacpp":
            self._select_external_model(True, model_name, runtime, cfg)
            return
        path = self._current_model_path(True)
        if not path:
            return
        self.sb_model_label.setText(f"Model: {os.path.basename(path)}")

        # Sync model to adapter
        self._sync_adapter_model(True)
        self.small_brain_model_changed.emit(model_name)

        # Guard: skip auto-restart if we're currently suppressing model-change restarts
        if getattr(self, "_suppress_model_change_restart", False):
            return

        running, models = self.provider_checker.check_llama_server(self._brain_port(True), timeout=2)
        if running:
            loaded = models[0] if models else ""
            # Only auto-restart if the user explicitly selected a DIFFERENT model
            # than what's loaded. Do NOT trigger on initial sync or probe mismatches.
            if loaded and self._norm_path(loaded) != self._norm_path(path):
                # Debounce: only restart if the selection actually changed
                if getattr(self, "_last_small_model", None) != path:
                    self._last_small_model = path
                    self._restart_brain_with(True, path)
        else:
            # Not running yet — just record the selection for next Start
            self._last_small_model = path

    def _on_big_brain_model_changed(self, model_name: str):
        """Handle Big Brain model change — restart the brain with the new
        model when it is running, else just record the selection for next Start."""
        if not model_name or model_name.startswith(self._PLACEHOLDER_MARKERS):
            return
        from agents.dual_brain_runtime import BrainRole, DualBrainRuntime
        runtime = DualBrainRuntime.from_env()
        cfg = runtime.config(BrainRole.BIG)
        if cfg.provider != "llamacpp":
            self._select_external_model(False, model_name, runtime, cfg)
            return
        path = self._current_model_path(False)
        if not path:
            return
        self.bb_model_label.setText(f"Model: {os.path.basename(path)}")

        # Sync model to adapter
        self._sync_adapter_model(False)
        self.big_brain_model_changed.emit(model_name)

        # Guard: skip auto-restart if we're currently suppressing model-change restarts
        if getattr(self, "_suppress_model_change_restart", False):
            return

        running, models = self.provider_checker.check_llama_server(self._brain_port(False), timeout=2)
        if running:
            loaded = models[0] if models else ""
            if loaded and self._norm_path(loaded) != self._norm_path(path):
                if getattr(self, "_last_big_model", None) != path:
                    self._last_big_model = path
                    self._restart_brain_with(False, path)
        else:
            self._last_big_model = path

    def _select_external_model(self, small: bool, model_name: str, runtime, cfg):
        """Persist an external model ID without treating it as a GGUF path."""
        role_key = "SMALL_BRAIN_MODEL" if small else "BIG_BRAIN_MODEL"
        cfg.model = model_name
        runtime.set_model(cfg.role, model_name)
        os.environ[role_key] = model_name
        try:
            from main import set_env_values
            set_env_values({role_key: model_name})
        except Exception:
            pass
        try:
            from agents.base_worker import _active_worker
            if _active_worker is not None:
                _active_worker.invalidate_provider_registry()
        except Exception:
            pass
        label = self.sb_model_label if small else self.bb_model_label
        label.setText(f"Model: {model_name}")
        self._log(
            f"✅ {'Small' if small else 'Big'} Brain model selected: "
            f"{model_name} ({cfg.provider}); provider will serve it on the next request."
        )
        threading.Thread(
            target=self._load_external_model,
            args=(small, cfg.provider, cfg.endpoint, model_name,
                  "Small Brain" if small else "Big Brain"),
            daemon=True,
        ).start()

    def _on_start_all(self):
        """Start both brains concurrently through their non-blocking probes."""
        self._log("Starting all providers...")
        self._on_start_small_brain()
        self._on_start_big_brain()

    # ═══════════════════════════════════════════════════════════════════
    # STATUS REFRESH — Detects already-running providers
    # ═══════════════════════════════════════════════════════════════════
    def _refresh_provider_status(self):
        """Refresh the status of both providers on a background thread so the
        GUI never blocks on HTTP to the llama-server ports (tab-switch freeze fix)."""
        import threading
        if self._closing:
            return
        thread = threading.Thread(target=self._probe_providers, daemon=True)
        self._provider_probe_thread = thread
        thread.start()

    def _probe_providers(self):
        if self._closing:
            return
        from agents.dual_brain_runtime import BrainRole, DualBrainRuntime
        # Settings can change provider/model values while this widget remains
        # open. Re-resolve from the current environment so probes never use a
        # startup-only runtime snapshot.
        runtime = DualBrainRuntime.from_env()
        self.runtime = runtime

        def _probe(small):
            role = BrainRole.SMALL if small else BrainRole.BIG
            cfg = runtime.config(role)
            if not cfg.enabled:
                return False, [], cfg.provider != "llamacpp", cfg.model
            if cfg.provider == "llamacpp":
                running, models = self.provider_checker.check_llama_server(self._brain_port(small))
                return running, models, False, cfg.model
            server_running, models = self.provider_checker.check_endpoint(cfg.models_path)
            if cfg.provider in ("lmstudio", "ollama"):
                loaded_server, loaded_models = self.provider_checker.check_loaded_provider(
                    cfg.provider, cfg.endpoint)
                selected = (cfg.model or "").strip().lower()
                loaded = {str(item).strip().lower() for item in loaded_models}
                role_loaded = bool(selected and selected in loaded)
                return server_running and loaded_server and role_loaded, models, True, cfg.model
            return server_running, models, True, cfg.model

        try:
            sb_running, sb_models, sb_external, sb_selected = _probe(True)
        except Exception:
            sb_running, sb_models, sb_external, sb_selected = False, [], False, ""
        try:
            bb_running, bb_models, bb_external, bb_selected = _probe(False)
        except Exception:
            bb_running, bb_models, bb_external, bb_selected = False, [], False, ""
        if self._closing:
            return
        try:
            self.provider_probed.emit({
                "sb_running": sb_running, "sb_models": sb_models,
                "bb_running": bb_running, "bb_models": bb_models,
                "sb_external": sb_external, "bb_external": bb_external,
                "sb_selected": sb_selected, "bb_selected": bb_selected,
            })
        except RuntimeError:
            pass

    def _apply_provider_status(self, data):
        """Apply probe results on the GUI thread."""
        sb_running = data["sb_running"]; sb_models = data["sb_models"]
        sb_external = data.get("sb_external", False)
        sb_selected = data.get("sb_selected", "")
        if sb_running:
            self.sb_status.setText("● Running")
            self.sb_status.setStyleSheet("color: #4caf50; font-weight: bold;")
            model_name = sb_selected if sb_selected in sb_models else (sb_models[0] if sb_models else "")
            if model_name:
                self.sb_model_label.setText(f"Model: {os.path.basename(model_name)}")
            self._repopulate_model_combo(True, model_name, sb_models)
            self.sb_start_btn.setEnabled(not sb_external)
            self.sb_stop_btn.setEnabled(not sb_external)
        else:
            self.sb_status.setText("● Stopped")
            self.sb_status.setStyleSheet("color: #ff5252; font-weight: bold;")
            self.sb_model_label.setText("Model: —")
            self._repopulate_model_combo(True, "")
            self.sb_start_btn.setEnabled(not sb_external)
            self.sb_stop_btn.setEnabled(False)

        bb_running = data["bb_running"]; bb_models = data["bb_models"]
        bb_external = data.get("bb_external", False)
        bb_selected = data.get("bb_selected", "")
        if bb_running:
            self.bb_status.setText("● Running")
            self.bb_status.setStyleSheet("color: #4caf50; font-weight: bold;")
            model_name = bb_selected if bb_selected in bb_models else (bb_models[0] if bb_models else "")
            if model_name:
                self.bb_model_label.setText(f"Model: {os.path.basename(model_name)}")
            self._repopulate_model_combo(False, model_name, bb_models)
            self.bb_start_btn.setEnabled(not bb_external)
            self.bb_stop_btn.setEnabled(not bb_external)
        else:
            self.bb_status.setText("● Stopped")
            self.bb_status.setStyleSheet("color: #ff5252; font-weight: bold;")
            self.bb_model_label.setText("Model: —")
            self._repopulate_model_combo(False, "")
            self.bb_start_btn.setEnabled(not bb_external)
            self.bb_stop_btn.setEnabled(False)

        # Update Start All button state
        both_running = sb_running and bb_running
        any_running = sb_running or bb_running
        try:
            if hasattr(self, "start_all_btn") and self.start_all_btn is not None:
                self.start_all_btn.setEnabled(not both_running)
            if hasattr(self, "stop_all_btn") and self.stop_all_btn is not None:
                self.stop_all_btn.setEnabled(any_running)
        except RuntimeError:
            # Widget is already torn down during tab rebuilds; ignore late updates.
            pass

    def _safe_apply_provider_status(self, data):
        """Keep late provider probes from escaping through a Qt signal slot."""
        try:
            self._apply_provider_status(data)
        except Exception as exc:
            self._record_start_failure("provider status refresh", exc)
    
    # ═══════════════════════════════════════════════════════════════════
    # EVENT LOG
    # ═══════════════════════════════════════════════════════════════════
    def _log(self, message):
        """Add a message to the event log."""
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_display.append(f"[{ts}] {message}")
        scrollbar = self.log_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # Public alias so main.py can call providers_tab.append_log(msg)
    # without depending on our private _log name.
    def append_log(self, message):
        self._log(message)
    
    # ═══════════════════════════════════════════════════════════════════
    # CLEANUP
    # ═══════════════════════════════════════════════════════════════════
    def cleanup(self):
        """Stop background threads when widget is destroyed."""
        self.gpu_worker.stop()
        self.gpu_worker.wait(7000)
        for name in (
            "_small_probe_worker", "_big_probe_worker",
            "_small_stop_worker", "_big_stop_worker",
            "_small_launch_worker", "_big_launch_worker",
        ):
            worker = getattr(self, name, None)
            if worker is not None and worker.isRunning():
                if hasattr(worker, "stop"):
                    worker.stop()
                worker.wait(3000)


class ProviderProbeWorker(QThread):
    """Check one provider endpoint without blocking the GUI thread."""

    probe_finished = Signal(bool, object)

    def __init__(self, checker, target, endpoint=False, provider="", model=""):
        super().__init__()
        self.checker = checker
        self.target = target
        self.endpoint = endpoint
        self.provider = provider
        self.model = model

    def run(self):
        try:
            if self.endpoint:
                if self.provider in ("lmstudio", "ollama"):
                    available, models = self.checker.check_loaded_provider(
                        self.provider, self.target, timeout=2)
                    wanted = (self.model or "").strip().lower()
                    loaded = {str(item).strip().lower() for item in models}
                    running = available and bool(wanted and wanted in loaded)
                else:
                    running, models = self.checker.check_endpoint(self.target, timeout=2)
            else:
                running, models = self.checker.check_llama_server(self.target, timeout=2)
        except Exception:
            running, models = False, []
        self.probe_finished.emit(running, models)


class ProviderStopWorker(QThread):
    """Stop one provider process without blocking the GUI thread."""

    stop_finished = Signal()

    def __init__(self, control, small: bool):
        super().__init__()
        self.control = control
        self.small = small

    def run(self):
        self.control._force_stop_brain(self.small)
        self.stop_finished.emit()


# Explicit adapters keep the provider-control API owned by DualBrainControl.
# The implementations remain on the legacy worker class temporarily; unlike
# the old conditional alias loop, each public handler is now deliberate and
# fails clearly if its backend is ever removed.
def _provider_handler(name):
    _NO_ARGUMENT_HANDLERS = {
        "_refresh_small_brain_models", "_refresh_big_brain_models",
        "_on_stop_small_brain", "_on_start_small_brain",
        "_on_start_big_brain", "_on_stop_big_brain", "_on_stop_all",
        "_on_start_all", "_refresh_provider_status", "_probe_providers",
    }

    def handler(self, *args, **kwargs):
        implementation = getattr(BrainLaunchWorker, name, None)
        if implementation is None:
            raise AttributeError(f"Provider handler backend missing: {name}")
        if name in _NO_ARGUMENT_HANDLERS:
            args = ()
        return implementation(self, *args, **kwargs)
    handler.__name__ = name
    handler.__qualname__ = f"DualBrainControl.{name}"
    return handler


for _handler_name in (
    "_refresh_small_brain_models", "_refresh_big_brain_models", "_get_llama_model",
    "_on_stop_small_brain", "_begin_stop_brain", "_on_brain_stopped",
    "_on_start_small_brain", "_probe_before_start", "_on_provider_probe_done",
    "_start_small_brain_after_probe", "_start_external_brain", "_on_small_brain_launched",
    "_on_start_big_brain", "_start_big_brain_after_probe", "_on_big_brain_launched",
    "_on_stop_big_brain", "_on_stop_all", "_on_small_brain_model_changed",
    "_on_big_brain_model_changed", "_sync_adapter_model", "_on_start_all",
    "_unload_external_model", "_load_external_model", "_finish_external_lifecycle",
    "_gpu_free_vram_gb", "_model_vram_need_gb", "_check_vram_affinity",
    "_show_vram_warning", "_refresh_provider_status", "_probe_providers",
    "_apply_provider_status", "_safe_apply_provider_status",
):
    setattr(DualBrainControl, _handler_name, _provider_handler(_handler_name))


# ═══════════════════════════════════════════════════════════════════════════
# REMOVAL INSTRUCTIONS
# ═══════════════════════════════════════════════════════════════════════════
# To completely remove the Dual Brain feature:
#
# 1. DELETE: gui/dual_brain_control.py
# 2. DELETE: gui/chat_tab.py, gui/dialogue_tab.py
# 3. DELETE: agents/big_brain.py, agents/small_brain.py
# 4. DELETE: prompts/big_brain.txt, prompts/small_brain.txt
# 5. DELETE: scripts/start_small_brain.ps1, scripts/start_big_brain.ps1
# 6. EDIT: gui/tab_builders.py — remove create_dual_brain_tab(),
#          create_chat_tab(), create_dialogue_tab()
# 7. EDIT: main.py — remove "Chat" and "Dialogue" from tab_specs
# 8. EDIT: settings.json — remove lm_studio provider (optional)
# 9. EDIT: .env — remove dual brain env vars (optional)
# ═══════════════════════════════════════════════════════════════════════════
