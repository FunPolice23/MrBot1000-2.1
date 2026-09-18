"""Regression test for dialogue context ordering (convergence + truncation).

Two defects this locks in:
1. Convergence — the opportunity board is re-injected every turn, so a human
   instruction that lived only as one history row was outranked by the board and
   the phase instruction. The context builder must surface the operator's most
   recent directive as its own line, ahead of the board.
2. Truncation — ``get_dialogue_context`` returns ``context[:limit]`` (cuts the
   TAIL), so the response contract ("Respond AS …", tool-call rules, "NEVER make
   up data") must be emitted BEFORE the board, or a long board can evict it.

Both invariants are asserted against a real DialogueTab instance.
"""

from __future__ import annotations

from gui.dialogue_tab import DialogueTab


class _StubBrain:
    model = "D:/llama.cpp/models/Llama-3-8B-Instruct-32k-v0.1.Q4_K_M.gguf"
    base_url = ""
    last_provider = "llamacpp"


def _make_tab() -> DialogueTab:
    tab = DialogueTab(small_brain=_StubBrain(), big_brain=_StubBrain())
    tab.goal = "earn money this week"
    tab.current_speaker = "Edward Hurst"
    tab.conversation_history = [
        {"role": "assistant", "speaker": "Edward Hurst",
         "content": "I propose evaluating the airdrops."},
        {"role": "user", "speaker": "Human",
         "content": "Lets ignore Airdrop as most feel like a scam."},
        {"role": "assistant", "speaker": "Jacob Stanley",
         "content": "BLOCKED: impossible values."},
    ]
    return tab


def test_operator_directive_precedes_board():
    """The human's latest instruction must be surfaced ahead of the board."""
    tab = _make_tab()
    ctx = tab.get_dialogue_context()

    assert "OPERATOR DIRECTIVE" in ctx, "missing explicit operator directive line"
    assert "ignore Airdrop" in ctx, "human instruction text not carried into context"

    board_idx = ctx.find("OPPORTUNITY")
    directive_idx = ctx.find("OPERATOR DIRECTIVE")
    if board_idx != -1:
        assert directive_idx < board_idx, (
            "operator directive must appear before the re-injected board")
    print("PASS: operator directive precedes the board")


def test_response_contract_survives_truncation():
    """The response contract must sit before the board so it is never cut."""
    tab = _make_tab()
    ctx = tab.get_dialogue_context()

    contract_idx = ctx.find("Respond AS Edward Hurst")
    assert contract_idx != -1, "response contract missing from context"
    assert contract_idx < tab._context_char_limit, (
        "response contract fell outside the truncation window")

    board_idx = ctx.find("OPPORTUNITY")
    if board_idx != -1:
        assert contract_idx < board_idx, (
            "response contract must be emitted before the board")
    print("PASS: response contract precedes the board / survives truncation")


def test_directive_tracks_the_most_recent_human_message():
    """A newer human message must supersede an older one in the directive line."""
    tab = _make_tab()
    tab.conversation_history.append(
        {"role": "user", "speaker": "Human",
         "content": "Focus only on freelance gigs with verifiable payouts."})
    ctx = tab.get_dialogue_context()

    assert "Focus only on freelance gigs" in ctx, "newest directive not surfaced"
    newest = ctx.rfind("Focus only on freelance gigs")
    older = ctx.rfind("ignore Airdrop")
    assert newest > older or older == -1, (
        "the newest operator directive must be the one surfaced")
    print("PASS: newest operator directive wins")
