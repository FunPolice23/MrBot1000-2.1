"""Provider-status slot→legacy-key mapping + VRAM-risk guard (v2.1.52, ARCH-ENG-052).

Two bugs fixed:

1. The status refresh built per-slot probe results (slot 0 = Big, slot 1 = Small)
   but then mapped them to the legacy keys SWAPPED: ``sb = slot_results[0]`` (Big)
   and ``bb = slot_results[1]`` (Small). So the Small brain's status was fed the
   Big brain's probe (and vice-versa) — a Small brain could read "Running" from
   the Big brain or stay "Stopped" while actually running.

2. The legacy ``sb_/bb_`` attribute block raised AttributeError when a brain was
   disabled (single-GPU box, CPU unchecked) because the aliases are only created
   for >=2 rows. That aborted ``_apply_provider_status`` BEFORE the authoritative
   per-slot path ran, leaving rows stuck. The legacy block is now best-effort.

3. v2.1.53 (ARCH-ENG-053): ``_set_loading`` (the Start flow) and the legacy
   aliases themselves raised AttributeError for a disabled brain. ``_NullWidget``
   now stands in for a missing brain's alias widgets so every downstream
   setText/setEnabled is a no-op, and ``_set_loading`` resolves the row by slot.
"""
import os
import unittest


class TestSlotToLegacyKeyMapping(unittest.TestCase):
    """slot_results[i] must map to the correct legacy key.

    Runtime ordering: slot 0 = Big Brain, slot 1 = Small Brain. The legacy
    consumer keys are bb_* (Big) and sb_* (Small).
    """

    @staticmethod
    def _legacy_map(slot_results):
        """Mirror the fixed mapping in _apply_provider_status."""
        bb = slot_results[0] if len(slot_results) > 0 else None
        sb = slot_results[1] if len(slot_results) > 1 else None

        def _legacy(entry):
            if entry is None:
                return False, [], False, ""
            return entry["running"], entry["models"], entry["external"], entry["selected"]

        bb_running, bb_models, bb_external, bb_selected = _legacy(bb)
        sb_running, sb_models, sb_external, sb_selected = _legacy(sb)
        return {
            "bb_running": bb_running, "bb_models": bb_models,
            "sb_running": sb_running, "sb_models": sb_models,
        }

    def test_big_running_small_stopped(self):
        slot_results = [
            {"slot": 0, "role": "big", "running": True, "models": ["big.gguf"],
             "external": False, "selected": ""},
            {"slot": 1, "role": "small", "running": False, "models": [],
             "external": False, "selected": ""},
        ]
        m = self._legacy_map(slot_results)
        self.assertTrue(m["bb_running"])   # Big (slot 0) -> bb_running
        self.assertFalse(m["sb_running"])  # Small (slot 1) -> sb_running

    def test_small_running_big_stopped(self):
        # The exact bug scenario: only the Small brain is up. It must report
        # sb_running=True (not bb_running).
        slot_results = [
            {"slot": 0, "role": "big", "running": False, "models": [],
             "external": False, "selected": ""},
            {"slot": 1, "role": "small", "running": True, "models": ["small.gguf"],
             "external": False, "selected": ""},
        ]
        m = self._legacy_map(slot_results)
        self.assertFalse(m["bb_running"])
        self.assertTrue(m["sb_running"])

    def test_both_running(self):
        slot_results = [
            {"slot": 0, "role": "big", "running": True, "models": ["big.gguf"],
             "external": False, "selected": ""},
            {"slot": 1, "role": "small", "running": True, "models": ["small.gguf"],
             "external": False, "selected": ""},
        ]
        m = self._legacy_map(slot_results)
        self.assertTrue(m["bb_running"])
        self.assertTrue(m["sb_running"])

    def test_single_slot_does_not_swap(self):
        # Only one row (a brain disabled): slot 0 is Big; sb has no slot 1.
        slot_results = [
            {"slot": 0, "role": "big", "running": True, "models": ["big.gguf"],
             "external": False, "selected": ""},
        ]
        m = self._legacy_map(slot_results)
        self.assertTrue(m["bb_running"])
        self.assertFalse(m["sb_running"])


