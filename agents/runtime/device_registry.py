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


def load_policy(root: Optional[str] = None) -> DevicePolicy:
    """Read the device policy from settings.json (absent/partial -> defaults)."""
    path = _settings_path(root)
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


def save_policy(policy: DevicePolicy, root: Optional[str] = None) -> bool:
    """Merge the device policy into settings.json, preserving other keys."""
    path = _settings_path(root)
    try:
        data = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        data.setdefault("devices", {})
        data["devices"]["enabled"] = dict(policy.enabled)
        data["devices"]["role"] = dict(policy.role)
        data["devices"]["models"] = dict(policy.models)
        data["devices"]["settings"] = {k: dict(v) for k, v in policy.settings.items()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


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


def _detect_gpus() -> List[ComputeDevice]:
    """Detect GPUs with stable UUIDs via nvidia-smi; fall back to the provider
    manager's probe (index-only) when the UUID query is unavailable."""
    devices: List[ComputeDevice] = []
    # Preferred: nvidia-smi with uuid for a stable identity. compute_cap is
    # nice-to-have; some drivers lack it, so try with it first and retry without
    # rather than dropping GPU detection entirely.
    import subprocess
    for query in (
        "index,name,memory.total,uuid,compute_cap",
        "index,name,memory.total,uuid",
    ):
        try:
            out = subprocess.run(
                ["nvidia-smi", f"--query-gpu={query}",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW).stdout
        except Exception:
            continue
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
    try:
        from agents.providers.provider_manager import ProviderManager
        for g in ProviderManager.instance().get_gpus(detect=False):
            devices.append(ComputeDevice(
                id=f"gpu{g.index}", kind="gpu", index=g.index, name=g.name,
                memory_gb=round((g.memory_total_mb or 0) / 1024.0, 1),
                compute_capability=g.compute_capability or ""))
    except Exception:
        pass
    return devices


def detect_devices(include_cpu: bool = True) -> List[ComputeDevice]:
    """All detected compute devices: GPUs (by VRAM desc) then the CPU pool."""
    devices = _detect_gpus()
    devices.sort(key=lambda d: d.memory_gb, reverse=True)
    if include_cpu:
        devices.append(_detect_cpu())
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
    "detect_devices", "load_policy", "save_policy", "resolve_assignments",
    "brain_placements", "format_assignments", "BIG_VRAM_GB", "SMALL_VRAM_GB",
]
