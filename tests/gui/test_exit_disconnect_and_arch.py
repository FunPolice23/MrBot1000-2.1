"""Phase G follow-ups — exit-time disconnect warnings + unknown-arch precheck
(ARCH-ENG-096/097).

- _disconnect_worker_signals must not emit RuntimeWarnings when the worker's C++
  object is already torn down (shiboken6.isValid guard + warning suppression).
- arch detection flags a model whose architecture this llama.cpp build doesn't
  know (e.g. xing4_0) as a SOFT warning, while known archs pass.
"""
import sys
import unittest

sys.path.insert(0, r"D:\MrBot1000_2.0")

_XING = r"D:/llama.cpp/models/Xing4.0-29B-A4B-Q4_K_M.gguf"          # unknown arch
_GLM = r"D:/llama.cpp/models/GLM-4.7-Flash-REAP-23B-A3B-UD-Q3_K_XL.gguf"  # known


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class TestArchDetection(unittest.TestCase):
    def test_unknown_arch_flagged(self):
        import os
        if not os.path.exists(_XING):
            self.skipTest("Xing model not present")
        from agents.providers.gguf_meta import detect_arch, arch_supported
        self.assertEqual(detect_arch(_XING), "xing4_0")
        self.assertFalse(arch_supported(_XING))

    def test_known_arch_passes(self):
        import os
        if not os.path.exists(_GLM):
            self.skipTest("GLM model not present")
        from agents.providers.gguf_meta import arch_supported
        self.assertTrue(arch_supported(_GLM))

    def test_known_set_contains_common_archs(self):
        from agents.providers.gguf_meta import KNOWN_ARCHITECTURES
        for a in ("llama", "qwen3", "gemma4", "glm", "deepseek", "nemotron_h_moe"):
            self.assertIn(a, KNOWN_ARCHITECTURES)


class TestDisconnectNoWarning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = _app()

    def test_disconnect_on_dead_object_is_silent(self):
        """Disconnecting a worker whose C++ object is gone must not warn."""
        import warnings
        from PySide6.QtCore import QThread, Signal
        from main import MainWindow

        class _W(QThread):
            sig = Signal(str)

        w = _W()
        mw = MainWindow.__new__(MainWindow)  # only need the method, not full init
        # Delete the underlying C++ object, then call the disconnect helper.
        import shiboken6
        shiboken6.delete(w)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            mw._disconnect_worker_signals(w)
        runtime = [c for c in caught if issubclass(c.category, RuntimeWarning)]
        self.assertEqual(runtime, [], f"unexpected RuntimeWarnings: {runtime}")

    def test_disconnect_on_live_worker_is_silent(self):
        import warnings
        from PySide6.QtCore import QThread, Signal
        from main import MainWindow

        class _W(QThread):
            sig = Signal(str)

        w = _W()
        mw = MainWindow.__new__(MainWindow)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            mw._disconnect_worker_signals(w)
        runtime = [c for c in caught if issubclass(c.category, RuntimeWarning)]
        self.assertEqual(runtime, [], f"unexpected RuntimeWarnings: {runtime}")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
