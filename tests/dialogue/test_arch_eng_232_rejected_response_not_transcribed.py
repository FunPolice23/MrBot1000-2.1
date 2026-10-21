"""ARCH-ENG-232 / AV-01 -- a rejected dialogue response must never enter the
shared transcript, including when the retries run out.

The defect
----------
`DialogueWorker.run()` validates a model turn with
`_is_bad_dialogue_response(response) or _is_repetitive(response)` and, on a
hit, retries up to `max_retries` times. Two things went wrong:

  1. The retry loop's exit test re-checked ONLY
     `_is_bad_dialogue_response`. A retry that stopped being "bad" but stayed
     repetitive was accepted as a successful recovery.

  2. When every attempt was rejected, the `for` loop simply fell out with the
     REJECTED text still bound to `response`, and the two emits at the end of
     the block wrote it into the shared transcript. The verdict the validator
     had just computed was discarded on the exhaust path -- so the validator's
     own docstring ("rejected before it can enter the shared transcript") was
     false on exactly the path that needed it. With `max_retries == 0` the
     rejected FIRST response reached the emit with no retry at all.

Why the suite was green
-----------------------
`_safe_fallback_response` -- whose docstring is "Return a bounded, phase-aware
fallback when retries are exhausted" -- had three tests and ZERO production
callers. Those three tests called the helper directly and asserted on its text.
None of them drove `run()`, so the missing caller was invisible to them.

These tests drive the worker. The probe in
`test_good_response_is_not_replaced_by_fallback` is what keeps them honest:
without it a fix that simply *always* emitted the fallback would satisfy every
other test here.
"""

import unittest
from unittest.mock import Mock

from gui.tabs.dialogue_tab import DialogueWorker


# A turn the validator must reject, for a reason that has nothing to do with
# thinking-budget exhaustion: pure model-identity boilerplate.
REJECTED = "The model is Gemma. I am an open-weights model with no internet access."

# A turn the validator must accept.
ACCEPTED = "I recommend starting with freelance work on a single platform."

# Repetitive but NOT "bad". `_is_repetitive` fires on `response.count("?") > 3`
# as well as on REPETITION_PHRASES matches, so four questions is enough. This
# payload is a realistic model-stall shape: it asks, and never answers.
REPETITIVE = "Should I start? Should I wait? Should I ask? Should I stop? Should I try?"


