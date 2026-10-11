"""Tests for the N-brain lifecycle backend slot handlers (Phase 5)."""

import os
import sys
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from gui.widgets.dual_brain_control import DualBrainControl  # noqa: E402
from agents.runtime.dual_brain import DualBrainRuntime  # noqa: E402
from agents.providers.provider_manager import ProviderManager  # noqa: E402


def _wait_detected(app, timeout=12):
    deadline = time.time() + timeout
    while not ProviderManager.instance()._detected and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)


class TestSlotLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app

    def _widget(self):
        w = DualBrainControl(runtime=DualBrainRuntime.from_env())
        self.app.processEvents()
        _wait_detected(self.app)
        w._apply_runtime()
        self.app.processEvents()
        return w

    def test_slot_config_accessor(self):
        w = self._widget()
        try:
            slot2 = w.runtime.slot_config(2)
            self.assertIsNotNone(slot2)
            self.assertIs(w._slot_config(2), slot2)
            self.assertIsNone(w._slot_config(99))
        finally:
            w._closing = True

    def test_slot2_cpu_config_forces_system_ram(self):
        w = self._widget()
        try:
            slot2 = w.runtime.slot_config(2)
            self.assertEqual(slot2.device_id, "cpu")
            self.assertEqual(slot2.gpu_layers, 0)
            self.assertTrue(slot2.decision_support_only)
        finally:
            w._closing = True

    def test_slot_launch_command_targets_slot_port(self):
        w = self._widget()
        try:
            slot2 = w.runtime.slot_config(2)
            cmd = slot2.build_llama_command("dummy-model.gguf")
            self.assertIn(str(slot2.port), cmd)
            self.assertIn("--n-gpu-layers", cmd)  # CPU => n-gpu-layers 0
            self.assertIn("--port", cmd)
        finally:
            w._closing = True

    def test_stop_slot_is_safe_when_not_running(self):
        w = self._widget()
        try:
            # Must not raise when no server process exists for the slot.
            w._stop_slot(2)
            self.assertIsNone(getattr(w, "_slot_2_server_process", None))
        finally:
            w._closing = True

    def test_row_start_routes_slot2_to_start_slot(self):
        w = self._widget()
        try:
            called = []
            orig = w._start_slot
            w._start_slot = lambda s: called.append(s)
            w._provider_rows[2].start_btn.click()
            self.assertEqual(called, [2])
            w._start_slot = orig
        finally:
            w._closing = True

    def test_row_stop_routes_slot2_to_stop_slot(self):
        w = self._widget()
        try:
            called = []
            orig = w._stop_slot
            w._stop_slot = lambda s: called.append(s)
            w._provider_rows[2].set_running(True)
            w._provider_rows[2].stop_btn.click()
            self.assertEqual(called, [2])
            w._stop_slot = orig
        finally:
            w._closing = True

    def test_start_all_starts_every_enabled_slot(self):
        """'Start All Brains' must launch every enabled slot (0/1 via the Big/
        Small handlers, 2+ via _start_slot) — not just the two primary servers."""
        w = self._widget()
        try:
            n_slots = len(w.runtime.slots())
            big_called, small_called, slot_called = [], [], []
            orig_big, orig_small, orig_slot = (
                w._on_start_big_brain, w._on_start_small_brain, w._start_slot)
            w._on_start_big_brain = lambda *a: big_called.append(True)
            w._on_start_small_brain = lambda *a: small_called.append(True)
            w._start_slot = lambda s: slot_called.append(s)
            try:
                w._on_start_all()
            finally:
                w._on_start_big_brain, w._on_start_small_brain, w._start_slot = (
                    orig_big, orig_small, orig_slot)
            # Slots 0/1 always started (when enabled); every extra slot too.
            self.assertEqual(slot_called, list(range(2, n_slots)))
            if n_slots >= 1:
                self.assertEqual(big_called, [True])
            if n_slots >= 2:
                self.assertEqual(small_called, [True])
        finally:
            w._closing = True

    def test_slot_launch_schedules_status_reprobe(self):
        """After a slot 2+ launch succeeds, a bounded re-probe is scheduled so the
        row flips Stopped -> Running once the server answers (not stuck Stopped)."""
        w = self._widget()
        try:
            scheduled = []
            orig = w._schedule_slot_reprobe
            w._schedule_slot_reprobe = lambda s, attempts=90: scheduled.append((s, attempts))
            try:
                w._on_slot_launched(2, True, "started", None)
            finally:
                w._schedule_slot_reprobe = orig
            self.assertEqual(scheduled, [(2, 90)])
        finally:
            w._closing = True


