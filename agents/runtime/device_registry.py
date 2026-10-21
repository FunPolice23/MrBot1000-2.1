"""agents/runtime/device_registry.py — Detected compute devices + operator policy.

This is the device-centric replacement for the hardwired "Big = device 0,
Small = device 1" assumption. It answers, purely from live detection plus the
operator's persisted enable/role choices:

  * What compute devices exist right now (every GPU by stable UUID, plus the
    CPU / system-RAM pool)?
  * For each, is it enabled for inference, and what brain class may it host
    (big / small) — decided by capability, NOT by a hardcoded model name?

Capability rule (the operator's spec):
  * VRAM (or, for CPU, system RAM) >= BIG_VRAM_GB  -> may host a BIG brain
  * >= SMALL_VRAM_GB but < BIG_VRAM_GB             -> may host a SMALL brain
  * below SMALL_VRAM_GB                            -> unsuitable (skipped)
  * The CPU/RAM pool additionally requires enough cores + RAM to be offered.

Persistence (settings.json, no secrets): per-device ``enabled`` and an optional
``role`` override ("big" | "small" | "" = auto by capability). Devices are keyed
by a STABLE id — the GPU UUID (survives reboots / PCI reordering) with the index
as a fallback, and "cpu" for the system pool. Nothing here hardcodes a specific
card; a 5060 Ti, a 1660 Super, or a future GPU are all handled identically.

The registry never mutates .env or spawns anything — it only reports detected
devices and the operator's policy. Callers (GUI, runtime) turn the enabled
devices into actual brain placements.
"""

from __future__ import annotations

import json
import os
import platform
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Capability thresholds (GB of VRAM, or system RAM for the CPU pool).
BIG_VRAM_GB = 12.0
SMALL_VRAM_GB = 4.0

# The CPU/RAM pool needs at least this much RAM and this many logical cores
# before it is offered as a brain host.
CPU_MIN_RAM_GB = 12.0
CPU_MIN_CORES = 4

SETTINGS_FILE = "settings.json"

# Why the last `nvidia-smi` probe could not run, or "" when it ran cleanly.
# Lets a caller distinguish "this box has no GPUs" from "we could not ask" —
# the two must never be conflated (ARCH-ENG-116).
_LAST_DETECT_ERROR = ""

# Substrings nvidia-smi prints when a GPU has dropped out of the driver
# (TDR reset / driver crash). A lost GPU is NOT "no GPUs": the healthy
# card(s) are still detected and usable, so this records a reboot hint
# rather than swallowing the GPU (B1).
_GPU_LOST_SIGNALS = ("gpu is lost", "unable to determine the device handle")


# ── Detected device ──────────────────────────────────────────────────────────
@dataclass
class ComputeDevice:
    """One detected compute device (a GPU or the CPU/RAM pool)."""
    id: str                 # stable: GPU UUID, or "gpu<index>", or "cpu"
    kind: str               # "gpu" | "cpu"
    index: int              # CUDA index for GPUs; -1 for the CPU pool
    name: str               # detected name (never hardcoded)
    memory_gb: float        # VRAM for GPUs; total system RAM for the CPU pool
    compute_capability: str = ""   # e.g. "12.0"; "" for CPU
    cores: int = 0               # logical cores (CPU pool only)
    uuid: str = ""               # GPU UUID when available

    @property
    def is_gpu(self) -> bool:
        return self.kind == "gpu"

    @property
    def is_cpu(self) -> bool:
        return self.kind == "cpu"

    def capability_class(self) -> str:
        """'big' | 'small' | 'none' by memory (and cores for CPU)."""
        if self.is_cpu:
            if (self.memory_gb >= BIG_VRAM_GB
                    and self.cores >= CPU_MIN_CORES * 2):
                return "big"
            if (self.memory_gb >= SMALL_VRAM_GB
                    and self.cores >= CPU_MIN_CORES):
                return "small"
            return "none"
        if self.memory_gb >= BIG_VRAM_GB:
            return "big"
        if self.memory_gb >= SMALL_VRAM_GB:
            return "small"
        return "none"

    def label(self) -> str:
        mem = f"{self.memory_gb:.0f} GB"
        if self.is_gpu:
            cap = f" · SM {self.compute_capability}" if self.compute_capability else ""
            return f"{self.name} ({mem}{cap})"
        return f"CPU / System RAM ({mem}, {self.cores} cores)"


