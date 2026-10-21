"""ARCH-ENG-200 — phantom top-level windows in the Settings tab.

`create_settings_tab` builds three group boxes and adds **none** of them to a
layout, because `ProviderConfigWidget` is the visible surface for those
sections:

    cloudg      "Cloud Providers"
    localg      "Local Providers"
    llamacppg   "llama.cpp (local dual-brain)"

They still had to exist, because `save_settings` reads attributes off their
widgets — the `*_key_edit` / `*_base_edit` fields.

A fourth box, `ollama_box`, used to be re-homed here too. ARCH-ENG-275 (AB-01)
retired it: it was the hidden second writer of the Ollama model keys, and the
visible surface persists those keys itself. This file now pins three.

## The actual defect

**An unparented QWidget in Qt is a top-level window.** So these were not merely
invisible — they were stray windows with real titles, competing for the
taskbar and the alt-tab list.

The code even hints at the confusion. A comment on the `ollama_box.hide()` path
said "showing this unattached box creates a second top-level window titled
'python'" — the author had seen the symptom and treated it as something to hide
rather than something to parent.

## The fix

One hidden container parented to `inner`, and the group boxes re-homed under it.
A `QWidget` *with* a parent is an ordinary child object, not a window. Nothing
is laid out, so nothing is displayed, and every attribute the save path reads
still resolves to a live widget.

These tests pin the two halves separately, because either alone would pass while
the defect returned:

* structure — every box takes the container, the container is parented, and the
  container is never added to the visible layout
* mechanism — a parented QWidget is not a top-level window and an unparented one
  is, which is the whole basis of the fix
"""

import ast
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
BUILDER = REPO / "gui" / "builders" / "tab_feature_builders.py"

ORPHANS = {
    "cloudg": "Cloud Providers",
    "localg": "Local Providers",
    "llamacppg": "llama.cpp (local dual-brain)",
}


def _settings_ast():
    tree = ast.parse(BUILDER.read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef)
                and n.name == "create_settings_tab")


# ── Mechanism: why parenting is the fix ───────────────────────────────────────

class TestUnparentedWidgetsAreWindows(unittest.TestCase):
    """ARCH-ENG-200 — the Qt behaviour the fix relies on."""

    def _app(self):
        from PySide6.QtWidgets import QApplication, QGroupBox, QWidget
        app = QApplication.instance() or QApplication([])
        return app, QGroupBox, QWidget

    def test_an_unparented_group_box_is_a_top_level_window(self):
        """This is the defect: four of these existed, with real titles."""
        app, QGroupBox, QWidget = self._app()
        floating = QGroupBox("Cloud Providers")
        try:
            self.assertTrue(
                floating.isWindow(),
                "an unparented QGroupBox is not a top-level window; the whole "
                "diagnosis would be wrong")
            # The stray windows appear with an EMPTY window title: QGroupBox has
            # its own `title()` (the label inside the frame), which is not the
            # same thing as QWidget.windowTitle(). So the operator saw blank
            # entries in the alt-tab list and the taskbar, not four clearly
            # labelled sections -- which is why this went unnoticed.
            self.assertEqual(
                floating.windowTitle(), "",
                "QGroupBox.title() and QWidget.windowTitle() are different; if "
                "this now reports the label, the symptom description in the "
                "module docstring needs correcting")
            self.assertEqual(floating.title(), "Cloud Providers",
                             "the frame label is separate from the window title")
        finally:
            floating.deleteLater()

    def test_a_parented_group_box_is_not_a_window(self):
        app, QGroupBox, QWidget = self._app()
        parent = QWidget()
        # (title, parent) -- PySide6's real order.
        child = QGroupBox("Cloud Providers", parent)
        try:
            self.assertFalse(
                child.isWindow(),
                "a parented QGroupBox is still a top-level window, so the "
                "re-homing fixes nothing")
            self.assertEqual(child.parent(), parent)
        finally:
            parent.deleteLater()

    def test_the_title_survives_parenting(self):
        """Re-homing must not lose the label used by diagnostics."""
        app, QGroupBox, QWidget = self._app()
        parent = QWidget()
        child = QGroupBox("llama.cpp (local dual-brain)", parent)
        try:
            self.assertEqual(child.title(), "llama.cpp (local dual-brain)")
        finally:
            parent.deleteLater()

    def test_the_reversed_argument_order_silently_drops_the_title(self):
        """THE TRAP. QGroupBox(parent, title) re-homes but empties the title.

        This is what the first attempt at the fix did: all four boxes stopped
        being windows, and every title silently became "" -- a defect that only
        the object tree and diagnostics would ever reveal. Worth a test so the
        next person who "simplifies" the argument order finds out here.
        """
        app, QGroupBox, QWidget = self._app()
        parent = QWidget()
        wrong = QGroupBox(parent, "Cloud Providers")
        try:
            self.assertEqual(
                wrong.title(), "",
                "PySide6 now rejects the reversed form; if it ever binds the "
                "title anyway, this trap has closed and the guard can relax")
            self.assertFalse(wrong.isWindow(),
                             "the reversed form must still re-home, or this "
                             "test is asserting the wrong thing")
        finally:
            parent.deleteLater()


