"""ARCH-ENG-195/196/197 — settings the operator edited that never persisted.

Three defects, all reported as "Save All doesn't fully work" and "the llama
settings don't save". Each one silently succeeded: the UI reported a save, and
nothing was written.

ARCH-ENG-195 — THE WRITE HAPPENED BEFORE THE DICT WAS FILLED.

`save_settings` built a `values` dict, called `set_env_values(values)` once, and
then inserted nine more keys into that same dict ~55 lines LATER. A dict handed
to a writer is a snapshot, so those nine keys were never written to `.env` at
all. Nothing reported the omission, because the write itself reported success.

Six keys were silently lost:

  * ``MAX_TOKENS``, ``LLM_TEMPERATURE``, ``LLM_TOP_P`` -- not even ``os.environ``
    was set, so the value died with the process. Worse, ``_settings_snapshot()``
    reads ``.env``, so the operator was never even prompted to restart.
  * ``DIALOGUE_MAX_TOKENS_BIG`` / ``_SMALL``, ``DIALOGUE_AUTO_TOKENS`` --
    ``os.environ`` was set, then ``load_dotenv(override=True)`` on the very next
    line clobbered them straight back to the stale ``.env`` value.

And nine CONTROLS were never read on any path, so editing them did nothing at
all -- including ``FILENAME_BLOCKLIST``, ``BLOCKED_MIME_TYPES``,
``LLM_DAILY_BUDGET_USD`` and ``WINRATE_DECLINE_BELOW``, which gate safety and
spend.

ARCH-ENG-196 — SAVE ALL REVERTED THE VISIBLE OLLAMA MODEL CHOICE.

Two writers, same keys. `ProviderConfigWidget` writes ``OLLAMA_MAIN_MODEL`` /
``OLLAMA_CHAT_MODEL`` from the VISIBLE widget the moment the operator picks a
model. `save_settings` wrote the SAME keys from `ollama_model_combo` -- which
lives inside `ollama_box`, a QGroupBox that is `hide()`n and never added to any
layout.

So: pick a model in Providers & GPU, it persists, then Save All overwrites it with
the hidden combo's build-time seed. Both writers report success, so the revert is
invisible. A hidden widget cannot express operator intent; the persisted value is
the only trustworthy source.

ARCH-ENG-197 — A LLAMA SETTING EDITED BEFORE DETECTION FINISHED WAS DROPPED.

`_on_brain_settings_changed` returned early when `self.runtime is None`, before
both `apply_to(cfg)` and `_persist_settings_async()`. Detection runs on a
background thread while the panel is already interactive, so the first seconds of
a session -- exactly when an operator reaches for a spinner -- silently discarded
the edit. Not applied, not written, not logged.

`_snapshot_settings_values()` reads only widgets and needs no runtime, so the
persist half was always possible. Only the in-memory apply genuinely needs a
config, so that is what gets deferred and replayed once detection completes.

Also fixed in this area: `temperature` for slots 2+ was write-only
(`_apply_saved_settings` never read it back), and `_save_provider_list` omitted
NVIDIA and NOUS even though both were written to `.env`.
"""

import ast
import inspect
import pathlib
import textwrap
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parents[2]
MAIN = REPO / "main.py"
PANEL = REPO / "gui" / "widgets" / "dual_brain_control.py"


def _save_settings_ast():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "save_settings")


def _save_settings_lines() -> str:
    """`save_settings` source, read from the FILE.

    `inspect.getsource(main.save_settings)` was the first approach and proved
    fragile twice over: it re-imports the whole application to answer a question
    the file already answers, and the source it returned did not line up with
    what the assertions expected. Every assertion here works off this instead.
    """
    src = MAIN.read_text(encoding="utf-8")
    fn = _save_settings_ast()
    return "\n".join(src.splitlines()[fn.lineno - 1:fn.end_lineno])


def _reload_lines():
    """Line numbers of every `load_dotenv` call inside `save_settings`.

    There is more than one, and only the LAST one matters: it runs after the
    write and would restore stale values over anything set earlier. Comparing
    against the first -- which is what a module-wide `str.index` finds -- asserts
    the ordering backwards.
    """
    return sorted(
        n.lineno for n in ast.walk(_save_settings_ast())
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "load_dotenv")