# ── Operator policy (persisted) ──────────────────────────────────────────────
@dataclass
class DevicePolicy:
    """Per-device enable/role/model/settings choices, keyed by stable device id."""
    enabled: Dict[str, bool] = field(default_factory=dict)
    # role override: "" = auto by capability, else "big" | "small"
    role: Dict[str, str] = field(default_factory=dict)
    # per-device selected model (full path). Home for slot 2+ model choices so
    # every enabled device remembers its model across restarts (slots 0/1 also
    # use .env BIG/SMALL_BRAIN_MODEL for back-compat; this is the N-brain store).
    models: Dict[str, str] = field(default_factory=dict)
    # per-device llama.cpp settings (context/threads/batch/kv/split/...). Home for
    # slot 2+ settings so every enabled device remembers them across restarts.
    settings: Dict[str, Dict[str, object]] = field(default_factory=dict)

    def is_enabled(self, dev: ComputeDevice, default: bool = True) -> bool:
        return self.enabled.get(dev.id, default)

    def role_override(self, dev: ComputeDevice) -> str:
        return self.role.get(dev.id, "")

    def model_for(self, dev: ComputeDevice) -> str:
        return self.models.get(dev.id, "")

    def settings_for(self, dev: ComputeDevice) -> Dict[str, object]:
        return self.settings.get(dev.id, {})


def _settings_path(root: Optional[str] = None) -> str:
    base = root or os.getcwd()
    return os.path.join(base, SETTINGS_FILE)


# ARCH-ENG-172: one lock for every settings.json read-modify-write.
#
# `merge_settings_file` is called from main.py and brain_roster.py;
# `save_policy` from five sites in dual_brain_control.py. Both are read-merge-
# write, and neither was synchronized, so an interleaving pair silently dropped
# one writer's top-level key. A ReentrantLock is used because `save_policy` and
# `merge_settings_file` call into each other's helpers.
#
# This is the same failure mode as ARCH-ENG-162 (`_persist` in
# OpportunityLifecycleTracker): an unserialized read-modify-write over a shared
# file, where the last writer wins and the other writer's data is gone.
_SETTINGS_WRITE_LOCK = threading.RLock()


def policy_path(root: Optional[str] = None) -> str:
    """Return the device-policy file path, honoring the test isolation override.

    ``MRBOT_DEVICE_SETTINGS_PATH`` redirects every read AND write to a throwaway
    file, exactly as ``MRBOT_ENV_PATH`` does for ``.env`` (ARCH-ENG-057). Without
    it, GUI tests that construct a real ``DualBrainControl`` (or call
    ``save_policy`` with no root) silently rewrite the operator's LIVE
    ``settings.json`` — a canary run wiped the operator's saved per-device model
    and every llama.cpp setting, and a test suite run is not supposed to be able
    to touch operator config at all. ``root`` still wins when passed explicitly.
    """
    if root:
        return _settings_path(root)
    override = (os.getenv("MRBOT_DEVICE_SETTINGS_PATH") or "").strip()
    if override:
        return override
    return _settings_path(None)


def load_policy(root: Optional[str] = None) -> DevicePolicy:
    """Read the device policy from settings.json (absent/partial -> defaults)."""
    path = policy_path(root)
    policy = DevicePolicy()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        dev = data.get("devices") or {}
        policy.enabled = {str(k): bool(v) for k, v in (dev.get("enabled") or {}).items()}
        policy.role = {str(k): str(v) for k, v in (dev.get("role") or {}).items()}
        policy.models = {str(k): str(v) for k, v in (dev.get("models") or {}).items()}
        policy.settings = {str(k): dict(v) for k, v in (dev.get("settings") or {}).items()
                           if isinstance(v, dict)}
    except Exception:
        pass  # missing/corrupt file -> all-default policy
    return policy