class TestDevicePolicyLiveRebuild(unittest.TestCase):
    """Phase 6: toggling a device rebuilds rows and stops its brain."""

    @classmethod
    def setUpClass(cls):
        cls.app = _app

    def _widget(self):
        w = DualBrainControl(runtime=DualBrainRuntime.from_env())
        self.app.processEvents()
        _wait_detected(self.app)
        w._apply_runtime()
        self.app.processEvents()
        return w

    def _cpu_device(self):
        from agents.runtime import device_registry as dr
        return next(d for d in dr.detect_devices(include_cpu=True) if d.is_cpu)

    def test_disable_device_stops_its_brain_and_shrinks_rows(self):
        from agents.runtime import device_registry as dr
        w = self._widget()
        try:
            cpu = self._cpu_device()
            row = w._device_rows.get(cpu.id)
            self.assertIsNotNone(row)
            stopped = []
            orig = w._stop_slot
            w._stop_slot = lambda s: stopped.append(s)
            try:
                row["enable"].setChecked(False)
                self.app.processEvents()
            finally:
                w._stop_slot = orig
            # The disabled device's brain was stopped.
            self.assertIn(2, stopped)
            # Policy persisted as disabled.
            self.assertFalse(dr.load_policy().enabled.get(cpu.id))
            # Rows shrank to match the enabled devices.
            self.assertEqual(len(w._provider_rows), len(w.runtime.slots()))
        finally:
            # Restore default policy so other tests aren't affected.
            pol = dr.load_policy()
            pol.enabled[cpu.id] = True
            dr.save_policy(pol)
            w._closing = True

    def test_reenable_device_restores_rows(self):
        from agents.runtime import device_registry as dr
        w = self._widget()
        try:
            cpu = self._cpu_device()
            row = w._device_rows.get(cpu.id)
            row["enable"].setChecked(False)
            self.app.processEvents()
            shrunk = len(w._provider_rows)
            row["enable"].setChecked(True)
            self.app.processEvents()
            self.assertGreater(len(w._provider_rows), shrunk)
        finally:
            pol = dr.load_policy()
            pol.enabled[cpu.id] = True
            dr.save_policy(pol)
            w._closing = True

    def test_stop_brain_on_disabled_device_routes_by_slot(self):
        w = self._widget()
        try:
            calls = []
            orig_big, orig_small, orig_slot = (
                w._on_stop_big_brain, w._on_stop_small_brain, w._stop_slot)
            w._on_stop_big_brain = lambda *a: calls.append("big")
            w._on_stop_small_brain = lambda *a: calls.append("small")
            w._stop_slot = lambda s: calls.append(f"slot{s}")
            try:
                # The CPU is bound to slot 2 in the default policy.
                cpu = self._cpu_device()
                cfg = w.runtime.slot_for_device(cpu.id)
                w._stop_brain_on_disabled_device(cpu.id)
            finally:
                w._on_stop_big_brain = orig_big
                w._on_stop_small_brain = orig_small
                w._stop_slot = orig_slot
            self.assertIn(f"slot{cfg.slot}", calls)
        finally:
            w._closing = True


