"""ARCH-ENG-313 — the Dialogue model-size gate became an advisory.

Operated report, verbatim symptom: `Jacob Stanley is paused: model size
below 2B (1.2B estimate). Select an instruct-tuned model of at least 2B...`
The 1.2B figure came from a FILENAME estimate, and the gate refused the
turn every time with no override. Same contract as ARCH-ENG-310: an
estimate on a name is not evidence, so it warns and the operator decides.
The speaker is never paused on a model estimate again; the flagged reason
is stated once so weak output has a cause instead of a mystery.
"""

from types import SimpleNamespace

import unittest


class _TabHarness(unittest.TestCase):
    def setUp(self):
        from gui.tabs.dialogue_tab import DialogueTab
        self.cls = DialogueTab
        self.tab = DialogueTab.__new__(DialogueTab)
        self.tab.current_speaker = "Jacob Stanley"
        self.tab._blocked_states = {}
        self.notes: list[str] = []
        self.tab.append_system = self.notes.append
        self.estimates = {}
        self.tab._estimate_model_size = lambda name: self.estimates.get(
            name, 1.2)

    # -- helpers ----------------------------------------------------------

    def _run(self, model: str, size: float):
        self.estimates[model] = size
        self.tab._apply_model_advisory(SimpleNamespace(model=model))


class TestTheTurnAlwaysProceeds(_TabHarness):
    def test_a_sub_2b_model_appends_one_advisory_and_never_pauses(self):
        self._run("tinyllama-1.1b", 1.2)
        self.assertEqual(len(self.notes), 1, "warned exactly once")
        self.assertIn("below 2B", self.notes[0])
        self.assertIn("Continuing anyway", self.notes[0])
        self.assertNotIn("paused", self.notes[0])
        self.assertEqual(
            {k: v for k, v in self.tab._blocked_states.items()
             if str(v).startswith("model:")},
            {}, "a model estimate must never mark a speaker blocked")

    def test_a_second_turn_is_not_spammed(self):
        self._run("tinyllama-1.1b", 1.2)
        self._run("tinyllama-1.1b", 1.2)
        self.assertEqual(len(self.notes), 1,
                         "the advisory notes per (speaker, reason), not per turn")

    def test_a_healthy_model_stays_silent(self):
        self._run("qwen3.5-35b-instruct", 35.0)
        self.assertEqual(self.notes, [])
        self.assertEqual(getattr(self.tab, "_model_advisory_notes", None),
                         None, "no advisory state is created needlessly")

    def test_an_evaluation_error_must_not_stop_a_turn(self):
        def boom(name):
            raise RuntimeError("partial brain")
        self.tab._dialogue_model_advisory = boom  # type: ignore[attr-defined]
        self.tab._apply_model_advisory(SimpleNamespace(model="x"))
        self.assertEqual(self.notes, [],
                         "errors are 'not flagged', never refusals")


class TestTheOldRefusalShapeIsGone(_TabHarness):
    def test_the_old_pause_copy_is_not_emitted(self):
        self._run("llama-3-8b-base", 8.0)
        self.assertEqual(len(self.notes), 1)
        self.assertNotIn("is paused", self.notes[0],
                         "the ARCH-ENG-279 refusal wording returned")
        self.assertFalse(
            any("try again" in n for n in self.notes),
            "the 'try again' refusal copy returned")


if __name__ == "__main__":
    unittest.main()