def merge_settings_file(updates: dict, root: Optional[str] = None) -> bool:
    """Merge `updates` into settings.json, preserving every other top-level key.

    ARCH-ENG-070: `main.py:_save_provider_list` (the Settings-tab Save button) wrote a
    whole-file dict containing only `{"providers": [...]}`. `save_policy` carefully
    preserves sibling keys; this writer did the opposite, so one click on Save erased
    the entire `devices` block — every per-device model choice, every
    context/threads/temperature setting, and every device-disable. On restart each
    device reverted to default-ENABLED, so a device the operator deliberately took
    out of use came back online, and nothing logged an error. Nothing in the codebase
    ever reads the `providers` key, so the write had zero readers and a purely
    destructive effect.

    Every writer to this shared file must go through this function.

    ARCH-ENG-172: "must go through this function" was NOT TRUE. Both this
    function and ``save_policy`` duplicated the read-merge-write, so a
    ``save_policy`` call could interleave with a ``merge_settings_file`` call.

    Two defects, both real on this path:

    1. NO LOCK AROUND THE WHOLE SEQUENCE. Read -> ``data.update`` -> write is
       three steps. ``merge_settings_file`` is called from ``main.py`` and
       ``brain_roster.py``; ``save_policy`` from five sites in
       ``dual_brain_control.py``. A ``devices`` save that read the file a
       millisecond before a ``roster`` save wrote it would then replace it with
       a snapshot that has no ``roster`` key — silently discarding an operator
       edit. There is no merge-at-write, so last-writer-wins drops the other
       writer's key entirely.

    2. A COLLIDING TEMP NAME. Both used ``f"{path}.tmp-{os.getpid()}"``. The PID
       is per-PROCESS, so every writer inside one process shared ONE temp file.
       Two threads opened it for writing: the second truncated the first's
       output mid-``json.dump``, and whichever reached ``os.replace`` first
       published a TRUNCATED settings file. The next read hits
       ``json.JSONDecodeError`` and quarantines the operator's settings as
       corrupt — losing per-device models, roles, and every tuning value.

    Fixed with a module-level lock around the whole sequence and a per-writer
    temp name. Note this is the same failure mode as ARCH-ENG-162 in
    ``OpportunityLifecycleTracker._persist``, one file format over: a fixed temp
    path plus an unserialized read-modify-write.
    """
    path = policy_path(root)
    with _SETTINGS_WRITE_LOCK:
        return _merge_and_write_settings(path, updates)


def _read_settings_for_merge(path: str) -> tuple:
    """Read settings.json for a merge, quarantining an unparseable file.

    Returns ``(data, corrupt_reason)``. Never raises and never deletes operator
    data: an unreadable file is ROTATED ASIDE to ``<name>.corrupt-<n>`` so the
    operator can inspect it, then the caller writes a clean file. Doing the
    quarantine inside the merge rather than the write is what ARCH-ENG-055 fixed
    — previously one unreadable byte made every future save fail silently.
    """
    data: dict = {}
    corrupt: Optional[str] = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
            else:
                corrupt = "not a JSON object"
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            corrupt = f"{type(exc).__name__}: {exc}"
    if corrupt is not None:
        try:
            n = 1
            while True:
                cand = f"{path}.corrupt-{n}"
                if not os.path.exists(cand):
                    break
                n += 1
            os.replace(path, cand)
        except OSError:
            pass
    return data, corrupt


def _atomic_write_settings(path: str, data: dict) -> bool:
    """Write `data` to `path` atomically, with a PER-WRITER temp name.

    ARCH-ENG-172: the temp name used to be ``<path>.tmp-<pid>``. A PID is
    per-PROCESS, so two threads in one process shared one temp file: the second
    truncated the first's output mid-``json.dump`` and the survivor published a
    truncated settings file, which the next read quarantined as corrupt —
    destroying every per-device model, role and tuning value the operator had
    set. The name now includes the thread id so each writer owns its file.
    """
    import threading as _threading
    tmp = f"{path}.tmp-{os.getpid()}-{_threading.get_ident()}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
        return False


def _merge_and_write_settings(path: str, updates: dict) -> bool:
    """Read-merge-write settings.json. Caller must hold `_SETTINGS_WRITE_LOCK`."""
    data, _corrupt = _read_settings_for_merge(path)
    data.update(updates)
    return _atomic_write_settings(path, data)


