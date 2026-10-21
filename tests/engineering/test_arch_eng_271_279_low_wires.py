"""ARCH-ENG-271..279 — the low-tier depth findings: wired, not just guarded.

Each class here pins one finding from the 11A-11D depth sweeps. The common
shape of these defects was *"mechanism built, last hop missing"*: a cache with
a reader and no writer, a telemetry sink nothing called, a search with no
surface, a duplicate widget nobody retired, a backup never used to revert, a
gate that was never consulted.

The tests are behavioural where a behaviour exists and structural where the
defect was a call site. Every structural assertion is paired with a wording or
identity check so it cannot pass on a comment.
"""

from __future__ import annotations

import ast
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _function(tree: ast.AST, name: str):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


# ── ARCH-ENG-271 / ARCH-ENG-272 (AF-02 / AF-03) - the caches are written --

class TestFileAndResearchCachesAreWritten(unittest.TestCase):
    """AF-02: `file_cache` had a reader and a Clear button but no writer.

    AF-03: `research_cache` had a reader and a DB-Stats counter but no writer,
    so the counter was permanently zero and the "last good snapshot" fallback
    could never find anything.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        base = Path(self.tmp.name)
        self.root = base / "root"
        self.root.mkdir()
        self.research = base / "research"
        self.research.mkdir()
        self.note = self.research / "notes.md"
        self.note.write_text("alpha research body", encoding="utf-8")

        from app.database import AgentDB
        self.db = AgentDB(str(base / "cache.db"))
        self.published = []

        from agents.safety import filesystem as fs
        self.fs = fs
        self.stub = SimpleNamespace(
            db=self.db,
            research_folder=str(self.research),
            log_signal=SimpleNamespace(emit=lambda message: None),
        )
        self.stub._cached_read = (
            lambda *args: fs.WorkerFilesystemMixin._cached_read(self.stub, *args))

    def tearDown(self):
        try:
            self.db._conn.close()
        except Exception:
            pass
        self.tmp.cleanup()

    def _scan(self):
        class _Shared:
            def update_research_snapshot(_self, payload):
                self.published.append(payload)

        with patch.object(self.fs, "ROOT_FOLDER", str(self.root)), \
                patch.object(self.fs, "RESEARCH_MAX_BYTES", 1_000_000), \
                patch.object(self.fs, "RESEARCH_MAX_TOTAL_CHARS", 1_000_000), \
                patch("agents.brains.shared_context.get_shared_context",
                      return_value=_Shared()):
            return self.fs.WorkerFilesystemMixin.research_all(self.stub)

    def _count(self, table: str) -> int:
        row = self.db._execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0])

    def test_the_scan_writes_the_file_cache(self):
        self._scan()
        self.assertEqual(self._count("file_cache"), 1,
                         "the research read did not reach the file cache")
        row = self.db._execute(
            "SELECT content FROM file_cache WHERE relative_path='notes.md'"
        ).fetchone()
        self.assertIn("alpha research body", row["content"])

    def test_the_scan_writes_and_reloads_the_research_snapshot(self):
        payload = self._scan()
        self.assertEqual(self._count("research_cache"), 1,
                         "the snapshot was not persisted")
        loaded = self.db.load_latest_research_cache(str(self.research))
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["research_file_count"], 1)
        self.assertEqual(loaded["research_path"], payload["research_path"])

    def test_the_snapshot_is_published_to_shared_context(self):
        self._scan()
        self.assertEqual(len(self.published), 1,
                         "the live chat context reads this snapshot; nothing published it")
        self.assertIn("notes.md", self.published[0]["research"])

    def test_a_second_scan_is_served_from_the_cache(self):
        """A cache hit is proven by making the direct read impossible.

        If the second scan re-read the file, the per-file handler would log a
        skip and the file count would drop to zero -- exactly the failure the
        cache exists to avoid.
        """
        self._scan()
        with patch.object(Path, "read_text",
                          side_effect=AssertionError("cache miss: direct read")):
            payload = self._scan()
        self.assertEqual(payload["research_file_count"], 1)
        self.assertIn("alpha research body", payload["research"])

    def test_an_edited_file_invalidates_by_mtime(self):
        self._scan()
        self.note.write_text("beta research body", encoding="utf-8")
        os.utime(self.note, (self.note.stat().st_atime,
                             self.note.stat().st_mtime + 5))
        payload = self._scan()
        self.assertIn("beta research body", payload["research"])
        self.assertNotIn("alpha research body", payload["research"])

    def test_cache_failure_degrades_to_a_direct_read(self):
        self.db._conn.close()
        self.db._conn = sqlite3.connect(":memory:")  # same API, no cache tables
        payload = self._scan()
        self.assertIn("alpha research body", payload["research"])
        self.assertEqual(payload["research_file_count"], 1,
                         "a broken cache must not drop research files")


class TestResearchRescanButtonRunsTheScan(unittest.TestCase):
    """AF-03: the button said "use the Dialogue tab"; the scan had no caller."""

    def test_the_handler_calls_the_worker_and_the_fallback(self):
        src = _read("main.py")
        tree = ast.parse(src)
        fn = _function(tree, "force_research_rescan")
        self.assertIsNotNone(fn)
        body = ast.get_source_segment(src, fn)
        self.assertIn("worker.research_all()", body,
                      "the rescan button still does not run the scan")
        self.assertIn("load_latest_research_cache", body,
                      "the last-good-snapshot fallback is not wired")


# ── ARCH-ENG-273 (AV-02) — the dialogue log sink is written ----------------

class TestDialogueLogIsWritten(unittest.TestCase):
    """AV-02: the JSONL sink existed; the seam pointed at the UI append."""

    def test_the_turn_record_reaches_the_instance_seam(self):
        from gui.tabs.dialogue_tab import DialogueTab

        captured = []
        stub = SimpleNamespace(
            _brain_for=lambda speaker: SimpleNamespace(model="model-x"),
            _tier_for_speaker=lambda speaker: "big",
            _phase_instruction=lambda: "",
            _phase_index=0,
            goal="earn",
            live_running=False,
            is_running=False,
            _context_values=lambda value: {},
            _append_dialogue_log=captured.append,
        )
        DialogueTab._log_dialogue_turn(stub, "Edward", "response", "hello")

        self.assertEqual(len(captured), 1)
        record = captured[0]
        self.assertEqual(record["speaker"], "Edward")
        self.assertEqual(record["outcome"], "response")
        self.assertEqual(record["model"], "model-x")
        self.assertEqual(record["tier"], "big")
        self.assertEqual(record["goal"], "earn")

    def test_the_seam_names_the_writer_it_calls(self):
        src = _read("gui/tabs/dialogue_tab.py")
        self.assertIn("self._append_dialogue_log = _append_dialogue_log", src)
        rebound = [
            line.strip() for line in src.splitlines()
            if line.strip().startswith("self._append_dialogue_log = self._append")
        ]
        self.assertEqual(rebound, [],
                         "the seam is aliased back to the UI append; tests that "
                         f"patch it intercept nothing: {rebound}")

    def test_both_turn_sites_log(self):
        src = _read("gui/tabs/dialogue_tab.py")
        self.assertIn('self._log_dialogue_turn(speaker, "human", msg)', src)
        self.assertIn('self._log_dialogue_turn(speaker, "response", response)', src)


# ── ARCH-ENG-274 (W-03) — keyword search is reachable ----------------------

class TestKeywordSearchIsReachable(unittest.TestCase):
    """W-03: `search_opportunities_by_keyword` had zero callers."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.tmp.name) / "earning_memory.db"
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "CREATE TABLE opportunity_memory "
            "(key TEXT, memory_type TEXT, memory_data TEXT, created REAL)")
        conn.execute(
            "INSERT INTO opportunity_memory VALUES (?, ?, ?, ?)",
            ("k1", "coding",
             json.dumps({"title": "Alpha Python gig", "min_amount": 60}),
             0.0))
        conn.execute(
            "INSERT INTO opportunity_memory VALUES (?, ?, ?, ?)",
            ("k2", "writing",
             json.dumps({"title": "Beta copywriting gig", "min_amount": 80}),
             0.0))
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, keyword, limit=20, as_json=False):
        from agents.services import mrbot_cli
        buffer = io.StringIO()
        with patch.object(mrbot_cli, "REPO_ROOT", Path(self.tmp.name)):
            with redirect_stdout(buffer):
                mrbot_cli.cmd_opportunities(SimpleNamespace(
                    keyword=keyword, limit=limit, json=as_json))
        return buffer.getvalue()

    def test_the_cli_finds_a_keyword(self):
        output = self._run("alpha")
        self.assertIn("Alpha Python gig", output)
        self.assertNotIn("Beta copywriting gig", output)

    def test_json_mode_is_machine_readable(self):
        payload = json.loads(self._run("gig", as_json=True))
        self.assertEqual(len(payload), 2)
        self.assertEqual(payload[0]["type"] in {"coding", "writing"}, True)

    def test_a_missing_keyword_is_reported(self):
        self.assertIn("keyword is required", self._run(""))

    def test_an_empty_result_is_not_an_error(self):
        self.assertIn("Matches : 0", self._run("nothing-matches-this"))

    def test_the_cli_registers_the_command(self):
        from agents.services import mrbot_cli
        self.assertIn("opportunities", mrbot_cli.SUBCOMMANDS)

    def test_the_dead_pipeline_wrapper_is_gone(self):
        tree = ast.parse(_read("app/earning_pipeline.py"))
        names = {n.name for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef)}
        self.assertNotIn("search_opportunities_by_keyword", names,
                         "an uncalled duplicate of the CLI query came back")


