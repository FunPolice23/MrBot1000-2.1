"""Canonical tests for Section E (GUI/perf/dense-MoE/memory) — phases 1-2 & G5/G6.

Run individually:  python -m unittest tests.test_section_e
Via suite:         python -m tests --test test_section_e

Mock-first / offline: no live network, no Ollama required. Architecture hints
are exercised via the static id-prefix table; `live=True` paths are guarded and
degrade to hints when Ollama is absent.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from PySide6.QtWidgets import QApplication, QGroupBox  # noqa: F401
    _PYQT_AVAILABLE = True
except Exception:
    _PYQT_AVAILABLE = False


class TestArchDetection(unittest.TestCase):
    def test_moe_family_detected(self):
        from provider_models import get_arch_info
        info = get_arch_info("qwen3:8b", live=False)
        self.assertTrue(info["moe"])
        self.assertEqual(info["architecture"], "qwen3")
        self.assertEqual(info["experts"], 128)
        self.assertEqual(info["active_experts"], 8)

    def test_dense_family_detected(self):
        from provider_models import get_arch_info
        info = get_arch_info("llama3.2:1b", live=False)
        self.assertFalse(info["moe"])
        self.assertEqual(info["architecture"], "llama")

    def test_unknown_model_safe_defaults(self):
        from provider_models import get_arch_info
        info = get_arch_info("totally-unknown-model-xyz", live=False)
        self.assertFalse(info["moe"])
        self.assertEqual(info["architecture"], "")
        self.assertIsNone(info["experts"])


class TestProviderProbeCache(unittest.TestCase):
    def test_cached_probe_and_forced_refresh(self):
        from gui.dual_brain_control import ProviderStatusChecker

        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"data": [{"id": "test"}]}'
        ProviderStatusChecker.clear_cache(19999)
        with patch("gui.dual_brain_control.urllib.request.urlopen", return_value=response) as urlopen:
            self.assertEqual(ProviderStatusChecker.check_llama_server(19999), (True, ["test"]))
            self.assertEqual(ProviderStatusChecker.check_llama_server(19999), (True, ["test"]))
            self.assertEqual(urlopen.call_count, 1)
            ProviderStatusChecker.check_llama_server(19999, refresh=True)
            self.assertEqual(urlopen.call_count, 2)
        ProviderStatusChecker.clear_cache(19999)

    def test_is_moe_convenience(self):
        from provider_models import is_moe
        self.assertTrue(is_moe("mixtral:8x7b", live=False))
        self.assertFalse(is_moe("gemma2:2b", live=False))

    def test_missing_model_empty(self):
        from provider_models import get_arch_info
        self.assertEqual(get_arch_info(""), {
            "architecture": "", "moe": False, "experts": None,
            "active_experts": None, "params_billion": None, "context": None})

    def test_modelinfo_labels(self):
        from provider_models import ModelInfo
        moe = ModelInfo(id="qwen3:8b", label="Qwen3 8B", moe=True, experts=128,
                        active_experts=8, params_billion=8.0)
        self.assertEqual(moe.arch_label, "MoE · 128e/8a")
        self.assertEqual(moe.params_label, "8.0B")
        dense = ModelInfo(id="llama3.2:1b", label="Llama 3.2 1B", moe=False,
                          params_billion=1.2)
        self.assertEqual(dense.arch_label, "dense")
        self.assertEqual(dense.params_label, "1.2B")
        # combo_text/tooltip include arch type + params
        self.assertIn("MoE", moe.combo_text)
        self.assertIn("type:", moe.tooltip)
        self.assertIn("8.0B", moe.tooltip)
        # architecture string shows in tooltip when present
        moe2 = ModelInfo(id="qwen3:8b", label="Q", architecture="qwen3", moe=True,
                         experts=128, active_experts=8, params_billion=8.0)
        self.assertIn("arch: qwen3", moe2.tooltip)


class TestNumGpuFor(unittest.TestCase):
    def _clear(self):
        os.environ.pop("OLLAMA_MAIN_GPU", None)
        os.environ.pop("OLLAMA_CHAT_GPU", None)

    def test_explicit_override_wins(self):
        from agents.base_worker import num_gpu_for
        os.environ["OLLAMA_CHAT_GPU"] = "24"
        try:
            self.assertEqual(num_gpu_for("qwen3:8b", chat=True), 24)
        finally:
            self._clear()

    def test_negative_means_auto(self):
        from agents.base_worker import num_gpu_for
        os.environ["OLLAMA_MAIN_GPU"] = "-1"
        try:
            # -1 / "auto" => AUTO (None): let Ollama manage offload to fit VRAM.
            self.assertIsNone(num_gpu_for("llama3.2:1b", chat=False))
        finally:
            self._clear()

    def test_unset_defaults_auto(self):
        from agents.base_worker import num_gpu_for
        self._clear()
        # Unset env => AUTO (None) so the program adapts to detected VRAM (e.g.
        # 6GB GTX 1660S) instead of forcing CPU (0).
        self.assertIsNone(num_gpu_for("qwen3:8b", chat=True))
        self.assertIsNone(num_gpu_for("llama3.2:1b", chat=False))

    def test_nonnumeric_env_defaults_auto(self):
        from agents.base_worker import num_gpu_for
        os.environ["OLLAMA_CHAT_GPU"] = "bogus"
        try:
            self.assertIsNone(num_gpu_for("qwen3:8b", chat=True))
        finally:
            self._clear()

    def test_zero_forces_cpu(self):
        from agents.base_worker import num_gpu_for
        os.environ["OLLAMA_CHAT_GPU"] = "0"
        try:
            self.assertEqual(num_gpu_for("qwen3:8b", chat=True), 0)
        finally:
            self._clear()


class TestRuntimeStats(unittest.TestCase):
    """Section E G5: steady-stream telemetry + adaptive cadence (pure logic)."""

    def test_record_and_snapshot(self):
        from manager import RuntimeStats
        rs = RuntimeStats()
        self.assertEqual(rs.snapshot()["cycles"], 0)
        rs.record_cycle(12.5, ok=True, kind="job")
        rs.record_cycle(3.0, ok=True, kind="chat")
        rs.record_cycle(5.0, ok=False, kind="heartbeat")
        snap = rs.snapshot()
        self.assertEqual(snap["cycles"], 3)
        self.assertEqual(snap["jobs_processed"], 1)
        self.assertEqual(snap["error_streak"], 1)
        self.assertIsInstance(snap["throughput_per_min"], float)

    def test_adaptive_sleep(self):
        from manager import RuntimeStats

        rs = RuntimeStats()

        def adaptive_sleep(pending):
            limit = int(os.getenv("STREAM_ERROR_STREAK_LIMIT", "5"))
            fast = 0.3
            idle = 1.0
            cap = 10.0
            if rs.error_streak >= limit:
                return min(cap, fast * (2 ** min(rs.error_streak - limit, 5)))
            return fast if pending else idle

        self.assertEqual(adaptive_sleep(False), 1.0)   # idle
        self.assertEqual(adaptive_sleep(True), 0.3)    # pending work -> fast
        for _ in range(6):
            rs.record_cycle(0.0, ok=False)             # streak=6 >= limit
        v = adaptive_sleep(False)
        self.assertTrue(0.3 <= v <= 10.0)
        rs.record_cycle(0.0, ok=False)
        self.assertGreaterEqual(adaptive_sleep(False), v)


class TestRoleMemory(unittest.TestCase):
    """Section E G6: per-role memory + long-term notes (SummarizerDB)."""

    def setUp(self):
        import tempfile
        self._path = os.path.join(tempfile.gettempdir(), "hermes-e6-test.db")
        if os.path.exists(self._path):
            os.remove(self._path)
        import agents.summarizer as S
        self.db = S.SummarizerDB(self._path)

    def tearDown(self):
        try:
            self.db._conn.close()
        except Exception:
            pass
        if os.path.exists(self._path):
            os.remove(self._path)

    def test_role_isolation(self):
        self.db.add_role_memory("chat", "hi")
        self.db.add_role_memory("main", "decision")
        self.assertEqual(len(self.db.get_role_memory("chat")), 1)
        self.assertEqual(len(self.db.get_role_memory("main")), 1)
        self.assertTrue(all(r["role"] == "chat" for r in self.db.get_role_memory("chat")))

    def test_summary_compaction(self):
        for i in range(12):
            self.db.add_role_memory("main", f"x{i}")
        summ = self.db.summarize_role_memory("main", keep=8)
        self.assertIsNotNone(summ)
        self.assertEqual(
            self.db._execute(
                "SELECT COUNT(*) FROM role_memory WHERE role='main' AND kind='exchange'"
            ).fetchone()[0], 8)
        self.assertEqual(
            self.db._execute(
                "SELECT COUNT(*) FROM role_memory WHERE role='main' AND kind='summary'"
            ).fetchone()[0], 1)

    def test_clear_and_notes(self):
        self.db.add_role_memory("chat", "a")
        self.db.clear_role_memory("chat")
        self.assertEqual(
            self.db._execute("SELECT COUNT(*) FROM role_memory WHERE role='chat'").fetchone()[0], 0)
        self.db.add_note("prefs", "concise")
        self.assertEqual(len(self.db.get_notes("prefs")), 1)
        self.db.clear_notes("prefs")
        self.assertEqual(self.db._execute("SELECT COUNT(*) FROM longterm_notes").fetchone()[0], 0)


@unittest.skipUnless(
    os.environ.get("QT_QPA_PLATFORM") or _PYQT_AVAILABLE,
    "PySide6 GUI test (set QT_QPA_PLATFORM=offscreen to run)")
class TestGuiTabs(unittest.TestCase):
    """Section E GUI (A1/A2/A3/A5): scroll-wrap, new tabs, lazy-build.

    Runs only when PySide6 is importable; offscreen by default.
    """
    def setUp(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        from main import MainWindow
        self.mw = MainWindow()
        # stop the autonomous timers that may fire mid-test
        try:
            self.mw._stats_timer.stop()
        except Exception:
            pass

    def tearDown(self):
        # Shut down the window so background QThreads/QTimers owned by built
        # tabs (GPU poller, safety refresh, auto-start llama) are stopped.
        # Without this they leak past the test and crash PySide6 at process
        # exit (exit code 127), which fails the whole pytest run.
        mw = getattr(self, "mw", None)
        if mw is not None:
            try:
                mw.shutdown()
            except Exception:
                pass
            try:
                mw.close()
            except Exception:
                pass
            del mw
            self.mw = None
        app = getattr(self, "app", None)
        if app is not None:
            try:
                app.processEvents()
            except Exception:
                pass

    def test_new_tabs_present(self):
        labels = [self.mw.tabs.tabText(i) for i in range(self.mw.tabs.count())]
        self.assertIn("Providers & GPU", labels)
        self.assertIn("Memory & Stream", labels)
        self.assertIn("Collaboration", labels)
        # The current GUI includes the dual-brain and safety surfaces in addition
        # to the original ten tabs.
        self.assertEqual(self.mw.tabs.count(), 21)
        self.assertIn("Model Library", labels)

    def test_lazy_then_scroll_on_open(self):
        from PySide6.QtWidgets import QScrollArea
        # Management, Providers & GPU, and Model Library are built eagerly at startup
        self.assertIsInstance(self.mw.tabs.widget(0), QScrollArea)
        self.assertIsInstance(self.mw.tabs.widget(1), QScrollArea)
        self.assertIsInstance(self.mw.tabs.widget(2), QScrollArea)
        # Others are placeholders until opened
        for i in range(3, self.mw.tabs.count()):
            self.assertFalse(isinstance(self.mw.tabs.widget(i), QScrollArea))
        # Opening every tab builds it into a QScrollArea
        for i in range(self.mw.tabs.count()):
            self.mw.tabs.setCurrentIndex(i)
            self.mw._on_tab_changed(i)
            self.assertIsInstance(self.mw.tabs.widget(i), QScrollArea)

    def test_post_move_widgets_exist(self):
        # Build all tabs then confirm relocated widgets keep their names
        for i in range(self.mw.tabs.count()):
            self.mw._ensure_tab_built(i)
        from gui.dual_brain_control import DualBrainControl
        provider_tab = self.mw.tabs.widget(1).widget().findChild(DualBrainControl)
        self.assertIsNotNone(provider_tab, "missing Providers & GPU control")
        for attr in ("sb_ctx_spin", "bb_ctx_spin", "start_all_btn", "stop_all_btn"):
            self.assertTrue(hasattr(provider_tab, attr), f"missing provider control {attr}")
        self.assertIsNotNone(provider_tab.findChild(QGroupBox, "quickActionsGroup"))
        for attr in ("model_info_browser", "max_tokens_spin", "memory_view",
                     "stream_health_label"):
            self.assertTrue(hasattr(self.mw, attr), f"missing {attr}")

    def test_refresh_db_stats_guarded_when_lazy(self):
        # DB Stats tab not built -> refresh must not raise
        if not hasattr(self.mw, "db_stats_label"):
            self.mw.refresh_db_stats()

    def test_db_stats_tab_starts_auto_refresh(self):
        self.mw.create_db_stats_tab()
        self.assertTrue(hasattr(self.mw, "_stats_timer"))
        self.assertGreater(self.mw._stats_timer.interval(), 0)

    def test_provider_status_override_persists_after_redetect(self):
        from agents.provider_manager import ProviderInfo, ProviderManager, ProviderStatus

        pm = ProviderManager()

        def fake_gpus():
            pm._gpus = []

        def fake_local():
            pm._providers["demo"] = ProviderInfo(
                name="Demo",
                provider_type="demo",
                status=ProviderStatus.RUNNING.value,
                is_local=True,
                is_cloud=False,
            )

        pm._detect_gpus = fake_gpus
        pm._detect_local_providers = fake_local
        pm._detect_cloud_providers = lambda: None

        pm.detect_providers()
        self.assertEqual(pm.get_provider("demo").status, ProviderStatus.RUNNING.value)

        pm.set_provider_status("demo", ProviderStatus.STOPPED.value)
        pm.detect_providers()
        self.assertEqual(pm.get_provider("demo").status, ProviderStatus.STOPPED.value)


if __name__ == "__main__":
    unittest.main()
