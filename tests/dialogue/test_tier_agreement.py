"""Cross-site tier-agreement regression tests.

Security's spec: assert `_tier_for_brain()` == `_model_output_contract`'s
"Capability tier:" == the "MODEL TIER:" label from `get_dialogue_context`, for
each (small, model) pair — a two-site test would have missed the third site
(the context body), which previously recomputed its tier independently and
could report a different tier than the system prompt/contract in one turn.

The fixed design computes ONE tier per turn in respond(), caches it, and has
every site read that cached value — so even if a VRAM probe flaps mid-turn
(simulated here by monkeypatching `_tier_for_brain` to a bogus value), all
three sites must still agree on the cached tier.
"""
from __future__ import annotations

import re

from gui.tabs.dialogue_tab import DialogueTab, _BIG, _SMALL

_BIG_MODEL = "D:/llama.cpp/models/Qwen3.6-14B-A3B-FableVibes-Q4_K_M.gguf"   # size 14 -> full
_SMALL_MODEL = "D:/llama.cpp/LFM2.5-2.6B-Q5_K_M.gguf"                        # size 2.6 -> tiny
_MID_MODEL = "NVIDIA-Nemotron-3-Nano-4B-Q4_K_M.gguf"                         # size 4 -> compact


class _StubBrain:
    model = _BIG_MODEL
    base_url = ""
    last_provider = "llamacpp"


def _tab():
    return DialogueTab(small_brain=_StubBrain(), big_brain=_StubBrain())


def _point_turn_at(tab, small, model):
    """Point the active turn at (small, model) with unknown (deterministic) VRAM."""
    tab.current_speaker = _SMALL if small else _BIG
    (tab.small_brain if small else tab.big_brain).model = model
    tab._brain_gpu_vram_gb = lambda _s: None


def _contract_tier(tab, small, model, tier=None):
    c = tab._model_output_contract(model, small=small, tier=tier)
    m = re.search(r"Capability tier:\s*(\w+)", c)
    return m.group(1) if m else None


def _context_tier(tab):
    m = re.search(r"MODEL TIER:\s*(\w+)", tab.get_dialogue_context())
    return m.group(1) if m else None


def test_all_three_sites_agree_for_every_pair():
    pairs = [
        (False, _BIG_MODEL),     # 14B big brain
        (True, _BIG_MODEL),      # 14B on the small-brain card
        (True, _SMALL_MODEL),    # 2.6B small brain
        (True, _MID_MODEL),      # 4B small brain
        (False, _MID_MODEL),     # 4B big brain
    ]
    for small, model in pairs:
        tab = _tab()
        _point_turn_at(tab, small, model)
        # The authoritative tier from the single shared source.
        authoritative = tab._tier_for_brain(small, model)
        # Cache it exactly as respond() does.
        tab._tier_cache = {"speaker": tab.current_speaker, "tier": authoritative}
        # All three sites must agree (contract called with the cached tier,
        # mirroring the respond() call site).
        assert _contract_tier(tab, small, model, tier=authoritative) == authoritative
        assert _context_tier(tab) == authoritative


def test_sites_do_not_reprobe_vram_mid_turn():
    """A flapping _tier_for_brain (simulated VRAM race) must not split a turn."""
    tab = _tab()
    _point_turn_at(tab, True, _MID_MODEL)  # compact small brain
    authoritative = tab._tier_for_brain(True, _MID_MODEL)
    assert authoritative == "compact"
    tab._tier_cache = {"speaker": tab.current_speaker, "tier": authoritative}

    # Simulate the VRAM probe flapping to a different answer mid-turn.
    tab._tier_for_brain = lambda small, model: "full"
    # Both the contract (given the cached tier in the call, as respond() does)
    # and the context body (which reads the cache) must still report the cached
    # tier — never a freshly-re-probed value that would split the turn.
    assert _contract_tier(tab, True, _MID_MODEL, tier=authoritative) == "compact"
    assert _context_tier(tab) == "compact"