# ── ARCH-ENG-195 ──────────────────────────────────────────────────────────────

class TestEveryValueIsPopulatedBeforeTheWrite(unittest.TestCase):
    """ARCH-ENG-195 — the ordering bug, asserted structurally."""

    def test_no_key_is_inserted_after_the_write(self):
        """THE REGRESSION. `values` is a snapshot at call time."""
        fn = _save_settings_ast()
        write_line = None
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "set_env_values"):
                write_line = node.lineno
        self.assertIsNotNone(write_line, "the .env write disappeared entirely")

        late = []
        for node in ast.walk(fn):
            if (isinstance(node, ast.Subscript)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "values"
                    and isinstance(node.ctx, ast.Store)
                    and node.lineno > write_line):
                key = (node.slice.value if isinstance(node.slice, ast.Constant)
                       else "<dynamic>")
                late.append((node.lineno, key))
        self.assertEqual(
            late, [],
            f"these keys are added to `values` AFTER it is written, so they never "
            f"reach .env: {late}")

    def test_the_nine_previously_lost_keys_are_written(self):
        src = MAIN.read_text(encoding="utf-8")
        fn = _save_settings_ast()
        write_line = min(
            n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "set_env_values")
        expected = (
            # lost to the ordering bug
            "MAX_TOKENS", "LLM_TEMPERATURE", "LLM_TOP_P",
            "DIALOGUE_MAX_TOKENS_BIG", "DIALOGUE_MAX_TOKENS_SMALL",
            "DIALOGUE_AUTO_TOKENS",
            # controls the handler never read at all
            "MAX_FILE_SIZE_MB", "RESEARCH_MAX_CHARS", "DEEP_READ_MAX_CHARS",
            "FILENAME_BLOCKLIST", "BLOCKED_MIME_TYPES",
            "LLM_DAILY_BUDGET_USD", "WINRATE_DECLINE_BELOW",
            "OPENAI_BASE_URL", "ANTHROPIC_BASE_URL",
        )
        lines = src.splitlines()
        for key in expected:
            with self.subTest(key=key):
                found = [
                    i for i, ln in enumerate(lines, 1)
                    if f'values["{key}"]' in ln]
                self.assertTrue(found, f"{key} is never written at all")
                self.assertLessEqual(
                    max(found), write_line,
                    f"{key} is assigned at line {max(found)}, after the write at "
                    f"{write_line}, so it cannot be persisted")

    def test_the_live_application_still_happens_after_the_reload(self):
        """The worker fields must be set AFTER the reload, not before it.

        Uses the LAST `load_dotenv` in the function: there is an earlier one, and
        comparing against the first was the bug in this test's first draft.
        """
        src = MAIN.read_text(encoding="utf-8")
        fn = _save_settings_ast()
        reload_lines = sorted(
            n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "load_dotenv")
        self.assertTrue(reload_lines, "the env reload disappeared")
        apply_line = min(
            (i for i, ln in enumerate(src.splitlines(), 1)
             if "self.worker._max_tokens" in ln),
            default=10 ** 9)
        self.assertGreater(
            apply_line, reload_lines[-1],
            "the live LLM parameters are applied BEFORE the final "
            "load_dotenv(override=True), so the reload overwrites them with the "
            "stale .env values; the apply must come last to win")

    def test_the_dialogue_keys_reach_osenviron_before_the_write(self):
        """Otherwise the reload that follows restores the old .env values.

        Scoped to the function, and against the FINAL `load_dotenv` -- the
        first draft compared against a module-wide `str.index`, which matched an
        earlier call and so asserted the ordering backwards.
        """
        body = _save_settings_lines()
        src = MAIN.read_text(encoding="utf-8")
        fn = _save_settings_ast()
        env_line = next(
            i for i, ln in enumerate(src.splitlines()[fn.lineno - 1:fn.end_lineno], 1)
            if "os.environ[_k] = values[_k]" in ln)
        reload_lines = sorted(
            n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "load_dotenv")
        self.assertTrue(reload_lines)
        self.assertLess(
            fn.lineno - 1 + env_line, reload_lines[-1],
            "os.environ is published after the final load_dotenv(override=True), "
            "so the reload restores the stale values over them")
        self.assertIn("os.environ[_k] = values[_k]", body)

    def test_one_bad_control_cannot_abort_the_save(self):
        self.assertIn(
            "[Settings] some values not saved", _save_settings_lines(),
            "a malformed control must be reported, not silently swallowed by "
            "the bare `except` that hides the whole block")


