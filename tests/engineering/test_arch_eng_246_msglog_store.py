"""ARCH-ENG-246 / 11G's AY-04 lesson applied to a NEW store -- the
Collaboration tab's message log must not live in the source tree.

The finding
-----------
ARCH-ENG-242 made the Collaboration tab a real tab (11Q's wiring fix), and
the tab's construction path built its MessageLog path from ``__file__``:
``gui/dual_brain_messages.db``. The first time the GUI was built -- the very
first smoke/full-window test run -- a live SQLite store appeared inside the
checkout. ARCH-ENG-167's root-hygiene audit existed for exactly this and
caught it: three governed tests failed on the undeclared store
(``discover_undeclared_stores`` -> ``gui\\dual_brain_messages.db``).

The fix keeps the ARCH-ENG-167 contract intact rather than declaring the
store: every persistent store in this tree lives under the app-data
directory (``%LOCALAPPDATA%\\MrBot1000\\`` beside goals.db and the event
log), never in the source tree. The path is now a module-level helper so
the property is checkable -- a path computed inline from ``__file__`` is not
reachable from a test without building the whole GUI.

Vacuity: against the pre-fix source the scan fails (the ``__file__``-based
join is present) and the behavioral check fails (the helper does not exist;
the old expression resolves inside the repo).
"""

import ast
import pathlib
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parents[2]
BUILDERS = REPO / "gui" / "builders" / "tab_feature_builders.py"


class TheStoreLeavesTheSourceTree(unittest.TestCase):

    def test_no_store_path_is_computed_from_file(self):
        """A store path may not be built from __file__ (that is how the
        source tree became a data directory the first time)."""
        tree = ast.parse(BUILDERS.read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "join"
                    and node.args
                    and isinstance(node.args[-1], ast.Constant)
                    and node.args[-1].value == "dual_brain_messages.db"):
                src = ast.unparse(node)
                if "__file__" in src:
                    offenders.append(f"line {node.lineno}: {src[:90]}")
        self.assertEqual(
            offenders, [],
            "the message-log path is computed inside the source tree: "
            + "; ".join(offenders))

    def test_the_helper_lands_in_app_data(self):
        from gui.builders.tab_feature_builders import _dual_brain_message_log_path
        with mock.patch.dict(
                "os.environ", {"LOCALAPPDATA": r"C:\fake\appdata"}, clear=False):
            path = _dual_brain_message_log_path()
        norm = path.replace("/", "\\").lower()
        self.assertIn(r"\mrbot1000\dual_brain_messages.db", norm)
        self.assertNotIn(
            str(REPO).replace("/", "\\").lower(), norm,
            "the store must not be inside the checkout")

    def test_the_root_hygiene_audit_sees_no_undeclared_store(self):
        """The audit that caught this stays the authority: the tree must
        report zero undeclared stores (no new exemption declared)."""
        from agents.core.persistence_contract import discover_undeclared_stores
        found = discover_undeclared_stores(REPO)
        self.assertEqual(found, {},
                         f"undeclared stores in the source tree: {found}")


if __name__ == "__main__":
    unittest.main()
