"""Background llama-server process worker."""

import os
import subprocess
import tempfile
import time
import urllib.request
from datetime import datetime

from PySide6.QtCore import QThread, Signal


class BrainLaunchPrepWorker(QThread):
    """Run the slow, widget-free parts of a brain launch OFF the GUI thread.

    Starting a brain does three expensive things before the server can be
    spawned — GGUF preflight validation, a VRAM-affinity estimate (nvidia-smi +
    GGUF header read), and building the llama-server command (which reads the
    chat-template key). On a cold model these total well over a second; doing
    them on the Qt thread froze the window on every Start click. This worker
    receives an already-configured role cfg (all widget values snapshotted by
    the caller) and does only the I/O, then hands the finished command back via
    ``prep_finished`` for a GUI-thread slot to spawn the real launcher.
    """

    # small, ok, message, cmd(list[str] | None)
    prep_finished = Signal(bool, bool, str, object)

    def __init__(self, small: bool, model_path: str, cfg, port: int,
                 gpu_device_index: int, parent=None):
        super().__init__(parent)
        self.small = small
        self.model_path = model_path
        self.cfg = cfg
        self.port = port
        self.gpu_device_index = gpu_device_index

    def run(self):
        label = "Small" if self.small else "Big"
        model = self.model_path
        try:
            # 1) GGUF preflight — reject malformed files before spawning.
            try:
                from agents.providers.gguf_meta import validate_model
                errors = validate_model(model)
            except Exception:
                errors = []
            if errors:
                self.prep_finished.emit(
                    self.small, False,
                    f"❌ {label} Brain model preflight failed: {errors[0]}. "
                    "Download a complete GGUF matching the model architecture "
                    "and llama.cpp build.", None)
                return

            # 2) VRAM-affinity estimate (warn-but-allow; never aborts here).
            try:
                from agents.providers.gguf_meta import estimate_vram_gb
                kv_bytes = {"f32": 4, "f16": 2, "q8_0": 1, "q4_0": 0.5,
                            "auto": 2}.get(self.cfg.kv_cache, 2)
                est = estimate_vram_gb(model, context=self.cfg.context,
                                       kv_type_bytes=kv_bytes)
                need = est.get("total_gb") or est.get("estimate_gb") or 0.0
                free = self._gpu_free_vram_gb(self.gpu_device_index)
                if free is not None and need > 0 and need > free:
                    # Non-fatal: llama.cpp spills to system RAM. Logged, not blocked.
                    self._warn = (f"⚠️ {label} Brain: {os.path.basename(model)} "
                                  f"needs ~{need:.1f} GB but only ~{free:.1f} GB "
                                  "VRAM is free; system-RAM spill is expected.")
            except Exception:
                pass

            # 3) Build the launch command (reads the chat-template key).
            cmd = self.cfg.build_llama_command(model_path=model)
            self.prep_finished.emit(self.small, True, getattr(self, "_warn", ""), cmd)
        except Exception as e:
            self.prep_finished.emit(self.small, False, f"❌ {label} launch prep failed: {e}", None)

    @staticmethod
    def _gpu_free_vram_gb(device_index: int):
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,memory.free",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW)
            if r.returncode != 0:
                return None
            for line in r.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2 and parts[0] == str(device_index):
                    return float(parts[1]) / 1024.0
        except Exception:
            return None
        return None