class TestARCHENG232RejectedResponseNeverEntersTranscript(unittest.TestCase):
    """Drives `DialogueWorker.run()` with a stub brain and captures emits."""

    def _worker(self, replies, max_retries=2, context=None):
        """A DialogueWorker wired only as far as run() actually touches it."""
        worker = DialogueWorker.__new__(DialogueWorker)
        worker.context = context if context is not None else "CURRENT PHASE: discover"
        worker.history = []
        worker.max_tokens = 512
        worker.speaker = "edward"
        worker.slot = 0
        worker.system_prompt = ""
        worker.images = []
        worker.anti_repetition = True
        worker.max_retries = max_retries
        worker._cancelled = False
        worker._stop_requested = lambda: False
        worker._ensure_model_selected = lambda: None
        # streaming / GPU-window accounting touched by the stream callback
        worker._stream_t0 = None
        worker._stream_chars = 0
        worker._last_gpu_emit = 0.0
        worker._emitted_tool_calls = set()
        worker.gpu_progress = Mock()
        worker.tool_activity = Mock()
        worker._tool_trace_cb_unused = None

        calls = []

        class Brain:
            model = "stub-model"

            def chat(self, *a, **kw):
                calls.append(kw)
                # First call is the normal turn; the rest are retries.
                idx = min(len(calls) - 1, len(replies) - 1)
                return replies[idx]

        worker.brain = Brain()
        worker.emitted = []
        worker.progress = Mock()
        worker.response_ready = Mock()
        worker.progress.emit = lambda *a, **kw: worker.emitted.append(("progress",) + a)
        worker.response_ready.emit = lambda *a, **kw: worker.emitted.append(("ready",) + a)
        return worker, calls

    def _emitted_text(self, worker):
        """The text the tab would have written into the shared transcript."""
        kinds = [e for e in worker.emitted if e[0] == "ready"]
        self.assertTrue(kinds, "worker never emitted a response")
        return kinds[-1][1]

    # ------------------------------------------------------------------
    # Fixture self-checks. If these fail the rest of the class proves nothing.
    # ------------------------------------------------------------------

    def test_fixtures_are_classified_as_intended(self):
        worker, _ = self._worker([REJECTED])
        self.assertTrue(worker._is_bad_dialogue_response(REJECTED),
                        "REJECTED fixture must fail the 'bad' check")
        self.assertFalse(worker._is_bad_dialogue_response(ACCEPTED),
                         "ACCEPTED fixture must pass the 'bad' check")
        self.assertFalse(worker._is_bad_dialogue_response(REPETITIVE),
                         "REPETITIVE fixture must PASS the 'bad' check -- the "
                         "repetitiveness half is what must catch it")
        self.assertTrue(worker._is_repetitive(REPETITIVE),
                        "REPETITIVE fixture must fail the repetitive check")

    # ------------------------------------------------------------------
    # The defect itself.
    # ------------------------------------------------------------------

    def test_exhausted_retries_emit_fallback_not_rejected_text(self):
        """Every attempt rejected -> the fallback, never the rejected text."""
        worker, calls = self._worker([REJECTED], max_retries=2)
        worker.run()

        self.assertEqual(len(calls), 3, f"expected 3 brain calls, got {len(calls)}")

        emitted = self._emitted_text(worker)
        self.assertTrue(
            emitted.startswith("BLOCKED:"),
            f"exhausted retries must emit the bounded fallback; got {emitted!r}")
        self.assertNotIn(
            "I am an open-weights model", emitted,
            "the REJECTED model-identity boilerplate reached the transcript")

    def test_max_retries_zero_never_emits_rejected_text(self):
        """A rejected FIRST response with no retries configured.

        The old `for attempt in range(0)` body never ran, so the rejected text
        went straight to the emit.
        """
        worker, calls = self._worker([REJECTED], max_retries=0)
        worker.run()

        self.assertEqual(len(calls), 1)
        emitted = self._emitted_text(worker)
        self.assertTrue(emitted.startswith("BLOCKED:"), f"got {emitted!r}")
        self.assertNotIn("open-weights model", emitted)

    def test_rejected_then_good_response_emits_the_good_one(self):
        """Recovery still works: a good retry wins over the fallback."""
        worker, calls = self._worker([REJECTED, ACCEPTED], max_retries=2)
        worker.run()

        self.assertEqual(len(calls), 2, "should stop retrying once a turn passes")
        self.assertEqual(self._emitted_text(worker), ACCEPTED)

    # ------------------------------------------------------------------
    # The second half of the defect: repetitiveness was dropped on retry.
    # ------------------------------------------------------------------

    def test_retry_that_is_repetitive_but_not_bad_is_still_rejected(self):
        """The exit test must cover both halves of the entry test.

        The old exit test re-checked only `_is_bad_dialogue_response`, so a
        retry that fixed the "bad" defect but kept the repetitive shape was
        accepted as a recovery.
        """
        # max_retries=1 so the shape is minimal and unambiguous: one normal
        # turn (rejected), exactly one retry (repetitive), then exhaustion.
        # Before ARCH-ENG-232 the retry's `not bad` test passed -- the text was
        # repetitive, not "bad" -- so the loop broke and this exact turn was
        # emitted as a successful recovery.
        worker, calls = self._worker([REJECTED, REPETITIVE], max_retries=1)
        worker.run()

        self.assertEqual(len(calls), 2)
        emitted = self._emitted_text(worker)
        self.assertTrue(emitted.startswith("BLOCKED:"),
                        f"a repetitive retry was accepted as a recovery: {emitted!r}")
        self.assertNotIn("Should I start", emitted,
                         "the repetitive retry reached the transcript")

    # ------------------------------------------------------------------
    # VACUITY PROBE -- without this, "always emit the fallback" passes.
    # ------------------------------------------------------------------

    def test_good_response_is_not_replaced_by_fallback(self):
        """A clean first turn must pass through untouched.

        This is the probe. Every other test in this class asserts the fallback
        appears; if the fix had been implemented as "emit the fallback
        unconditionally", all of them would still pass. This one fails for
        exactly that implementation.
        """
        worker, calls = self._worker([ACCEPTED], max_retries=2)
        worker.run()

        self.assertEqual(len(calls), 1,
                         "a good first turn must not trigger a retry at all")
        emitted = self._emitted_text(worker)
        self.assertEqual(emitted, ACCEPTED)
        self.assertFalse(emitted.startswith("BLOCKED:"),
                         "the fallback replaced a perfectly good response")

    def test_fallback_is_phase_aware_on_the_exhausted_path(self):
        """The emitted fallback must be the phase-aware one, not a constant."""
        ctx = "CURRENT PHASE: discover\nPHASE INSTRUCTION: approve or block."
        worker, _ = self._worker([REJECTED], max_retries=1, context=ctx)
        worker.run()

        emitted = self._emitted_text(worker)
        self.assertIn("identity-document list is too broad", emitted)
        self.assertIn("jurisdiction", emitted)

    def test_non_discover_phase_fallback_names_the_approval_rule(self):
        """The other branch of the phase-aware fallback, on the emitted path."""
        ctx = "CURRENT PHASE: deliver\nPHASE INSTRUCTION: ship the artefact."
        worker, _ = self._worker([REJECTED], max_retries=1, context=ctx)
        worker.run()

        emitted = self._emitted_text(worker)
        self.assertTrue(emitted.startswith("BLOCKED:"))
        self.assertIn("No registration", emitted)


if __name__ == "__main__":
    unittest.main()