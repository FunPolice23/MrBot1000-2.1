"""Provider lifecycle operations used by the Dual Brain Qt facade."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.request
from typing import Any, Callable, Dict, Optional, Protocol

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox, QDoubleSpinBox

from agents.providers.provider_lifecycle import ProviderStatusChecker
from gui.workers.brain_launch_worker import BrainLaunchWorker, BrainLaunchPrepWorker
from gui.workers.provider_workers import ProviderProbeWorker, ProviderStopWorker


def _qt_object_alive(obj) -> bool:
    """True when a Qt wrapper still has a live C++ object behind it.

    ``QObject.deleteLater()`` destroys the C++ side while the Python wrapper
    survives, so any later attribute access (``isRunning()``, ``stop()`` …)
    raises ``RuntimeError: libshiboken: Internal C++ object already deleted``.
    Callers that cache QObjects must gate on this before touching them.
    """
    try:
        import shiboken6
        return shiboken6.isValid(obj)
    except Exception:
        # shiboken unavailable: fall back to a probe that would raise if dead.
        try:
            obj.objectName()
            return True
        except RuntimeError:
            return False


# ARCH-ENG-194: THE MIXIN CONTRACT, WRITTEN DOWN.
#
# Every name below is something `ProviderLifecycleBackend` reads off `self` and
# does NOT define itself. They are the facade's, not the backend's. Listing them
# turns 47 implicit dependencies into a checked contract: the guard test asserts
# each one exists on `DualBrainControl`, so removing or renaming one fails a test
# instead of raising AttributeError when the operator clicks Start.
#
# The `bb_*` / `sb_*` entries are the llama-server parameter controls (context,
# GPU layers, batch, threads, KV type, tensor split). They appear here because
# the backend reads them to build the llama command line -- which is why a
# settings-persistence gap in them shows up as a server that ignores the value.
#
# `big_brain`, `small_brain` and `parent` are supplied at runtime by the
# application (brain instances and the Qt parent), so they are required but
# cannot be verified by class inspection alone.
class ProviderLifecycleHost(Protocol):
    """What `ProviderLifecycleBackend` requires of the object it is mixed into."""

    # ?? Methods the backend calls ???????????????????????????????????????????
    _set_loading: Callable[[bool, bool, str], None]
    _record_start_failure: Callable[..., None]
    _repopulate_model_combo: Callable[..., None]
    _current_model_path: Callable[[bool], str]
    _resolve_model_path: Callable[..., str]
    _snapshot_settings_values: Callable[[], dict]
    _brain_port: Callable[[bool], int]
    _brain_models_url: Callable[[bool], str]
    _discover_gguf_models: Callable[[bool], list]
    _kill_llama_on_port: Callable[[int], list]
    _persist_settings: Callable[[], None]
    _restart_brain_with: Callable[..., None]

    # ?? State the backend reads or mutates ??????????????????????????????????
    provider_manager: Any
    provider_checker: Any
    runtime: Any
    provider_probed: bool
    _PLACEHOLDER_MARKERS: Any
    _external_lifecycle_finished: Any
    small_brain_model_changed: Any
    big_brain_model_changed: Any
    log_display: Any
    start_all_btn: Any
    stop_all_btn: Any
    auto_start_check: Any
    show_server_consoles_check: Any
    # Big-brain llama controls
    bb_status: Any
    bb_model_label: Any
    bb_ctx_spin: Any
    bb_gpu_layers_spin: Any
    bb_batch_spin: Any
    bb_threads_spin: Any
    bb_split_combo: Any
    bb_kv_combo: Any
    bb_start_btn: Any
    bb_stop_btn: Any
    # Small-brain llama controls
    sb_status: Any
    sb_model_label: Any
    sb_ctx_spin: Any
    sb_gpu_layers_spin: Any
    sb_batch_spin: Any
    sb_threads_spin: Any
    sb_split_combo: Any
    sb_kv_combo: Any
    sb_start_btn: Any
    sb_stop_btn: Any
    # Supplied at runtime by the application
    big_brain: Any
    small_brain: Any
    parent: Any


#: Every member `ProviderLifecycleHost` requires, as plain strings.
#:
#: Derived from the class annotations plus the three runtime-supplied names, so
#: the guard test has a single list to check rather than re-deriving it (which
#: would let a rename in the backend silently shrink the contract).
HOST_METHODS: tuple = (
    "_set_loading", "_record_start_failure", "_repopulate_model_combo",
    "_current_model_path", "_resolve_model_path", "_snapshot_settings_values",
    "_brain_port", "_brain_models_url", "_discover_gguf_models",
    "_kill_llama_on_port", "_persist_settings", "_restart_brain_with",
)

HOST_ATTRS: tuple = (
    "provider_manager", "provider_checker", "runtime", "provider_probed",
    "_PLACEHOLDER_MARKERS", "_external_lifecycle_finished",
    "small_brain_model_changed", "big_brain_model_changed", "log_display",
    "start_all_btn", "stop_all_btn", "auto_start_check",
    "show_server_consoles_check",
    "bb_status", "bb_model_label", "bb_ctx_spin", "bb_gpu_layers_spin",
    "bb_batch_spin", "bb_threads_spin", "bb_split_combo", "bb_kv_combo",
    "bb_start_btn", "bb_stop_btn",
    "sb_status", "sb_model_label", "sb_ctx_spin", "sb_gpu_layers_spin",
    "sb_batch_spin", "sb_threads_spin", "sb_split_combo", "sb_kv_combo",
    "sb_start_btn", "sb_stop_btn",
    # Supplied at runtime by the application, so class inspection cannot verify
    # them; they are listed so the omission is deliberate rather than forgotten.
    "big_brain", "small_brain", "parent",
)

#: True when `host` provides everything the backend reads off `self`.
#:
#: Runtime-evaluable so the check works on an INSTANCE, where instance
#: attributes (the controls created during `setup_ui`) actually exist. A
#: class-level check would report all 32 attributes as missing, because they are
#: assigned while the UI is built rather than declared on the class.
def host_contract_satisfied(host) -> list:
    """Return the names in `HOST_METHODS` + `HOST_ATTRS` that `host` lacks.

    Empty list means the mixin can be used with this object.
    """
    missing = []
    for name in tuple(HOST_METHODS) + tuple(HOST_ATTRS):
        if not hasattr(host, name):
            missing.append(name)
    return missing

class ProviderLifecycleBackend:
    """Provider-control implementations, MIXED IN to a Qt facade.

    ARCH-ENG-194: THE COUPLING IS NOW DECLARED AND CHECKED, NOT DISCOVERED.

    This backend is intentionally free of widget construction, but it is NOT
    independent of its host. Measured across the two files:

      * 64 methods here, 104 on ``DualBrainControl``, with only two shared names
        (``_log`` and ``cleanup``). Nothing is duplicated -- this is a clean
        horizontal split of provider control away from widget code, which is
        the right shape.
      * but this backend references **115 distinct** ``self.<attr>``, and only
        **48** are defined here. The other **67 live on the widget**: 12 widget
        *methods* (``_set_loading`` x19, ``_record_start_failure`` x6,
        ``_repopulate_model_combo`` x6, ``_current_model_path`` x5,
        ``_brain_port`` x4, ``_resolve_model_path`` x3, ``_snapshot_settings_values``
        x2, ``_brain_models_url``, ``_discover_gguf_models``, ``_kill_llama_on_port``,
        ``_persist_settings``, ``_restart_brain_with``) and 55 data attributes
        (``provider_checker`` x12, ``runtime`` x8, ``sb_status`` x5, the
        ``sb_*`` controls ``_set_loading`` drives, ``_persist_dirty``,
        ``_persist_thread``, ``we_started_*``, ...).

    So ``self`` here means "the facade", and that was previously only knowable by
    grepping. ``ProviderLifecycleHost`` below states the requirement
    explicitly, and ``test_arch_eng_194_mixin_contract.py`` asserts every member
    of it exists on the real widget -- so dropping one becomes a test failure
    instead of an ``AttributeError`` discovered when a user clicks Start.

    WHY COMPOSITION WAS NOT DONE INSTEAD. Passing the widget as ``self`` is
    semantically identical to mixing it in, so "converting" would be a rename,
    not a refactor: ~180 ``self.`` sites inside this file to rewrite, for zero
    architectural gain, against a test surface that already subclasses and
    monkey-patches these methods. Real decoupling needs a view object exposing
    55 attributes and 12 methods -- a rewrite, not a remediation, and not one
    that should be attempted without a dedicated test pass over the Providers &
    GPU tab.

    What this buys instead: the next person who considers the 180-site rewrite
    finds the measured numbers and the reason here, rather than rediscovering
    them.
    """

    # ARCH-ENG-252 (V-01) / ARCH-ENG-253 (V-02): the unreachable temperature
    # preset table and the duplicate llama model probe were deleted. The spin
    # box is the only temperature control, and model selection goes through the
    # live provider lifecycle.
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
                encoding="utf-8", errors="replace",
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

    def _model_vram_need_gb(self, small: bool, model_path: str,
                            context: Optional[int] = None,
                            kv_name: Optional[str] = None) -> Dict[str, Any]:
        """Estimate a model's total VRAM need (weights + KV @ configured ctx).

        Returns {estimate_gb, complete, kv_gb, weights_gb}. Bounded; never raises.
        Falls back to weights+margin when metadata is unreadable.
        """
        ctx = context if context is not None else (
            self.sb_ctx_spin.value() if small else self.bb_ctx_spin.value())
        kv_name = kv_name or (
            self.sb_kv_combo.currentText() if small else self.bb_kv_combo.currentText()) or "f16"
        kv_type_bytes = {
            "f32": 4,
            "f16": 2,
            "q8_0": 1,
            "q4_0": 0.5,
            "auto": 2,
        }.get(kv_name, 2)
        try:
            from agents.providers.gguf_meta import estimate_vram_gb
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
        
        result = {"value": True, "done": False, "warning": ""}
        context = self.sb_ctx_spin.value() if small else self.bb_ctx_spin.value()
        kv_name = (self.sb_kv_combo.currentText() if small else self.bb_kv_combo.currentText()) or "f16"
        
        def _check():
            try:
                est = self._model_vram_need_gb(
                    small, model_path, context=context, kv_name=kv_name)
                need = est.get("total_gb") or est.get("estimate_gb") or 0.0
                free = self._gpu_free_vram_gb(1 if small else 0)
                if free is None or need <= 0:
                    result["value"] = True
                elif need <= free:
                    result["value"] = True
                else:
                    # Never block the GUI with a modal confirmation while a
                    # model is loading. llama.cpp can spill to system RAM;
                    # report the risk and let the background launch continue.
                    result["warning"] = (
                        f"{os.path.basename(model_path)} needs ~{need:.1f} GB, "
                        f"but only ~{free:.1f} GB VRAM is free; system-RAM spill is expected.")
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
        if result["warning"]:
            self._log(f"⚠️ {('Small' if small else 'Big')} Brain: {result['warning']}")
        return result["value"]

    # ARCH-ENG-218: `_validate_model_before_launch` REMOVED.
    #
    # This was a GGUF preflight that nothing called. It was not, however, a
    # missing safety check: `BrainLaunchPrepWorker.run()` performs the identical
    # preflight and ABORTS the launch when it fails --
    #
    #     # 1) GGUF preflight -- reject malformed files before spawning.
    #     errors = validate_model(model)
    #     if errors:
    #         self.prep_finished.emit(self.small, False, "... preflight failed ...", None)
    #         return
    #
    # That is the better placement anyway: it runs on the prep worker, before a
    # command is built or a process spawned, and reports through the
    # `prep_finished` signal the UI already listens to. This copy returned a
    # bool no one read, and set loading state the UI never saw.
    #
    # So it was a SUPERSEDED DUPLICATE, not a hole. Both facts are worth
    # stating, because "zero callers" on its own says nothing -- this function
    # had none, and the safety property it was written for was fully enforced
    # by a method twenty lines away in a different file.

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
    def _on_stop_small_brain(self, *_args):
        """Stop the Small Brain server on its configured port.

        Stops whatever is listening on the Small Brain port whether this panel
        started it or not (it may be a leftover from a prior run / scripts). The
        panel owns that port, so Stop always acts on it (v2.0.36s fix).
        """
        self._begin_stop_brain(True)

    def _runtime_from_settings(self):
        """Build the runtime from the persisted roster, flushing pending edits.

        ARCH-ENG-153: ``BrainRosterPanel._on_changed`` debounces its write
        behind a 400 ms timer, and this is a READ of what that write
        produced. Calling ``DualBrainRuntime.from_settings()`` directly meant
        an edit followed by Start inside the window launched the previous
        model. Every read site goes through here so a new caller cannot
        reintroduce the lag. Never raises.
        """
        try:
            from gui.widgets.brain_roster_panel import flush_pending_roster_edit
            flush_pending_roster_edit(getattr(self, "brain_roster_panel", None))
        except Exception:
            pass
        from agents.runtime.dual_brain import DualBrainRuntime
        return DualBrainRuntime.from_settings()

    def _begin_stop_brain(self, small: bool):
        label = "Small Brain" if small else "Big Brain"
        from agents.runtime.dual_brain import BrainRole, DualBrainRuntime
        runtime = self.runtime or self._runtime_from_settings()
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
    # ── Start re-entrancy guard ────────────────────────────────────────────
    def _start_in_progress(self, small: bool) -> bool:
        """True while a start (probe/prep/launch) is in flight for this brain."""
        return bool(getattr(self, "_small_starting" if small else "_big_starting", False))

    def _set_start_in_progress(self, small: bool, value: bool):
        setattr(self, "_small_starting" if small else "_big_starting", bool(value))

    def _clear_start_in_progress(self, small: bool):
        """Release the start guard on any terminal outcome (done/failed/cancelled)."""
        self._set_start_in_progress(small, False)

    def _on_start_small_brain(self, *_args):
        self._probe_before_start(True)

    def _probe_before_start(self, small: bool):
        label = "Small Brain" if small else "Big Brain"
        # Re-entrancy guard: a start is already in flight for this brain
        # (probe running, prep running, or launcher running). Without this a
        # second click — or Start All racing auto-start, or the model-restart
        # path — spawns a SECOND llama-server on the same port (SO_REUSEADDR
        # lets two bind one port): the "multiple instances" bug. Cleared on
        # every terminal path via _clear_start_in_progress.
        if self._start_in_progress(small):
            self._log(f"ℹ️ {label} start already in progress; ignoring duplicate request.")
            return
        self._set_start_in_progress(small, True)
        try:
            from agents.runtime.dual_brain import BrainRole, DualBrainRuntime
            runtime = self._runtime_from_settings()
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
            self._clear_start_in_progress(small)

    def _on_provider_probe_done(self, small: bool, running: bool, models):
        try:
            if running:
                self._log(f"{'Small' if small else 'Big'} Brain provider is reachable")
                self._clear_start_in_progress(small)
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
            from agents.runtime.dual_brain import BrainRole, DualBrainRuntime
            rt = self._runtime_from_settings()
            cfg = rt.config(BrainRole.SMALL)
            if not cfg.enabled:
                self._log("ℹ️ Small Brain is disabled in Settings; no local server started.")
                self._set_loading(True, False, "")
                # ARCH-ENG-178: every terminal path must release the re-entrancy
                # guard, or the brain logs "start already in progress" forever and
                # can never be started again in this session.
                self._clear_start_in_progress(True)
                return
            active_local = self.provider_manager.resolve_enabled_provider(local=True)
            if active_local != cfg.provider:
                self._log(f"ℹ️ Small Brain has no active {cfg.provider} route; select or enable a provider in Settings.")
                self._set_loading(True, False, "")
                self._clear_start_in_progress(True)      # ARCH-ENG-178
                return
            if cfg.provider != "llamacpp":
                # Hands off to the external-brain path, which owns the terminal
                # transition from there.
                self._clear_start_in_progress(True)      # ARCH-ENG-178
                self._start_external_brain(True, cfg)
                return
            detected_gpu_indexes = {gpu.index for gpu in self.provider_manager.get_gpus()}
            cpu_fallback = (
                cfg.gpu_layers == 0
                or cfg.device not in detected_gpu_indexes
            )
            if (cfg.gpu_layers is None or cfg.gpu_layers < 0) and cfg.device not in detected_gpu_indexes:
                # The persisted dual-GPU default cannot be used on a
                # single-GPU machine. Apply the fallback at the final command
                # construction point so the GUI cannot overwrite it with Auto.
                cfg.gpu_layers = 0
                if getattr(self, "sb_gpu_layers_spin", None) is not None:
                    self.sb_gpu_layers_spin.setValue(0)
                cfg.gpu_label = "CPU / System RAM"
                cfg.decision_support_only = True
                self._log("Small Brain: secondary GPU unavailable; using CPU/system RAM.")
            else:
                self._log("Starting Small Brain (llama-server)...")

            selected_model = self._resolve_model_path(True, self._current_model_path(True))
            model = selected_model
            if cpu_fallback:
                from agents.runtime.dual_brain import (
                    choose_cpu_decision_model, is_cpu_decision_model)
                configured_cpu_model = os.getenv("SMALL_BRAIN_CPU_MODEL", "").strip()
                # v2.1.51 (ARCH-ENG-051): CPU/RAM mode accepts ANY model the
                # operator picks — a 27B Q1 (3.5 GB) runs fine on system RAM and
                # is far more capable than a 2B dense. The old <=2B cap was wrong:
                # the model never crashed, it ran out of TOKEN BUDGET on internal
                # reasoning before it could emit an answer (finish_reason: length,
                # empty content). So we no longer substitute by size; we only
                # resolve a fallback model when NONE is configured, and we let the
                # caller's token-budget fix give reasoning models room to think.
                model = selected_model or configured_cpu_model
                if not model:
                    model = choose_cpu_decision_model(
                        "", self._discover_gguf_models())
                if not model:
                    self._log(
                        "❌ CPU/RAM mode: no model configured or discovered. Set "
                        "SMALL_BRAIN_MODEL / SMALL_BRAIN_CPU_MODEL or pick a model, "
                        "then Start.")
                    self._set_loading(True, False, "")
                    return
                if not is_cpu_decision_model(model):
                    # Informational only — larger CPU models are allowed and run.
                    self._log(
                        f"ℹ️ CPU/RAM mode: {os.path.basename(model)} is a larger model; "
                        "generation on system RAM will be slower (~a few tok/s).")
                owner = self.parent()
                adapter = getattr(owner, "small_brain", None)
                if adapter is not None:
                    adapter.decision_support_only = True
            if not model:
                self._log("❌ Small Brain: no model found. Set SMALL_BRAIN_MODEL in .env or pick a real model, then Start.")
                self._set_loading(True, False, "")
                return
            # Snapshot every GUI value NOW (widgets are GUI-thread-only), then
            # hand the heavy I/O (GGUF preflight, VRAM estimate, command build)
            # to a background prep worker so a Start click never freezes the UI.
            cfg.context = self.sb_ctx_spin.value()
            cfg.threads = self.sb_threads_spin.value()
            cfg.batch = self.sb_batch_spin.value()
            cfg.split_mode = self.sb_split_combo.currentText() or "none"
            cfg.kv_cache = self.sb_kv_combo.currentText() or "f16"
            gpu_l = self.sb_gpu_layers_spin.value()
            cfg.gpu_layers = None if gpu_l < 0 else int(gpu_l)
            if not detected_gpu_indexes or cfg.device not in detected_gpu_indexes:
                cfg.gpu_layers = 0
            cfg.model = model
            # Feedback before the slow prep so the GUI never looks idle.
            self._set_loading(True, True, model)
            # .env write is ~350ms of disk I/O and is not needed before the
            # server spawns (cfg is already snapshotted) — persist off-thread.
            self._persist_settings_async()
            self._dispatch_launch_prep(True, model, cfg)
            
        except Exception as e:
            self._log(f"❌ Failed to start Small Brain: {e}")
            self._record_start_failure("small launch setup", e)
            self._set_loading(True, False, "")

    def _on_small_brain_launched(self, success: bool, message: str, proc):
        """Handle small brain launch completion."""
        self._clear_start_in_progress(True)
        try:
            if success:
                self._small_server_process = proc
                # Adopted (pre-existing) servers arrive with proc=None: don't
                # claim we started it, or teardown would try to manage/stop it.
                self.we_started_small = proc is not None
                self._log(f"✅ {message}")
                self._on_launch_success_reprobe(True)
            else:
                self._log(f"❌ {message}")
                self.we_started_small = False
            self._set_loading(True, False, "")
        except Exception as exc:
            self._record_start_failure("small completion", exc)

    def _persist_settings_async(self):
        """Persist llama.cpp settings to .env without blocking the GUI thread.

        The widget snapshot happens HERE (GUI thread — cheap reads of
        .value()/.currentText()); only the ~350ms atomic .env rewrite runs on a
        background thread. Coalesced with a DIRTY re-arm: an edit arriving while
        a write is in flight is not dropped — the writer runs again so the
        operator's latest change always lands. This is what stops a Start click
        from stuttering on disk I/O.
        """
        if getattr(self, "_persist_thread", None) is not None                 and self._persist_thread.is_alive():
            # A write is in flight and this snapshot is newer than what it is
            # writing. Record that so the drain re-runs the write instead of
            # silently losing the operator's last change.
            self._persist_dirty = True
            self._arm_persist_drain()
            return
        values = self._snapshot_settings_values()
        if not values:
            return
        # ARCH-ENG-314: ride the stale-key set through the writer call chain so
        # un-setting an advanced flag persists exactly as a setting does.
        remove_keys = set(getattr(self, "_stale_env_keys", None) or ())
        self._persist_dirty = False
        # Arm the drain BEFORE spawning the writer (see _persist_settings_async).
        self._arm_persist_drain()
        self._start_persist_write(values, remove_keys)

    def _start_persist_write(self, values: dict, remove_keys=None):
        """Spawn the background .env writer. Called on the GUI thread only."""
        import threading
        self._persist_thread = threading.Thread(
            target=self._persist_settings_worker,
            args=(values, set(remove_keys or ())),
            name="persist-settings", daemon=True)
        self._persist_thread.start()

    def _arm_persist_drain(self):
        """Poll for a pending re-write FROM THE GUI THREAD.

        A ``QTimer.singleShot`` posted by the background writer never fires:
        Qt delivers a functor-only singleShot to the *posting* thread, and that
        thread runs no event loop. So the re-snapshot must be driven from here,
        where both the timer and the widgets live. Purely file I/O stays on the
        worker.

        The facade ``self`` is a QWidget, so ``QTimer(self)`` gives the timer
        GUI-thread affinity and a real owner. If ``self`` is not a QObject
        (unit-test doubles), fall back to an ownerless timer and drive it
        manually.
        """
        if getattr(self, "_persist_drain_timer", None) is not None:
            return
        try:
            timer = QTimer(self)
        except Exception:
            timer = QTimer()
        try:
            timer.setInterval(50)
            timer.timeout.connect(self._drain_persist_dirty)
            self._persist_drain_timer = timer
            timer.start()
        except Exception:
            self._persist_drain_timer = None

    def _drain_persist_dirty(self):
        """GUI-thread slot: deliver queued messages and re-write if dirty."""
        thread = getattr(self, "_persist_thread", None)
        busy = thread is not None and thread.is_alive()
        message = getattr(self, "_pending_persist_message", None)
        if message:
            self._pending_persist_message = None
            try:
                self._log(message)
            except Exception:
                pass
        if busy:
            return  # still writing; check again on the next tick
        if getattr(self, "_persist_dirty", False):
            self._persist_dirty = False
            try:
                values = self._snapshot_settings_values()
            except Exception:
                self._stop_persist_drain()
                return
            if values:
                self._start_persist_write(
                    values,
                    set(getattr(self, "_stale_env_keys", None) or ()))
                return
        # Idle: nothing queued, nothing left to write. The worker sets its
        # confirmation AFTER its final write, so stay armed for one extra tick
        # to be sure it is delivered rather than racing the shutdown.
        if message is None:
            self._persist_idle_ticks = getattr(self, "_persist_idle_ticks", 0) + 1
            if self._persist_idle_ticks >= 3:
                self._persist_idle_ticks = 0
                self._stop_persist_drain()
        else:
            self._persist_idle_ticks = 0

    def _stop_persist_drain(self):
        timer = getattr(self, "_persist_drain_timer", None)
        self._persist_drain_timer = None
        if timer is not None:
            try:
                timer.stop()
                timer.deleteLater()
            except Exception:
                pass

    def _persist_settings_worker(self, values: dict, remove_keys=None):
        """Background .env writer — pure file I/O, never touches Qt."""
        self._write_env_values(values, remove_keys=remove_keys)

    def _write_env_values(self, values: dict, remove_keys=None):
        """Background .env writer — pure file I/O, no Qt/widget access."""
        try:
            import pathlib
            try:
                from main import EnvWriteRefused, set_env_values
            except Exception:
                return
            try:
                set_env_values(values, remove_keys=remove_keys)
            except EnvWriteRefused:
                return
            except Exception:
                repo_env = pathlib.Path(__file__).resolve().parents[2] / ".env"
                try:
                    set_env_values(
                        values, path=repo_env, remove_keys=remove_keys)
                except Exception:
                    return
            for k in ("SMALL_BRAIN_MODEL", "BIG_BRAIN_MODEL", "SHOW_BRAIN_CONSOLES"):
                if k in values:
                    os.environ[k] = values[k]
            # Never touch Qt widgets from this thread — hand the message back
            # to the GUI thread. _log() appends to a QTextEdit directly.
            self._emit_persist_saved()
        except Exception:
            pass

    def _emit_persist_saved(self):
        """Queue the .env save confirmation for the GUI-thread drain.

        ``_log()`` appends to a QTextEdit, so calling it from the writer thread
        is unsafe. Runs ON THE WORKER THREAD, so it must only set a flag: it
        must not create a QTimer here. Qt delivers a functor-only
        ``QTimer.singleShot`` to the *posting* thread, which runs no event loop,
        so that never fired and the message vanished; and ``QTimer(self)`` from
        this thread is refused outright ("Cannot create children for a parent
        that is in a different thread"), leaving a dead timer in
        ``_persist_drain_timer`` that would permanently short-circuit the
        "already armed" guard. The drain was already armed on the GUI thread
        before the writer started, so setting the message is all that is needed.
        """
        self._pending_persist_message = (
            "💾 llama.cpp settings and model defaults saved to .env")

    def _dispatch_launch_prep(self, small: bool, model: str, cfg):
        """Run the slow launch-prep (GGUF preflight, VRAM estimate, command
        build) on a background thread, then spawn the real launcher from the
        GUI-thread completion slot. ``cfg`` must already carry every widget
        value (the caller snapshots them — widgets are GUI-thread-only)."""
        prep = BrainLaunchPrepWorker(
            small, model, cfg, self._brain_port(small),
            gpu_device_index=1 if small else 0, parent=self)
        prep.prep_finished.connect(self._on_launch_prep_finished)
        prep.finished.connect(prep.deleteLater)
        setattr(self, "_small_prep_worker" if small else "_big_prep_worker", prep)
        prep.start()

    def _on_launch_prep_finished(self, small: bool, ok: bool, message: str, cmd):
        """GUI-thread slot: apply prep results and spawn the launcher."""
        if getattr(self, "_closing", False):
            self._clear_start_in_progress(small)
            return
        if message:
            self._log(message)
        if not ok or not cmd:
            self._set_loading(small, False, "")
            self._clear_start_in_progress(small)
            if small:
                self.we_started_small = False
            else:
                self.we_started_big = False
            return
        worker = BrainLaunchWorker(
            "small" if small else "big", cmd, self._brain_port(small),
            visible_console=self.show_server_consoles_check.isChecked())
        if small:
            self._small_launch_worker = worker
            worker.launch_finished.connect(self._on_small_brain_launched)
        else:
            self._big_launch_worker = worker
            worker.launch_finished.connect(self._on_big_brain_launched)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_start_big_brain(self, *_args):
        self._probe_before_start(False)

    def _start_big_brain_after_probe(self):
        """Start Big Brain (llama-server on 5060 Ti, port 1234)."""
        try:
            from agents.runtime.dual_brain import BrainRole, DualBrainRuntime
            rt = self._runtime_from_settings()
            cfg = rt.config(BrainRole.BIG)
            if not cfg.enabled:
                self._log("ℹ️ Big Brain is disabled in Settings; no local server started.")
                self._set_loading(False, False, "")
                self._clear_start_in_progress(False)     # ARCH-ENG-178
                return
            active_local = self.provider_manager.resolve_enabled_provider(local=True)
            if active_local != cfg.provider:
                self._log(f"ℹ️ Big Brain has no active {cfg.provider} route; select or enable a provider in Settings.")
                self._set_loading(False, False, "")
                self._clear_start_in_progress(False)     # ARCH-ENG-178
                return
            if cfg.provider != "llamacpp":
                self._clear_start_in_progress(False)     # ARCH-ENG-178
                self._start_external_brain(False, cfg)
                return
            self._log("Starting Big Brain (llama-server on 5060 Ti)...")

            model = self._resolve_model_path(False, self._current_model_path(False))
            if not model:
                self._log("❌ Big Brain: no model found. Set BIG_BRAIN_MODEL in .env or pick a real model, then Start.")
                self._set_loading(False, False, "")
                self._clear_start_in_progress(False)     # ARCH-ENG-178
                return
            # Snapshot GUI values, then run the heavy I/O off-thread (see the
            # Small Brain path / _dispatch_launch_prep for the rationale).
            cfg.context = self.bb_ctx_spin.value()
            cfg.threads = self.bb_threads_spin.value()
            cfg.batch = self.bb_batch_spin.value()
            cfg.split_mode = self.bb_split_combo.currentText() or "none"
            cfg.kv_cache = self.bb_kv_combo.currentText() or "f16"
            gpu_l = self.bb_gpu_layers_spin.value()
            cfg.gpu_layers = None if gpu_l < 0 else int(gpu_l)
            cfg.model = model
            self._set_loading(False, True, model)
            self._persist_settings_async()
            self._dispatch_launch_prep(False, model, cfg)
            
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
        self._clear_start_in_progress(False)
        try:
            if success:
                self._big_server_process = proc
                # Adopted (pre-existing) servers arrive with proc=None: don't
                # claim we started it, or teardown would try to manage/stop it.
                self.we_started_big = proc is not None
                self._log(f"✅ {message}")
                self._on_launch_success_reprobe(False)
            else:
                self._log(f"❌ {message}")
                self.we_started_big = False
            self._set_loading(False, False, "")
        except Exception as exc:
            self._record_start_failure("big completion", exc)


    
    def _on_stop_big_brain(self, *_args):
        """Stop the Big Brain server on its configured port.

        Stops whatever is listening on the Big Brain port whether this panel
        started it or not (it may be a leftover from a prior run / scripts). The
        panel owns that port, so Stop always acts on it (v2.0.36s fix).
        """
        self._begin_stop_brain(False)

    # ═══════════════════════════════════════════════════════════════════
    # STOP ALL HANDLER
    # ═══════════════════════════════════════════════════════════════════
    def _on_stop_all(self, *_args):
        """Stop both Small Brain and Big Brain using port-specific filters."""
        self._log("Stopping all providers...")
        self._on_stop_small_brain()
        self._on_stop_big_brain()
        # N-brain (Phase 5): also stop any extra slots (2+).
        for slot in range(2, len(getattr(self.runtime, "slots", list)() if self.runtime else [])):
            self._stop_slot(slot)

    # ═══════════════════════════════════════════════════════════════════
    # N-BRAIN SLOT HANDLERS (Phase 5) — slots 2+ (slots 0/1 use the
    # per-role paths above). Fully additive; never touches the Big/Small
    # machinery. Builds the launch command from the slot's BrainConfig and
    # reuses the generic BrainLaunchWorker / _kill_llama_on_port.
    # ═══════════════════════════════════════════════════════════════════
    def _slot_config(self, slot: int):
        """Return the BrainConfig for ``slot`` from the runtime (or None)."""
        if self.runtime is None:
            return None
        getter = getattr(self.runtime, "slot_config", None)
        if getter is None:
            return None
        return getter(slot)

    def _start_slot(self, slot: int):
        """Launch the llama-server for an extra brain slot (2+)."""
        cfg = self._slot_config(slot)
        if cfg is None:
            self._log(f"❌ No configuration for brain slot {slot}.")
            return
        label = f"Brain #{slot} ({cfg.gpu_label or 'device'})"
        if not cfg.enabled:
            self._log(f"ℹ️ {label} is disabled; no server started.")
            return
        # Resolve a model: prefer an already-selected model, else discover one.
        model = cfg.model or self._resolve_model_path(False, "")
        if not model:
            discovered = self._discover_gguf_models() if hasattr(self, "_discover_gguf_models") else []
            model = discovered[0] if discovered else ""
        # v2.1.51 (ARCH-ENG-051): CPU/RAM slots accept ANY model — no size cap.
        # A 27B Q1 (3.5 GB) runs fine on system RAM; the earlier <=2B substitution
        # was based on a wrong OOM theory. Larger CPU models are allowed (just
        # slower); the real fix for "no answer" is the token budget, not the model
        # size. Only log an informational note when the slot is CPU-bound and the
        # model is large, so the operator knows generation will be slow.
        try:
            is_cpu_slot = (cfg.gpu_layers == 0) or bool(getattr(cfg, "decision_support_only", False))
        except Exception:
            is_cpu_slot = False
        if is_cpu_slot and model:
            from agents.runtime.dual_brain import is_cpu_decision_model
            if not is_cpu_decision_model(model):
                self._log(
                    f"ℹ️ {label} (CPU/RAM): {os.path.basename(model)} is a larger model; "
                    "generation on system RAM will be slower (~a few tok/s).")
        if not model:
            self._log(f"❌ {label}: no model found. Pick a model, then Start.")
            return
        cfg.model = model
        # Build the command off the GUI thread's way (build_llama_command reads
        # only GGUF metadata, which is cached); then spawn the generic launcher.
        try:
            cmd = cfg.build_llama_command(model)
        except Exception as exc:
            self._log(f"❌ {label}: failed to build launch command: {exc}")
            return
        self._log(f"Starting {label} (llama-server on port {cfg.port})...")
        worker = BrainLaunchWorker(
            f"slot{slot}", cmd, cfg.port,
            visible_console=getattr(
                getattr(self, "show_server_consoles_check", None), "isChecked",
                lambda: True)())
        setattr(self, f"_slot_{slot}_launch_worker", worker)
        worker.launch_finished.connect(
            lambda ok, msg, proc, s=slot: self._on_slot_launched(s, ok, msg, proc))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_slot_launched(self, slot: int, ok: bool, message: str, proc):
        label = f"Brain #{slot}"
        if message:
            self._log(message)
        if ok:
            self._log(f"✅ {label} started")
            setattr(self, f"_slot_{slot}_server_process", proc)
            # A llama-server answers /v1/models only after the model loads into
            # VRAM (many seconds). Schedule a bounded re-probe so the row flips
            # Stopped -> Running once it's actually reachable (same contract as
            # the slots 0/1 reprobe path).
            setattr(self, f"_slot_{slot}_reprobe_done", False)
            self._schedule_slot_reprobe(slot)
        else:
            self._log(f"❌ {label} failed to start")
            setattr(self, f"_slot_{slot}_server_process", None)

    def _schedule_slot_reprobe(self, slot: int, attempts: int = 90):
        """Re-probe provider status until the just-launched slot server answers
        (or the bounded ~3 min budget runs out). Mirrors
        ``_on_launch_success_reprobe`` for the extra slots (2+).

        ARCH-ENG-223: THE PROBE USED TO RUN ON THE GUI THREAD.

        `check_llama_server` defaults to `timeout=10`
        (`agents/providers/provider_lifecycle.py:53`), and this method is
        invoked from a `QTimer.singleShot`. With the 2 s interval and a 90-attempt
        budget that is up to 3 minutes of GUI-thread blocking HTTP.

        The case this loop exists for is precisely the one that times out: a
        just-launched llama-server accepts the TCP socket immediately but cannot
        answer `/v1/models` until the model is resident in VRAM, which is many
        seconds on a large local model. So the slow path is the NORMAL path here,
        not an edge case.

        Now it copies the pattern `_refresh_provider_status` uses 300 lines
        below in this same file: one daemon thread per probe, skipped while the
        previous one is still alive, with the reschedule already armed before
        the thread starts so the GUI returns immediately. The blocking check
        never leaves this function.
        """
        if getattr(self, "_closing", False):
            return
        cfg = self._slot_config(slot)
        if cfg is None:
            return

        # Already answered? A previous probe reached the server, so this loop has
        # done its job. `running` used to return from THIS frame; with the check
        # moved onto the worker thread the flag has to be read on the next tick
        # instead, or the loop would keep probing for the full 90 attempts after
        # the server was already up.
        if getattr(self, f"_slot_{slot}_reprobe_done", False):
            return

        # Re-arm FIRST, so the loop's cadence does not depend on how long the
        # probe takes. This is the whole point: the timer must fire on schedule
        # whether or not the server is up yet.
        if attempts > 0:
            QTimer.singleShot(
                2000, lambda: self._schedule_slot_reprobe(slot, attempts - 1))

        # Do not pile up threads while a previous probe is still blocked on the
        # socket -- the same guard `_refresh_provider_status` uses.
        pending = getattr(self, "_slot_reprobe_thread", None)
        if pending is not None and pending.is_alive():
            return

        def _probe():
            try:
                running, _models = self.provider_checker.check_llama_server(cfg.port)
            except Exception:
                running = False
            # Read back on the next tick, on the GUI thread. The loop is already
            # armed, so there is nothing to schedule from here.
            setattr(self, f"_slot_{slot}_reprobe_done", bool(running))
            self._refresh_provider_status()

        thread = threading.Thread(
            target=_probe, daemon=True, name=f"slot-reprobe-{slot}")
        self._slot_reprobe_thread = thread
        thread.start()

    def _stop_slot(self, slot: int):
        """Stop an extra brain slot (2+) by terminating its child or its port."""
        cfg = self._slot_config(slot)
        port = cfg.port if cfg is not None else None
        label = f"Brain #{slot}"
        self._log(f"Stopping {label}...")
        proc = getattr(self, f"_slot_{slot}_server_process", None)
        stopped = False
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
                stopped = True
            except Exception:
                try:
                    proc.kill()
                    stopped = True
                except Exception:
                    pass
        # Fall back to killing whatever listens on the slot's port.
        if not stopped and port is not None and hasattr(self, "_kill_llama_on_port"):
            try:
                self._kill_llama_on_port(port)
                stopped = True
            except Exception:
                pass
        if stopped:
            self._log(f"✅ {label} stopped")
            setattr(self, f"_slot_{slot}_server_process", None)
        else:
            self._log(f"ℹ️ {label} was not running")

    def _unload_external_model(self, small, provider, endpoint, model, label):
        ok, message = self.provider_checker.unload_provider_model(
            provider, endpoint, model)
        self._external_lifecycle_finished.emit(
            small, ok, f"{label} {message}")

    def _load_external_model(self, small, provider, endpoint, model, label):
        ok, message = self.provider_checker.load_provider_model(
            provider, endpoint, model)
        self._external_lifecycle_finished.emit(
            small, ok, f"{label} {message}")

    def _finish_external_lifecycle(self, small, ok, message):
        prefix = "✅" if ok else "❌"
        self._log(f"{prefix} {message}")
        self._set_loading(small, False, "")
        self._refresh_provider_status()

    # ═══════════════════════════════════════════════════════════════════
    # MODEL SWITCH HANDLERS
    # ═══════════════════════════════════════════════════════════════════
    def _sync_adapter_model(self, small: bool):
        """Sync the selected model to the corresponding adapter."""
        model_path = self._current_model_path(small)
        if not model_path:
            return
        
        # Do not probe the server here. This method is called directly from a
        # combo-box signal, so even a short HTTP timeout would freeze the GUI.
        # The server's canonical model id is only needed by the background
        # selection probe that decides whether a restart is required.
        model_name = os.path.basename(model_path)
        
        if small:
            if self.small_brain is not None:
                self.small_brain.model = model_name
        else:
            if self.big_brain is not None:
                self.big_brain.model = model_name

    def _probe_model_selection(self, small: bool, path: str):
        """Check the loaded model off the Qt thread after a combo selection."""
        probes = getattr(self, "_model_selection_probes", None)
        if probes is None:
            probes = {}
            self._model_selection_probes = probes
        pending = getattr(self, "_pending_model_selections", None)
        if pending is None:
            pending = {}
            self._pending_model_selections = pending
        old = probes.get(small)
        # A finished probe is deleteLater()'d, so its Python wrapper can outlive
        # the C++ object. Calling isRunning() on that dead wrapper raises
        # "libshiboken: Internal C++ object already deleted" — check validity
        # first, and drop a stale entry so it can never be reused.
        if old is not None and not _qt_object_alive(old):
            probes.pop(small, None)
            old = None
        if old is not None and old.isRunning():
            pending[small] = path
            old.requestInterruption()
            return
        worker = ProviderProbeWorker(
            self.provider_checker,
            self._brain_port(small),
        )
        probes[small] = worker
        worker.probe_finished.connect(
            lambda running, models, s=small, p=path:
            self._on_model_selection_probe_done(s, p, running, models)
        )
        worker.finished.connect(lambda s=small, w=worker: self._on_probe_worker_finished(s, w))
        worker.start()

    def _on_probe_worker_finished(self, small: bool, worker):
        """Drop the probe reference when its thread ends.

        Must run BEFORE ``deleteLater`` so the dict never holds a wrapper whose
        C++ object is already gone.
        """
        probes = getattr(self, "_model_selection_probes", None)
        if probes is not None and probes.get(small) is worker:
            probes.pop(small, None)
        try:
            worker.deleteLater()
        except RuntimeError:
            pass

    def _on_model_selection_probe_done(self, small: bool, path: str,
                                       running: bool, models):
        """Apply a background model probe result on the Qt thread."""
        pending = getattr(self, "_pending_model_selections", {})
        latest = pending.pop(small, None)
        if latest is not None and latest != path:
            self._probe_model_selection(small, latest)
            return
        if getattr(self, "_suppress_model_change_restart", False):
            return
        if running:
            loaded = models[0] if models else ""
            if loaded and not self.provider_checker.model_ids_match(path, loaded):
                attr = "_last_small_model" if small else "_last_big_model"
                if getattr(self, attr, None) != path:
                    setattr(self, attr, path)
                    self._restart_brain_with(small, path)
        else:
            setattr(self, "_last_small_model" if small else "_last_big_model", path)

    def _persist_role_model(self, small: bool, model_name: str, runtime, cfg, *, persist=False):
        """Apply a model selection, optionally saving it as the next default.

        ``persist`` defaults to **False**: writing the operator's `.env` requires an
        explicit opt-in. Every production caller passes it explicitly, and a default
        of True let a test run rewrite `.env` (resetting BIG_BRAIN_MODEL to a path
        that need not exist).
        """
        model_name = str(model_name or "").strip()
        if not model_name:
            return
        role_key = "SMALL_BRAIN_MODEL" if small else "BIG_BRAIN_MODEL"
        cfg.model = model_name
        runtime.set_model(cfg.role, model_name)
        if not persist:
            os.environ[role_key] = model_name
            return
        try:
            from main import set_env_values
            set_env_values({role_key: model_name})
        except Exception:
            pass
        os.environ[role_key] = model_name

    def _on_small_brain_model_changed(self, model_name: str):
        """Handle Small Brain model change — restart the brain with the new
        model when it is running, else just record the selection for next Start."""
        # Guard against placeholder/error items (v2.1).
        if not model_name or model_name.startswith(self._PLACEHOLDER_MARKERS):
            return
        # Guard: skip if the model hasn't actually changed (combo refresh).
        if getattr(self, "_last_small_model_emitted", None) == model_name:
            return
        from agents.runtime.dual_brain import BrainRole, DualBrainRuntime
        runtime = self._runtime_from_settings()
        cfg = runtime.config(BrainRole.SMALL)
        if cfg.provider != "llamacpp":
            self._select_external_model(True, model_name, runtime, cfg)
            return
        path = self._current_model_path(True)
        if not path:
            return
        self._persist_role_model(True, path, runtime, cfg, persist=False)
        self.sb_model_label.setText(f"Model: {os.path.basename(path)}")

        # Sync model to adapter
        self._sync_adapter_model(True)
        self._last_small_model_emitted = model_name
        self.small_brain_model_changed.emit(model_name)

        # Guard: skip auto-restart if we're currently suppressing model-change restarts
        if getattr(self, "_suppress_model_change_restart", False):
            return

        self._probe_model_selection(True, path)

    def _on_big_brain_model_changed(self, model_name: str):
        """Handle Big Brain model change — restart the brain with the new
        model when it is running, else just record the selection for next Start."""
        if not model_name or model_name.startswith(self._PLACEHOLDER_MARKERS):
            return
        # Guard: skip if the model hasn't actually changed (combo refresh).
        if getattr(self, "_last_big_model_emitted", None) == model_name:
            return
        from agents.runtime.dual_brain import BrainRole, DualBrainRuntime
        runtime = self._runtime_from_settings()
        cfg = runtime.config(BrainRole.BIG)
        if cfg.provider != "llamacpp":
            self._select_external_model(False, model_name, runtime, cfg)
            return
        path = self._current_model_path(False)
        if not path:
            return
        self._persist_role_model(False, path, runtime, cfg, persist=False)
        self.bb_model_label.setText(f"Model: {os.path.basename(path)}")

        # Sync model to adapter
        self._sync_adapter_model(False)
        self._last_big_model_emitted = model_name
        self.big_brain_model_changed.emit(model_name)

        # Guard: skip auto-restart if we're currently suppressing model-change restarts
        if getattr(self, "_suppress_model_change_restart", False):
            return

        self._probe_model_selection(False, path)

    def _select_external_model(self, small: bool, model_name: str, runtime, cfg):
        """Persist an external model ID without treating it as a GGUF path."""
        self._persist_role_model(small, model_name, runtime, cfg, persist=False)
        try:
            from agents.brains.base_worker import _active_worker
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

    def _on_start_all(self, *_args):
        """Start every enabled brain slot through its per-slot start path.

        N-brain: starts slots 0/1 via the Big/Small handlers and slots 2+ via the
        generalized slot path, so "Start All Brains" launches the CPU/RAM brain
        (and any extra GPU) too — not just the two primary llama servers.
        """
        self._log("Starting all providers...")
        n_slots = len(getattr(self.runtime, "slots", list)() if self.runtime else [])
        if n_slots <= 2:
            # Legacy 2-brain fast path (unchanged behavior).
            self._on_start_small_brain()
            self._on_start_big_brain()
            return
        for slot in range(n_slots):
            cfg = self._slot_config(slot)
            if cfg is None or not getattr(cfg, "enabled", True):
                continue
            if slot == 0:
                self._on_start_big_brain()
            elif slot == 1:
                self._on_start_small_brain()
            else:
                self._start_slot(slot)

    def maybe_auto_start(self):
        """Auto-start both llama-server instances if the user opted in.

        Called once, deferred, after the app window is shown. Each brain is
        started through its existing non-blocking probe path, so an instance
        that is already reachable, disabled, or on a non-local route is left
        alone (idempotent). Never blocks the GUI thread.
        """
        if not self.auto_start_check.isChecked():
            self._log("ℹ️ Auto-start disabled in Quick Actions; servers not started.")
            return
        self._log("🚀 Auto-start enabled — launching both servers...")
        self._on_start_small_brain()
        self._on_start_big_brain()

    # ═══════════════════════════════════════════════════════════════════
    # STATUS REFRESH — Detects already-running providers
    # ═══════════════════════════════════════════════════════════════════
    def _refresh_provider_status(self, *_args):
        """Refresh the status of both providers on a background thread so the
        GUI never blocks on HTTP to the llama-server ports (tab-switch freeze fix)."""
        import threading
        if self._closing:
            return
        # v2.1.60 (ARCH-ENG-073): the periodic liveness timer (4s) can fire while
        # a previous probe is still running (a hung port blocks up to the probe
        # timeout). Spawning a thread every tick would pile them up. Skip this
        # tick if the last probe thread is still alive; it will emit its result
        # and the next tick resumes normal polling.
        prev = getattr(self, "_provider_probe_thread", None)
        if prev is not None and prev.is_alive():
            return
        thread = threading.Thread(target=self._probe_providers, daemon=True)
        self._provider_probe_thread = thread
        thread.start()

    def _probe_providers(self, *_args):
        if self._closing:
            return
        from agents.runtime.dual_brain import BrainRole, DualBrainRuntime
        # Settings can change provider/model values while this widget remains
        # open. Re-resolve from the current environment so probes never use a
        # startup-only runtime snapshot.
        runtime = self.runtime or self._runtime_from_settings()

        def _probe_cfg(cfg):
            """Probe one BrainConfig -> (running, models, external, selected)."""
            if cfg is None or not cfg.enabled:
                return False, [], False, ""
            if cfg.provider == "llamacpp":
                # v2.1.60 (ARCH-ENG-073): short timeout so a hung/dead port is
                # detected within the 4s liveness window instead of the 10s
                # default, which would leave a dead brain showing "Running".
                running, models = self.provider_checker.check_llama_server(
                    cfg.port, timeout=2)
                return running, models, False, cfg.model
            # Pass the provider so a CLOUD probe carries its Bearer token —
            # without it a valid cloud brain probes 401 and its row shows
            # "Stopped" forever.
            # Short timeout (2s), matching the llamacpp path above: the default
            # 10s lets an unreachable cloud endpoint exceed the 4s liveness
            # window and the status-refresh wait, so the probe never emits and
            # every row sticks at "Checking...".
            server_running, models = self.provider_checker.check_endpoint(
                cfg.models_path, timeout=2, provider=cfg.provider)
            if cfg.provider in ("lmstudio", "ollama"):
                loaded_server, loaded_models = self.provider_checker.check_loaded_provider(
                    cfg.provider, cfg.endpoint, timeout=2)
                selected = (cfg.model or "").strip().lower()
                loaded = {str(item).strip().lower() for item in loaded_models}
                role_loaded = bool(selected and selected in loaded)
                return server_running and loaded_server and role_loaded, models, True, cfg.model
            return server_running, models, True, cfg.model

        def _probe_with_deadline(cfg, deadline_s: float = 2.0):
            """Run _probe_cfg with a HARD total deadline.

            urlopen(timeout=N) is a PER-OPERATION timeout (connect + each read),
            so a busy/trickling llama-server can keep a read alive past N by
            sending data in small chunks — the probe then blocks past the status
            wait and rows stick at "Checking...". Run the check on a daemon
            sub-thread and join with a hard deadline; on timeout treat the slot
            as Stopped (never block the whole refresh).
            """
            import threading
            box = {}

            def _run():
                try:
                    box["v"] = _probe_cfg(cfg)
                except Exception:
                    box["v"] = (False, [], False, "")

            t = threading.Thread(target=_run, daemon=True)
            t.start()
            t.join(deadline_s)
            return box.get("v", (False, [], False, ""))

        # Probe one status entry per VISIBLE row (N-brain), not per runtime
        # slot. _build_provider_rows can render more rows than runtime.slots()
        # returns (the empty-env fixture has 0 runtime slots but the rows are
        # synthesized), and _apply_slot_statuses matches entry["slot"] to
        # rows[slot] by index — so emitting per runtime-slot left the extra
        # rows stuck at "Checking...". Map each row to its slot config
        # (Stopped when none) so the status count always matches the rows.
        rows = getattr(self, "_provider_rows", None)
        if rows:
            slot_results = []
            for i, row in enumerate(rows):
                cfg = None
                try:
                    cfg = runtime.slot_config(getattr(row, "slot", i))
                except Exception:
                    cfg = None
                try:
                    running, models, external, selected = _probe_with_deadline(cfg)
                except Exception:
                    running, models, external, selected = False, [], False, ""
                role = getattr(row, "role", "") or ("big" if i == 0 else "small")
                slot_results.append({
                    "slot": i,
                    "role": role,
                    "device_id": getattr(cfg, "device_id", "") if cfg is not None else "",
                    "running": running, "models": models,
                    "external": external, "selected": selected,
                })
        else:
            # Standalone backend (no rendered rows): fall back to runtime slots.
            slots = runtime.slots()
            slot_results = []
            for i, cfg in enumerate(slots):
                try:
                    running, models, external, selected = _probe_with_deadline(cfg)
                except Exception:
                    running, models, external, selected = False, [], False, ""
                slot_results.append({
                    "slot": i,
                    "role": cfg.role.value if hasattr(cfg.role, "value") else str(cfg.role),
                    "device_id": getattr(cfg, "device_id", ""),
                    "running": running, "models": models,
                    "external": external, "selected": selected,
                })
        # Legacy keys for slots 0/1 (back-compat with existing consumers).
        # Slot 0 = Big Brain, slot 1 = Small Brain (runtime ordering).
        bb = slot_results[0] if len(slot_results) > 0 else None
        sb = slot_results[1] if len(slot_results) > 1 else None
        def _legacy(entry):
            if entry is None:
                return False, [], False, ""
            return entry["running"], entry["models"], entry["external"], entry["selected"]
        bb_running, bb_models, bb_external, bb_selected = _legacy(bb)
        sb_running, sb_models, sb_external, sb_selected = _legacy(sb)
        if self._closing:
            return
        try:
            self.provider_probed.emit({
                "slots": slot_results,
                "sb_running": sb_running, "sb_models": sb_models,
                "bb_running": bb_running, "bb_models": bb_models,
                "sb_external": sb_external, "bb_external": bb_external,
                "sb_selected": sb_selected, "bb_selected": bb_selected,
            })
        except RuntimeError:
            pass

    def _on_launch_success_reprobe(self, small: bool, attempts: int = 90):
        """Re-probe until a just-launched server actually answers.

        The launch worker reports success as soon as the process is alive, but
        a llama-server loading a model into VRAM does not answer /v1/models for
        many seconds afterwards. A single immediate probe therefore leaves the
        status at "Stopped" and the operator has to click Start a second time
        to see it go reachable. Re-probe every 2s until the just-launched
        brain reports reachable, or the bounded budget (~3 min) runs out.
        """
        if getattr(self, "_closing", False):
            return
        flag = "_sb_reachable" if small else "_bb_reachable"
        if getattr(self, flag, False):
            return
        self._refresh_provider_status()
        if attempts > 0:
            QTimer.singleShot(
                2000, lambda: self._on_launch_success_reprobe(small, attempts - 1))

    def _apply_provider_status(self, data):
        """Apply probe results on the GUI thread."""
        self._sb_reachable = bool(data.get("sb_running"))
        self._bb_reachable = bool(data.get("bb_running"))
        # ── Legacy sb_/bb_ attribute path (slots 0/1) ──────────────────────
        # v2.1.52 (ARCH-ENG-052): this block touches self.sb_status / bb_status,
        # which are only aliased when >=2 provider rows exist (see
        # _alias_legacy_provider_attrs, which returns early for <2 rows). When a
        # brain is disabled (e.g. CPU unchecked on a single-GPU box) the alias is
        # absent and these setText() calls raise AttributeError — which aborted
        # the WHOLE method before _apply_slot_statuses() ran, leaving every row
        # stuck at its placeholder. The per-slot path below is authoritative for
        # the N-brain UI, so this legacy block is best-effort and must NEVER
        # abort the method. Wrap it and fall through.
        try:
            sb_running = data["sb_running"]; sb_models = data["sb_models"]
            sb_external = data.get("sb_external", False)
            sb_selected = data.get("sb_selected", "")
            if sb_running:
                sb_selected_available = (
                    not sb_selected or not sb_models
                    or any(self.provider_checker.model_ids_match(sb_selected, model)
                           for model in sb_models)
                )
                self.sb_status.setText(
                    "● Running" if sb_selected_available
                    else "● Running · selected model differs from loaded")
                self.sb_status.setStyleSheet(
                    "color: #4caf50; font-weight: bold;" if sb_selected_available
                    else "color: #ffb74d; font-weight: bold;")
                model_name = sb_selected or (sb_models[0] if sb_models else "")
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
                bb_selected_available = (
                    not bb_selected or not bb_models
                    or any(self.provider_checker.model_ids_match(bb_selected, model)
                           for model in bb_models)
                )
                self.bb_status.setText(
                    "● Running" if bb_selected_available
                    else "● Running · selected model differs from loaded")
                self.bb_status.setStyleSheet(
                    "color: #4caf50; font-weight: bold;" if bb_selected_available
                    else "color: #ffb74d; font-weight: bold;")
                model_name = bb_selected or (bb_models[0] if bb_models else "")
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
            both_running = sb_running and bb_running
            any_running = sb_running or bb_running
        except (AttributeError, RuntimeError):
            # Missing legacy attrs (disabled brain) or torn-down widget: the
            # per-slot path below is authoritative, so just skip the legacy UI.
            sb_running = data.get("sb_running"); bb_running = data.get("bb_running")
            both_running = bool(sb_running and bb_running)
            any_running = bool(sb_running or bb_running)
        try:
            if hasattr(self, "start_all_btn") and self.start_all_btn is not None:
                self.start_all_btn.setEnabled(not both_running)
            if hasattr(self, "stop_all_btn") and self.stop_all_btn is not None:
                self.stop_all_btn.setEnabled(any_running)
        except RuntimeError:
            # Widget is already torn down during tab rebuilds; ignore late updates.
            pass

        # N-brain: update EVERY provider row's status from the per-slot probe so
        # slots 2+ (e.g. the CPU/RAM brain) reflect Running/Stopped instead of
        # staying stuck at their initial "Checking...". Slots 0/1 were handled
        # above via the legacy sb_/bb_ paths; this covers all rows uniformly
        # (and re-affirms 0/1, which is harmless and keeps them consistent).
        self._apply_slot_statuses(data.get("slots") or [])

    def _apply_slot_statuses(self, slot_results):
        """Push per-slot probe results into the Provider Control rows."""
        rows = getattr(self, "_provider_rows", None)
        if not rows or not slot_results:
            return
        for entry in slot_results:
            slot = entry.get("slot")
            if slot is None or not (0 <= slot < len(rows)):
                continue
            row = rows[slot]
            running = bool(entry.get("running"))
            models = entry.get("models") or []
            selected = entry.get("selected") or ""
            if running:
                selected_ok = (
                    not selected or not models
                    or any(self.provider_checker.model_ids_match(selected, m)
                           for m in models))
                row.set_status(
                    "● Running" if selected_ok
                    else "● Running · selected model differs from loaded",
                    "#4caf50" if selected_ok else "#ffb74d")
                model_name = selected or (models[0] if models else "")
                if model_name:
                    row.set_model(model_name)
                row.set_running(True)
            else:
                row.set_status("● Stopped", "#ff5252")
                row.set_running(False)

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
        """Stop background threads before the widget is destroyed.

        Sets the closing flag first so background callbacks stop re-arming,
        joins the provider-probe thread, then stops the GPU poller and every
        per-brain worker. Each stop is guarded: a worker already processed by
        deleteLater() raises RuntimeError from isRunning(), and letting that
        escape would abort teardown and leave the remaining threads running
        (the "QThread: Destroyed while thread is still running" failure).
        """
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
            "_small_prep_worker", "_big_prep_worker",
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


__all__ = ["ProviderLifecycleBackend"]
