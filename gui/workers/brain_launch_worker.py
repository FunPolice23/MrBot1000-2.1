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

            # 1b) Soft arch-support warning (Phase G, ARCH-ENG-097). A model
            # whose architecture this llama.cpp build doesn't know (e.g. a very
            # new arch) fails to load with 'unknown model architecture'. Warn
            # the operator up front but do NOT hard-block — a llama.cpp update
            # may add it, and the operator can still try.
            try:
                from agents.providers.gguf_meta import arch_supported, detect_arch
                if not arch_supported(model):
                    arch = detect_arch(model)
                    self.prep_finished.emit(
                        self.small, True,
                        f"⚠️ {label} Brain: architecture '{arch}' is not known to "
                        f"this llama.cpp build — it will likely fail to load "
                        f"('unknown model architecture'). Update llama.cpp or "
                        f"pick a supported model.", None)
                    return
            except Exception:
                pass

            # 2) VRAM-affinity estimate (v2.1.52, ARCH-ENG-052).
            # Two brains can share ONE GPU (e.g. a single-GPU box where the CPU
            # pool is disabled). llama.cpp WILL spill weights/KV to system RAM
            # when VRAM is short, so we do NOT hard-block — but a large over-
            # allocation makes the CUDA allocator fail hard, which on Windows
            # routinely triggers a TDR driver reset -> full crash/reboot. The 32k
            # KV cache is usually the avoidable part (a 4B dense @32k is ~7.5 GB,
            # ~4.3 GB of it KV). So warn LOUDLY with the exact shortfall and the
            # fix (lower context / stop the other brain / smaller model) instead
            # of the old quiet note.
            try:
                from agents.providers.gguf_meta import estimate_vram_gb
                kv_bytes = {"f32": 4, "f16": 2, "q8_0": 1, "q4_0": 0.5,
                            "auto": 2}.get(self.cfg.kv_cache, 2)
                est = estimate_vram_gb(model, context=self.cfg.context,
                                       kv_type_bytes=kv_bytes)
                need = est.get("total_gb") or est.get("estimate_gb") or 0.0
                kv_gb = est.get("kv_gb") or 0.0
                free = self._gpu_free_vram_gb(self.gpu_device_index)
                if free is not None and need > 0 and need > free:
                    over = need - free
                    self._warn = (
                        f"⚠️ {label} Brain VRAM RISK: {os.path.basename(model)} needs "
                        f"~{need:.1f} GB but only ~{free:.1f} GB is free (short by "
                        f"~{over:.1f} GB) — another brain may already be on this GPU. "
                        f"It will spill to system RAM, but a large overrun can crash "
                        f"the Windows GPU driver. Lower the context (KV cache is "
                        f"~{kv_gb:.1f} GB at {self.cfg.context} tokens), stop the other "
                        f"brain, or pick a smaller model.")
            except Exception:
                pass

            # 2b) System-RAM contention guard (v2.1.55, ARCH-ENG-055).
            # A GPU brain is NOT VRAM-isolated: llama.cpp mmaps the GGUF, so the
            # model's weights live in the system page cache and are faulted into
            # resident RAM under memory pressure. When the CPU/RAM brain then
            # generates and builds its KV cache, it drains system RAM, which
            # forces the GPU brain's ~10 GB model pages resident — the two
            # footprints collide and the GPU brain's llama-server hits a failed
            # allocation and ABORTS (silently: no OS crash, no GPU TDR). This is
            # the "big brain terminal just exits when I Chat the small brain"
            # report. We measure REAL running-server RAM for the other brains
            # (not an estimate), add this brain's own weights+KV, and warn LOUDLY
            # when the total would leave too little headroom — warn-only, never a
            # hard block (llama.cpp legitimately spills; the operator decides).
            try:
                self._warn = self._system_ram_contention_warn(label, model) or getattr(self, "_warn", "")
            except Exception:
                pass

            # 2c) The multi-model contention accounting (ARCH-ENG-231 -> 310).
            #
            # `brain_contention.can_add_brain` is the only component in this
            # codebase that reasons about VRAM, system RAM and CPU cores TOGETHER,
            # across all committed placements. It once had ZERO production
            # callers; ARCH-ENG-231 wired it here, and until ARCH-ENG-310 it
            # could hard-REFUSE this launch when the estimate outran free VRAM
            # by the severe threshold.
            #
            # ARCH-ENG-310: warn-only. A model larger than the card still loads
            # (llama.cpp spills the excess to system RAM) and the operator gets
            # the slower-generation note instead of a refusal. See
            # `_contention_gate` for the full history of why the refusal came
            # out; `_warn` here is only for the launch result banner.
            self._contention_gate(label, model)

            # 3) Build the launch command (reads the chat-template key).
            cmd = self.cfg.build_llama_command(model_path=model)
            self.prep_finished.emit(self.small, True, getattr(self, "_warn", ""), cmd)
        except Exception as e:
            self.prep_finished.emit(self.small, False, f"❌ {label} launch prep failed: {e}", None)

    # ARCH-ENG-310: the gate no longer refuses anything (see `_contention_gate`);
    # its only output is a warning appended to `self._warn`.
    _SEVERE_OVERRUN_GB = None

    def _contention_gate(self, label: str, model: str):
        """Compose this launch's multi-model VRAM contention warning.

        ARCH-ENG-310. Returns "" to proceed -- ALWAYS. A warning, when there
        is one, is appended to ``self._warn`` and the launch goes ahead: a
        model larger than the card still loads (llama.cpp spills the excess
        to system RAM) and the operator gets the slower-generation note
        instead of a refusal.

        History: ARCH-ENG-231 wired this as a fail-closed gate that refused a
        launch when the estimate outran free VRAM by `_SEVERE_OVERRUN_GB`
        (4 GB, later 6). On a 16 GB card a ~22 GB big brain trips any such
        threshold -- and a threshold on an ESTIMATE is worse than the risk it
        guards, because the operator has now seen the model actually work
        (slower, swapped) after overriding the refusal. So the risk decision
        the override encoded is now the policy itself: warn and proceed.

        Legacy knob retained: ``MRBOT_ALLOW_RISKY_LAUNCH=1`` silences even
        the warning, for operators who do not want the note at all.
        """
        if os.environ.get("MRBOT_ALLOW_RISKY_LAUNCH", "").strip() in (
                "1", "true", "yes", "on"):
            return ""
        try:
            from agents.runtime import brain_contention as bc
            from agents.runtime import device_registry as dr

            devices = dr.detect_devices(include_cpu=True)
            gpu_idx = getattr(self.cfg, "device", None)
            device = next((d for d in devices
                           if getattr(d, "is_gpu", False)
                           and getattr(d, "index", None) == gpu_idx), None)
            if device is None:
                device = next((d for d in devices
                               if getattr(d, "is_cpu", False)), None)
            if device is None:
                return ""

            placements = self._committed_placements(device)
            candidate = {
                "model": model,
                "model_path": model,
                "context": getattr(self.cfg, "context", 8192),
                "gpu_layers": getattr(self.cfg, "gpu_layers", None),
                "threads": getattr(self.cfg, "threads", 0),
            }
            ok, reason = bc.can_add_brain(device, placements, candidate,
                                          devices=devices)
            if ok:
                return ""
            if "cannot establish" in reason.lower():
                return ""              # unknown footprint: nothing to warn about

            head = bc.device_headroom(device, placements, devices=devices) or {}
            need = None
            if getattr(device, "is_gpu", False):
                need = bc.estimate_model_vram_gb(
                    model, candidate["gpu_layers"], candidate["context"])
            free_gb = head.get("vram_free_gb")
            if need is not None and free_gb is not None:
                short = need - free_gb
                detail = (f"needs ~{need:.1f} GB with only ~{free_gb:.1f} GB "
                          f"free (short ~{short:.1f} GB: {reason})")
            else:
                detail = reason
            warn = (
                f"⚠️ {label} Brain VRAM contention: {detail} — the model will "
                f"load anyway and generation will be slower (the excess spills "
                f"to system RAM). Lower the context, offload fewer layers, or "
                f"pick a smaller model for full speed.")
            # ARCH-ENG-310: merge, do not clobber — steps 2/2b may already have
            # left the measured VRAM-RISK or system-RAM notes in `_warn`.
            prev = getattr(self, "_warn", "") or ""
            self._warn = f"{prev}\n{warn}" if prev else warn
            return ""                  # ARCH-ENG-310: a warning, never a refusal
        except Exception:
            # The gate must never become a NEW reason for a launch to fail.
            return ""

    def _committed_placements(self, device):
        """What the OTHER brains already hold, so the gate is not judging this
        one in a vacuum -- which is exactly the case that used to look safe."""
        placements = []
        try:
            from agents.runtime.dual_brain import BrainRole, DualBrainRuntime
            runtime = DualBrainRuntime.from_env()
            for role in (BrainRole.BIG, BrainRole.SMALL):
                try:
                    cfg = runtime.config(role)
                except Exception:
                    continue
                if cfg is None or not getattr(cfg, "enabled", True):
                    continue
                if cfg is self.cfg:
                    continue                        # not an "other" brain
                if getattr(cfg, "port", None) == getattr(self.cfg, "port", None):
                    continue                        # the same server
                placements.append({
                    "model": getattr(cfg, "model", "") or "",
                    "model_path": getattr(cfg, "model", "") or "",
                    "context": getattr(cfg, "context", 8192),
                    "gpu_layers": getattr(cfg, "gpu_layers", None),
                    "threads": getattr(cfg, "threads", 0),
                })
        except Exception:
            return []
        return placements

    @staticmethod
    def _gpu_free_vram_gb(device_index: int):
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,memory.free",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace",
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

    # ── System-RAM contention guard (v2.1.55, ARCH-ENG-055) ──────────────
    # A GPU brain is not VRAM-isolated: llama.cpp mmaps the GGUF, so the
    # model's weights occupy the system page cache and get faulted into
    # resident RAM under pressure. When the CPU/RAM brain generates it
    # builds its KV cache and drains system RAM; the GPU brain's weights
    # then go resident, the footprints collide, and the GPU brain's
    # llama-server hits a failed allocation and ABORTS — silently (no OS
    # crash, no GPU TDR). Measured live: a 10.7 GB GPU model spiked
    # 378 MB → 11.4 GB resident right as the CPU brain built its 32k KV,
    # then died. We sum the REAL resident RAM of the OTHER running servers
    # (via a single CIM query) plus this brain's own projected weights+KV,
    # compare against currently-available RAM, and warn LOUDLY when the
    # total would leave too little headroom. Warn-only — llama.cpp
    # legitimately spills, so the operator decides, never a hard block.

    #: Keep at least this much system RAM free after this brain loads.
    _RAM_HEADROOM_GB = 4.0

    @staticmethod
    def _available_ram_gb() -> float:
        """Currently-available physical RAM in GB (Windows perf counters)."""
        try:
            import ctypes

            class _MEMSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            st = _MEMSTATUSEX()
            st.dwLength = ctypes.sizeof(_MEMSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return st.ullAvailPhys / (1024.0 ** 3)
        except Exception:
            return 0.0

    @staticmethod
    def _other_servers_ram_gb(exclude_port: int) -> tuple:
        """(total_gb, [(role, ram_gb), ...]) for every OTHER running llama-server.

        Uses a single ``tasklist``-style CIM query so it works without psutil.
        The role is derived from the --port in the command line.
        """
        total = 0.0
        details = []
        try:
            import json
            # PowerShell is guaranteed present on the target (Windows) host and
            # returns structured JSON; keep the timeout tight so a slow shell
            # can never stall the launch.
            ps = (
                "Get-CimInstance Win32_Process -Filter \"name='llama-server.exe'\" "
                "| Select-Object ProcessId,WorkingSetSize,CommandLine "
                "| ConvertTo-Json -Compress"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, timeout=6,
                encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if r.returncode != 0 or not r.stdout.strip():
                return 0.0, []
            data = json.loads(r.stdout)
            if isinstance(data, dict):
                data = [data]
            for proc in data:
                cl = proc.get("CommandLine") or ""
                # crude port parse
                import re
                m = re.search(r"--port\s+(\d+)", cl)
                port = int(m.group(1)) if m else None
                if port is not None and port == exclude_port:
                    continue
                ram_gb = float(proc.get("WorkingSetSize") or 0) / (1024.0 ** 3)
                total += ram_gb
                role = {1234: "Big/GPU", 1235: "Small/CPU"}.get(port, f"port{port}")
                details.append((role, ram_gb))
        except Exception:
            return 0.0, []
        return total, details

    def _system_ram_contention_warn(self, label: str, model: str) -> str:
        """Return a loud warning string when launching ``model`` as ``label``
        would leave too little system RAM given the other running brains."""
        try:
            avail = self._available_ram_gb()
            if avail <= 0:
                return ""
            # This brain's own footprint: weights (file size) + KV cache.
            try:
                weights_gb = os.path.getsize(model) / (1024.0 ** 3)
            except OSError:
                weights_gb = 0.0
            try:
                from agents.providers.gguf_meta import estimate_vram_gb
                kv_bytes = {"f32": 4, "f16": 2, "q8_0": 1, "q4_0": 0.5,
                            "auto": 2}.get(getattr(self.cfg, "kv_cache", "auto"), 2)
                est = estimate_vram_gb(model, context=self.cfg.context,
                                       kv_type_bytes=kv_bytes)
                kv_gb = est.get("kv_gb") or 0.0
            except Exception:
                kv_gb = 0.0
            own_gb = weights_gb + kv_gb
            other_gb, details = self._other_servers_ram_gb(self.port)
            projected = own_gb + other_gb
            headroom_after = avail - projected
            if headroom_after >= self._RAM_HEADROOM_GB:
                return ""
            other_txt = ""
            if details:
                other_txt = (" Another brain is already using "
                             + ", ".join(f"{r} ~{g:.1f} GB" for r, g in details)
                             + " of system RAM.")
            short = self._RAM_HEADROOM_GB - headroom_after
            return (
                f"⚠️ {label} Brain SYSTEM-RAM RISK: {os.path.basename(model)} needs "
                f"~{own_gb:.1f} GB (weights ~{weights_gb:.1f} GB + KV ~{kv_gb:.1f} GB "
                f"at {self.cfg.context} tokens), and only ~{avail:.1f} GB is free."
                f"{other_txt} After this loads only ~{max(headroom_after, 0):.1f} GB "
                f"would remain (want ≥{self._RAM_HEADROOM_GB:.0f} GB, short by "
                f"~{short:.1f} GB). A GPU brain is NOT VRAM-isolated — its model "
                f"lives in system RAM too — so when the other brain generates it "
                f"drains RAM and this server can hit a failed allocation and abort "
                f"(its terminal just closes). Lower the context (KV is the big "
                f"chunk), stop the other brain, or pick a smaller model."
            )
        except Exception:
            return ""



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
                encoding="utf-8", errors="replace",
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
                # ARCH-ENG-184: GIVE THE READINESS PROBE A REAL CHANCE BEFORE DECLARING READY.
                #
                # The `_proc_alive()` branch used to return on the FIRST loop
                # iteration, which made the `check_fn(self.port)` probe below it
                # UNREACHABLE dead code -- and it made the 120-second retry loop
                # unreachable too. The consequence: success was emitted the
                # instant Popen returned, so a llama-server that started and then
                # crashed two seconds later on an incompatible GGUF was reported
                # to the operator as "ready on :1234".
                #
                # The ORIGINAL intent behind returning early was sound and is
                # preserved: a busy server may not answer /v1/models promptly,
                # and killing a live server that is mid-generation is worse than
                # reporting it optimistically. The fix is therefore not "wait
                # longer" but "report honestly":
                #
                #   * probe FIRST, with a bounded wait, so a healthy server is
                #     genuinely confirmed before the word "ready" is used;
                #   * if the probe has not answered but the PROCESS is alive,
                #     still succeed -- never terminate a live server -- but say
                #     "launched, not yet answering" instead of "ready".
                #
                # The operator can then tell the two states apart, which they
                # could not before.
                if self._proc_alive():
                    if self.check_fn(self.port):
                        if log_file is not None:
                            log_file.close()
                        mode = ("visible console" if self.visible_console
                                else f"hidden; log={log_path}")
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
                            f"{self.role_name} ready on :{self.port} "
                            f"({mode}; endpoint answering)",
                            spawned,
                        )
                        return
                    # Not answering yet, but alive. Do NOT kill it; report the
                    # weaker state honestly.
                    if log_file is not None:
                        log_file.close()
                    mode = ("visible console" if self.visible_console
                            else f"hidden; log={log_path}")
                    spawned = self._proc
                    self._proc = None
                    self.launch_finished.emit(
                        True,
                        f"{self.role_name} LAUNCHED but not yet answering on "
                        f":{self.port} ({mode}; process alive, endpoint has not "
                        f"responded). It may still be loading its model — check "
                        f"the log if it does not come up.",
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