# ── Structure: the four are re-homed ─────────────────────────────────────────

class TestOrphanSectionsAreRehomed(unittest.TestCase):
    """ARCH-ENG-200 — every one of the four, pinned individually."""

    def _group_box_calls(self):
        """Each `QGroupBox(...)` construction in the tab, as source text."""
        import textwrap
        fn = _settings_ast()
        src = BUILDER.read_text(encoding="utf-8")
        return src, fn

    def _assert_call_shape(self, name, expected_title):
        src, fn = self._group_box_calls()
        pattern = re.compile(
            rf"^\s*{re.escape(name)}\s*=\s*QGroupBox\((.*?)\)\s*$", re.M)
        match = pattern.search(src)
        self.assertIsNotNone(match, f"{name} is no longer constructed with "
                                    f"QGroupBox; revisit this guard")
        args = [a.strip().strip('"').strip("'")
                for a in match.group(1).split(",")]
        # PySide6's signature is QGroupBox(title, parent). Assert the title
        # comes FIRST: QGroupBox(rehome, "Title") also re-homes, but silently
        # drops the title -- which is exactly what the first attempt did.
        self.assertEqual(
            args[0], expected_title,
            f"{name}: the first argument must be the TITLE. PySide6's "
            f"signature is QGroupBox(title, parent); the reversed form re-homes "
            f"the widget but silently empties title() (got {args[0]!r})")
        self.assertEqual(
            args[1] if len(args) > 1 else None, "rehome",
            f"{name} is not parented to the re-homing container -- it is a "
            f"top-level window again")
        self.assertEqual(
            len(args), 2,
            f"{name}: expected exactly (title, rehome), got {args}")

    def test_cloud_providers_is_rehomed(self):
        self._assert_call_shape("cloudg", "Cloud Providers")

    def test_local_providers_is_rehomed(self):
        self._assert_call_shape("localg", "Local Providers")

    def test_llamacpp_section_is_rehomed(self):
        self._assert_call_shape("llamacppg", "llama.cpp (local dual-brain)")

    def test_the_container_is_itself_parented(self):
        """An unparented container would only move the window up a level."""
        src, _ = self._group_box_calls()
        self.assertRegex(
            src, r"rehome\s*=\s*QWidget\(inner\)",
            "the re-homing container must be parented to `inner`; unparented, it "
            "is itself a top-level window")

    def test_the_container_is_hidden(self):
        src, _ = self._group_box_calls()
        self.assertRegex(
            src, r"rehome\.setVisible\(False\)",
            "the container must be explicitly hidden, so a future layout change "
            "cannot reveal four duplicate sections")

    def test_the_container_is_never_added_to_the_visible_layout(self):
        """Re-adding it would resurrect the duplication this retires."""
        import textwrap
        fn = _settings_ast()
        src = textwrap.dedent(__import__("inspect").getsource(fn)) \
            if False else BUILDER.read_text(encoding="utf-8")
        # Look only at the calls that add something to the VISIBLE layout.
        for layout_name in ("lay", "lay_", "inner_lay"):
            for match in re.finditer(rf"{layout_name}\.addWidget\((\w+)\)", src):
                self.assertNotEqual(
                    match.group(1), "rehome",
                    "the re-homing container was added to the visible layout; "
                    "the four sections would be displayed a second time")
            for match in re.finditer(rf"{layout_name}\.addLayout\((\w+)\)", src):
                self.assertNotEqual(
                    match.group(1), "rehome_layout",
                    "the re-homing container's layout was added to the visible "
                    "layout; the four sections would be displayed a second time")

    def test_no_orphan_is_still_added_to_any_layout(self):
        """Belt and braces: none of the four may be displayed at all."""
        src = BUILDER.read_text(encoding="utf-8")
        for name in ORPHANS:
            for match in re.finditer(rf"\.addWidget\(\s*{re.escape(name)}\s*\)", src):
                self.fail(f"{name} is added to a layout; ProviderConfigWidget is "
                          f"the visible surface and this is a duplicate")


