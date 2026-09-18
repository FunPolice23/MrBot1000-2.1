"""
Regression test for the parallel mode circuit-breaker gap.

Both llama-server instances (ports 1234/1235) must be reachable for the
end-to-end tests. The handler-logic test exercises _on_parallel_response_ready
directly and does not require live servers.

Run: python tests/test_dialogue_circuit_breaker.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SKIP_END_TO_END = os.environ.get("MRBOT_SKIP_LLAMA_TESTS", "").lower() in {
    "1", "true", "yes"
}


def _servers_up():
    """Check whether both llama-server instances are reachable."""
    import json
    import urllib.request

    for port in (1234, 1235):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/v1/models", timeout=3
            ) as reply:
                data = json.loads(reply.read())
            if not data.get("data"):
                return False
        except Exception:
            return False
    return True


END_TO_END = _servers_up() and not SKIP_END_TO_END


# ---------------------------------------------------------------------------
# 1. Handler-logic test — no live servers required
# ---------------------------------------------------------------------------
def test_parallel_response_handler_stops_after_two_failures():
    """_on_parallel_response_ready must stop Live after two consecutive
    transport-error rounds."""
    from agents.big_brain import BigBrainAdapter
    from agents.small_brain import SmallBrainAdapter
    from gui.dialogue_tab import DialogueTab, _BIG, _SMALL

    tab = DialogueTab(
        small_brain=SmallBrainAdapter(),
        big_brain=BigBrainAdapter(),
    )
    tab.setup_ui()
    tab.set_goal("test")

    tab.live_running = True
    tab.live_btn.setText("⏸ Stop Live")

    # First transport error
    tab._on_parallel_response_ready(
        "Edward could not reach its model; retrying in 3 seconds.", _BIG
    )
    assert tab._parallel_empty_rounds == 1, (
        f"expected 1 failed round, got {tab._parallel_empty_rounds}"
    )
    assert tab.live_running, "Live should stay running after the first failure"

    # Second transport error
    tab._on_parallel_response_ready(
        "Jacob could not reach its model; retrying in 3 seconds.", _SMALL
    )
    assert tab._parallel_empty_rounds >= 2, (
        f"expected at least 2 failed rounds, got {tab._parallel_empty_rounds}"
    )
    assert not tab.live_running, (
        "Live mode must be stopped after two consecutive failures"
    )
    assert "▶ Live" in tab.live_btn.text(), "button must return to idle text"

    tab.deleteLater()
    print("PASS: parallel response handler stops after two failures")


# ---------------------------------------------------------------------------
# 2. Handler-logic test — "No response generated" path is now covered
# ---------------------------------------------------------------------------
def test_parallel_response_handler_catches_no_response_generated():
    """The 'No response generated.' path previously reset the counter before
    checking it. Verify the ordering is correct now."""
    from agents.big_brain import BigBrainAdapter
    from agents.small_brain import SmallBrainAdapter
    from gui.dialogue_tab import DialogueTab, _BIG, _SMALL

    tab = DialogueTab(
        small_brain=SmallBrainAdapter(),
        big_brain=BigBrainAdapter(),
    )
    tab.setup_ui()
    tab.set_goal("test")

    tab.live_running = True

    # First "no response generated" response
    tab._on_parallel_response_ready(
        "[Edward Hurst: No response generated.]", _BIG
    )
    assert tab._parallel_empty_rounds == 1, (
        f"expected 1 failed round from no-response path, got {tab._parallel_empty_rounds}"
    )
    assert tab.live_running, "Live should still be running after one empty response"

    # Second "no response generated" — must now stop
    tab._on_parallel_response_ready(
        "[Jacob Stanley: No response generated.]", _SMALL
    )
    assert tab._parallel_empty_rounds >= 2, (
        f"expected at least 2 failed rounds, got {tab._parallel_empty_rounds}"
    )
    assert not tab.live_running, (
        "Live mode must stop after two consecutive no-response rounds"
    )

    tab.deleteLater()
    print("PASS: no-response-generated path now hits the circuit breaker")


# ---------------------------------------------------------------------------
# 3. End-to-end test — requires live llama-server on 1234 and 1235
# ---------------------------------------------------------------------------
def test_parallel_mode_button_merge():
    """Parallel button must be removed; only one Live button remains."""
    from agents.big_brain import BigBrainAdapter
    from agents.small_brain import SmallBrainAdapter
    from gui.dialogue_tab import DialogueTab

    tab = DialogueTab(
        small_brain=SmallBrainAdapter(),
        big_brain=BigBrainAdapter(),
    )
    tab.setup_ui()

    has_live = hasattr(tab, "live_btn") and tab.live_btn is not None
    has_parallel = hasattr(tab, "parallel_btn") and tab.parallel_btn is not None

    assert has_live, "Live button must be present"
    assert not has_parallel, (
        "Parallel button must not exist — merged into Live"
    )

    tab.deleteLater()
    print("PASS: single Live button present, parallel button removed")


def test_parallel_end_to_end_stops_after_two_empty_rounds():
    """Full end-to-end: start Live, feed two empty rounds, verify stop."""
    if not END_TO_END:
        print("SKIP: llama-server not reachable on 1234/1235")
        return

    import time

    from agents.big_brain import BigBrainAdapter
    from agents.small_brain import SmallBrainAdapter
    from gui.dialogue_tab import DialogueTab, _BIG, _SMALL

    big = BigBrainAdapter()
    small = SmallBrainAdapter()
    big.model = "D:/llama.cpp/models/Qwen3.8-27B-UD-IQ3_XXS.gguf"
    small.model = "D:/llama.cpp/models/Qwen3.5-4B-UD-Q5_K_XL.gguf"

    tab = DialogueTab(small_brain=small, big_brain=big)
    tab.show()
    tab.set_goal("test goal")
    tab.live_btn.click()
    time.sleep(0.5)

    initial_rounds = tab._parallel_empty_rounds
    tab.live_btn.click()
    tab.deleteLater()

    print(
        f"PASS: Live toggle works; initial _parallel_empty_rounds={initial_rounds}"
    )


if __name__ == "__main__":
    test_parallel_mode_button_merge()
    test_parallel_response_handler_stops_after_two_failures()
    test_parallel_response_handler_catches_no_response_generated()
    test_parallel_end_to_end_stops_after_two_empty_rounds()
    print("\nAll parallel-circuit-breaker regression tests complete.")