def save_policy(policy: DevicePolicy, root: Optional[str] = None) -> bool:
    """Merge the device policy into settings.json, preserving other keys.

    Writes atomically (temp file + os.replace) so a crash mid-write cannot
    leave a truncated/corrupt policy. A pre-existing settings.json that cannot
    be parsed (corrupt / truncated / not JSON at all) is rotated aside to
    ``<name>.corrupt-<n>`` and replaced with a fresh policy instead of making
    every future save fail silently (ARCH-ENG-055): previously the merge-read
    lived inside the same ``try`` as the write, so one unreadable byte made
    ``save_policy`` return False forever and per-device settings never
    persisted again — the operator lost every edit with no error anywhere.

    ARCH-ENG-172: this duplicated `merge_settings_file`'s read-merge-write
    verbatim, and both were unsynchronized. It now shares one locked helper, so
    a device-policy save can no longer overwrite a `roster`/`providers` key
    written a millisecond earlier by `main.py` or `brain_roster.py`.
    """
    path = policy_path(root)
    updates: dict = {"devices": {}}
    updates["devices"]["enabled"] = dict(policy.enabled)
    updates["devices"]["role"] = dict(policy.role)
    updates["devices"]["models"] = dict(policy.models)
    updates["devices"]["settings"] = {k: dict(v) for k, v in policy.settings.items()}

    with _SETTINGS_WRITE_LOCK:
        data, _corrupt = _read_settings_for_merge(path)
        # Merge, do not replace: `data["devices"]` may already carry keys this
        # policy does not model, and every OTHER top-level key (roster,
        # providers, theme) must survive untouched.
        devices = data.get("devices")
        if not isinstance(devices, dict):
            devices = {}
        for key, value in updates["devices"].items():
            devices[key] = value
        data["devices"] = devices
        written = _atomic_write_settings(path, data)
        if written:
            # ARCH-ENG-221: a policy edit changes which devices are enabled and
            # which role owns what, so any cached detection result is now stale
            # by definition. Only on success -- a failed write changed nothing.
            invalidate_device_cache()
        return written


# ── Detection ────────────────────────────────────────────────────────────────
def _detect_cpu() -> ComputeDevice:
    """Best-effort CPU / system-RAM detection. Never raises."""
    ram_gb, cores = 0.0, (os.cpu_count() or 0)
    try:
        import psutil  # type: ignore
        ram_gb = psutil.virtual_memory().total / (1024 ** 3)
        cores = psutil.cpu_count(logical=True) or cores
    except Exception:
        try:
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            st = _MS(); st.dwLength = ctypes.sizeof(_MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                ram_gb = st.ullTotalPhys / (1024 ** 3)
        except Exception:
            ram_gb = 0.0
    name = (platform.processor() or "CPU").replace("(R)", "").replace("(TM)", "").strip() or "CPU"
    return ComputeDevice(id="cpu", kind="cpu", index=-1, name=name,
                         memory_gb=round(ram_gb, 1), cores=cores)


def _run_nvidia_smi(query: str) -> str:
    """Run `nvidia-smi --query-gpu=<query>` and return its stdout.

    ARCH-ENG-116: `subprocess.run(..., capture_output=True)` pipes the child's
    stdout through a freshly created OS handle. On Windows that handle must be
    made inheritable via `DuplicateHandle`, which FAILS (WinError 50 / errno 22
    "The request is not supported") when the parent's own stdout is a pipe that
    a capture layer has reconfigured — exactly what pytest's `--capture=fd`
    does. The spawn then raises before nvidia-smi ever runs.

    Measured: `_detect_gpus()` under `pytest --capture=fd` raises
    `OSError(22, 'The request is not supported', None, 50, None)` on every
    attempt, so GPU detection returned ZERO devices and every caller believed
    the box had no GPUs at all. With `--capture=sys` or `-s` the same code
    returns both cards.

    Writing to a real temp FILE instead of an inherited pipe sidesteps the
    stdout duplication, and passing DEVNULL for BOTH stdin and stderr means
    nothing has to be inherited at all — the child opens the path itself.
    Measured: this succeeds under `pytest --capture=fd`, where the previous
    `capture_output=True` form raised WinError 50 on every attempt.

    Note the failing handle was STDIN, not stdout: `_get_handles` duplicates
    whichever of the three standard streams it is given, and leaving stdin
    implicit made it inherit the capture pipe. So all three are named
    explicitly here.

    ARCH-ENG-186: RETURN AN EMPTY STRING ON A NON-ZERO EXIT.
    `check=False` with a discarded return code meant a FAILED nvidia-smi was
    indistinguishable from a successful one that happened to print nothing: its
    stdout (which is where a driver error would not go — stderr is DEVNULL)
    was returned and parsed. The two callers redirected here by ARCH-ENG-166
    (`provider_manager._detect_gpus`, `llm.detect_vram_gb`) each used to check
    `result.returncode == 0` on their own copy of the call, so routing them here
    silently dropped that check. A non-zero exit now yields "" — the same
    "no devices" answer the callers produced before, and the only honest one:
    a query that did not succeed says nothing about what hardware is present.
    """
    import subprocess
    import tempfile

    argv = ["nvidia-smi", f"--query-gpu={query}",
            "--format=csv,noheader,nounits"]
    flags = 0
    try:
        flags = subprocess.CREATE_NO_WINDOW
    except AttributeError:
        flags = 0

    handle = None
    path = None
    try:
        fd, path = tempfile.mkstemp(prefix="mrb_smi_", suffix=".csv")
        handle = os.fdopen(fd, "w+", encoding="utf-8", errors="replace")
        result = subprocess.run(argv,
                                stdin=subprocess.DEVNULL,
                                stdout=handle,
                                stderr=subprocess.DEVNULL,
                                timeout=5, creationflags=flags, check=False)
        if getattr(result, "returncode", 0) != 0:
            # ARCH-ENG-186: the query failed; report no rows rather than
            # whatever partial text landed in the temp file.
            return ""
        handle.flush()
        handle.seek(0)
        return handle.read()
    finally:
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass
        if path:
            try:
                os.unlink(path)
            except Exception:
                pass


# ── Local process introspection ───────────────────────────────────────────────
# ARCH-ENG-187: ONE implementation, shared by the two callers that need it.
#
# `DualBrainControl` and `ProviderStatusChecker.check_llama_process` both need to
# answer "is a llama.cpp server listening on this port, and whose is it". They
# each had their own copy, and the copies had already diverged into two
# different bugs (below). The two facts that must be right are:
#
#   * which executable names count as "ours" — the app spawns `llama-server.exe`,
#     while one copy filtered for `llama.exe` and therefore ALWAYS reported
#     "no llama process", which reads as a confident negative;
#   * that a port alone is not proof of ownership — 1234 is both the Big Brain
#     port and LM Studio's default, so a port-only check either kills a stranger
#     (ARCH-ENG-171) or, at best, cannot say which process it found.


def _run_windows_text(argv: List[str], timeout: float = 5.0) -> str:
    """Run a Windows console tool and return its stdout, hardened.

    ARCH-ENG-116: all three standard handles are named EXPLICITLY. Leaving
    `stdin` implicit made the child inherit the parent's capture pipe, and
    `_get_handles` must duplicate whichever handles it is given — which fails
    with `OSError(22, 'The request is not supported')` / WinError 50 under
    `pytest --capture=fd`. A non-zero exit yields "" (see `_run_nvidia_smi`,
    ARCH-ENG-186: a query that did not succeed says nothing).
    """
    import subprocess
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout, creationflags=flags, check=False,
        )
    except Exception:
        return ""
    if getattr(result, "returncode", 0) != 0:
        return ""
    return (getattr(result, "stdout", b"") or b"").decode(
        "utf-8", errors="replace")