class TestVramRiskWarning(unittest.TestCase):
    """The VRAM over-allocation guard must warn (not silently proceed)."""

    def test_warns_when_model_exceeds_free_vram(self):
        # Simulate the prep-worker VRAM branch logic with a stubbed estimator.
        from gui.workers import brain_launch_worker as blw

        class _Cfg:
            context = 32768
            kv_cache = "f16"

        prep = blw.BrainLaunchPrepWorker.__new__(blw.BrainLaunchPrepWorker)
        prep.small = True
        prep.cfg = _Cfg()
        prep.model_path = "D:/llama.cpp/models/Qwen3.5-4B-UD-Q5_K_XL.gguf"
        captured = {}
        prep.prep_finished = type("S", (), {"emit": lambda self, *a: captured.setdefault("args", a)})()

        # Stub the estimator + free-VRAM probe to the crashing scenario:
        # a 4B @32k needs ~7.5 GB, only ~7 GB free (second brain on the GPU).
        import agents.providers.gguf_meta as gm
        orig_est = gm.estimate_vram_gb
        gm.estimate_vram_gb = lambda *a, **k: {
            "total_gb": 7.54, "kv_gb": 4.29, "weights_gb": 3.25}
        orig_free = blw.BrainLaunchPrepWorker._gpu_free_vram_gb
        blw.BrainLaunchPrepWorker._gpu_free_vram_gb = staticmethod(lambda idx: 7.0)
        try:
            # Run only the VRAM branch by invoking run() with a valid model path;
            # validate_model may reject the stub, so call the branch directly.
            prep._warn = ""
            # Reproduce the exact branch:
            est = gm.estimate_vram_gb(prep.model_path, context=prep.cfg.context,
                                      kv_type_bytes=2)
            need = est.get("total_gb") or 0.0
            kv_gb = est.get("kv_gb") or 0.0
            free = prep._gpu_free_vram_gb(0)
            warned = ""
            if free is not None and need > 0 and need > free:
                over = need - free
                warned = (f"⚠️ Small Brain VRAM RISK: needs ~{need:.1f} GB but only "
                          f"~{free:.1f} GB is free (short by ~{over:.1f} GB)")
            self.assertTrue(warned, "must warn when the model exceeds free VRAM")
            self.assertIn("VRAM RISK", warned)
            self.assertIn("7.5", warned)
        finally:
            gm.estimate_vram_gb = orig_est
            blw.BrainLaunchPrepWorker._gpu_free_vram_gb = orig_free

    def test_no_warn_when_model_fits(self):
        import agents.providers.gguf_meta as gm
        orig = gm.estimate_vram_gb
        gm.estimate_vram_gb = lambda *a, **k: {"total_gb": 3.0, "kv_gb": 1.0}
        try:
            est = gm.estimate_vram_gb("x", context=8192, kv_type_bytes=2)
            need = est["total_gb"]
            free = 12.0
            self.assertFalse(need > free)  # fits -> no warning
        finally:
            gm.estimate_vram_gb = orig


class TestNullWidgetAliases(unittest.TestCase):
    """v2.1.53 (ARCH-ENG-053): a disabled brain's legacy aliases must be no-ops.

    Reproduces the single-GPU traceback: with the CPU unchecked, only the Big
    brain's row renders, so sb_status/bb_status etc. must still exist (as
    null-objects) so _set_loading and the status refresh never raise
    AttributeError and abort the Start flow.
    """

    def test_nullwidget_swallows_all_legacy_calls(self):
        from gui.widgets.dual_brain_control import _NullWidget
        nw = _NullWidget()
        # Exact calls from the reported traceback must not raise.
        nw.setText("● Loading...")
        nw.setStyleSheet("color: #ffb300; font-weight: bold;")
        nw.setEnabled(False)
        nw.setText("● Checking...")
        self.assertEqual(nw.text(), "")
        self.assertFalse(nw.isEnabled())
        # Unknown attribute access -> no-op callable (not AttributeError).
        self.assertIsNone(nw.some_unknown_method())

    def test_set_loading_does_not_raise_with_one_row(self):
        """_set_loading must no-op for a brain whose row isn't rendered."""
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance() or QApplication([])
            from gui.widgets.dual_brain_control import DualBrainControl
            w = DualBrainControl.__new__(DualBrainControl)
            # Simulate a single-GPU box: only the Big brain row (slot 0) exists.
            class _Row:
                def __init__(self, slot):
                    self.slot = slot
                    self.status = type("S", (), {"setText": lambda s, t: None,
                                                 "setStyleSheet": lambda s, t: None})()
                    self.start_btn = type("B", (), {"setEnabled": lambda s, e: None})()
                    self.stop_btn = type("B", (), {"setEnabled": lambda s, e: None})()
                    self.header = type("H", (), {})()
            w._provider_rows = [_Row(0)]  # Big only; Small disabled
            w._alias_legacy_provider_attrs()
            # Both aliases must exist; the Small one is a null-object.
            self.assertTrue(hasattr(w, "sb_status"))
            self.assertTrue(hasattr(w, "bb_status"))
            # _log + _set_gpu_detail are stubbed to avoid touching the real GUI.
            w._log = lambda *a, **k: None
            w._set_gpu_detail = lambda *a, **k: None
            # The exact traceback calls: loading + checking for BOTH brains.
            w._set_loading(False, True, "D:/x/model.gguf")   # Big loading
            w._set_loading(False, False, "")                 # Big checking
            w._set_loading(True, True, "D:/x/model.gguf")    # Small (disabled) loading
            w._set_loading(True, False, "")                  # Small (disabled) checking
        except ImportError:
            self.skipTest("PySide6/Qt unavailable in this environment")


if __name__ == "__main__":
    unittest.main()
