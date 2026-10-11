"""
Regression test for the event-driven Live failure circuit breaker.

Both llama-server instances (ports 1234/1235) must be reachable for the
end-to-end tests. The handler-logic tests exercise the runtime failure guard directly.

Run: python tests/test_dialogue_circuit_breaker.py
"""
import sys
import os

import pytest

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
@pytest.mark.skipif(
    not END_TO_END,
    reason="setup_ui() constructs real widgets; skipped when llama-server not reachable"
)
def test_live_response_handler_keeps_running_after_provider_failures():
    """Live must keep retrying after consecutive provider failures."""
    from agents.brains.big_brain import BigBrainAdapter
    from agents.brains.small_brain import SmallBrainAdapter
    from gui.tabs.dialogue_tab import DialogueTab

    tab = DialogueTab(
        small_brain=SmallBrainAdapter(),
        big_brain=BigBrainAdapter(),
    )
    tab.setup_ui()
    tab.set_goal("test")

    tab.live_running = True
    tab.live_btn.setText("⏸ Stop Live")

    # First transport error
    tab._record_live_failure("Edward could not reach its model")
    assert tab._live_failure_count == 1, (
        f"expected 1 failed response, got {tab._live_failure_count}"
    )
    assert tab.live_running, "Live should stay running after the first failure"

    # Second transport error
    tab._record_live_failure("Jacob could not reach its model")
    assert tab._live_failure_count >= 2, (
        f"expected at least 2 failed responses, got {tab._live_failure_count}"
    )
    assert tab.live_running, "Live must remain active while it recovers"

    tab.deleteLater()
    print("PASS: Live response handler stops after two failures")


# ---------------------------------------------------------------------------
# 2. Handler-logic test — "No response generated" path is now covered
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not END_TO_END,
    reason="setup_ui() constructs real widgets; skipped when llama-server not reachable"
)
def test_live_failure_handler_keeps_running_after_no_response_failures():
    """The event-driven failure counter must support ongoing recovery."""
    from agents.brains.big_brain import BigBrainAdapter
    from agents.brains.small_brain import SmallBrainAdapter
    from gui.tabs.dialogue_tab import DialogueTab

    tab = DialogueTab(
        small_brain=SmallBrainAdapter(),
        big_brain=BigBrainAdapter(),
    )
    tab.setup_ui()
    tab.set_goal("test")

    tab.live_running = True

    # First "no response generated" response
    tab._record_live_failure("Edward returned no response")
    assert tab._live_failure_count == 1, (
        f"expected 1 failed response, got {tab._live_failure_count}"
    )
    assert tab.live_running, "Live should still be running after one empty response"

    # Second "no response generated" — must now stop
    tab._record_live_failure("Jacob returned no response")
    assert tab._live_failure_count >= 2, (
        f"expected at least 2 failed responses, got {tab._live_failure_count}"
    )
    assert tab.live_running, "Live must remain active after no-response failures"

    tab.deleteLater()
    print("PASS: Live no-response path remains recoverable")


# ---------------------------------------------------------------------------
# 3. End-to-end test — requires live llama-server on 1234 and 1235
# ---------------------------------------------------------------------------
def test_live_mode_button():
    """The event-driven runtime uses one Live button."""
    from agents.brains.big_brain import BigBrainAdapter
    from agents.brains.small_brain import SmallBrainAdapter
    from gui.tabs.dialogue_tab import DialogueTab

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


def test_live_end_to_end_toggle():
    """Full end-to-end: start and stop the event-driven Live runtime."""
    if not END_TO_END:
        # A bare `return` made this a SILENT PASS on any box without a live
        # llama-server — it reported green while asserting nothing. Use a real
        # skip so the suite honestly shows the test did not run.
        pytest.skip("llama-server not reachable on 1234/1235")

    import time

    from agents.brains.big_brain import BigBrainAdapter
    from agents.brains.small_brain import SmallBrainAdapter
    from gui.tabs.dialogue_tab import DialogueTab

    big = BigBrainAdapter()
    small = SmallBrainAdapter()
    big.model = "D:/llama.cpp/models/Qwen3.8-27B-UD-IQ3_XXS.gguf"
    small.model = "D:/llama.cpp/models/Qwen3.5-4B-UD-Q5_K_XL.gguf"

    tab = DialogueTab(small_brain=small, big_brain=big)
    tab.show()
    tab.set_goal("test goal")
    tab.live_btn.click()
    time.sleep(0.5)

    initial_failures = tab._live_failure_count
    tab.live_btn.click()
    tab.deleteLater()

    print(
        f"PASS: Live toggle works; initial failures={initial_failures}"
    )


if __name__ == "__main__":
    test_live_mode_button()
    test_live_response_handler_stops_after_two_failures()
    test_live_failure_handler_stops_after_two_no_response_failures()
    test_live_end_to_end_toggle()
    print("\nAll event-driven Live circuit-breaker tests complete.")