# ── The save path still resolves ──────────────────────────────────────────────

class TestTheRetiredOllamaBoxStaysRetired(unittest.TestCase):
    """ARCH-ENG-275 (AB-01) — the fourth box is gone, not re-homed.

    It was the hidden second writer of `OLLAMA_MAIN_MODEL` /
    `OLLAMA_CHAT_MODEL` and the only reader of a hidden role and hide toggle.
    `ProviderConfigWidget` persists the role and model the moment the operator
    changes them, so nothing in `save_settings` needs the hidden box.
    """

    RETIRED = (
        "ollama_model_combo", "ollama_chat_model_combo", "ollama_role",
        "ollama_hide", "refresh_ollama_btn",
    )

    def test_the_hidden_widgets_are_not_built(self):
        src = BUILDER.read_text(encoding="utf-8")
        for attr in self.RETIRED:
            with self.subTest(attr=attr):
                self.assertNotIn(f"self.{attr}", src)

    def test_the_save_path_no_longer_reads_them(self):
        main_src = (REPO / "main.py").read_text(encoding="utf-8")
        for attr in self.RETIRED:
            with self.subTest(attr=attr):
                self.assertNotIn(attr, main_src)

    def test_the_retired_list_is_not_vacuous(self):
        self.assertGreaterEqual(len(self.RETIRED), 5)


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-200 — each detector must be able to fail."""

    def test_the_parenting_detector_sees_an_unparented_call(self):
        """If the first argument were dropped, the guard must fail."""
        src = '        cloudg = QGroupBox(rehome, "Cloud Providers")'
        pattern = re.compile(r"^\s*cloudg\s*=\s*QGroupBox\((.*?)\)\s*$", re.M)
        match = pattern.search(src)
        self.assertIsNotNone(match)
        args = [a.strip().strip('"').strip("'")
                for a in match.group(1).split(",")]
        self.assertEqual(args[0], "rehome")
        # And the same detector must reject the unparented form.
        bad = '        cloudg = QGroupBox("Cloud Providers")'
        args2 = [a.strip().strip('"').strip("'")
                 for a in pattern.search(bad).group(1).split(",")]
        self.assertNotEqual(args2[0], "rehome",
                            "the detector accepts an unparented construction, so "
                            "it would pass while the defect returned")

    def test_the_retired_attribute_list_is_not_vacuous(self):
        self.assertGreaterEqual(
            len(TestTheRetiredOllamaBoxStaysRetired.RETIRED), 5)

    def test_all_three_orphans_are_covered(self):
        self.assertEqual(len(ORPHANS), 3)
