"""agents/runtime/hardware_plan.py — Detect hardware and plan brain allocation.

MrBot1000 historically hardwired exactly two roles — Big Brain (device 0) and
Small Brain (device 1) — on fixed ports. That breaks the moment the operator
adds/removes a GPU or wants a CPU/RAM brain. This module is the single source
of truth for "what hardware do we have, and which brain should run where".

It answers three questions from live detection:
  1. What GPUs exist (index, name, VRAM, compute capability)?
  2. What does the CPU/RAM look like (cores, total RAM) for an optional CPU brain?
  3. Given a brain-count/VRAM policy, which hardware hosts which brain, on
     which port?

The output (``BrainPlan``) is intentionally a plain data structure so the GUI,
the runtime, and the launcher can all consume it without importing Qt. The
planner never mutates config or spawns anything — it only *recommends*; the
caller decides whether to apply it.

Policy (operator-tunable, defaults chosen for this box):
  - Big Brain  -> the GPU with the MOST VRAM (>= BIG_VRAM_GB).
  - Small Brain-> the next GPU by VRAM (>= SMALL_VRAM_GB), else CPU/RAM.
  - CPU brain  -> optional; created when enabled AND the CPU/RAM can host a
                  small model (enough cores + RAM). Its "big or small" class
                  follows the same VRAM-equivalent thresholds applied to RAM.

Nothing here invents hardware: a brain is only placed on a target that was
actually detected.
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field
from typing import List, Optional

# VRAM/RAM thresholds (GB) that decide a target's brain class. A target at or
# above BIG_VRAM_GB can host a Big Brain; at or above SMALL_VRAM_GB a Small
# Brain; below that it is unsuitable for local inference.
BIG_VRAM_GB = 12.0
SMALL_VRAM_GB = 4.0

# A CPU/RAM brain needs at least this much system RAM and this many cores to be
# worth offering (a 2-core / 8 GB box would only frustrate the operator).
CPU_MIN_RAM_GB = 12.0
CPU_MIN_CORES = 4


@dataclass
class HardwareTarget:
    """One place a brain could run: a GPU or the CPU/system-RAM pool."""
    kind: str                 # "gpu" | "cpu"
    index: int                # GPU index, or -1 for the CPU pool
    name: str
    vram_gb: float            # GPU VRAM, or total system RAM for the CPU pool
    compute_capability: str = ""   # GPU only (e.g. "8.9"); "" for CPU
    brain_class: str = "none"      # "big" | "small" | "none" (by VRAM/RAM)

    @property
    def is_gpu(self) -> bool:
        return self.kind == "gpu"

    def label(self) -> str:
        if self.is_gpu:
            cap = f" · SM {self.compute_capability}" if self.compute_capability else ""
            return f"GPU {self.index}: {self.name} ({self.vram_gb:.0f} GB{cap})"
        return f"CPU / System RAM ({self.vram_gb:.0f} GB)"


@dataclass
class PlannedBrain:
    """A recommended brain placement produced by the planner."""
    role: str                 # "big" | "small" | "extra-big" | "extra-small"
    target: HardwareTarget
    port: int
    is_cpu: bool = False

    def label(self) -> str:
        kind = "Big" if self.role.startswith("big") else "Small"
        return f"{kind} Brain -> {self.target.label()} (:{self.port})"


@dataclass
class BrainPlan:
    """The full recommended allocation for the detected hardware."""
    targets: List[HardwareTarget] = field(default_factory=list)
    brains: List[PlannedBrain] = field(default_factory=list)
    cpu_enabled: bool = False
    notes: List[str] = field(default_factory=list)

    def big_brain(self) -> Optional[PlannedBrain]:
        return next((b for b in self.brains if b.role == "big"), None)

    def small_brain(self) -> Optional[PlannedBrain]:
        return next((b for b in self.brains if b.role == "small"), None)


def _classify(vram_gb: float) -> str:
    if vram_gb >= BIG_VRAM_GB:
        return "big"
    if vram_gb >= SMALL_VRAM_GB:
        return "small"
    return "none"


def detect_cpu_target() -> HardwareTarget:
    """Best-effort CPU / system-RAM detection. Never raises."""
    ram_gb = 0.0
    cores = os.cpu_count() or 0
    # psutil is the accurate source; fall back to platform + ctypes when absent.
    try:
        import psutil  # type: ignore
        ram_gb = psutil.virtual_memory().total / (1024 ** 3)
        cores = psutil.cpu_count(logical=True) or cores
    except Exception:
        try:
            import ctypes

            class _MEMORYSTATUSEX(ctypes.Structure):
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

            st = _MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                ram_gb = st.ullTotalPhys / (1024 ** 3)
        except Exception:
            ram_gb = 0.0
    cpu_name = platform.processor() or "CPU"
    # Trim the marketing noise so the label stays readable.
    cpu_name = cpu_name.replace("(R)", "").replace("(TM)", "").strip() or "CPU"
    return HardwareTarget(
        kind="cpu", index=-1, name=cpu_name, vram_gb=round(ram_gb, 1),
        compute_capability="", brain_class=_classify(ram_gb))


def _gpu_targets_from_manager() -> List[HardwareTarget]:
    """Read detected GPUs from the ProviderManager singleton (no re-probe)."""
    try:
        from agents.providers.provider_manager import ProviderManager
        gpus = ProviderManager.instance().get_gpus(detect=False)
    except Exception:
        return []
    targets: List[HardwareTarget] = []
    for g in gpus:
        vram_gb = round((g.memory_total_mb or 0) / 1024.0, 1)
        targets.append(HardwareTarget(
            kind="gpu", index=g.index, name=g.name, vram_gb=vram_gb,
            compute_capability=g.compute_capability or "",
            brain_class=_classify(vram_gb)))
    return targets


def build_brain_plan(cpu_enabled: bool = False,
                     base_port: int = 1234) -> BrainPlan:
    """Detect hardware and recommend a brain allocation.

    GPUs are ranked by VRAM (largest first). The largest becomes the Big Brain;
    the next becomes the Small Brain. If only one GPU exists, the Small Brain
    falls back to the CPU/RAM pool (when enabled and capable). When ``cpu_enabled``
    and there is spare CPU/RAM headroom beyond the GPUs, an additional CPU brain
    is appended. Ports are assigned sequentially from ``base_port``.

    This is a pure recommendation — it does not touch config, .env, or processes.
    """
    plan = BrainPlan(cpu_enabled=cpu_enabled)
    gpus = _gpu_targets_from_manager()
    cpu = detect_cpu_target()
    # All candidate targets, GPUs first (by VRAM desc), then CPU if enabled.
    gpus_sorted = sorted(gpus, key=lambda t: t.vram_gb, reverse=True)
    plan.targets = list(gpus_sorted)
    if cpu_enabled:
        plan.targets.append(cpu)

    port = base_port
    placed_gpus = 0
    for t in gpus_sorted:
        if t.brain_class == "none":
            plan.notes.append(f"{t.label()} has too little VRAM for local inference; skipped.")
            continue
        if placed_gpus == 0:
            role = "big"
        elif placed_gpus == 1:
            role = "small"
        else:
            # Extra GPUs beyond the first two become additional brains.
            role = "extra-big" if t.brain_class == "big" else "extra-small"
        plan.brains.append(PlannedBrain(role=role, target=t, port=port, is_cpu=False))
        port += 1
        placed_gpus += 1

    # No Small Brain yet and a CPU pool is available -> place Small on CPU/RAM.
    has_small = any(b.role == "small" for b in plan.brains)
    if cpu_enabled and not has_small and cpu.brain_class != "none":
        if cpu.vram_gb >= CPU_MIN_RAM_GB and (os.cpu_count() or 0) >= CPU_MIN_CORES:
            plan.brains.append(PlannedBrain(role="small", target=cpu, port=port, is_cpu=True))
            port += 1
        else:
            plan.notes.append(
                f"CPU/RAM brain skipped: needs >= {CPU_MIN_RAM_GB:.0f} GB RAM and "
                f">= {CPU_MIN_CORES} cores (found {cpu.vram_gb:.0f} GB, {os.cpu_count()} cores).")

    if not any(b.role == "big" for b in plan.brains):
        plan.notes.append("No GPU meets the Big Brain VRAM threshold; "
                          "assign a cloud provider or lower BIG_VRAM_GB.")
    return plan


def format_brain_plan(plan: BrainPlan) -> str:
    """Human-readable summary for the Live Log / diagnostics."""
    lines = ["🧠 Detected hardware:"]
    for t in plan.targets:
        lines.append(f"   • {t.label()}  [{t.brain_class}]")
    if plan.brains:
        lines.append("📋 Recommended brain allocation:")
        for b in plan.brains:
            lines.append(f"   • {b.label()}")
    else:
        lines.append("📋 No local brains can be placed on the detected hardware.")
    for n in plan.notes:
        lines.append(f"   ⚠️ {n}")
    return "\n".join(lines)


__all__ = [
    "HardwareTarget", "PlannedBrain", "BrainPlan",
    "detect_cpu_target", "build_brain_plan", "format_brain_plan",
    "BIG_VRAM_GB", "SMALL_VRAM_GB",
]
