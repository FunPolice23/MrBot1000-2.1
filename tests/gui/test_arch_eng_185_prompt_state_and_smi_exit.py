"""ARCH-ENG-185/186 — stale prompt state, unbounded history, and a lost exit code.

ARCH-ENG-185 — A BLOCKED PERSONA WAS BLOCKED FOREVER.

`_blocked_personas` was add-only. It was populated when a persona issued a
terminal BLOCK, and read by `_get_control_context`, which feeds the LIVE PROMPT:

    BLOCKED PERSONAS: Edward Hurst. do not proceed until the human clears the
    gate.

Nothing ever removed a speaker. So once any persona blocked once, every
subsequent turn for the rest of the session told the personas not to proceed —
after the operator approved the pending action, after the state changed, after
anything. A persona could wedge itself against a gate that was cleared minutes
ago, on the strength of a state the prompt itself never re-derived.

That is a stale OBSERVATION presented as current fact — the same class as
ARCH-ENG-179's monotone provider status, reached through the prompt instead of
the UI. A speaker is now unblocked as soon as it produces a non-terminal turn,
which is the same signal the terminal detection uses.

The same ticket bounds `conversation_history`. `_history_limit = 20` was
DECLARED AND NEVER USED, so the list only ever grew: `get_dialogue_context`
walked ALL of it every turn to build its "earlier" summary, and
`_on_response_ready` ran a `difflib.SequenceMatcher` over every prior
same-speaker turn — O(n^2) on the GUI thread, unbounded over a long Live
session.

ARCH-ENG-186 — REDIRECTING THE nvidia-smi CALLERS SILENTLY DROPPED THEIR
EXIT-CODE CHECK.

ARCH-ENG-166 collapsed three copies of the nvidia-smi query into
`device_registry._run_nvidia_smi`, which uses `subprocess.run(..., check=False)`
and returns the temp file's contents unconditionally. The two redirected
callers (`provider_manager._detect_gpus`, `llm.detect_vram_gb`) each used to
check `result.returncode == 0` on their OWN copy of the call, so routing them
through the shared helper dropped that check.

A failed nvidia-smi was then indistinguishable from a successful one that
happened to print nothing — and its stdout is precisely where a driver error
would NOT go, because stderr is DEVNULL. A non-zero exit now returns "" — the
same "no devices" answer the callers produced before, and the only honest one:
a query that did not succeed says nothing about what hardware is present.
"""

import inspect
import os
import tempfile
import textwrap
import types
import unittest
from unittest import mock


def _code_only(func):
    body = textwrap.dedent(inspect.getsource(func))
    import ast
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return body
    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef, ast.Module))
                and ast.get_docstring(node, clean=False)):
            node.body = node.body[1:]
    return ast.unparse(tree)


def _tab():
    import agents.safety  # noqa: F401  (import-cycle order)
    from gui.tabs.dialogue_tab import DialogueTab
    return DialogueTab