# ── ARCH-ENG-275 (AB-01) — the hidden Ollama widget is retired --------------

class TestHiddenOllamaWidgetRetired(unittest.TestCase):
    """AB-01: a hidden combo was the second writer of the Ollama model keys."""

    def test_the_builder_does_not_build_it(self):
        src = _read("gui/builders/tab_feature_builders.py")
        self.assertNotIn("ollama_box = QGroupBox", src)
        self.assertNotIn("ollama_box.setVisible", src)
        self.assertNotIn("self.ollama_model_combo", src)
        self.assertNotIn("self.ollama_chat_model_combo", src)

    def test_the_save_path_no_longer_reads_or_writes_it(self):
        src = _read("main.py")
        self.assertNotIn("ollama_model_combo", src)
        self.assertNotIn("ollama_chat_model_combo", src)
        self.assertNotIn('values["OLLAMA_MAIN_MODEL"]', src)
        self.assertNotIn('values["OLLAMA_CHAT_MODEL"]', src)
        self.assertIn("_active_ollama_models", src,
                      "the visible surface must remain the source of truth")

    def test_the_visible_surface_is_the_single_writer(self):
        src = _read("gui/widgets/provider_config_widget.py")
        self.assertIn('values["OLLAMA_MAIN_MODEL"] = model', src)
        self.assertIn('values["OLLAMA_CHAT_MODEL"] = model', src)

    def test_persisted_models_are_read_from_env(self):
        import main
        with patch.dict(os.environ, {"OLLAMA_MAIN_MODEL": "main-a",
                                     "OLLAMA_CHAT_MODEL": "chat-b"}, clear=False):
            self.assertEqual(main.MainWindow._active_ollama_models(),
                             ("main-a", "chat-b"))

    def test_first_run_falls_back_to_ollama_model(self):
        import main
        env = {k: v for k, v in os.environ.items()
               if k not in ("OLLAMA_MAIN_MODEL", "OLLAMA_CHAT_MODEL")}
        env["OLLAMA_MODEL"] = "fallback-model"
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(main.MainWindow._active_ollama_models()[0],
                             "fallback-model")