#: Executable names this application may treat as its own llama.cpp server.
#:
#: ARCH-ENG-187: the app spawns `llama-server.exe` (see `BrainLaunchWorker`).
#: `llama.exe` is the legacy alias some launcher scripts produce. Nothing else is
#: accepted — the whole point is that a port does not identify a process we own.
_LLAMA_SERVER_IMAGES = ("llama-server", "llama")


def is_llama_server_image(image_name: str) -> bool:
    """True only for a llama.cpp server executable name.

    ARCH-ENG-187: deliberately narrow, and deliberately NOT "contains llama" —
    `llama-server-helper.exe` and `xllama.exe` are somebody else's process.
    """
    name = (image_name or "").strip().lower()
    if not name.endswith(".exe"):
        return False
    return name[:-4] in _LLAMA_SERVER_IMAGES


def process_image_name(pid: int) -> str:
    """Lower-cased executable name for `pid`, or "" if it cannot be read."""
    try:
        out = _run_windows_text(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"])
    except Exception:
        return ""
    for line in out.splitlines():
        parts = [p.strip().strip('"') for p in line.split('","')]
        if not parts:
            continue
        name = parts[0].strip('"').strip()
        if name.lower().endswith(".exe"):
            return name.lower()
    return ""


def pids_listening_on(port: int) -> List[int]:
    """Every PID in LISTENING state on `port`, de-duplicated.

    More than one can exist when a duplicate llama-server slipped through
    (SO_REUSEADDR lets two bind one port) or a stale server from a prior run
    lingers. `netstat` also reports one socket twice for some addresses
    (`0.0.0.0:` and `[::]:` across v4+v6), so the list is de-duplicated here
    rather than by each caller — a repeated kill of the same PID is both
    wasteful and can race.
    """
    try:
        want = int(port)
    except (TypeError, ValueError):
        return []
    out = _run_windows_text(["netstat", "-ano", "-p", "tcp"])
    pids: List[int] = []
    seen = set()
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) >= 5 and parts[0] == "TCP":
            local, state, pid = parts[1], parts[3], parts[4]
            if state == "LISTENING" and local.endswith(f":{want}") and pid.isdigit():
                value = int(pid)
                if value not in seen:
                    seen.add(value)
                    pids.append(value)
    return pids


