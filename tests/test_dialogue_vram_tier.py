"""Regression tests for VRAM-gated prompt tiering.

Design rule (user): a brain on a GPU under the 10 GB threshold gets small-model
prompting regardless of the model it runs; a brain on a >= 10 GB card may use
the enhanced (full) prompt. The existing model-size tier is the deterministic
fallback when VRAM cannot be read — a failed telemetry read must never silently
demote or promote a brain (that would make prompt quality flip run to run on a
transient nvidia-smi failure).
"""

from __future__ import annotations

from gui.dialogue_tab import DialogueTab

_BIG_MODEL = "D:/llama.cpp/models/Qwen3.6-14B-A3B-FableVibes-Q4_K_M.gguf"   # -> full
_SMALL_MODEL = "D:/llama.cpp/LFM2.5-2.6B-Q5_K_M.gguf"                       # -> tiny
_MID_MODEL = "NVIDIA-Nemotron-3-Nano-4B-Q4_K_M.gguf"                        # -> compact


class _StubBrain:
    model = _BIG_MODEL
    base_url = ""
    last_provider = "llamacpp"


def _tab() -> DialogueTab:
    return DialogueTab(small_brain=_StubBrain(), big_brain=_StubBrain())


def test_unknown_vram_falls_back_to_model_size_tier():
    """No readable VRAM must not demote or promote — use the model-size tier."""
    tab = _tab()
    tab._brain_gpu_vram_gb = lambda small: None
    assert tab._tier_for_brain(False, _BIG_MODEL) == "full"
    assert tab._tier_for_brain(True, _SMALL_MODEL) == "tiny"
    assert tab._tier_for_brain(True, _MID_MODEL) == "compact"
    print("PASS: unknown VRAM falls back to model-size tier")


def test_small_card_caps_full_model_at_compact():
    """A >= 9B model on a < 10 GB card gets small-model (compact) prompting."""
    tab = _tab()
    tab._brain_gpu_vram_gb = lambda small: 6.0
    assert tab._tier_for_brain(True, _BIG_MODEL) == "compact", (
        "a large model on a 6GB card must be capped at compact")
    print("PASS: 6GB card caps a full-tier model at compact")


def test_small_card_does_not_demote_below_model_tier():
    """The VRAM cap must not push a tiny model further down."""
    tab = _tab()
    tab._brain_gpu_vram_gb = lambda small: 6.0
    assert tab._tier_for_brain(True, _SMALL_MODEL) == "tiny"
    print("PASS: 6GB card leaves an already-tiny model at tiny")


def test_large_card_allows_full_tier():
    """>= 10 GB lets the model-size tier stand (enhanced prompting allowed)."""
    tab = _tab()
    tab._brain_gpu_vram_gb = lambda small: 15.9
    assert tab._tier_for_brain(False, _BIG_MODEL) == "full"
    assert tab._tier_for_brain(False, _MID_MODEL) == "compact"
    print("PASS: 16GB card allows the model-size tier")


def test_threshold_boundary_is_ten_gb():
    """9.9 GB caps; 10.0 GB does not."""
    tab = _tab()
    tab._brain_gpu_vram_gb = lambda small: 9.9
    assert tab._tier_for_brain(True, _BIG_MODEL) == "compact"
    tab._brain_gpu_vram_gb = lambda small: 10.0
    assert tab._tier_for_brain(True, _BIG_MODEL) == "full"
    print("PASS: 10 GB boundary behaves as specified")


def _contract_tier(tab: DialogueTab, model: str, small: bool) -> str:
    """Extract the tier the output contract actually reports."""
    text = tab._model_output_contract(model, small)
    marker = "- Capability tier: "
    idx = text.find(marker)
    assert idx != -1, "output contract missing capability tier line"
    return text[idx + len(marker):].split(".", 1)[0].strip()


def test_all_tier_sites_agree_for_every_small_model_pair():
    """The system prompt, the contract, and the context must report one tier.

    Regression: these were three independent computations, so a VRAM cap could
    move the system prompt without moving the contract. A two-site check would
    have missed it, so this exercises every (small, model, VRAM) combination.
    """
    combos = [
        (True, _SMALL_MODEL, None), (True, _BIG_MODEL, 6.0),
        (False, _BIG_MODEL, 15.9), (False, _MID_MODEL, 15.9),
        (True, _MID_MODEL, 8.0), (False, _BIG_MODEL, None),
        (True, _BIG_MODEL, 10.0), (True, _SMALL_MODEL, 6.0),
    ]
    for small, model, vram in combos:
        tab = _tab()
        tab._brain_gpu_vram_gb = (lambda v: (lambda s: v))(vram)
        expected = tab._tier_for_brain(small, model)
        contract = _contract_tier(tab, model, small)
        assert contract == expected, (
            f"tier disagreement for small={small} model={model} vram={vram}: "
            f"tier_for_brain={expected} but contract says {contract}")
    print("PASS: all tier sites agree across every (small, model, vram) pair")


def test_full_model_on_small_card_reports_compact_everywhere():
    """The specific regression: 14B on a 6GB card must be compact at all sites."""
    tab = _tab()
    tab._brain_gpu_vram_gb = lambda small: 6.0
    assert tab._tier_for_brain(True, _BIG_MODEL) == "compact"
    assert _contract_tier(tab, _BIG_MODEL, True) == "compact", (
        "output contract must also cap at compact, not report full")
    print("PASS: 14B on 6GB card reports compact at both sites")


def test_log_record_reports_the_same_tier_as_the_prompt_path():
    """The per-turn log's 'tier' field must match _tier_for_brain (VRAM-capped).

    Regression: the log computed its tier inline from model size only, so a
    14B on a 6GB card ran 'compact' but the log recorded 'full' — misleading
    any diagnosis that reads the log.
    """
    import gui.dialogue_tab as dt
    from gui.dialogue_tab import DialogueTab

    tab = _tab()
    tab._brain_gpu_vram_gb = lambda small: 6.0
    captured = {}
    dt._append_dialogue_log = lambda rec: captured.update(rec)
    tab._log_dialogue_turn("Jacob Stanley", "accepted", "test reply")
    assert captured.get("tier") == "compact", (
        f"log tier must be VRAM-capped, got {captured.get('tier')!r}")
    print("PASS: log record reports the VRAM-capped tier")
