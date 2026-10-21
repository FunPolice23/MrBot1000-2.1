"""ARCH-ENG-314 — un-setting an advanced llama.cpp flag must persist.

Operator symptom: checking a box under "Advanced llama.cpp Flags — Small
Brain" (e.g. "Keep KV cache in system RAM") saved fine, but UNCHECKING it —
or setting a combo back to "(default)", or clearing the mmproj path — was
silently reverted on the next reload. Snapshot/write paths treated "unset"
as "write nothing", while ``set_env_values`` only ever MERGES. The previous
value stayed in `.env` forever, so the control re-appeared in its old state
and the launch command kept the old flag with no override possible.

The contract now: a control at its "not set" sentinel names its
``{prefix}_{key}`` for REMOVAL, the snapshot carries that set alongside the
values, and the .env writer drops the stale lines. Also pinned: a sentinel
value must never be resurrected by the removal (write wins), and comments
plus unknown keys survive the rewrite.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.environment import set_env_values  # noqa: E402


class TestSetEnvValuesRemovesStaleKeys(unittest.TestCase):
    """The writer primitive: merge values, drop the removals it names."""

    def setUp(self):
        self.fd, self.path = tempfile.mkstemp(suffix=".env")
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(
                "# a header comment that must survive\n"
                "KEEP_ME=1\n"
                "STALE_SMALL_FLAG=true\n"
                "ALSO_STALE=on\n")
        os.close(self.fd)

    def tearDown(self):
        os.unlink(self.path)

    def read(self) -> str:
        return Path(self.path).read_text(encoding="utf-8")

    def test_a_removed_key_cannot_resurrect(self):
        ok = set_env_values({"KEEP_ME": "2", "NEW_FLAG": "on"},
                            path=Path(self.path),
                            remove_keys={"STALE_SMALL_FLAG"})
        self.assertTrue(ok)
        text = self.read()
        self.assertIn("KEEP_ME=2", text)
        self.assertIn("NEW_FLAG=on", text)
        self.assertNotIn("STALE_SMALL_FLAG", text,
                         "the stale key still lives in .env — the operator's "
                         "un-set action does not persist")
        self.assertIn("ALSO_STALE=on", text)
        self.assertIn("# a header comment", text)

    def test_an_explicit_rewrite_beats_the_removal(self):
        ok = set_env_values({"STALE_SMALL_FLAG": "off"},
                            path=Path(self.path),
                            remove_keys={"STALE_SMALL_FLAG"})
        self.assertTrue(ok)
        self.assertIn("STALE_SMALL_FLAG=off", self.read())

    def test_an_unknown_or_dangling_removal_is_harmless(self):
        ok = set_env_values({"KEEP_ME": "3"},
                            path=Path(self.path),
                            remove_keys={"NEVER_EXISTED"})
        self.assertTrue(ok)
        self.assertIn("KEEP_ME=3", self.read())

    def test_removal_never_eats_a_comment(self):
        ok = set_env_values({"KEEP_ME": "4"}, path=Path(self.path),
                            remove_keys={"STALE_SMALL_FLAG"})
        self.assertTrue(ok)
        self.assertIn("# a header comment that must survive", self.read())


class TestTheSnapshotCarriesStaleKeys(unittest.TestCase):
    """Widget round trip: un-check must yield a removal, check a value."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _widget(self):
        from gui.widgets.dual_brain_control import DualBrainControl
        from agents.runtime.dual_brain import DualBrainRuntime
        return DualBrainControl(runtime=DualBrainRuntime.from_env())

    def _flag_values(self, control, prefix):
        controls = getattr(control, "sb_adv_group", None)
        return control._llama_flag_values(prefix, controls)

    def test_checked_box_writes_true_and_unchecked_names_removal(self):
        control = self._widget()
        try:
            controls = control.sb_adv_group
            box = controls["CPU_MOE"]
            prefix = "SMALL_BRAIN"
            box.setChecked(True)
            values, stale = control._llama_flag_values(prefix, controls)
            self.assertEqual(values.get(f"{prefix}_CPU_MOE"), "true")
            self.assertNotIn(f"{prefix}_CPU_MOE", stale)
            box.setChecked(False)
            values, stale = control._llama_flag_values(prefix, controls)
            self.assertNotIn(f"{prefix}_CPU_MOE", values)
            self.assertIn(f"{prefix}_CPU_MOE", stale)
        finally:
            control.deleteLater()

    def test_combo_back_to_default_names_removal(self):
        control = self._widget()
        try:
            controls = control.bb_adv_group
            combo = controls["FLASH_ATTN"]
            combo.setCurrentText("on")
            values, stale = control._llama_flag_values("BIG_BRAIN", controls)
            self.assertEqual(values.get("BIG_BRAIN_FLASH_ATTN"), "on")
            self.assertNotIn("BIG_BRAIN_FLASH_ATTN", stale)
            combo.setCurrentText("(default)")
            values, stale = control._llama_flag_values("BIG_BRAIN", controls)
            self.assertNotIn("BIG_BRAIN_FLASH_ATTN", values)
            self.assertIn("BIG_BRAIN_FLASH_ATTN", stale)
        finally:
            control.deleteLater()

    def test_spin_sentinel_names_removal_but_a_real_value_persists(self):
        control = self._widget()
        try:
            controls = control.bb_adv_group
            spin = controls["N_CPU_MOE"]
            spin.setValue(17)
            values, stale = control._llama_flag_values("BIG_BRAIN", controls)
            self.assertEqual(values.get("BIG_BRAIN_N_CPU_MOE"), "17")
            spin.setValue(0)
            values, stale = control._llama_flag_values("BIG_BRAIN", controls)
            self.assertNotIn("BIG_BRAIN_N_CPU_MOE", values)
            self.assertIn("BIG_BRAIN_N_CPU_MOE", stale)
        finally:
            control.deleteLater()

    def test_a_reasoning_budget_of_minus_1_is_a_setting_not_unsent(self):
        """REASONING_BUDGET=-1 means unrestricted — a real value. The old
        blanket "<=0 means unset" rule silently dropped it; the per-control
        metadata keeps it while the "(default)" -2 sentinel stays unset."""
        control = self._widget()
        try:
            controls = control.bb_adv_group
            spin = controls["REASONING_BUDGET"]
            spin.setValue(-2)
            values, stale = control._llama_flag_values("BIG_BRAIN", controls)
            self.assertIn("BIG_BRAIN_REASONING_BUDGET", stale)
            spin.setValue(-1)
            values, stale = control._llama_flag_values("BIG_BRAIN", controls)
            self.assertEqual(values.get("BIG_BRAIN_REASONING_BUDGET"), "-1")
            self.assertNotIn("BIG_BRAIN_REASONING_BUDGET", stale)
        finally:
            control.deleteLater()

    def test_snapshot_records_the_stale_keys_on_the_widget(self):
        control = self._widget()
        try:
            # Force one known stale key so the snapshot has work.
            control.bb_adv_group["FLASH_ATTN"].setCurrentText("(default)")
            snapshot = control._snapshot_settings_values()
            self.assertTrue(snapshot)
            self.assertIn("BIG_BRAIN_FLASH_ATTN",
                          getattr(control, "_stale_env_keys", set()),
                          "the snapshot must hand the writer the stale set")
        finally:
            control.deleteLater()


class TestTheWritersThreadTheRemovalThrough(unittest.TestCase):
    def test_every_writer_passes_remove_keys(self):
        import ast
        for rel, fn in (("gui/widgets/dual_brain_control.py",
                         "_persist_settings"),
                        ("gui/workers/provider_lifecycle_backend.py",
                         "_write_env_values")):
            src = (ROOT / rel).read_text(encoding="utf-8")
            tree = ast.parse(src)
            found = False
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == fn:
                    body = ast.get_source_segment(src, node) or ""
                    found = "remove_keys" in body
            self.assertTrue(found, f"{rel}:{fn} still writes without "
                                   "remove_keys — un-setting regresses")


if __name__ == "__main__":
    unittest.main()