def llama_server_pids_on(port: int) -> List[int]:
    """The PIDs on `port` that are llama.cpp servers OURS may manage.

    The port tells you WHO IS THERE; the image name tells you WHOSE IT IS.
    Callers that kill what this returns can no longer destroy a stranger's
    process (ARCH-ENG-171), and callers that merely probe no longer report a
    confident "no server" when the listener was a different program
    (ARCH-ENG-187).
    """
    return [pid for pid in pids_listening_on(port)
            if is_llama_server_image(process_image_name(pid))]


def _detect_gpus() -> List[ComputeDevice]:
    """Detect GPUs with stable UUIDs via nvidia-smi; fall back to the provider
    manager's probe (index-only) when the UUID query is unavailable."""
    devices: List[ComputeDevice] = []
    global _LAST_DETECT_ERROR
    _LAST_DETECT_ERROR = ""
    lost_hint = False
    # Preferred: nvidia-smi with uuid for a stable identity. compute_cap is
    # nice-to-have; some drivers lack it, so try with it first and retry without
    # rather than dropping GPU detection entirely.
    for query in (
        "index,name,memory.total,uuid,compute_cap",
        "index,name,memory.total,uuid",
    ):
        try:
            out = _run_nvidia_smi(query)
        except Exception as exc:
            # ARCH-ENG-116: this used to `continue` silently, so a subprocess
            # that could not even be spawned (pytest's fd capture on Windows
            # makes `DuplicateHandle` fail with WinError 50; a locked driver
            # does the same) was indistinguishable from "this query form is
            # unsupported". GPU detection then reported ZERO GPUs and every
            # caller believed the box had none: `tests/gui/test_gui_smoke.py::`
            # test_management_tab_builds` failed with 1 persona field instead of
            # 3, and the brain prompt's hardware line was dropped entirely.
            # Record the reason so the caller can tell "no GPUs" from "could
            # not ask", and retry the next query form regardless.
            if not lost_hint:
                _LAST_DETECT_ERROR = f"nvidia-smi spawn failed: {exc!r}"
            continue
        # B1: a lost GPU (TDR reset / driver crash) prints "GPU is lost" or
        # "Unable to determine the device handle" in the query output. That is
        # NOT "no GPUs" — the healthy card(s) are still listed and usable — so
        # record a reboot hint instead of silently dropping the GPU, and keep
        # parsing the healthy lines below.
        low_out = out.lower()
        if any(sig in low_out for sig in _GPU_LOST_SIGNALS):
            _LAST_DETECT_ERROR = (
                "nvidia-smi reported a lost GPU (\"GPU is lost\" / "
                "\"Unable to determine the device handle\"): a GPU has dropped "
                "out of the driver, usually after a TDR reset or driver crash. "
                "Reboot the machine to recover the lost GPU(s); the healthy "
                "GPU(s) below are still detected and usable."
            )
            lost_hint = True
        parsed: List[ComputeDevice] = []
        for line in out.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3 and parts[0].isdigit():
                idx = int(parts[0])
                name = parts[1]
                try:
                    mem_mb = int(float(parts[2]))
                except ValueError:
                    continue
                uuid = parts[3] if len(parts) >= 4 else ""
                cap = parts[4] if len(parts) >= 5 else ""
                dev_id = uuid if uuid else f"gpu{idx}"
                parsed.append(ComputeDevice(
                    id=dev_id, kind="gpu", index=idx, name=name,
                    memory_gb=round(mem_mb / 1024.0, 1),
                    compute_capability=cap, uuid=uuid))
        if parsed:
            return parsed
    # Fallback: provider manager (no UUID -> id by index).
    #
    # ARCH-ENG-116: `detect=False` returns the provider manager's CACHED GPU
    # list, which is empty until something has probed. This fallback only runs
    # when nvidia-smi already failed, so nothing had probed — the call returned
    # [] every single time and the "fallback" was dead code. GPU detection then
    # silently reported ZERO GPUs and every caller believed the box had none.
    # `detect=True` forces the probe; verified to return both cards on this box.
    try:
        from agents.providers.provider_manager import ProviderManager
        for g in ProviderManager.instance().get_gpus(detect=True):
            devices.append(ComputeDevice(
                id=f"gpu{g.index}", kind="gpu", index=g.index, name=g.name,
                memory_gb=round((g.memory_total_mb or 0) / 1024.0, 1),
                compute_capability=g.compute_capability or ""))
    except Exception as exc:
        if not lost_hint:
            _LAST_DETECT_ERROR = f"provider-manager fallback failed: {exc!r}"
    return devices