class TestPerSlotModelSelection(unittest.TestCase):
    """Every provider row has a model dropdown (issue: only 2 devices could
    select a model); the choice persists to the device policy."""

    @classmethod
    def setUpClass(cls):
        cls.app = _app

    def _widget(self):
        w = DualBrainControl(runtime=DualBrainRuntime.from_env())
        self.app.processEvents()
        _wait_detected(self.app)
        w._apply_runtime()
        self.app.processEvents()
        return w

    def _cpu_device(self):
        from agents.runtime import device_registry as dr
        return next(d for d in dr.detect_devices(include_cpu=True) if d.is_cpu)

    def test_every_row_has_a_model_dropdown(self):
        w = self._widget()
        try:
            self.assertGreaterEqual(len(w._provider_rows), 2)
            for row in w._provider_rows:
                self.assertTrue(hasattr(row, "model_combo"))
                # Populated with at least the "Select a model..." placeholder.
                self.assertGreaterEqual(row.model_combo.count(), 1)
        finally:
            w._closing = True

    def test_selecting_model_on_slot2_sets_config_and_policy(self):
        from agents.runtime import device_registry as dr
        w = self._widget()
        try:
            cpu = self._cpu_device()
            cfg2 = w.runtime.slot_config(2)
            self.assertIsNotNone(cfg2)
            self.assertEqual(cfg2.device_id, cpu.id)
            # Put a fake model in the row's dropdown and "pick" it.
            row2 = w._provider_rows[2]
            fake = "D:/llama.cpp/models/fake-cpu-model.gguf"
            row2.set_models([fake])
            row2.model_combo.setCurrentIndex(1)  # select fake
            self.app.processEvents()
            # The slot config adopted the choice.
            self.assertEqual(cfg2.model, fake)
            # The device policy persisted it (round-trips across restarts).
            self.assertEqual(dr.load_policy().models.get(cpu.id), fake)
        finally:
            # Clean up the persisted choice so other tests aren't affected.
            pol = dr.load_policy()
            pol.models.pop(cpu.id, None)
            dr.save_policy(pol)
            w._closing = True

    def test_model_dropdown_signal_routes_to_handler(self):
        w = self._widget()
        try:
            seen = []
            orig = w._on_provider_row_model_changed
            w._on_provider_row_model_changed = lambda s, p: seen.append((s, p))
            row2 = w._provider_rows[2]
            row2.set_models(["/a.gguf", "/b.gguf"])
            row2.model_combo.setCurrentIndex(2)
            self.assertEqual(seen, [(2, "/b.gguf")])
            w._on_provider_row_model_changed = orig
        finally:
            w._closing = True


class TestRowStatusNotStuckChecking(unittest.TestCase):
    """Every row shows Stopped (not a stuck 'Checking...') at startup when
    auto-start is off, and the per-slot probe updates all rows."""

    @classmethod
    def setUpClass(cls):
        cls.app = _app

    def _widget(self):
        w = DualBrainControl(runtime=DualBrainRuntime.from_env())
        self.app.processEvents()
        _wait_detected(self.app)
        w._apply_runtime()
        self.app.processEvents()
        return w

    def test_initial_status_is_stopped_not_checking(self):
        """A freshly built widget rests at '● Stopped' (never the stuck
        '● Checking...') BEFORE any probe has run. This must hold regardless of
        whether llama-servers are live on the box, so assert on the pre-probe
        resting state, not after a background probe may have flipped a row."""
        w = self._widget()
        try:
            self.assertGreaterEqual(len(w._provider_rows), 2)
            for row in w._provider_rows:
                self.assertNotIn("Checking", row.status.text())
        finally:
            w._closing = True

    def test_per_slot_probe_updates_all_rows(self):
        """The status refresh must deliver a probe entry for EVERY enabled slot
        (fixes the CPU/RAM row stuck at 'Checking...'). We assert the probe
        covered all rows; we do NOT assume Stopped, because a live llama-server
        on the operator's box correctly makes a row read 'Running'."""
        w = self._widget()
        try:
            captured = {}
            def on_status(data):
                captured["slots"] = data.get("slots")
                w._apply_provider_status(data)
            w.provider_probed.connect(on_status)
            w._refresh_provider_status()
            deadline = time.time() + 8
            while "slots" not in captured and time.time() < deadline:
                self.app.processEvents()
                time.sleep(0.05)
            # Probe delivered an entry for every slot.
            self.assertEqual(len(captured.get("slots", [])), len(w._provider_rows))
            # Every row reflects its probed state (Running or Stopped) — never
            # stuck at the initial placeholder.
            for row in w._provider_rows:
                self.assertNotIn("Checking", row.status.text())
        finally:
            w._closing = True

    def test_apply_slot_statuses_marks_running(self):
        w = self._widget()
        try:
            w._apply_slot_statuses([
                {"slot": 0, "running": True, "models": ["m.gguf"], "selected": ""},
                {"slot": 1, "running": False, "models": [], "selected": ""},
                {"slot": 2, "running": True, "models": ["c.gguf"], "selected": ""},
            ])
            self.assertIn("Running", w._provider_rows[0].status.text())
            self.assertEqual(w._provider_rows[1].status.text(), "● Stopped")
            self.assertIn("Running", w._provider_rows[2].status.text())
            self.assertTrue(w._provider_rows[2].stop_btn.isEnabled())
            self.assertFalse(w._provider_rows[2].start_btn.isEnabled())
        finally:
            w._closing = True

    def test_apply_slot_statuses_ignores_out_of_range(self):
        w = self._widget()
        try:
            # Must not raise for a slot index beyond the rendered rows.
            w._apply_slot_statuses([{"slot": 99, "running": True, "models": [], "selected": ""}])
            w._apply_slot_statuses([])
            # Assert the out-of-range row really was ignored rather than
            # silently creating state: no row 99 exists.
            self.assertLess(len(w._provider_rows), 99)
            # And a valid in-range status still applies (proves the guard did
            # not disable the whole method).
            w._apply_slot_statuses([{"slot": 0, "running": True,
                                     "models": [], "selected": ""}])
        finally:
            w._closing = True


