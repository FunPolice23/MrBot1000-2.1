"""Provider lifecycle operations used by the Dual Brain Qt facade."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.request
from typing import Any, Dict, Optional

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


class ProviderLifecycleBackend:
    """Provider-control implementations used by the Qt facade.

    This backend is intentionally free of widget construction. Its methods
    operate on the facade passed as ``self`` for compatibility during the
    extraction; the next slice will replace the remaining dynamic dispatch
    with explicit service calls.
    """

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

    def _validate_model_before_launch(self, small: bool, model_path: str) -> bool:
        """Reject malformed GGUFs before spawning llama-server."""
        try:
            from agents.providers.gguf_meta import validate_model
            errors = validate_model(model_path)
        except Exception as exc:
            self._log(f"⚠️ Model preflight skipped: {exc}")
            return True
        if not errors:
            return True
        label = "Small" if small else "Big"
        self._log(
            f"❌ {label} Brain model preflight failed: {errors[0]}. "
            "Download a complete GGUF matching the model architecture and llama.cpp build.")
        self._set_loading(small, False, "")
        return False
    
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

    def _begin_stop_brain(self, small: bool):
        label = "Small Brain" if small else "Big Brain"
        from agents.runtime.dual_brain import BrainRole, DualBrainRuntime
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
                model = selected_model or configured_cpu_model
                if not model:
                    model = choose_cpu_decision_model(
                        "", self._discover_gguf_models())
                if model and not is_cpu_decision_model(model):
                    self._log(
                        f"⚠️ Small Brain CPU/RAM mode selected {os.path.basename(model)}; "
                        "larger models may be slower but are allowed.")
                if not model:
                    self._log(
                        "❌ Small Brain CPU fallback requires a configured or discovered "
                        "dense/similar model at or below 2B parameters "
                        "(SMALL_BRAIN_CPU_MODEL).")
                    self._set_loading(True, False, "")
                    return
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
        background thread. Coalesced: a call while one is in flight is dropped.
        This is what stops a Start click from stuttering on disk I/O.
        """
        if getattr(self, "_persist_thread", None) is not None                 and self._persist_thread.is_alive():
            return
        values = self._snapshot_settings_values()
        if not values:
            return
        import threading
        self._persist_thread = threading.Thread(
            target=self._write_env_values, args=(values,),
            name="persist-settings", daemon=True)
        self._persist_thread.start()

    def _write_env_values(self, values: dict):
        """Background .env writer — pure file I/O, no Qt/widget access."""
        try:
            import pathlib
            try:
                from main import EnvWriteRefused, set_env_values
            except Exception:
                return
            try:
                set_env_values(values)
            except EnvWriteRefused:
                return
            except Exception:
                repo_env = pathlib.Path(__file__).resolve().parents[2] / ".env"
                try:
                    set_env_values(values, path=repo_env)
                except Exception:
                    return
            for k in ("SMALL_BRAIN_MODEL", "BIG_BRAIN_MODEL", "SHOW_BRAIN_CONSOLES"):
                if k in values:
                    os.environ[k] = values[k]
            self._log("💾 llama.cpp settings and model defaults saved to .env")
        except Exception:
            pass

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
            self._schedule_slot_reprobe(slot)
        else:
            self._log(f"❌ {label} failed to start")
            setattr(self, f"_slot_{slot}_server_process", None)

    def _schedule_slot_reprobe(self, slot: int, attempts: int = 90):
        """Re-probe provider status until the just-launched slot server answers
        (or the bounded ~3 min budget runs out). Mirrors
        ``_on_launch_success_reprobe`` for the extra slots (2+)."""
        if getattr(self, "_closing", False):
            return
        cfg = self._slot_config(slot)
        if cfg is None:
            return
        # Already reachable? Stop rescheduling.
        try:
            running, _models = self.provider_checker.check_llama_server(cfg.port)
        except Exception:
            running = False
        if running:
            self._refresh_provider_status()
            return
        self._refresh_provider_status()
        if attempts > 0:
            QTimer.singleShot(
                2000, lambda: self._schedule_slot_reprobe(slot, attempts - 1))

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

    def _on_temp_preset(self, text: str, spin: QDoubleSpinBox, env_key: str):
        """Apply a temperature preset to the spinbox and persist."""
        presets = {"0.0 (Precise)": 0.0, "0.3 (Low)": 0.3, "0.5 (Default)": 0.5,
                   "0.7 (Medium)": 0.7, "1.0 (Creative)": 1.0, "1.5 (Wild)": 1.5}
        if text in presets:
            spin.setValue(presets[text])
            self._persist_settings()

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
        runtime = DualBrainRuntime.from_env()
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
        runtime = DualBrainRuntime.from_env()
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
        runtime = self.runtime or DualBrainRuntime.from_env()

        def _probe_cfg(cfg):
            """Probe one BrainConfig -> (running, models, external, selected)."""
            if cfg is None or not cfg.enabled:
                return False, [], False, ""
            if cfg.provider == "llamacpp":
                running, models = self.provider_checker.check_llama_server(cfg.port)
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

        # Probe every slot (N-brain): slots 0/1 are the role configs; slots 2+
        # are extra enabled devices. Each becomes a per-slot dict so the GUI can
        # update ALL rows, not just the two role brains (fixes the CPU row
        # stuck at "Checking...").
        slots = runtime.slots()
        slot_results = []
        for i, cfg in enumerate(slots):
            try:
                running, models, external, selected = _probe_cfg(cfg)
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
        sb = slot_results[0] if len(slot_results) > 0 else None
        bb = slot_results[1] if len(slot_results) > 1 else None
        # slot 0 is Big, slot 1 is Small in the runtime ordering.
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