# ARCH-ENG-221: (monotonic_now, devices) for the detection cache below.
_DEVICE_CACHE: Optional[tuple] = None

# How long a detection result may be reused. Matching `DUAL_BRAIN_HEALTH_TTL`
# (10 s) so the two caches on the display path age at the same rate.
_DEVICE_CACHE_TTL_S = float(os.getenv("MRBOT_DEVICE_CACHE_TTL", "10"))


def invalidate_device_cache() -> None:
    """ARCH-ENG-221: force the next `detect_devices` to re-run nvidia-smi.

    Needed by anything that changes what is attached -- a provider start or
    stop, a device policy edit, or a UI action that wants live truth right now
    rather than up to one TTL old.
    """
    global _DEVICE_CACHE
    _DEVICE_CACHE = None


def detect_devices(include_cpu: bool = True) -> List[ComputeDevice]:
    """All detected compute devices: GPUs (by VRAM desc) then the CPU pool.

    ARCH-ENG-221: NOW CACHED. THIS RAN ON EVERY CHAT TURN.

    `_hardware_line()` in both `big_brain.py:200` and `small_brain.py:170` calls
    this to build one line of the system prompt. `_detect_gpus()` spawns
    `nvidia-smi` as a subprocess and parses its output, so the whole NVML
    cold-start plus process creation was paid once per prompt, per brain --
    measured at hundreds of milliseconds on a loaded 6-core machine, for a
    string that cannot change between turns.

    `_detect_gpus` itself is deliberately left UNCACHED, because tests patch it
    directly and a cache there would silently serve one test's mock to another.

    A copy of the list is returned so a caller sorting or mutating it cannot
    corrupt the cache.
    """
    global _DEVICE_CACHE, _LAST_DETECT_ERROR
    now = time.monotonic()
    # `include_cpu` changes the RESULT, not just the length, so it is part of
    # the key. Caching on time alone would let a `include_cpu=False` caller be
    # handed a list containing the CPU pool.
    if (_DEVICE_CACHE is not None
            and _DEVICE_CACHE[0] == include_cpu
            and (now - _DEVICE_CACHE[2]) < _DEVICE_CACHE_TTL_S):
        # ARCH-ENG-222: restore the error string that was captured WITH these
        # devices. `_LAST_DETECT_ERROR` is module-global state written by
        # `_detect_gpus`, and `dual_brain_control.py:800` reads it to show the
        # reboot hint. Without this, a cache hit returned a device list from the
        # previous probe while the error text described a DIFFERENT probe --
        # two observations from two moments presented as one. That is the
        # ARCH-ENG-179/185/188 defect in a new place.
        _LAST_DETECT_ERROR = _DEVICE_CACHE[3]
        return list(_DEVICE_CACHE[1])

    devices = _detect_gpus()
    detect_error = _LAST_DETECT_ERROR
    devices.sort(key=lambda d: d.memory_gb, reverse=True)
    if include_cpu:
        devices.append(_detect_cpu())
    _DEVICE_CACHE = (include_cpu, list(devices), now, detect_error)
    return devices


# ── Effective allocation ─────────────────────────────────────────────────────
@dataclass
class DeviceAssignment:
    """A device paired with the brain class it will host under current policy."""
    device: ComputeDevice
    enabled: bool
    role: str            # effective role: "big" | "small" | "none"
    auto: bool           # True when role came from capability, not an override
    reason: str = ""     # why disabled / none (for the GUI + logs)