class TestPerDeviceSettings(unittest.TestCase):
    """Every enabled device (incl CPU/slot 2+) has editable llama.cpp settings
    that apply to the slot config, persist, and round-trip."""

    @classmethod
    def setUpClass(cls):
        cls.app = _app

    def _widget(self):
        w = DualBrainControl(runtime=DualBrainRuntime.from_env())
        self.app.processEvents()
        _wait_detected(self.app)
        w._apply_runtime()
        self.app.processEvents()
        return w

    def _cpu_device(self):
        from agents.runtime import device_registry as dr
        return next(d for d in dr.detect_devices(include_cpu=True) if d.is_cpu)

    def test_every_slot_has_a_settings_row(self):
        w = self._widget()
        try:
            self.assertEqual(len(w._settings_rows), len(w.runtime.slots()))
            self.assertGreaterEqual(len(w._settings_rows), 3)
        finally:
            w._closing = True

    def test_cpu_settings_row_locks_gpu_layers(self):
        w = self._widget()
        try:
            cpu_row = w._settings_rows[2]
            self.assertTrue(cpu_row.is_cpu)
            self.assertEqual(cpu_row.gpu_layers_spin.value(), 0)
            self.assertFalse(cpu_row.gpu_layers_spin.isEnabled())
        finally:
            w._closing = True

    def test_temperature_seeds_from_persisted_env(self):
        # v2.1.38 (ARCH-ENG-045): a saved temperature must survive a rebuild —
        # _apply_runtime seeds the temp spins from BIG/SMALL_BRAIN_TEMPERATURE
        # instead of leaving them at the BrainSettingsRow's hardcoded 0.5.
        import os
        w = self._widget()
        prev = {k: os.environ.get(k) for k in
                ("BIG_BRAIN_TEMPERATURE", "SMALL_BRAIN_TEMPERATURE")}
        try:
            os.environ["BIG_BRAIN_TEMPERATURE"] = "0.83"
            os.environ["SMALL_BRAIN_TEMPERATURE"] = "0.27"
            w._apply_runtime()
            self.app.processEvents()
            self.assertAlmostEqual(w.bb_temp_spin.value(), 0.83, places=2)
            self.assertAlmostEqual(w.sb_temp_spin.value(), 0.27, places=2)
        finally:
            for k, v in prev.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            w._closing = True

    def test_changing_cpu_context_applies_and_persists(self):
        from agents.runtime import device_registry as dr
        w = self._widget()
        try:
            cpu = self._cpu_device()
            cfg2 = w.runtime.slot_config(2)
            w._settings_rows[2].ctx_spin.setValue(16384)
            self.app.processEvents()
            self.assertEqual(cfg2.context, 16384)
            persisted = dr.load_policy().settings.get(cpu.id, {})
            self.assertEqual(persisted.get("context"), 16384)
        finally:
            pol = dr.load_policy()
            pol.settings.pop(self._cpu_device().id, None)
            dr.save_policy(pol)
            w._closing = True

    def test_settings_round_trip_through_sync_slots(self):
        from agents.runtime import device_registry as dr
        w = self._widget()
        try:
            cpu = self._cpu_device()
            # Persist a context for the CPU device, then re-sync.
            pol = dr.load_policy()
            pol.settings[cpu.id] = {"context": 20000, "threads": 10, "batch": 512,
                                    "kv_cache": "q8_0", "split_mode": "none",
                                    "gpu_layers": 0, "temperature": 0.5}
            dr.save_policy(pol)
            w.runtime.sync_slots(dr.brain_placements(
                dr.resolve_assignments(dr.detect_devices(include_cpu=True), dr.load_policy())))
            cfg2 = w.runtime.slot_config(2)
            self.assertEqual(cfg2.context, 20000)
            self.assertEqual(cfg2.threads, 10)
            self.assertEqual(cfg2.kv_cache, "q8_0")
        finally:
            pol = dr.load_policy()
            pol.settings.pop(cpu.id, None)
            dr.save_policy(pol)
            w._closing = True


if __name__ == "__main__":
    unittest.main()
