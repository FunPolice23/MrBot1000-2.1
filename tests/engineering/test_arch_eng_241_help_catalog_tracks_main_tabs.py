"""ARCH-ENG-241 / BC-01 -- a hand-maintained mirror needs an executable check.

The finding
-----------
``help_catalog.FEATURES`` is a hand-maintained transcription of the UI, and
the depth pass measured it drifted: the real `tab_specs` in ``main.py`` has
24 labels, while the catalog described 10 -- one of them WRONG ("Browse Root
/ file browser tab"; the real tab is "Web Browser") and 14 simply ABSENT
(Model Library, Approvals, Registration, Insights, Opportunities, Social
Activity, Self-Improvement, Autonomous Learning, Live Portfolio, Strategy
Simulator, Analytics, Reputation, Data Explorer). The docstring's grounding
list cited four files that do not exist (`gui/tab_builders.py`,
`gui/chat_tab.py`, `gui/model_switcher.py`, `agents/personas.py`). There
were ZERO tests referencing the catalog, so the docstring's "Every entry is
grounded in the real code" was an assertion, not a check -- the shape 11G's
AY-04 named for deletions ("a deletion with no executable check is a claim,
not a change"), applied to a mirror: *a hand-maintained mirror with no
executable check is a claim, not a mirror.*

The fix: the wrong entry corrected, all 24 real tabs covered (the optional
ones each NAME their canonical feature env key, since an operator reading
help against a hidden tab is exactly who this artifact serves), the
grounding citations repaired, and this test -- which parses main.py's
`tab_specs`/`optional_tabs` as ground truth and fails on any drift.

The importability contract is preserved and asserted: help_catalog stays
stdlib-only, importable without Qt (the help panel's standalone point).

Vacuity: against the pre-fix catalog, the coverage assertions fail on the
14 absent tabs (and the stale "Browse Root" name), and the citation scan
fails while the phantom paths are cited.
"""

import ast
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]

MAIN = REPO / "main.py"
CATALOG = REPO / "agents" / "knowledge" / "help_catalog.py"

import agents.knowledge.help_catalog as hc


def _tab_labels():
    """Parse main.py's tab_specs labels via AST (no Qt import)."""
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    labels = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "tab_specs"
                for t in node.targets):
            for elt in node.value.elts:
                labels.append(elt.elts[0].value)
            break
    else:
        raise AssertionError("tab_specs assignment not found in main.py")
    return labels


def _optional_tabs():
    """Parse main.py's optional_tabs mapping: label -> feature name."""
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "optional_tabs"
                for t in node.targets):
            return {k.value: v.value
                    for k, v in zip(node.value.keys, node.value.values)}
    return {}


def _env_for_feature(feature):
    from agents.core.feature_flags import feature_env_key
    return feature_env_key(feature)


class TheCatalogCoversEveryRealTab(unittest.TestCase):

    def _covered(self, label):
        """An entry documents the tab if the label appears as the entry's
        category, or inside its feature name."""
        for entry in hc.FEATURES:
            if label.lower() in (entry["category"].lower(),
                                 entry["feature"].lower()):
                return entry
        return None

    def test_every_tab_label_is_described(self):
        for label in _tab_labels():
            self.assertIsNotNone(
                self._covered(label),
                f"main.py tab_specs label {label!r} has no catalog entry "
                f"-- the help surface went silent about a real tab")

    def test_the_deprecated_tab_name_is_gone(self):
        text = CATALOG.read_text(encoding="utf-8")
        self.assertNotIn(
            '"Browse Root"', text,
            "the recorded drift: the real tab was always named 'Web "
            "Browser' (main.py tab_specs); a catalog may not invent names")

    def test_optional_tabs_name_their_env_key(self):
        """A tab hidden behind a flag is where an operator most often needs
        help; those entries must SAY which env key shows it."""
        optional = _optional_tabs()
        self.assertTrue(optional, "optional_tabs not parsed")
        for label, feature in optional.items():
            entry = self._covered(label)
            if entry is None:
                continue  # covered-by-all-tabs test reports the gap
            env_key = _env_for_feature(feature)
            self.assertIn(
                env_key, entry["description"],
                f"the {label!r} entry must name its gate "
                f"({env_key}); an operator cannot else tell why "
                f"the tab is hidden")

    def test_grounding_citations_are_real_paths(self):
        """The docstring claims 'Every entry is grounded in the real code'
        -- its own citations must survive `git ls-files`."""
        text = CATALOG.read_text(encoding="utf-8")
        for phantom in ("gui/tab_builders.py", "gui/chat_tab.py",
                        "gui/model_switcher.py", "agents/personas.py"):
            self.assertNotIn(
                phantom, text,
                f"the grounding list cites {phantom}, which does not exist")
        for real in ("agents/cognition/personas.py",
                     "gui/builders/tab_feature_builders.py",
                     "gui/tabs/chat_tab.py"):
            self.assertIn(
                real, text,
                f"the grounding list must cite the real path {real}")


class TheCatalogStaysImportableStandalone(unittest.TestCase):
    """The module's own contract: stdlib only, no Qt, no gui/ imports. The
    help panel's honest-failure mode (it reports 'could not load') relies on
    the import succeeding independently of Qt."""

    def test_only_stdlib_imports(self):
        tree = ast.parse(CATALOG.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertTrue(
                        alias.name.startswith("typing"),
                        f"non-stdlib import at line {node.lineno}: "
                        f"{alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                self.assertIn(
                    node.module, ("typing", "__future__"),
                    f"non-stdlib import at line {node.lineno}: {node.module}")

    def test_lookup_never_raises_and_always_returns_a_list(self):
        for kw in (None, "", "   ", "gpu", "OOOOO_not_a_feature"):
            result = hc.lookup(kw)
            self.assertIsInstance(result, list)
            self.assertLessEqual(len(result), len(hc.FEATURES))

    def test_catalog_text_is_renderable(self):
        text = hc.catalog_text()
        self.assertGreater(len(text), len(hc.FEATURES) * 10)
        self.assertIn("Web Browser", text)


if __name__ == "__main__":
    unittest.main()
