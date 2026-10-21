"""ARCH-ENG-153 — the roster debounce made a launch read the PREVIOUS model.

``BrainRosterPanel._on_changed`` (f345698) coalesces roster writes behind a
400 ms single-shot QTimer instead of writing settings.json per keystroke.
The write itself is correct. What was missed is that the **launch path reads
the roster back from disk**, not from the panel:

  ``_probe_before_start`` -> ``DualBrainRuntime.from_settings()``
      -> ``BrainRoster.load_or_none(root)`` -> settings.json

There was no flush anywhere between the operator's edit and that read — the
only forced flushes are inside ``save_roster_from``, which the start path
never calls. So: edit the Big-brain model field, click Start inside the 400 ms
window, and llama-server launches the **previous** model. Pre-debounce the
write was synchronous inside ``_on_changed``, so the read always saw it.

Reproduced by execution against the real panel + real roster + real runtime
(table below), then fixed with ``flush_pending_roster_edit`` called from every
``from_settings()`` read site via ``_runtime_from_settings()``.

The behavioural test is the primary evidence. The structural tests are the
terminating guard: they pin that every read site routes through the flushing
helper, so a new caller cannot reintroduce the lag.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO = Path(__file__).resolve().parents[2]


class TestDebouncedEditReachesTheLaunchRead(unittest.TestCase):
    """Real panel + real roster + real runtime, no event-loop pump."""

    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            cls.app = QApplication.instance() or QApplication([])
        except Exception as exc:  # pragma: no cover - Qt-less CI
            raise unittest.SkipTest(f"Qt unavailable: {exc}")

    def test_a_pending_edit_is_on_disk_before_the_launch_read(self):
        """THE reproduction. Edit -> read, with only the flush in between."""
        import tempfile

        from agents.runtime.brain_roster import BrainRoster, BrainSlot
        from agents.runtime.dual_brain import BrainRole, DualBrainRuntime
        from gui.widgets.brain_roster_panel import (
            BrainRosterPanel, flush_pending_roster_edit)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            roster = BrainRoster.load(root=root)
            roster.big = [BrainSlot(model="models/OLD-BIG.gguf")]
            roster.save(root=root)

            panel = BrainRosterPanel(
                None, root=str(root),
                models=["models/OLD-BIG.gguf", "models/NEW-BIG.gguf"])
            try:
                row = panel._tier_widgets["big"]["rows"].itemAt(0).widget()
                # A real operator edit: the combo emits `changed` ->
                # _on_changed, which collects rows and arms the 400 ms timer.
                row.model_combo.setCurrentText("models/NEW-BIG.gguf")

                # Precondition: the widget state is the NEW model, but the
                # write is still pending. This is the window the defect lived
                # in — if it is gone the debounce itself changed and this
                # test no longer describes reality.
                self.assertEqual(panel.roster.big[0].model, "models/NEW-BIG.gguf")
                self.assertTrue(
                    panel._save_timer.isActive(),
                    "the edit did not arm the debounce timer — the scenario "
                    "this test reproduces no longer exists")
                on_disk_before = BrainRoster.load(root=root).big[0].model
                self.assertEqual(
                    on_disk_before, "models/OLD-BIG.gguf",
                    "the write is no longer debounced; ARCH-ENG-153 cannot "
                    "reproduce and this suite must be re-derived")

                # The fix: what every launch read now does first.
                flush_pending_roster_edit(panel)

                self.assertEqual(
                    BrainRoster.load(root=root).big[0].model,
                    "models/NEW-BIG.gguf",
                    "flush_pending_roster_edit did not persist the pending "
                    "edit (ARCH-ENG-153)")
                rt = DualBrainRuntime.from_settings(root=str(root))
                self.assertEqual(
                    rt.config(BrainRole.BIG).model, "models/NEW-BIG.gguf",
                    "the launch path still reads the PREVIOUS model — the "
                    "debounced edit does not reach the roster read "
                    "(ARCH-ENG-153)")
            finally:
                panel.deleteLater()

    def test_flush_is_safe_with_no_panel_and_no_pending_edit(self):
        """Unconditional call on hot paths must be a no-op, never raise."""
        from gui.widgets.brain_roster_panel import flush_pending_roster_edit

        flush_pending_roster_edit(None)      # no panel at all
        flush_pending_roster_edit(object())  # wrong type entirely
        # A panel with a stopped timer (nothing pending).
        import tempfile

        from agents.runtime.brain_roster import BrainRoster
        from gui.widgets.brain_roster_panel import BrainRosterPanel

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            BrainRoster.load(root=root).save(root=root)
            panel = BrainRosterPanel(None, root=str(root))
            try:
                panel._save_timer.stop()
                before = (root / "settings.json").read_bytes() \
                    if (root / "settings.json").exists() else None
                flush_pending_roster_edit(panel)
                after = (root / "settings.json").read_bytes() \
                    if (root / "settings.json").exists() else None
                self.assertEqual(
                    before, after,
                    "flush rewrote settings.json with no pending edit — it is "
                    "not a no-op and will re-open the fsync storm f345698 "
                    "closed")
            finally:
                panel.deleteLater()

    def test_a_pending_edit_survives_app_exit(self):
        """The SECOND read-side path: teardown must flush too.

        ``DualBrainControl.cleanup()`` runs on window close. The roster
        panel's only writer is the 400 ms timer, and closing stops the event
        loop before it fires — so an edit made in the last moments was
        silently discarded on every exit. Same hazard as the launch read, one
        path later; the second discovery pass of ARCH-ENG-153 found it.
        """
        import tempfile

        from agents.runtime.brain_roster import BrainRoster, BrainSlot
        from gui.widgets.brain_roster_panel import (
            BrainRosterPanel, flush_pending_roster_edit)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            roster = BrainRoster.load(root=root)
            roster.big = [BrainSlot(model="models/OLD-BIG.gguf")]
            roster.save(root=root)

            panel = BrainRosterPanel(
                None, root=str(root),
                models=["models/OLD-BIG.gguf", "models/NEW-BIG.gguf"])
            try:
                row = panel._tier_widgets["big"]["rows"].itemAt(0).widget()
                row.model_combo.setCurrentText("models/NEW-BIG.gguf")
                self.assertTrue(
                    panel._save_timer.isActive(),
                    "the edit did not arm the debounce timer — the exit-path "
                    "scenario this test reproduces no longer exists")

                # What DualBrainControl.cleanup() now does first. Pinned
                # structurally in TestEveryRosterReadFlushesFirst; here the
                # effect on the real file is asserted.
                flush_pending_roster_edit(panel)

                self.assertEqual(
                    BrainRoster.load(root=root).big[0].model,
                    "models/NEW-BIG.gguf",
                    "closing the app discards a debounced roster edit — the "
                    "operator's last change is lost on exit (ARCH-ENG-153)")
            finally:
                panel.deleteLater()


class TestEveryRosterReadFlushesFirst(unittest.TestCase):
    """Structural guard: the read side cannot bypass the flush."""

    def _src(self, rel):
        return (REPO / rel).read_text(encoding="utf-8")

    def test_no_bare_from_settings_call_remains_in_the_lifecycle_backend(self):
        """Every ``from_settings()`` read must route through the flushing helper.

        Pinned by counting: any call site added later that reads the roster
        directly changes this number and fails, rather than silently launching
        the previous model.
        """
        src = self._src("gui/workers/provider_lifecycle_backend.py")
        # The helper itself is allowed exactly one direct call.
        body_start = src.find("def _runtime_from_settings(self):")
        self.assertGreater(body_start, 0, "the flushing helper is gone")
        outside = src[:body_start] + src[src.find("\n    def ", body_start + 10):]
        bare = [ln.strip() for ln in outside.splitlines()
                if "DualBrainRuntime.from_settings()" in ln]
        self.assertEqual(
            bare, [],
            "these roster reads bypass the pending-edit flush and will "
            "launch the previous model when an edit is still debounced "
            "(ARCH-ENG-153): " + "; ".join(bare))

    def test_the_helper_flushes_before_it_reads(self):
        """Ordering inside the helper: flush, then read."""
        src = self._src("gui/workers/provider_lifecycle_backend.py")
        start = src.find("def _runtime_from_settings(self):")
        end = src.find("\n    def ", start + 10)
        body = src[start:end if end > 0 else len(src)]
        flush = body.find("flush_pending_roster_edit")
        # Match the STATEMENT, not the docstring's mention of the old call.
        read = body.find("return DualBrainRuntime.from_settings()")
        self.assertGreater(flush, -1, "the helper no longer flushes pending edits")
        self.assertGreater(read, -1, "the helper no longer reads the roster")
        self.assertLess(
            flush, read,
            "the flush runs AFTER the read, so it cannot affect the config "
            "this launch uses (ARCH-ENG-153)")

    def test_the_read_side_call_sites_are_still_enumerated(self):
        """The set of guarded call sites must not shrink unnoticed."""
        src = self._src("gui/workers/provider_lifecycle_backend.py")
        n = src.count("self._runtime_from_settings()")
        self.assertEqual(
            n, 7,
            f"provider_lifecycle_backend.py has {n} guarded roster read "
            f"sites (was 7). If a call site was removed, confirm it is truly "
            f"gone; if one was added, route it through _runtime_from_settings "
            f"so it flushes first (ARCH-ENG-153).")

    def test_teardown_also_flushes_the_pending_roster_edit(self):
        """``DualBrainControl.cleanup()`` must flush before the loop stops.

        The launch read was the first read-side path; window close is the
        second, and it is the more damaging one — the edit is lost outright
        rather than applied late. The panel itself exposes no ``cleanup()``,
        so the owning control has to do it.
        """
        src = self._src("gui/widgets/dual_brain_control.py")
        start = src.find("def cleanup(self):")
        self.assertGreater(start, 0, "DualBrainControl.cleanup() is gone")
        end = src.find("\n    def ", start + 10)
        body = src[start:end if end > 0 else len(src)]
        self.assertIn(
            "flush_pending_roster_edit",
            body,
            "DualBrainControl.cleanup() no longer flushes the roster panel. "
            "Closing the window stops the event loop before the 400 ms "
            "debounce fires, so any edit made in the last moments is silently "
            "discarded on exit (ARCH-ENG-153).")
        # And it must be the FIRST thing cleanup does — a flush after the
        # worker joins would still race the same teardown.
        self.assertLess(
            body.find("flush_pending_roster_edit"),
            body.find("_status_timer", body.find("flush_pending_roster_edit")),
            "the roster flush happens after cleanup() starts stopping "
            "resources; move it to the top so the write cannot be pre-empted "
            "by teardown (ARCH-ENG-153)")


if __name__ == "__main__":
    unittest.main()