class BrainLaunchWorker(QThread):
    """Background worker for launching llama-server - prevents GUI freeze."""

    launch_finished = Signal(bool, str, object)  # success, message, process

    def __init__(self, role_name: str, cmd: list, port: int, check_fn=None,
                 visible_console: bool = True):
        super().__init__()
        self.role_name = role_name
        self.cmd = cmd
        self.port = port
        self.check_fn = check_fn or self._default_check
        self.visible_console = bool(visible_console and os.name == "nt")
        self._proc = None
        self.adopted = False  # True when we adopted a pre-existing server (not spawned)
        self._stop_requested = False

    def stop(self):
        """Request cancellation; terminate ONLY a process this worker itself spawned.

        Adopted (pre-existing) servers have ``_proc`` None and ``adopted`` True,
        so this is a no-op for them — the app must never kill a server it did
        not launch (it may be shared with another manager, or externally managed).
        """
        self._stop_requested = True
        proc = self._proc
        if proc is None or getattr(self, "adopted", False):
            return
        if proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    def _default_check(self, port):
        try:
            import urllib.request
            req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/models")
            with urllib.request.urlopen(req, timeout=30) as resp:
                return True
        except Exception:
            # A server under load may not answer /v1/models within 30s.
            # Treat "process still alive" as ready rather than killing it.
            return False

    def _proc_alive(self):
        """True if the child process is still running (even if not answering probes)."""
        return self._proc is not None and self._proc.poll() is None

    def _port_is_bound(self) -> bool:
        """True if any process is LISTENING on 127.0.0.1:<port> right now.

        Uses netstat (not an HTTP probe) so it also catches a server that has
        bound the port but is still loading its model and not yet answering
        /v1/models — the window in which a naive pre-flight would spawn a
        duplicate.
        """
        try:
            out = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW).stdout
        except Exception:
            return False
        for ln in out.splitlines():
            parts = ln.split()
            if len(parts) >= 5 and parts[0] == "TCP":
                local, state = parts[1], parts[3]
                if state == "LISTENING" and local.endswith(f":{self.port}"):
                    return True
        return False

    def _wait_then_adopt(self, max_wait_s: float = 20.0) -> bool:
        """Poll /v1/models for up to ``max_wait_s``; return True once it answers.

        A bound-but-silent port is a server mid-startup. Rather than spawn a
        duplicate, wait for it to come up and adopt it.
        """
        import urllib.request
        deadline = time.monotonic() + max_wait_s
        while time.monotonic() < deadline and not self._stop_requested:
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/models")
                with urllib.request.urlopen(req, timeout=2) as resp:
                    if resp.status == 200:
                        return True
            except Exception:
                pass
            time.sleep(1.0)
        return False

    def run(self):
        """Launch server and wait for it to be ready."""
        import time
        import urllib.request
        # Adopt-existing-listener pre-flight: if something already answers
        # /v1/models on this port, ADOPT it instead of spawning a duplicate
        # llama-server. A second instance can bind the same port (SO_REUSEADDR),
        # producing two PIDs per port and nondeterministic routing — one request
        # may land on a server with a *different* model loaded. Adopting the
        # live server (reported as success, _proc=None) removes that ambiguity
        # as a side effect and means teardown will never terminate a server this
        # app did not spawn. We only Popen when the port is free.
        #
        # A port that is LISTENING but not yet answering /v1/models means a
        # server is mid-startup (loading its model into VRAM). Spawning a second
        # one then is exactly the "two servers on one port" bug, so treat a
        # bound port as "already starting" and wait for it rather than stacking
        # another process.
        if self._port_is_bound():
            # Give an in-flight server a bounded window to answer; if it does,
            # adopt it; if it stays silent, still do NOT spawn a duplicate.
            adopted = self._wait_then_adopt()
            if adopted:
                self.adopted = True
                self._proc = None
                self.launch_finished.emit(
                    True,
                    f"{self.role_name}: adopted existing server on :{self.port} "
                    f"(not spawned; the app will not manage or stop it)",
                    None)
                return
            # Bound but silent after the wait — a server is starting. Report it
            # as in progress rather than piling on a second process.
            self.adopted = True
            self._proc = None
            self.launch_finished.emit(
                True,
                f"{self.role_name}: a server is already starting on :{self.port}; "
                f"not spawning a duplicate",
                None)
            return
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/models")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    self.adopted = True
                    self._proc = None
                    self.launch_finished.emit(
                        True,
                        f"{self.role_name}: adopted existing server on :{self.port} "
                        f"(not spawned; the app will not manage or stop it)",
                        None)
                    return
        except Exception:
            pass
        self.adopted = False
        log_path = os.path.join(tempfile.gettempdir(), f"mrbot-{self.role_name.lower()}-llama-server.log")
        try:
            if self.visible_console:
                # A visible console is useful during setup: it proves that the
                # actual llama-server process was spawned and shows CUDA/model
                # errors immediately. The hidden mode below retains a file log.
                log_file = None
                creationflags = subprocess.CREATE_NEW_CONSOLE
                self._proc = subprocess.Popen(
                    self.cmd, creationflags=creationflags)
            else:
                log_file = open(log_path, "w", encoding="utf-8", errors="replace")
                self._proc = subprocess.Popen(
                    self.cmd,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
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
                    if log_file is not None:
                        log_file.close()
                    try:
                        with open(log_path, encoding="utf-8", errors="replace") as f:
                            tail = f.read()[-1200:].strip()
                    except OSError:
                        tail = ""
                    detail = f"Process exited with code {self._proc.returncode}"
                    if "tensor '" in tail and "not found" in tail:
                        detail += " — the selected GGUF is incomplete or incompatible with this llama.cpp build; re-download it or choose a matching model."
                    self.launch_finished.emit(False, f"{self.role_name}: {detail}\n{tail}", None)
                    return
                # A busy server may not answer /v1/models promptly. Treat a live
                # process as "launched successfully" rather than failing the launch
                # and later terminating a server that is mid-generation.
                if self._proc_alive():
                    if log_file is not None:
                        log_file.close()
                    mode = "visible console" if self.visible_console else f"hidden; log={log_path}"
                    # Hand the spawned process to the caller and DROP our own
                    # reference. On Windows a CREATE_NEW_CONSOLE child's console
                    # window is tied to the Popen handle; if THIS worker is later
                    # deleteLater'd while still holding the only reference, the
                    # handle closes and the visible console tears down even though
                    # the llama-server keeps running. The backend retains `proc`
                    # (for stop/terminate), so releasing it here keeps the console
                    # alive for the process's whole life and still stoppable.
                    spawned = self._proc
                    self._proc = None
                    self.launch_finished.emit(
                        True,
                        f"{self.role_name} ready on :{self.port} ({mode}; process alive, awaiting first request)",
                        spawned,
                    )
                    return
                if self.check_fn(self.port):
                    if log_file is not None:
                        log_file.close()
                    # Same console-handle handoff as above: release our reference
                    # so the worker's deleteLater can't tear down the visible
                    # console; the backend retains `proc` for stop/terminate.
                    spawned = self._proc
                    self._proc = None
                    self.launch_finished.emit(True, f"{self.role_name} ready on :{self.port}", spawned)
                    return
                time.sleep(1.0)

            if log_file is not None:
                log_file.close()
            if self._proc.poll() is not None:
                # Process died — report failure with tail.
                try:
                    with open(log_path, encoding="utf-8", errors="replace") as f:
                        tail = f.read()[-1200:].strip()
                except OSError:
                    tail = ""
                detail = f"Process exited with code {self._proc.returncode}"
                if "tensor '" in tail and "not found" in tail:
                    detail += " — the selected GGUF is incomplete or incompatible with this llama.cpp build; re-download it or choose a matching model."
                self.launch_finished.emit(False, f"{self.role_name}: {detail}\n{tail}", None)
                return
            elif self._stop_requested:
                self.launch_finished.emit(
                    False, f"{self.role_name}: launch cancelled before ready", None)
                return
            else:
                # Process alive but probe never confirmed — that means it is
                # starting slowly (common on large models / cold VRAM). Do NOT
                # terminate it; report "ready, awaiting first request" and let
                # the first chat completion be the real readiness proof.
                # Release our reference so the worker's deleteLater can't tear
                # down the visible console; the backend retains `proc`.
                spawned = self._proc
                self._proc = None
                self.launch_finished.emit(
                    True,
                    f"{self.role_name} ready on :{self.port} ({'visible console' if self.visible_console else f'hidden; log={log_path}'}; process alive, awaiting first request)",
                    spawned,
                )
                return
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


__all__ = ["BrainLaunchWorker", "BrainLaunchPrepWorker"]
