"""ARCH-ENG-318 -- the Settings tab must build without a NameError.

The finding
-----------
ARCH-ENG-203 removed the local `_env_bool` parser from the settings builders
and re-seeded the reads on `app.effects.env_bool` (now the ONE canonical
parser). The delegation import was added function-locally to
`create_settings_tab` and `_build_provider_sections` -- but
`_build_appearance_group` also parses `MRBOT_FX_COMPACT_DENSITY` /
`MRBOT_FX_ROUNDED_CORNERS` through `_env_bool`, and a function-scoped import
in a *sibling* method is invisible to it. Building the Settings tab then died
with ``NameError: name '_env_bool' is not defined``; the tab-build failure
path caught it and rendered the "could not be initialized" error widget, so
the operator had no Settings tab at all.

Fix: `_build_appearance_group` imports `env_bool as _env_bool` the same way
its sibling sections do.

Regression: this test builds the REAL Settings tab offscreen (not an AST
scan -- the 203 tests already pin that, and AST missed this because the scan
looked for calls, not unresolved names). A harness subclass auto-stubs the
window-level callbacks with mocks; only data-carrying widgets are real.
"""

import ast
import unittest
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]

qt_available = True
try:
    from PySide6.QtWidgets import QLabel  # noqa: F401
except Exception:  # pragma: no cover - headless CI without Qt
    qt_available = False


@unittest.skipUnless(qt_available, "PySide6 unavailable")
class TestArchEng318SettingsTabBuilds(unittest.TestCase):

    def test_appearance_group_has_the_canonical_parse_import(self):
        """The UnresolvedName is exactly what bit the operator: without the
        import, executing _build_appearance_group raises NameError before any
        widget exists."""
        src = (REPO / "gui" / "builders" / "tab_feature_builders.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_build_appearance_group":
                local_imports = [
                    n for n in ast.walk(node)
                    if (isinstance(n, ast.ImportFrom) and n.module == "app.effects"
                        and any(a.asname == "_env_bool" for a in n.names))
                ]
                self.assertTrue(
                    local_imports,
                    "_build_appearance_group reads _env_bool but never imports "
                    "it -- building the Settings tab raises NameError "
                    "(ARCH-ENG-318)")
                uses = [
                    n for n in ast.walk(node)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "_env_bool"
                ]
                self.assertTrue(uses, "expected the MRBOT_FX_* reads")

    def test_real_settings_tab_builds_offscreen(self):
        """Behavioral pin: the whole Settings tab constructs, and the FX
        checkboxes round-trip the canonical parser."""
        from unittest.mock import Mock, patch

        from gui.builders.tab_builders import TabBuildersMixin

        class Harness(TabBuildersMixin):
            def __getattr__(self, name):
                m = Mock(name=name)
                setattr(self, name, m)
                return m

        from PySide6.QtWidgets import QLabel

        h = Harness()
        h.THEMES = {"Dark": {}, "Light": {}}
        h.status_label = QLabel()
        # The FX checkboxes read the operator env; clear the two keys so the
        # documented defaults are exercised deterministically.
        with patch.dict("os.environ", {"MRBOT_FX_COMPACT_DENSITY": "",
                                       "MRBOT_FX_ROUNDED_CORNERS": ""}):
            tab = h.create_settings_tab()
            self.assertIsNotNone(tab)
            self.assertFalse(h.fx_compact.isChecked())   # default False via env_bool
            self.assertTrue(h.fx_rounded.isChecked())    # default True via env_bool
        self.assertTrue(h.llamacpp_big_enabled.isChecked())
        self.assertTrue(h.llamacpp_small_enabled.isChecked())

    def test_module_has_no_global_env_bool_alias(self):
        """Every function that calls _env_bool/env_bool must be able to see an
        import in its own scope OR an enclosing function's scope (closures).
        This is precisely the shape of the 318 defect: the call was legal
        syntax in _build_appearance_group, but the only sibling import was in
        a DIFFERENT function, so Python raised NameError at build time."""
        src = (REPO / "gui" / "builders" / "tab_feature_builders.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)

        def callers(fn):
            return {n.func.id for n in ast.walk(fn)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id in ("_env_bool", "env_bool")}

        def own_import(fn):
            return any(
                isinstance(n, (ast.Import, ast.ImportFrom))
                and any(a.name == "env_bool"
                        and a.asname in (None, "env_bool", "_env_bool")
                        for a in getattr(n, "names", []))
                for n in ast.walk(fn))

        # Walk (function, enclosing-function-stack); the import is visible if
        # any scope in the chain has it.
        def visit(node, chain):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.FunctionDef):
                    if callers(child) and not any(own_import(f) for f in chain + [child]):
                        self.fail(
                            f"{child.name} uses env_bool/_env_bool without an "
                            "import in its own or an enclosing scope -- "
                            "NameError at build time (ARCH-ENG-318)")
                    visit(child, chain + [child])
                else:
                    visit(child, chain)

        visit(tree, [])


if __name__ == "__main__":
    unittest.main()