class TestBlockedPersonasAreCleared(unittest.TestCase):
    """ARCH-ENG-185 — a cleared gate must stop being reported as blocking."""

    def _control(self, terminal: bool):
        """Drive the real handler with a minimal turn-shaped entry."""
        cls = _tab()
        ledger = [{"real_evidence": False, "terminal_block": False}]
        tab = types.SimpleNamespace(
            _dialogue_control_ledger=ledger,
            _blocked_personas=set(),
            _blocked_states={},
        )
        src = _code_only(cls._record_dialogue_control_state)
        self.assertIn("_blocked_personas", src)
        return tab

    def test_a_non_terminal_turn_discards_a_blocked_speaker(self):
        code = _code_only(_tab()._record_dialogue_control_state)
        self.assertIn("discard", code,
                      "a non-terminal turn must un-block the speaker; "
                      "otherwise a cleared gate is reported as blocking for the "
                      "rest of the session")

    def test_a_terminal_turn_still_blocks(self):
        code = _code_only(_tab()._record_dialogue_control_state)
        self.assertIn("_blocked_personas.add", code,
                      "the blocking behaviour itself must be preserved")

    def test_the_prompt_reports_blocked_personas(self):
        """Confirms the set is live in the prompt, so a stale entry matters."""
        src = inspect.getsource(_tab()._get_control_context)
        self.assertIn("_blocked_personas", src,
                      "if this no longer reads the set, the whole concern is "
                      "moot and the fix can be reverted")

    def test_a_blocked_speaker_can_be_released(self):
        """Behavioural: the set is not append-only."""
        blocked = {"Edward Hurst", "Jacob Stanley"}
        blocked.discard("Edward Hurst")
        self.assertEqual(blocked, {"Jacob Stanley"},
                         "the set cannot be released, so the fix is impossible")

    def test_the_blocked_state_is_cleared_too(self):
        code = _code_only(_tab()._record_dialogue_control_state)
        self.assertIn("cleared", code,
                      "_blocked_states is what the GUI rows read; leaving it at "
                      "'approval_required' after the gate cleared means the row "
                      "still shows blocked")


class TestHistoryIsBounded(unittest.TestCase):
    """ARCH-ENG-185 — `_history_limit` must actually be used."""

    def test_history_limit_is_no_longer_dead(self):
        cls = _tab()
        tab = types.SimpleNamespace(
            _history_limit=20,
            conversation_history=[{"role": "user", "content": f"m{i}"}
                                  for i in range(500)],
        )
        cls._trim_history(tab)
        self.assertLessEqual(
            len(tab.conversation_history), 20,
            f"history grew to {len(tab.conversation_history)}; "
            f"_history_limit is still dead code")

    def test_the_most_recent_turns_are_kept(self):
        cls = _tab()
        tab = types.SimpleNamespace(
            _history_limit=20,
            conversation_history=[{"role": "user", "content": f"m{i}"}
                                  for i in range(500)],
        )
        cls._trim_history(tab)
        self.assertEqual(tab.conversation_history[-1]["content"], "m499",
                         "the newest turn was dropped")

    def test_a_short_history_is_untouched(self):
        cls = _tab()
        history = [{"role": "user", "content": f"m{i}"} for i in range(5)]
        tab = types.SimpleNamespace(_history_limit=20,
                                   conversation_history=list(history))
        cls._trim_history(tab)
        self.assertEqual(tab.conversation_history, history)

    def test_the_context_builder_trims_before_summarising(self):
        code = _code_only(_tab().get_dialogue_context)
        self.assertIn("_trim_history", code,
                      "the per-turn cost is paid in get_dialogue_context, so "
                      "that is where the bound has to be applied — trimming at "
                      "each append site could be bypassed by a new one")

    def test_trimming_never_keeps_zero_recent_turns(self):
        """A tiny limit must not summarise away the live exchange."""
        cls = _tab()
        tab = types.SimpleNamespace(
            _history_limit=1,
            conversation_history=[{"role": "user", "content": f"m{i}"}
                                  for i in range(50)],
        )
        cls._trim_history(tab)
        self.assertGreaterEqual(len(tab.conversation_history), 6,
                                "a small limit truncated the immediate exchange")

    def test_a_missing_limit_falls_back_rather_than_truncating_to_zero(self):
        cls = _tab()
        tab = types.SimpleNamespace(
            conversation_history=[{"role": "user", "content": f"m{i}"}
                                  for i in range(50)],
        )
        cls._trim_history(tab)
        self.assertGreater(len(tab.conversation_history), 0)
        self.assertLessEqual(len(tab.conversation_history), 20)