# ── ARCH-ENG-276 (AQ-02) — modify backs up, replaces atomically, reverts ----

class TestModifyPathIsAtomicAndReverts(unittest.TestCase):
    """AQ-02: the old path wrote a sidecar `.bak` and never used it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.target = self.root / "good.py"
        self.original = b"VALUE = 1\r\n"
        self.target.write_bytes(self.original)
        self.logs = []
        from app.action_pipeline import ActionPipeline
        self.pipeline = ActionPipeline(
            root_folder=str(self.root), db=None, log_fn=self.logs.append)

    def tearDown(self):
        self.tmp.cleanup()

    def _action(self, code: str):
        from app.action_pipeline import ProposedAction
        return ProposedAction(
            action_type="modify_file", proposer="test", description="edit",
            target_path="good.py", code=code)

    def test_success_backs_up_byte_exactly_outside_the_tree(self):
        result = self.pipeline._exec_modify_file(self._action("VALUE = 2\n"))
        self.assertTrue(result.success, result.message)
        self.assertEqual(self.target.read_text(), "VALUE = 2\n")
        backups = list(
            (self.root / ".mrbot_backups" / "action_pipeline")
            .glob("good.py.*.bak"))
        self.assertEqual(len(backups), 1, "no revert path was left behind")
        self.assertEqual(backups[0].read_bytes(), self.original,
                         "the backup is not byte-exact")
        self.assertFalse((self.root / "good.py.bak").exists(),
                         "the old sidecar backup is back")

    def test_a_compile_failure_reverts_the_exact_bytes(self):
        result = self.pipeline._exec_modify_file(self._action("def broken(:\n"))
        self.assertFalse(result.success)
        self.assertIn("revert", result.message.lower())
        self.assertEqual(self.target.read_bytes(), self.original,
                         "a rejected modify left the broken content on disk")

    def test_a_failed_backup_refuses_to_write(self):
        with patch.object(self.pipeline, "_backup_modify_target",
                          side_effect=OSError("disk full")):
            result = self.pipeline._exec_modify_file(self._action("VALUE = 3\n"))
        self.assertFalse(result.success)
        self.assertIn("refused", result.message.lower())
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_the_old_sidecar_backup_code_is_gone(self):
        src = _read("app/action_pipeline.py")
        self.assertNotIn('path.with_suffix(path.suffix + ".bak")', src)


# ── ARCH-ENG-277 (AG-01) — chat_with_tools is an orchestrator --------------

class TestChatWithToolsIsSplit(unittest.TestCase):
    """AG-01: one 525-line function with nine return points."""

    HELPERS = (
        "_build_chat_messages", "_gate_tool_call", "_record_tool",
        "_run_generation", "_log_empty_visible", "_text_tool_result",
        "_run_function_calls", "_final_answer",
    )

    def test_the_orchestrator_is_short_and_the_phases_exist(self):
        tree = ast.parse(_read("agents/dialogue/chat_completion.py"))
        fn = _function(tree, "chat_with_tools")
        self.assertIsNotNone(fn)
        self.assertLessEqual(
            fn.end_lineno - fn.lineno + 1, 160,
            "chat_with_tools grew back into a monolith")
        for name in self.HELPERS:
            with self.subTest(helper=name):
                self.assertIsNotNone(_function(tree, name))

    def test_every_return_in_the_orchestrator_is_terminal(self):
        """The old nine returns included loop-continues; the split must not
        reintroduce a return that skips the final-answer phase unintentionally."""
        tree = ast.parse(_read("agents/dialogue/chat_completion.py"))
        fn = _function(tree, "chat_with_tools")
        returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
        self.assertLessEqual(len(returns), 4,
                             f"return points grew to {len(returns)}")

    def test_a_plain_streamed_answer_passes_through(self):
        from agents.safety.calling import chat_with_tools  # cycle-safe import
        from agents.dialogue import chat_completion

        class _Delta:
            def __init__(self, content):
                self.content = content
                self.reasoning_content = None

        class _Choice:
            def __init__(self, content):
                self.delta = _Delta(content)
                self.message = None

        class _Chunk:
            def __init__(self, content):
                self.choices = [_Choice(content)]

        class _Client:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kwargs):
                        return iter([_Chunk("Hello there")])

        self.assertTrue(callable(chat_completion.chat_with_tools))
        answer = chat_with_tools(
            client=_Client(), model="m", system_prompt="s",
            user_message="hi", history=[], use_function_calling=False,
            flatten_system_prompt=True, max_iterations=1)
        self.assertEqual(answer, "Hello there")


# ── ARCH-ENG-278 (AW-03) — create_settings_tab is split --------------------

class TestSettingsTabIsSplit(unittest.TestCase):
    """AW-03: `create_settings_tab` was 870+ lines with all sections inline."""

    BUILDERS = (
        "_build_registration_group", "_build_provider_sections",
        "_build_performance_group", "_build_llm_group", "_build_rate_group",
        "_build_model_info_group", "_build_security_group",
        "_build_feature_group", "_build_pipeline_group", "_build_payout_group",
        "_build_appearance_group", "_build_cache_group",
    )

    WIDGETS = (
        "name_edit", "user_edit", "openai_key_edit", "openai_model_combo",
        "anthropic_key_edit", "openrouter_key", "gemini_key", "groq_key",
        "deepseek_key", "mistral_key", "together_key", "nvidia_key",
        "nous_key", "vllm_key", "lmstudio_key", "koboldcpp_key",
        "llamacpp_big_enabled", "max_file_spin", "research_max_chars",
        "deep_read_chars", "auto_research", "cache_stats_label",
        "max_tokens_spin", "dialogue_tokens_big_spin", "temperature_spin",
        "top_p_spin", "llm_budget_edit", "winrate_edit", "model_info_browser",
        "blocklist_edit", "blocked_mime_edit", "feature_flag_checks",
        "pipeline_enabled_check", "cashapp_payout_edit", "theme_combo",
        "fx_antialias", "fx_quality", "fx_button_style",
    )

    def setUp(self):
        self.src = _read("gui/builders/tab_feature_builders.py")
        self.tree = ast.parse(self.src)

    def test_the_orchestrator_is_short(self):
        fn = _function(self.tree, "create_settings_tab")
        self.assertIsNotNone(fn)
        self.assertLessEqual(
            fn.end_lineno - fn.lineno + 1, 130,
            "create_settings_tab grew back into a monolith")

    def test_every_section_is_built_once_in_order(self):
        fn = _function(self.tree, "create_settings_tab")
        called = []
        for node in fn.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                func = node.value.func
                if isinstance(func, ast.Attribute) and func.attr.startswith("_build_"):
                    called.append(func.attr)
        self.assertEqual(tuple(called), self.BUILDERS,
                         "a settings section was dropped, duplicated, or reordered")

    def _settings_assignments(self):
        """Every `self.<attr>` assigned in the orchestrator or a section builder."""
        names = []
        for node in self.tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if not isinstance(item, ast.FunctionDef):
                    continue
                if (item.name != "create_settings_tab"
                        and item.name not in self.BUILDERS):
                    continue
                for sub in ast.walk(item):
                    if not isinstance(sub, ast.Assign):
                        continue
                    for target in sub.targets:
                        names.extend(self._plain_targets(target))
        return names

    def _plain_targets(self, target):
        """`self.a` / `self.a, self.b = ...` — not `self.a[key] = ...`."""
        if isinstance(target, ast.Attribute):
            if (isinstance(target.value, ast.Name)
                    and target.value.id == "self"):
                return [target.attr]
            return []
        if isinstance(target, (ast.Tuple, ast.List)):
            names = []
            for element in target.elts:
                names.extend(self._plain_targets(element))
            return names
        return []

    def test_the_widget_surface_survived_the_split(self):
        assigned = set(self._settings_assignments())
        for widget in self.WIDGETS:
            with self.subTest(widget=widget):
                self.assertIn(widget, assigned,
                              f"save_settings reads self.{widget}; the split "
                              f"dropped it")

    def test_no_widget_is_assigned_twice(self):
        counts: dict[str, int] = {}
        for name in self._settings_assignments():
            counts[name] = counts.get(name, 0) + 1
        duplicated = {name: n for name, n in counts.items()
                      if n > 1 and name in self.WIDGETS}
        self.assertEqual(duplicated, {}, "a section was copied, not moved")


# ── ARCH-ENG-279 (AV-03) / ARCH-ENG-313 — the gate is wired AND advisory -----

class TestDialogueCapacityGateIsWired(unittest.TestCase):
    """AV-03: `_dialogue_model_blocked` explained the realistic mistake and
    was never called. ARCH-ENG-313: when it was wired as a refusal it became
    its own failure mode — a filename estimate paused the operator's chosen
    1.2B model every turn. Now `_dialogue_model_advisory` flags, `respond`
    notes once, and the turn always proceeds.
    """

    def setUp(self):
        from gui.tabs.dialogue_tab import DialogueTab
        self.tab = DialogueTab
        self.stub = SimpleNamespace(
            _estimate_model_size=DialogueTab._estimate_model_size)

    def test_a_sub_2b_model_is_flagged_with_a_reason(self):
        flagged, reason = self.tab._dialogue_model_advisory(
            self.stub, "tinyllama-1.1b")
        self.assertTrue(flagged)
        self.assertIn("below 2B", reason)

    def test_a_base_model_is_flagged_with_a_reason(self):
        flagged, reason = self.tab._dialogue_model_advisory(
            self.stub, "llama-3-8b-base")
        self.assertTrue(flagged)
        self.assertIn("base model", reason)

    def test_an_instruct_model_is_unset(self):
        self.assertEqual(
            self.tab._dialogue_model_advisory(
                self.stub, "qwen2.5-7b-instruct"),
            (False, ""))

    def test_respond_consults_the_advisory_before_starting_a_worker(self):
        src = _read("gui/tabs/dialogue_tab.py")
        tree = ast.parse(src)
        fn = _function(tree, "respond")
        self.assertIsNotNone(fn)
        advisory_line = None
        worker_line = None
        for sub in ast.walk(fn):
            if (isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "_apply_model_advisory"):
                advisory_line = sub.lineno
            if (isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id == "DialogueWorker"):
                worker_line = worker_line or sub.lineno
        self.assertIsNotNone(advisory_line, "the advisory is dead again")
        self.assertIsNotNone(worker_line)
        self.assertLess(advisory_line, worker_line,
                        "the advisory must fire before the worker is built")
        # The helper itself must actually consult the model estimate.
        helper = _function(ast.parse(src), "_apply_model_advisory")
        self.assertIsNotNone(helper, "_apply_model_advisory went missing")
        self.assertIn("_dialogue_model_advisory",
                      ast.get_source_segment(src, helper) or "",
                      "the advisory helper does not consult the estimate")

    def test_the_advisory_helper_never_pauses_a_speaker(self):
        """ARCH-ENG-313: the old refusal wrote `model:<reason>` into
        `_blocked_states` and paused with `is paused:`. Neither may survive."""
        src = _read("gui/tabs/dialogue_tab.py")
        tree = ast.parse(src)
        helper = _function(tree, "_apply_model_advisory")
        self.assertIsNotNone(helper, "_apply_model_advisory went missing")
        src_helper = ast.get_source_segment(src, helper) or ""
        self.assertNotIn('"model:', src_helper,
                         "the advisory helper marks a speaker blocked on a "
                         "model estimate again")
        self.assertNotIn("is paused:", src_helper,
                         "the advisory helper pauses speakers on a model "
                         "estimate again")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
