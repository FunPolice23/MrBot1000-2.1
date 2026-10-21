"""D — a deterministic empty model response is not a transport error.

The brains emit "[<Name> Error: model returned an empty response for '...']"
when a generation comes back blank. That string used to be classified as a
TRANSPORT error (it starts with '[' and contains ' error:'), so Live burned its
whole transport-retry budget — 8 identical retries, ~10 min CPU — on a fault a
reconnect cannot fix. A blank generation needs a stronger prompt (the bounded
empty-response handler), not another connection attempt.

These tests target the classification BEHAVIOUR, so they FAIL if the empty
marker is (re)folded into the transport path. Pure functions: no Qt, no network.
"""
import os
import sys
import unittest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gui.tabs.dialogue_tab import (
    _is_transport_error_text,
    _is_empty_response_text,
    _is_empty_model_response,
)

# The exact shape big_brain.py / small_brain.py emit for a blank generation.
_EMPTY_MARKER_RESPONSE = (
    "[Edward Hurst Error: model returned an empty response for "
    "'qwen3.gguf' at http://127.0.0.1:1234/v1. Check the loaded model "
    "and chat template.]"
)


class EmptyResponseIsNotTransportErrorTest(unittest.TestCase):
    def test_empty_model_response_is_not_transport_error(self):
        # The core fix: a blank generation must NOT trip the transport path.
        self.assertFalse(_is_transport_error_text(_EMPTY_MARKER_RESPONSE))

    def test_empty_model_response_is_empty_response(self):
        # ...and must be routed to the bounded empty-response handler.
        self.assertTrue(_is_empty_response_text(_EMPTY_MARKER_RESPONSE))
        self.assertTrue(_is_empty_model_response(_EMPTY_MARKER_RESPONSE))

    def test_real_transport_errors_still_trip(self):
        # The transport path must keep working for genuine connection faults.
        for msg in (
            "Error: connection error",
            "[error: connection refused]",
            "connection error to host",
            "no model selected",
            "no model loaded",
        ):
            self.assertTrue(_is_transport_error_text(msg), msg)

    def test_blank_and_empty_marker_are_empty_not_transport(self):
        for msg in ("", "(empty)"):
            self.assertFalse(_is_transport_error_text(msg))
            self.assertTrue(_is_empty_response_text(msg))

    def test_valid_persona_turn_is_neither(self):
        turn = "I think we should pursue the GitHub bounty — it fits our skills."
        self.assertFalse(_is_transport_error_text(turn))
        self.assertFalse(_is_empty_response_text(turn))


if __name__ == "__main__":
    unittest.main()
