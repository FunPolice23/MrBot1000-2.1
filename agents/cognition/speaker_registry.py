"""agents/cognition/speaker_registry.py — N-brain speaker roster.

Maps each enabled runtime slot to a Speaker: a distinct NAME + a TIER
("big"/"small") that selects the shared skillset/prompt. This is the N-brain
generalization of the old fixed Edward (big) + Jacob (small) pair.

Design (shared-skills peer council):
- Big-tier brains share ONE earning-agent skillset/prompt, differing only by name.
  Slot 0 keeps the name Edward Hurst; each additional big device gets the next
  big-tier name from the pool.
- Small-tier brains share ONE helper/support prompt, differing only by name.
  Slot 1 keeps the name Jacob Stanley; each additional small/CPU device gets the
  next small-tier name.
- Names are data (a pool), not hardcoded branches, so a 5th brain just consumes
  the next pool entry. Any name is overridable via BRAIN_SLOT{n}_NAME (and the
  first two via BIG_BRAIN_NAME / SMALL_BRAIN_NAME for back-compat), matching the
  Management tab's per-persona name editing.

Nothing here imports Qt or touches the GUI — it is pure data assembly so the
Dialogue tab, tests, and any consumer can build the roster without a display.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Distinct, non-famous-person names for extra brains, assigned in registry order.
# Kept as data so adding more brains never requires a code branch. The first big
# (Edward Hurst) and first small (Jacob Stanley) names come from the existing
# personas for back-compat; these pools supply names 2..N.
BIG_TIER_NAME_POOL: List[str] = [
    "Rowan Vale",
    "Sienna Cross",
    "Dax Mercer",
    "Wren Halloway",
    "Kai Aldridge",
    "Nova Sinclair",
    "Rook Pemberton",
    "Iris Calloway",
]

SMALL_TIER_NAME_POOL: List[str] = [
    "Pip Marlowe",
    "Juno Reyes",
    "Ash Whitlock",
    "Fern Delacroix",
    "Cole Bannister",
    "Sage Ellery",
    "Reeve Stanton",
    "Lark Morrow",
]


@dataclass
class Speaker:
    """One dialogue participant: a named brain on a detected device."""

    slot: int
    key: str                 # "big_brain" | "small_brain" | f"brain_slot{n}"
    name: str                # display name (customizable)
    tier: str                # "big" | "small"  (which shared skillset/prompt)
    brain: object = None     # adapter (set by the caller; registry is Qt-free)
    device_label: str = ""   # "NVIDIA GeForce RTX 5060 Ti (16 GB)"
    is_primary_big: bool = False    # slot 0 big (Edward)
    is_primary_small: bool = False  # slot 1 small (Jacob)

    @property
    def is_big(self) -> bool:
        return self.tier == "big"

    @property
    def is_small(self) -> bool:
        return self.tier == "small"


def _env_name(slot: int, tier: str) -> str:
    """Return the operator-configured name for a slot, or "" if unset.

    Slots 0/1 honor the legacy BIG_BRAIN_NAME / SMALL_BRAIN_NAME keys; every slot
    (including 0/1) also honors BRAIN_SLOT{n}_NAME, which wins if set.
    """
    import os
    slot_key = f"BRAIN_SLOT{slot}_NAME"
    v = (os.getenv(slot_key, "") or "").strip()
    if v:
        return v
    if slot == 0 and tier == "big":
        return (os.getenv("BIG_BRAIN_NAME", "") or "").strip()
    if slot == 1 and tier == "small":
        return (os.getenv("SMALL_BRAIN_NAME", "") or "").strip()
    return ""


def _default_name(slot: int, tier: str, big_seen: int, small_seen: int) -> str:
    """Default display name for a slot from the per-tier pool.

    Slot 0 big -> Edward Hurst; slot 1 small -> Jacob Stanley (back-compat with
    the existing personas). Additional slots consume the next pool name.
    """
    if slot == 0 and tier == "big":
        return "Edward Hurst"
    if slot == 1 and tier == "small":
        return "Jacob Stanley"
    if tier == "big":
        idx = big_seen - 1  # big_seen counts this one; Edward is index 0
        pool = BIG_TIER_NAME_POOL
    else:
        idx = small_seen - 1
        pool = SMALL_TIER_NAME_POOL
    if 0 <= idx < len(pool):
        return pool[idx]
    # Pool exhausted: deterministic fallback so names stay unique.
    return f"{'Big' if tier == 'big' else 'Small'} Brain #{slot}"


def build_speakers(placements: List[Dict], brains: Optional[Dict[int, object]] = None
                   ) -> List[Speaker]:
    """Build the speaker roster from device placements.

    ``placements`` is the list from ``device_registry.brain_placements()`` — each
    has {role, device_id, name, port, is_cpu, label, ...}. ``brains`` optionally
    maps slot -> adapter (the caller supplies adapters; the registry stays
    Qt-free). Slots are ordered as given (big-class first, then small, per the
    registry). Names come from the per-tier pool / env override; no two enabled
    speakers share a name.
    """
    speakers: List[Speaker] = []
    used_names = set()
    big_seen = 0
    small_seen = 0
    for i, p in enumerate(placements or []):
        role = str(p.get("role", "")).lower()
        tier = "big" if role == "big" else "small"
        if tier == "big":
            big_seen += 1
        else:
            small_seen += 1
        # Key: slots 0/1 keep the legacy big_brain/small_brain keys; 2+ are
        # brain_slot{n}. This matches the persistence + DB logger keys.
        if i == 0:
            key = "big_brain"
        elif i == 1:
            key = "small_brain"
        else:
            key = f"brain_slot{i}"
        # Name: env override wins, else the per-tier pool default.
        name = _env_name(i, tier) or _default_name(i, tier, big_seen, small_seen)
        # Guarantee uniqueness even if the operator duplicates a name.
        base = name
        n = 2
        while name.casefold() in used_names:
            name = f"{base} ({n})"
            n += 1
        used_names.add(name.casefold())
        device_label = p.get("label") or p.get("name", "") or ""
        speakers.append(Speaker(
            slot=i,
            key=key,
            name=name,
            tier=tier,
            brain=(brains or {}).get(i),
            device_label=device_label,
            is_primary_big=(i == 0 and tier == "big"),
            is_primary_small=(i == 1 and tier == "small"),
        ))
    return speakers


def speaker_for_slot(speakers: List[Speaker], slot: int) -> Optional[Speaker]:
    for s in speakers:
        if s.slot == slot:
            return s
    return None


def speaker_for_key(speakers: List[Speaker], key: str) -> Optional[Speaker]:
    for s in speakers:
        if s.key == key:
            return s
    return None


def speaker_for_name(speakers: List[Speaker], name: str) -> Optional[Speaker]:
    target = (name or "").strip().casefold()
    for s in speakers:
        if s.name.casefold() == target:
            return s
    return None


def default_pingpong_order(speakers: List[Speaker]) -> List[Speaker]:
    """The classic 1-big + 1-small ping-pong order (Edward, Jacob).

    Returns [primary big, primary small] when both exist; otherwise the first two
    speakers. Used as the default turn order so the 2-brain case is unchanged.
    """
    big = next((s for s in speakers if s.is_primary_big), None)
    small = next((s for s in speakers if s.is_primary_small), None)
    if big is not None and small is not None:
        return [big, small]
    return speakers[:2]


def build_team_brief(speakers: List[Speaker], self_speaker: Optional[Speaker],
                     goal: str = "") -> str:
    """Build the multi-brain council block injected into a brain's system prompt.

    Returns "" for the single-brain case (no behavior change). For 2+ brains it
    lists the other enabled participants (name · tier · device) and states the
    peer-deliberation rule: read the teammates' latest thoughts + tool-call
    results already in the transcript, then add YOUR own perspective (agree,
    refine, dissent, or call your own tool). Shared-skills peer council: you are
    peers working toward one goal, not a driver/navigator hierarchy.

    The block is deliberately compact so it does not bloat the small-model token
    budget; it replaces, not duplicates, per-persona identity (which the caller
    already emits via the persona's own IDENTITY block).
    """
    if self_speaker is None or len(speakers) < 2:
        return ""
    peers = [s for s in speakers if s is not self_speaker]
    if not peers:
        return ""
    lines = ["\n# TEAM (peer council — you are peers, not a hierarchy)"]
    if goal:
        lines.append(f"Shared goal: {goal}")
    lines.append("Teammates on this run:")
    for p in peers:
        tier = "big (earning agent)" if p.is_big else "small (helper/support)"
        dev = (p.device_label or "").strip()
        dev_str = f" · {dev}" if dev else ""
        lines.append(f"- {p.name} — {tier}{dev_str}")
    lines.append(
        "Peer deliberation: the transcript already shows your teammates' latest "
        "thoughts and any tool-call results. Read them, then add YOUR OWN "
        "perspective — agree, refine, push back, or call your own tool. Do not "
        "just echo them; do not wait for permission. Speak as "
        f"{self_speaker.name} in first person. "
        "When the OPPORTUNITY BOARD is present, do NOT just pick the first row: "
        "name the full ranked list, argue the candidates best->worst with your "
        "reasoning, then converge on ONE concrete next action. If you have no "
        "new evidence, say so plainly (UNKNOWN/BLOCKED) instead of inventing "
        "agreement."
    )
    return "\n".join(lines) + "\n\n"


__all__ = [
    "Speaker", "build_speakers", "speaker_for_slot", "speaker_for_key",
    "speaker_for_name", "default_pingpong_order", "build_team_brief",
    "BIG_TIER_NAME_POOL", "SMALL_TIER_NAME_POOL",
]
