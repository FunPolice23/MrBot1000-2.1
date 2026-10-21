"""agents/runtime/brain_roster.py — N-brain roster model (Phase 3).

A ``BrainRoster`` describes up to 10 Big + 10 Small brains, each with
enabled/provider/model/device, persisted in ``settings.json`` under ``"roster"``.
It drives placements: ``to_placements`` emits roster-driven placements in the
SAME dict shape ``device_registry.brain_placements`` produces, so
``speaker_registry.build_speakers`` consumes them unchanged.

Pure: no Qt, no network, no subprocess. Persistence goes through
``device_registry.merge_settings_file`` (ARCH-ENG-070: preserve every sibling
top-level key — the roster write must never erase the ``devices`` block).

Ports: sequential from a base, unique per ACTIVE LOCAL brain; cloud providers
get no port (a cloud brain is an API endpoint, not a local server).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

MAX_BIG = 10
MAX_SMALL = 10
ROSTER_KEY = "roster"
# ARCH-ENG-219: ONE MODEL PER DEVICE, UNLESS THE DEVICE HAS >= 32 GB VRAM.
#
# Two slots may name the same device, and `to_placements` previously allowed it
# unconditionally: `by_id.get(slot.device_id)` returns a device without
# consulting `taken`, so only AUTO-assigned slots were de-duplicated. The
# operator could select a second model on a device and the roster would emit two
# placements for it.
#
# That is not reachable at runtime today -- `to_placements()` has no production
# caller -- which is exactly why it should be fixed here rather than discovered
# later. The rule is a hardware fact, not a UI preference: below ~32 GB of VRAM
# a second resident model does not fit alongside the first, and llama.cpp spills
# to system RAM, which is slow enough to look like a hang.
#
# CPU devices are excluded from the exemption regardless of `memory_gb`: for a
# CPU pool that field is total system RAM, not VRAM, so a 64 GB-RAM machine must
# not be read as "can host two models".
MULTI_MODEL_MIN_VRAM_GB = 32.0


# How many models one device may keep resident. One is the default; a device
# with enough VRAM for two gets two. Not unlimited -- a 32 GB card holding three
# quantised models spills to system RAM and generation collapses to a few tok/s,
# which is indistinguishable from a hang to the operator.
MULTI_MODEL_CAPACITY = 2


def _capacity_for(dev: Any) -> int:
    """Resident-model budget for `dev`. 1, or MULTI_MODEL_CAPACITY when eligible."""
    return MULTI_MODEL_CAPACITY if device_can_host_multiple_models(dev) else 1


def device_can_host_multiple_models(dev: Any) -> bool:
    """True when `dev` has enough VRAM to keep two resident models.

    GPU only, and at least `MULTI_MODEL_MIN_VRAM_GB`. Used by `to_placements` to
    reject an over-subscribed device and by the roster panel to grey out the
    offending selection, so the operator is told at selection time rather than
    discovering it when a model fails to load.
    """
    is_gpu = bool(getattr(dev, "is_gpu", False)) or (
        getattr(dev, "kind", "") == "gpu")
    if not is_gpu:
        return False
    try:
        vram = float(getattr(dev, "memory_gb", 0.0) or 0.0)
    except (TypeError, ValueError):
        return False
    return vram >= MULTI_MODEL_MIN_VRAM_GB

DEFAULT_BASE_PORT = 1234

# Providers that run a local server and therefore need a port. Cloud providers
# (openai/nvidia_nim/openrouter/groq/together/...) do not.
LOCAL_PROVIDERS = {"llamacpp", "ollama", "lmstudio", "vllm", "koboldcpp"}


@dataclass
class BrainSlot:
    """One brain in the roster.

    ``port`` is reserved for an operator override (0 = auto-assign at placement
    time). ``device_id`` empty = auto-pick a compatible device.
    """
    tier: str = "big"               # "big" | "small"
    enabled: bool = True
    provider: str = "llamacpp"
    model: str = ""
    device_id: str = ""             # device-registry id ("gpu0", "cpu", ...)
    port: int = 0                   # 0 = auto; cloud brains ignore it

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Any) -> "BrainSlot":
        d = d if isinstance(d, dict) else {}
        tier = str(d.get("tier", "big"))
        if tier not in ("big", "small"):
            tier = "big"
        try:
            port = int(d.get("port", 0) or 0)
        except (TypeError, ValueError):
            port = 0
        return cls(
            tier=tier,
            enabled=bool(d.get("enabled", True)),
            provider=str(d.get("provider", "llamacpp")),
            model=str(d.get("model", "")),
            device_id=str(d.get("device_id", "")),
            port=port,
        )

    @property
    def is_local(self) -> bool:
        return self.provider.strip().lower() in LOCAL_PROVIDERS


class BrainRoster:
    """Up to MAX_BIG big + MAX_SMALL small brains."""

    def __init__(self, big: List[BrainSlot], small: List[BrainSlot]):
        self.big = list(big)[:MAX_BIG]
        self.small = list(small)[:MAX_SMALL]

    # ── constructors ──────────────────────────────────────────────────────
    @classmethod
    def default(cls) -> "BrainRoster":
        """One enabled big + one enabled small (today's dual-brain)."""
        return cls(big=[BrainSlot(tier="big")], small=[BrainSlot(tier="small")])

    def to_dict(self) -> Dict[str, Any]:
        return {"big": [s.to_dict() for s in self.big],
                "small": [s.to_dict() for s in self.small]}

    @classmethod
    def from_dict(cls, d: Any) -> "BrainRoster":
        d = d if isinstance(d, dict) else {}
        big = [BrainSlot.from_dict(x) for x in (d.get("big") or [])]
        small = [BrainSlot.from_dict(x) for x in (d.get("small") or [])]
        return cls(big=big, small=small)

    def active_slots(self) -> List[BrainSlot]:
        return [s for s in (self.big + self.small) if s.enabled]

    # ── persistence (via device_registry; preserve sibling keys) ──────────
    @classmethod
    def load(cls, root: Optional[str] = None) -> "BrainRoster":
        from agents.runtime.device_registry import policy_path
        path = policy_path(root)
        data: Dict[str, Any] = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
            except Exception:
                data = {}
        roster = data.get(ROSTER_KEY)
        if isinstance(roster, dict) and (roster.get("big") or roster.get("small")):
            return cls.from_dict(roster)
        return cls.default()

    @classmethod
    def load_or_none(cls, root: Optional[str] = None) -> Optional["BrainRoster"]:
        """Load the persisted roster, or ``None`` when no ``"roster"`` key exists.

        Lets the runtime fall back to the legacy env path byte-identically when
        the operator has not set up a roster (vs. ``load`` which returns the
        default dual-brain). Never raises.
        """
        from agents.runtime.device_registry import policy_path
        path = policy_path(root)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
        except Exception:
            return None
        if not isinstance(loaded, dict):
            return None
        roster = loaded.get(ROSTER_KEY)
        if isinstance(roster, dict) and (roster.get("big") or roster.get("small")):
            return cls.from_dict(roster)
        return None

    def save(self, root: Optional[str] = None) -> bool:
        from agents.runtime.device_registry import merge_settings_file
        return merge_settings_file({ROSTER_KEY: self.to_dict()}, root=root)

    # ── placements ────────────────────────────────────────────────────────
    def to_placements(self, devices: List[Any],
                      base_port: int = DEFAULT_BASE_PORT) -> List[Dict[str, Any]]:
        """Emit roster-driven placements in brain_placements' dict shape.

        Order: active big brains first, then active small (stable within tier).
        Ports: sequential from ``base_port``, unique per ACTIVE LOCAL brain;
        cloud brains get ``port=None``. A slot whose device cannot be resolved
        is skipped (never fabricate a device).
        """
        devices = list(devices or [])
        by_id = {getattr(d, "id", ""): d for d in devices}
        ordered = [s for s in self.big if s.enabled] + \
                  [s for s in self.small if s.enabled]
        placements: List[Dict[str, Any]] = []
        # ARCH-ENG-219: slots refused because their device was already
        # occupied. Readable afterwards via `last_rejected_placements`.
        rejected: List[Dict[str, Any]] = []
        port = base_port
        taken: set = set()          # device ids already placed this pass
        _used: Dict[str, int] = {}  # ARCH-ENG-219: models already placed per device
        for slot in ordered:
            dev = by_id.get(slot.device_id) or _auto_device(slot, devices, taken)
            if dev is None:
                continue
            dev_id = getattr(dev, "id", "")

            # ARCH-ENG-219: reject a second model on a device that cannot hold
            # one. The explicit-`device_id` branch above never consulted
            # `taken`, which is how two models ended up assigned to one device.
            #
            # The rejection is RECORDED, not silent. A slot that is quietly
            # dropped is indistinguishable from one the operator never
            # configured, and this codebase's recurring defect is a claim the
            # code has not verified -- a silently dropped placement would be
            # exactly that, one layer down from the model that was never
            # launched in the first place.
            # Capacity, not a boolean: a >=32 GB device hosts TWO models, not an
            # unlimited number. An earlier draft tested only `dev_id in taken`,
            # which let a THIRD model onto a 32 GB card -- the predicate was true
            # so the check never fired. The rule is a per-device budget.
            #
            # LOCAL BRAINS ONLY, and that scoping was found by an EXISTING test
            # rather than by reasoning: `test_to_placements_3big_2small_unique_
            # ports_cloud_no_port` asserts that a CLOUD slot may name a device
            # already used by a local one. It is right -- an OpenAI or Groq brain
            # loads NO model onto the GPU and is placed with `port=None`, so it
            # consumes no VRAM at all. Counting it against the device budget
            # would refuse a configuration that costs the device nothing.
            #
            # The rule is about RESIDENT LOCAL MODELS, which is what the VRAM
            # figure describes.
            if slot.is_local and _used.get(dev_id, 0) >= _capacity_for(dev):
                rejected.append({
                    "slot_tier": slot.tier,
                    "device_id": dev_id,
                    "device_label": (dev.label() if hasattr(dev, "label")
                                     else dev_id),
                    "model": slot.model,
                    # ARCH-ENG-219: the two rejection causes need DIFFERENT
                    # messages. A first draft emitted "below the 32 GB needed"
                    # for both, so a third model refused from a 48 GB card was
                    # reported as having too little VRAM -- which is false, and
                    # would send the operator looking at the wrong number.
                    "reason": (
                        f"device already holds {_used[dev_id]} model(s) and its "
                        f"capacity is {_capacity_for(dev)}"
                        if device_can_host_multiple_models(dev) else
                        f"device holds {getattr(dev, 'memory_gb', 0.0):.0f} GB "
                        f"VRAM, below the {MULTI_MODEL_MIN_VRAM_GB:.0f} GB "
                        f"needed to keep two resident models"),
                })
                continue
            taken.add(dev_id)
            # ARCH-ENG-219: only a resident local model occupies VRAM.
            if slot.is_local:
                _used[dev_id] = _used.get(dev_id, 0) + 1
            if slot.is_local:
                # An operator-pinned port wins over the sequential auto-assign
                # (ARCH-ENG-141: `slot.port` was parsed and then silently
                # ignored — a pin of 8080 became 1234, defeating the override).
                slot_port: Optional[int] = slot.port if slot.port else port
                if not slot.port:
                    port += 1
            else:
                slot_port = None
            placements.append({
                "role": slot.tier,
                "device_id": getattr(dev, "id", ""),
                "kind": getattr(dev, "kind", ""),
                "index": getattr(dev, "index", -1),
                "name": getattr(dev, "name", ""),
                "memory_gb": getattr(dev, "memory_gb", 0.0),
                "is_cpu": getattr(dev, "is_cpu", getattr(dev, "kind", "") == "cpu"),
                "port": slot_port,
                "label": dev.label() if hasattr(dev, "label") else getattr(dev, "id", ""),
                # roster extras (forward-compatible; build_slot_config may read)
                "provider": slot.provider,
                "model": slot.model,
            })
        # ARCH-ENG-219: recorded, not silent. See `device_can_host_multiple_models`.
        self.last_rejected_placements = rejected
        return placements


def _auto_device(slot: BrainSlot, devices: List[Any], taken: Optional[set] = None) -> Any:
    """Pick a device for a slot with no/invalid device_id.

    ARCH-ENG-141: the old tier branch was dead — ``if slot.tier == "big" and
    gpus: return gpus[0]`` was immediately followed by ``if gpus: return
    gpus[0]`` — so a 1-big + 1-small roster placed BOTH slots on the SAME GPU
    (two llama.cpp servers on one card: the VRAM collision the device registry
    exists to prevent). It also ignored ``capability_class()``, so a big slot
    could land on a device the registry itself classifies ``small``.

    Now: ``taken`` (device ids already placed this pass) is excluded, a big slot
    prefers a ``capability_class() == "big"`` GPU, a small slot prefers a
    different (untaken) GPU and then the CPU pool. Deterministic (first match).
    """
    if not devices:
        return None
    taken = taken if taken is not None else set()

    def _is_gpu(d):
        return getattr(d, "is_gpu", getattr(d, "kind", "") == "gpu")

    def _cap_class(d):
        fn = getattr(d, "capability_class", None)
        return fn() if callable(fn) else ""

    gpus = [d for d in devices if _is_gpu(d)]
    cpus = [d for d in devices
            if getattr(d, "is_cpu", getattr(d, "kind", "") == "cpu")]
    free_gpus = [d for d in gpus if getattr(d, "id", "") not in taken]
    free_cpus = [d for d in cpus if getattr(d, "id", "") not in taken]

    if slot.tier == "big":
        # Prefer a device the registry itself classifies big-capable.
        big_gpus = [d for d in free_gpus if _cap_class(d) == "big"]
        if big_gpus:
            return big_gpus[0]
        if free_gpus:
            return free_gpus[0]
        if free_cpus:
            return free_cpus[0]
        return devices[0]

    # small: a DIFFERENT GPU than any already-placed slot, then the CPU pool.
    if free_gpus:
        return free_gpus[0]
    if free_cpus:
        return free_cpus[0]
    return devices[0]


__all__ = ["BrainSlot", "BrainRoster", "MAX_BIG", "MAX_SMALL", "ROSTER_KEY",
           "DEFAULT_BASE_PORT", "LOCAL_PROVIDERS"]