# ── ARCH-ENG-196 ──────────────────────────────────────────────────────────────

class TestTheHiddenOllamaComboIsRetired(unittest.TestCase):
    """ARCH-ENG-196 → ARCH-ENG-275 (AB-01).

    ARCH-ENG-196 made the *persisted* value win over the hidden combo. That was
    a guard, not a fix: the combo was still built, and `save_settings` still
    named it. AB-01 deleted the combo and its save-path participation, so there
    is no second writer left to prefer against.
    """

    def test_save_settings_does_not_write_the_ollama_model_keys(self):
        src = _save_settings_lines()
        self.assertNotIn("ollama_model_combo", src)
        self.assertNotIn('values["OLLAMA_MAIN_MODEL"]', src)
        self.assertNotIn('values["OLLAMA_CHAT_MODEL"]', src)

    def test_the_hidden_box_is_gone_not_hidden(self):
        src = (REPO / "gui" / "builders" / "tab_feature_builders.py").read_text(
            encoding="utf-8")
        self.assertNotIn("ollama_box.hide()", src,
                         "the hidden box is back; the duplicate-writer risk "
                         "returns with it")
        self.assertNotIn("self.ollama_model_combo", src)
        self.assertNotIn("self.ollama_chat_model_combo", src)

    def test_the_visible_surface_is_the_single_writer(self):
        src = (REPO / "gui" / "widgets" / "provider_config_widget.py").read_text(
            encoding="utf-8")
        self.assertIn('values["OLLAMA_MAIN_MODEL"] = model', src)
        self.assertIn('values["OLLAMA_CHAT_MODEL"] = model', src)


# ── ARCH-ENG-197 ──────────────────────────────────────────────────────────────