def resolve_assignments(devices: List[ComputeDevice],
                        policy: DevicePolicy) -> List[DeviceAssignment]:
    """Apply the operator policy to detected devices.

    A device is a candidate when enabled AND its capability class is not 'none'.
    Its effective role is the override if set, else its capability class. An
    override may only PROMOTE within capability (a small-VRAM GPU cannot be
    forced to 'big'); an impossible override falls back to capability with a
    note. Returns assignments for every device (enabled or not) so the GUI can
    render the full list with toggles.
    """
    out: List[DeviceAssignment] = []
    for dev in devices:
        cap = dev.capability_class()
        enabled = policy.is_enabled(dev)
        override = policy.role_override(dev)
        role, auto, reason = cap, True, ""
        if not enabled:
            role, reason = "none", "disabled by operator"
        elif cap == "none":
            role, reason = "none", (
                f"insufficient memory (needs >= {SMALL_VRAM_GB:.0f} GB)")
        elif override in ("big", "small") and override != cap:
            # Only allow a downgrade-safe promotion: small-VRAM can't be big.
            rank = {"none": 0, "small": 1, "big": 2}
            if rank[override] > rank[cap]:
                role, reason = cap, f"cannot host {override} (only {cap}-class)"
            else:
                role, auto = override, False
        out.append(DeviceAssignment(device=dev, enabled=enabled,
                                    role=role, auto=auto, reason=reason))
    return out


def brain_placements(assignments: List[DeviceAssignment],
                     base_port: int = 1234) -> List[dict]:
    """Turn enabled assignments into ordered brain placements with ports.

    Order: big-class devices first (most memory first), then small-class. Ports
    are assigned sequentially from ``base_port``. Each placement is a plain dict
    so GUI/runtime/launcher can consume it without importing Qt.
    """
    active = [a for a in assignments if a.enabled and a.role in ("big", "small")]
    # Order by the 2-role→slot convention the runtime/GUI depend on:
    #   slot 0 = the Big Brain (first big-class GPU),
    #   slot 1 = the Small Brain (first small-class device, GPU or CPU),
    #   slot 2+ = any remaining devices (extra big GPUs, extra small GPUs,
    #             or a CPU pool) so an N-GPU box yields N brains.
    # Within a class a GPU always precedes the CPU pool (better host for the
    # class); ties break on most memory first. The first big-class GPU and the
    # first small-class device are pulled to the front so slots 0/1 are stable.
    bigs = sorted([a for a in active if a.role == "big"],
                  key=lambda a: (0 if a.device.is_gpu else 1, -a.device.memory_gb))
    smalls = sorted([a for a in active if a.role == "small"],
                    key=lambda a: (0 if a.device.is_gpu else 1, -a.device.memory_gb))
    ordered = []
    if bigs:
        ordered.append(bigs[0])
    if smalls:
        ordered.append(smalls[0])
    seen = {a.device.id for a in ordered}
    for a in bigs[1:] + smalls[1:]:
        if a.device.id not in seen:
            ordered.append(a)
            seen.add(a.device.id)
    placements = []
    port = base_port
    for a in ordered:
        placements.append({
            "role": a.role,
            "device_id": a.device.id,
            "kind": a.device.kind,
            "index": a.device.index,
            "name": a.device.name,
            "memory_gb": a.device.memory_gb,
            "is_cpu": a.device.is_cpu,
            "port": port,
            "label": a.device.label(),
        })
        port += 1
    return placements


def format_assignments(assignments: List[DeviceAssignment]) -> str:
    """Human-readable summary for the Live Log / diagnostics."""
    lines = ["🖥️  Detected compute devices:"]
    for a in assignments:
        dev = a.device
        state = "✅ enabled" if a.enabled else "⬚ disabled"
        role = a.role if a.role != "none" else "—"
        tag = " (auto)" if a.auto and a.role != "none" else ""
        note = f" — {a.reason}" if a.reason else ""
        lines.append(f"   {state}  {dev.label():45} -> {role}{tag}{note}")
    return "\n".join(lines)


__all__ = [
    "ComputeDevice", "DevicePolicy", "DeviceAssignment",
    "detect_devices", "invalidate_device_cache", "load_policy", "save_policy",
    "resolve_assignments",
    "brain_placements", "format_assignments", "policy_path",
    "BIG_VRAM_GB", "SMALL_VRAM_GB",
]