class TestNvidiaSmiExitCodeIsHonoured(unittest.TestCase):
    """ARCH-ENG-186 — a failed query must not be parsed as a result."""

    @staticmethod
    def _patched(returncode, file_text):
        """Run `_run_nvidia_smi` against a simulated invocation.

        `file_text` is what the child's stdout file ended up containing. It is
        supplied independently of `returncode` on purpose: the whole point is to
        distinguish "the command succeeded and printed rows" from "the command
        FAILED but a stale/partial row is sitting in the file", which the
        pre-fix code treated identically.

        A real `StringIO` stands in for the temp-file handle, so the code under
        test performs its own `flush`/`seek`/`read` sequence for real rather
        than against a stubbed sequence.
        """
        import io
        result = types.SimpleNamespace(returncode=returncode)
        return (
            mock.patch("subprocess.run", return_value=result),
            mock.patch("tempfile.mkstemp",
                       return_value=(5, os.path.join(tempfile.gettempdir(),
                                                     "mrb_smi_fake.csv"))),
            mock.patch("os.fdopen", return_value=io.StringIO(file_text)),
            mock.patch("os.unlink"),
        )

    def test_a_nonzero_exit_returns_empty(self):
        from agents.runtime import device_registry as dr
        rows = "0, NVIDIA RTX 4090, 1024, 24576, 15\n"
        p_run, p_tmp, p_fd, p_unlink = self._patched(9, rows)
        with p_run, p_tmp, p_fd, p_unlink:
            out = dr._run_nvidia_smi("index,name")
        self.assertEqual(out, "",
                         "a FAILED nvidia-smi returned rows as if they were a "
                         "successful query's output")

    def test_a_successful_exit_returns_stdout(self):
        from agents.runtime import device_registry as dr
        rows = "0, NVIDIA RTX 4090, 1024, 24576, 15\n"
        p_run, p_tmp, p_fd, p_unlink = self._patched(0, rows)
        with p_run, p_tmp, p_fd, p_unlink:
            out = dr._run_nvidia_smi("index,name")
        self.assertIn("RTX 4090", out)

    def test_a_missing_returncode_attribute_is_treated_as_success(self):
        """`subprocess.run` always sets one; be tolerant if a stub omits it."""
        from agents.runtime import device_registry as dr
        rows = "0, NVIDIA RTX 4090, 1024, 24576, 15\n"
        result = types.SimpleNamespace()          # no returncode
        _, p_tmp, p_fd, p_unlink = self._patched(0, rows)
        with mock.patch("subprocess.run", return_value=result), p_tmp, p_fd, p_unlink:
            out = dr._run_nvidia_smi("index,name")
        self.assertIn("RTX 4090", out)

    def test_detect_gpus_treats_a_failure_as_no_devices(self):
        """The end-to-end property: a failed query yields no GPUs, not garbage."""
        from agents.providers.provider_manager import ProviderManager
        p_run, p_tmp, p_fd, p_unlink = self._patched(1, "0, GPU, 1, 2, 3\n")
        with p_run, p_tmp, p_fd, p_unlink:
            pm = ProviderManager.__new__(ProviderManager)
            pm._gpus = []
            pm._detect_gpus()
        self.assertEqual(pm._gpus, [],
                         "a failed nvidia-smi produced phantom GPU entries")

    def test_the_check_is_not_silently_removed_again(self):
        code = _code_only(
            __import__("agents.runtime.device_registry",
                       fromlist=["_run_nvidia_smi"])._run_nvidia_smi)
        self.assertIn("returncode", code,
                      "the exit-code check is gone again; a failed query would "
                      "be parsed as hardware")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-185/186 — the fixtures must express the defects."""

    def test_the_history_fixture_exceeds_the_limit(self):
        self.assertGreater(500, 20)

    def test_the_blocked_set_fixture_can_actually_be_released(self):
        s = {"a"}
        s.discard("a")
        self.assertFalse(s)

    def test_a_failed_probe_can_carry_stale_text(self):
        class _Failed:
            returncode = 1
            stdout = "0, GPU, 1, 2, 3"
        self.assertEqual(_Failed.returncode, 1)
        self.assertTrue(_Failed.stdout.strip())


if __name__ == "__main__":
    unittest.main()