class TestEarlySettingsEditIsNotDropped(unittest.TestCase):
    """ARCH-ENG-197 — the first seconds of a session used to be a black hole."""

    def _none_runtime_branch(self) -> str:
        """The body of the `if self.runtime is None:` branch, via AST.

        Slicing the source with `str.find("return")` was the first draft's
        approach and it truncated inside the ARCH-ENG-197 COMMENT, which quotes
        the word "return" while explaining the old bug. Structural, not textual.
        """
        import agents.safety  # noqa: F401  (import-cycle order)
        from gui.widgets.dual_brain_control import DualBrainControl
        fn = DualBrainControl._on_brain_settings_changed
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        def _is_runtime_none(test):
            # `if self.runtime is None:` is a COMPARE node whose left side is the
            # attribute. The first draft matched an Attribute directly and so
            # never found the branch at all.
            return (isinstance(test, ast.Compare)
                    and isinstance(test.left, ast.Attribute)
                    and test.left.attr == "runtime"
                    and len(test.ops) == 1 and isinstance(test.ops[0], ast.Is)
                    and len(test.comparators) == 1
                    and isinstance(test.comparators[0], ast.Constant)
                    and test.comparators[0].value is None)

        for node in ast.walk(tree):
            if isinstance(node, ast.If) and _is_runtime_none(node.test):
                return ast.unparse(ast.Module(body=node.body, type_ignores=[]))
        self.fail("the `runtime is None` branch is gone; the guard needs revisiting")

    def test_a_none_runtime_still_persists(self):
        branch = self._none_runtime_branch()
        self.assertIn("_persist_settings_async", branch,
                      "an edit made before detection finishes is not persisted; "
                      "the snapshot reads only widgets and needs no runtime")

    def test_a_none_runtime_records_the_deferred_apply(self):
        self.assertIn(
            "_pending_slot_applies", self._none_runtime_branch(),
            "the in-memory apply is deferred but not recorded, so the setting is "
            "saved and then never applied")

    def test_a_none_runtime_tells_the_operator(self):
        self.assertRegex(
            self._none_runtime_branch(), r"self\._log\(",
            "the operator must be told the value is saved but pending, or a "
            "silent deferral is indistinguishable from the old silent drop")

    def test_the_deferred_applies_are_replayed(self):
        from gui.widgets.dual_brain_control import DualBrainControl
        self.assertTrue(
            hasattr(DualBrainControl, "_replay_pending_slot_applies"),
            "there is no replay, so 'applied when detection finishes' is a "
            "promise the panel does not keep")
        src = inspect.getsource(DualBrainControl._replay_pending_slot_applies)
        self.assertIn("apply_to", src,
                      "the replay must actually apply the row to the config")

    def test_the_replay_runs_after_the_detected_defaults_are_seeded(self):
        """Order matters: an explicit edit must beat a later fallback."""
        src = inspect.getsource(
            __import__("gui.widgets.dual_brain_control",
                       fromlist=["DualBrainControl"]).DualBrainControl._apply_runtime)
        seed = src.index("_update_detected_brains_summary")
        replay = src.index("_replay_pending_slot_applies")
        self.assertGreater(
            replay, seed,
            "the pending applies are replayed BEFORE the detected defaults are "
            "seeded, so a fallback overwrites the operator's explicit edit")

    def test_the_replay_is_a_noop_without_pending_or_runtime(self):
        from gui.widgets.dual_brain_control import DualBrainControl
        import types
        tab = types.SimpleNamespace(_pending_slot_applies=set())
        self.assertIsNone(
            DualBrainControl._replay_pending_slot_applies(tab),
            "the replay must do nothing when there is nothing pending")

    def test_a_pending_slot_is_cleared_after_replay(self):
        """Otherwise it is re-applied forever, fighting later edits."""
        from gui.widgets.dual_brain_control import DualBrainControl
        import types

        applied = []

        class _Row:
            def apply_to(self, cfg):
                applied.append(cfg)

        class _Runtime:
            def slot_config(self, slot):
                return f"cfg{slot}"

        tab = types.SimpleNamespace(
            _pending_slot_applies={2},
            _settings_rows=[_Row(), _Row(), _Row()],
            runtime=_Runtime(),
        )
        DualBrainControl._replay_pending_slot_applies(tab)
        self.assertEqual(applied, ["cfg2"])
        self.assertEqual(tab._pending_slot_applies, set(),
                         "the replayed slot was not cleared; it would be "
                         "re-applied on every future _apply_runtime")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-195/196/197 — the detectors must be able to fail."""

    def test_the_ordering_detector_would_catch_a_late_write(self):
        """Prove the AST check sees a post-write mutation."""
        snippet = (
            "def f():\n"
            "    values = {}\n"
            "    set_env_values(values)\n"
            "    values['LATE'] = 'x'\n"
        )
        fn = ast.parse(snippet).body[0]
        write = next(n.lineno for n in ast.walk(fn)
                     if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Name)
                     and n.func.id == "set_env_values")
        late = [n.lineno for n in ast.walk(fn)
                if isinstance(n, ast.Subscript)
                and isinstance(n.value, ast.Name) and n.value.id == "values"
                and isinstance(n.ctx, ast.Store) and n.lineno > write]
        self.assertEqual(late, [4],
                         "the detector must flag a post-write mutation, or the "
                         "real guard is vacuous")

    def test_the_hidden_ollama_combo_is_retired(self):
        """ARCH-ENG-275 (AB-01): the duplicate writer is gone, not guarded.

        ARCH-ENG-196 made the persisted value win over the hidden combo, but
        the combo itself stayed -- still built, still named by the save path.
        It is now deleted along with its save-path participation, so there is
        no second writer left to prefer against. The visible
        ProviderConfigWidget writes OLLAMA_MAIN_MODEL/OLLAMA_CHAT_MODEL as the
        operator picks a model.
        """
        settings = (REPO / "gui" / "builders" / "tab_feature_builders.py").read_text(
            encoding="utf-8")
        main_src = (REPO / "main.py").read_text(encoding="utf-8")
        for attr in ("ollama_model_combo", "ollama_chat_model_combo"):
            with self.subTest(attr=attr):
                self.assertNotIn(attr, settings,
                                 "the hidden Settings box was rebuilt")
                self.assertNotIn(attr, main_src,
                                 "the save path reads the retired combo again")
        self.assertIn(
            "OLLAMA_MAIN_MODEL",
            (REPO / "gui" / "widgets" / "provider_config_widget.py").read_text(
                encoding="utf-8"),
            "the visible surface must remain the writer, or nothing persists "
            "the operator's choice")
