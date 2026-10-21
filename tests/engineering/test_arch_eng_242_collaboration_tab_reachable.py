"""ARCH-ENG-242 / AW-01 -- the Collaboration / Run Monitor tab is reachable.

The finding
-----------
``create_collaboration_tab`` (gui/builders/tab_feature_builders.py:226,
41 lines) builds and wires ``gui/tabs/collaboration_tab.CollaborationTab``
-- a whole panel class wired to the shared ``DualBrainCoordinator`` -- but
was never listed in ``main.py``'s ``tab_specs`` and had no other production
caller. Only ``tests/gui/test_gui_smoke.py:321`` asserted the builder
*exists*. Everything its docstring promised (shared ledger so Chat,
Dialogue and the monitor observe the same collaboration; a down server
degrading to a FAILED run, never blocking) was unreachable. The bidirectional
goal bridges ("_bridge_goal_to_dialogue" / "_bridge_goal_to_collaboration")
sat complete and dead on both sides.

This is 10s's R-01 narrowed by history: the OTHER unwired tab it found
(diagnostics) was resolved deliberately -- the surface moved into DB Stats
and ``create_diagnostics_tab`` is a documented backward-compat shim (11D).
Collaboration got neither wiring nor a disposition, so the fix is the one
its design always had in place: wire it into ``tab_specs`` (label
"Collaboration", placed after Dialogue) and let the ARCH-ENG-241 catalog
drift-check see it.

Vacuity: against pre-fix ``main.py``, the wiring assertions fail (the
builder is defined but no spec line constructs it).
"""

import ast
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]

MAIN = REPO / "main.py"
BUILDERS = REPO / "gui" / "builders" / "tab_feature_builders.py"
COLLAB_TAB = REPO / "gui" / "tabs" / "collaboration_tab.py"


import agents.knowledge.help_catalog as hc


def _tab_specs():
    """Parse main.py's tab_specs as (label, builder_name) pairs."""
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    specs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "tab_specs"
                for t in node.targets):
            for elt in node.value.elts:
                label = elt.elts[0].value
                call = elt.elts[1]
                specs.append((label, call.attr))
            break
    else:
        raise AssertionError("tab_specs assignment not found in main.py")
    return specs


class TheCollaborationTabIsReachable(unittest.TestCase):

    def test_a_tab_spec_builds_the_collaboration_tab(self):
        builders = [builder for _label, builder in _tab_specs()]
        self.assertIn(
            "create_collaboration_tab", builders,
            "create_collaboration_tab is defined but no tab_spec "
            "constructs it -- an unreachable panel (AW-01)")

    def test_the_label_matches_the_builder_name(self):
        for label, builder in _tab_specs():
            if builder == "create_collaboration_tab":
                self.assertEqual(
                    label, "Collaboration",
                    "the tab label must name the collaboration surface")

    def test_the_builder_loops_nothing_but_the_tab(self):
        """The builder must still construct CollaborationTab and keep both
        direction of the goal bridge wired at build time."""
        src = BUILDERS.read_text(encoding="utf-8")
        self.assertIn("CollaborationTab(", src)
        self.assertIn("goal_changed.connect(self._bridge_goal_to_dialogue)", src)
        self.assertIn("def _bridge_goal_to_collaboration", src)
        self.assertIn("def _bridge_goal_to_dialogue", src)

    def test_the_panel_source_exists(self):
        src = COLLAB_TAB.read_text(encoding="utf-8")
        self.assertIn("class CollaborationTab", src)
        self.assertIn("goal_input", src)


class TheCatalogSeesTheWiredTab(unittest.TestCase):
    """ARCH-ENG-241 made the catalog's coverage executable; wiring a new tab
    must immediately extend it. This class is the drift-check doing its job
    on the very next change."""

    def test_catalog_describes_collaboration(self):
        matches = [e for e in hc.FEATURES
                   if "Collaboration" in (e["category"], e["feature"])]
        self.assertTrue(
            matches,
            "a real tab wired into tab_specs must gain a catalog entry")
        for entry in matches:
            self.assertIn("DualBrainCoordinator", entry["description"],
                          "the entry must describe the wired coordinator")

    def test_lookup_finds_it(self):
        self.assertTrue(hc.lookup("Collaboration"))
        self.assertTrue(hc.lookup("run monitor"))


if __name__ == "__main__":
    unittest.main()
