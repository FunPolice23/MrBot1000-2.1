"""Canonical tests for Section E (GUI/perf/dense-MoE/memory) — phases 1-2 & G5/G6.

Run individually:  python -m unittest tests.gui.test_section_e
Via suite:         python -m tests --test test_section_e

Mock-first / offline: no live network, no Ollama required. Architecture hints
are exercised via the static id-prefix table; `live=True` paths are guarded and
degrade to hints when Ollama is absent.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from PySide6.QtWidgets import QApplication, QGroupBox  # noqa: F401
    _PYQT_AVAILABLE = True
except Exception:
    _PYQT_AVAILABLE = False


class TestArchDetection(unittest.TestCase):
    def test_moe_family_detected(self):
        from app.provider_models import get_arch_info
        info = get_arch_info("qwen3:8b", live=False)
        self.assertTrue(info["moe"])
        self.assertEqual(info["architecture"], "qwen3")
        self.assertEqual(info["experts"], 128)
        self.assertEqual(info["active_experts"], 8)

    def test_dense_family_detected(self):
        from app.provider_models import get_arch_info
        info = get_arch_info("llama3.2:1b", live=False)
        self.assertFalse(info["moe"])
        self.assertEqual(info["architecture"], "llama")

    def test_unknown_model_safe_defaults(self):
        from app.provider_models import get_arch_info
        info = get_arch_info("totally-unknown-model-xyz", live=False)
        self.assertFalse(info["moe"])
        self.assertEqual(info["architecture"], "")
        self.assertIsNone(info["experts"])


class TestProviderProbeCache(unittest.TestCase):
    def test_cached_probe_and_forced_refresh(self):
        from gui.widgets.dual_brain_control import ProviderStatusChecker

        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"data": [{"id": "test"}]}'
        ProviderStatusChecker.clear_cache(19999)
        with patch("gui.widgets.dual_brain_control.urllib.request.urlopen", return_value=response) as urlopen:
            self.assertEqual(ProviderStatusChecker.check_llama_server(19999), (True, ["test"]))
            self.assertEqual(ProviderStatusChecker.check_llama_server(19999), (True, ["test"]))
            self.assertEqual(urlopen.call_count, 1)
            ProviderStatusChecker.check_llama_server(19999, refresh=True)
            self.assertEqual(urlopen.call_count, 2)
        ProviderStatusChecker.clear_cache(19999)

    def test_is_moe_convenience(self):
        from app.provider_models import is_moe
        self.assertTrue(is_moe("mixtral:8x7b", live=False))
        self.assertFalse(is_moe("gemma2:2b", live=False))

    def test_missing_model_empty(self):
        from app.provider_models import get_arch_info
        self.assertEqual(get_arch_info(""), {
            "architecture": "", "moe": False, "experts": None,
            "active_experts": None, "params_billion": None, "context": None})

    def test_modelinfo_labels(self):
        from app.provider_models import ModelInfo
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
        from agents.brains.base_worker import num_gpu_for
        os.environ["OLLAMA_CHAT_GPU"] = "24"
        try:
            self.assertEqual(num_gpu_for("qwen3:8b", chat=True), 24)
        finally:
            self._clear()

    def test_negative_means_auto(self):
        from agents.brains.base_worker import num_gpu_for
        os.environ["OLLAMA_MAIN_GPU"] = "-1"
        try:
            # -1 / "auto" => AUTO (None): let Ollama manage offload to fit VRAM.
            self.assertIsNone(num_gpu_for("llama3.2:1b", chat=False))
        finally:
            self._clear()

    def test_unset_defaults_auto(self):
        from agents.brains.base_worker import num_gpu_for
        self._clear()
        # Unset env => AUTO (None) so the program adapts to detected VRAM (e.g.
        # 6GB GTX 1660S) instead of forcing CPU (0).
        self.assertIsNone(num_gpu_for("qwen3:8b", chat=True))
        self.assertIsNone(num_gpu_for("llama3.2:1b", chat=False))

    def test_nonnumeric_env_defaults_auto(self):
        from agents.brains.base_worker import num_gpu_for
        os.environ["OLLAMA_CHAT_GPU"] = "bogus"
        try:
            self.assertIsNone(num_gpu_for("qwen3:8b", chat=True))
        finally:
            self._clear()

    def test_zero_forces_cpu(self):
        from agents.brains.base_worker import num_gpu_for
        os.environ["OLLAMA_CHAT_GPU"] = "0"
        try:
            self.assertEqual(num_gpu_for("qwen3:8b", chat=True), 0)
        finally:
            self._clear()


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
            # Drain queued work while the window object is still alive. Calling
            # deleteLater() and *then* processing events delivers deferred
            # deletes (and any still-queued signal) to a destroyed C++ object,
            # which aborts the interpreter with an access violation.
            try:
                app.processEvents()
            except Exception:
                pass
            try:
                app.sendPostedEvents(None, 0)
            except Exception:
                pass

    def test_new_tabs_present(self):
        from agents.core.feature_flags import feature_enabled
        labels = [self.mw.tabs.tabText(i) for i in range(self.mw.tabs.count())]

        # Surfaces that are never feature-gated.
        for label in ("Providers & GPU", "Live Logs", "DB Stats", "Model Library",
                      "Dialogue", "Management", "Settings"):
            self.assertIn(label, labels)

        # Tabs governed by a fail-closed feature flag: present iff the flag is
        # explicitly enabled. Absence is the correct default, so the old test's
        # unconditional assertions on "Live Portfolio"/"Strategy Simulator" were
        # wrong whenever live trading is (correctly) left off.
        gated = {
            "Social Activity": "social_automation",
            "Self-Improvement": "self_improvement",
            "Autonomous Learning": "autonomous_learning",
            "Live Portfolio": "live_trading",
            "Strategy Simulator": "live_trading",
        }
        for label, flag in gated.items():
            if feature_enabled(flag):
                self.assertIn(label, labels)
            else:
                self.assertNotIn(label, labels)

        # Count must equal the ungated tabs plus the enabled gated tabs
        # (live_trading gates two tabs).
        ungated = ["Management", "Providers & GPU", "Model Library", "Safety & Tools",
                   "Chat", "Dialogue", "Collaboration", "Approvals", "Registration",
                   "Web Browser",
                   "Payments", "Earnings", "Insights", "Opportunities", "Analytics",
                   "Reputation", "Data Explorer", "Settings", "Live Logs", "DB Stats"]
        expected = len(ungated) + sum(1 for f in gated.values() if feature_enabled(f))
        self.assertEqual(self.mw.tabs.count(), expected)

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
        from gui.widgets.dual_brain_control import DualBrainControl
        provider_tab = self.mw.tabs.widget(1).widget().findChild(DualBrainControl)
        self.assertIsNotNone(provider_tab, "missing Providers & GPU control")
        for attr in ("sb_ctx_spin", "bb_ctx_spin", "start_all_btn", "stop_all_btn"):
            self.assertTrue(hasattr(provider_tab, attr), f"missing provider control {attr}")
        self.assertIsNotNone(provider_tab.findChild(QGroupBox, "quickActionsGroup"))
        for attr in ("model_info_browser", "max_tokens_spin"):
            self.assertTrue(hasattr(self.mw, attr), f"missing {attr}")

    def test_refresh_db_stats_guarded_when_lazy(self):
        # DB Stats tab not built -> refresh must not raise
        if not hasattr(self.mw, "db_stats_label"):
            self.mw.refresh_db_stats()

    def test_db_stats_tab_starts_auto_refresh(self):
        self.mw.create_db_stats_tab()
        self.assertTrue(hasattr(self.mw, "_stats_timer"))
        self.assertGreater(self.mw._stats_timer.interval(), 0)

    def test_provider_status_override_is_visible_until_the_next_probe(self):
        """ARCH-ENG-179 — an operator's Stop is shown immediately, then yields to the probe.

        `set_provider_status` is how the UI reflects the operator pressing Stop or
        Start, so its result must be visible immediately — the operator should
        not have to wait for a refresh to see their own action.

        What it must NOT do is survive a subsequent PROBE. Every real detector
        (`_detect_ollama` and friends) sets an explicit status on both paths —
        RUNNING on success, STOPPED on failure — so a previous status carried
        forward is never "the detector had no opinion"; it is a stale claim. The
        old merge re-applied the PRE-detect status over the fresh probe result,
        which meant a provider could never be shown stopped again for the life
        of the process — and `provider_config_widget` sets RUNNING optimistically
        with no probe at all, so that fiction persisted forever.

        So: the override holds until a probe disagrees, then the world wins.
        """
        from agents.providers.provider_manager import ProviderInfo, ProviderManager, ProviderStatus

        pm = ProviderManager()
        seen_status = {"value": ProviderStatus.RUNNING.value}

        def fake_gpus():
            pm._gpus = []

        def fake_local():
            pm._providers["demo"] = ProviderInfo(
                name="Demo",
                provider_type="demo",
                status=seen_status["value"],
                is_local=True,
                is_cloud=False,
            )

        pm._detect_gpus = fake_gpus
        pm._detect_local_providers = fake_local
        pm._detect_cloud_providers = lambda: None

        pm.detect_providers()
        self.assertEqual(pm.get_provider("demo").status, ProviderStatus.RUNNING.value)

        # The operator presses Stop: visible immediately, without a re-detect.
        pm.set_provider_status("demo", ProviderStatus.STOPPED.value)
        self.assertEqual(pm.get_provider("demo").status,
                         ProviderStatus.STOPPED.value,
                         "the operator's own action must be visible at once")

        # A fresh probe that finds the provider UP wins over the stale override.
        pm.detect_providers()
        self.assertEqual(pm.get_provider("demo").status,
                         ProviderStatus.RUNNING.value,
                         "the fresh probe result must win; a carried-forward "
                         "status is a lie about whether the provider is up")

    def test_a_stopped_probe_is_not_overwritten_by_an_old_running_status(self):
        """ARCH-ENG-179 — THE REGRESSION.

        Reproduced: once a provider was `running`, no later detect could ever
        report it stopped, because the merge re-applied the previous status. The
        operator watched a dead server listed as running for the rest of the
        session.
        """
        from agents.providers.provider_manager import ProviderInfo, ProviderManager, ProviderStatus

        pm = ProviderManager()
        state = {"running": True}

        pm._detect_gpus = lambda: setattr(pm, "_gpus", [])
        pm._detect_cloud_providers = lambda: None

        def fake_local():
            pm._providers["demo"] = ProviderInfo(
                name="Demo",
                provider_type="demo",
                status=(ProviderStatus.RUNNING.value if state["running"]
                        else ProviderStatus.STOPPED.value),
                is_local=True,
                is_cloud=False,
            )

        pm._detect_local_providers = fake_local

        pm.detect_providers()
        self.assertEqual(pm.get_provider("demo").status,
                         ProviderStatus.RUNNING.value)

        # The server dies.
        state["running"] = False
        pm.detect_providers()
        self.assertEqual(
            pm.get_provider("demo").status, ProviderStatus.STOPPED.value,
            "a provider that went down is still reported as running — the "
            "status merge is monotone and can never report stopped")

    def test_operator_choices_still_survive_a_redetect(self):
        """ARCH-ENG-179 — the fix must not drop what the merge was FOR.

        The old merge preserved the operator's selected model, GPU assignment,
        base url and key env var. Those must still survive: they are choices,
        not observations, so a probe genuinely has no opinion about them.
        """
        from agents.providers.provider_manager import ProviderInfo, ProviderManager, ProviderStatus

        pm = ProviderManager()
        pm._detect_gpus = lambda: setattr(pm, "_gpus", [])
        pm._detect_cloud_providers = lambda: None
        pm._detect_local_providers = lambda: pm._providers.__setitem__(
            "demo", ProviderInfo(name="Demo", provider_type="demo",
                                 status=ProviderStatus.RUNNING.value,
                                 is_local=True, is_cloud=False))

        pm.detect_providers()
        provider = pm.get_provider("demo")
        provider.selected_model = "my-model.gguf"
        provider.gpu_index = 1
        provider.base_url = "http://127.0.0.1:9999"

        pm.detect_providers()
        after = pm.get_provider("demo")
        self.assertEqual(after.selected_model, "my-model.gguf",
                         "the operator's model choice was lost on re-detect")
        self.assertEqual(after.gpu_index, 1)
        self.assertEqual(after.base_url, "http://127.0.0.1:9999")


if __name__ == "__main__":
    unittest.main()
