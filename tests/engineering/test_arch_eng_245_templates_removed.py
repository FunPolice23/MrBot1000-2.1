"""ARCH-ENG-245 / AY-02 -- the workshop template subsystem stays deleted.

The finding (11G)
-----------------
The template subsystem was entirely dead, and not merely unused -- the pair
was never a feature. Two half-mechanisms that did not touch:

- ``get_template`` (workshop.py:728, 80 lines -- the largest dead method in
  the depth pass) returned one of FOUR HARDCODED skeleton strings
  (proposal / application / research_note / invoice) from an in-memory dict,
  and never read the workshop's ``templates/`` directory;
- ``save_template`` (workshop.py:809) wrote ``templates/template_<n>.md``
  files that NOTHING could ever read back -- not get_template, not any tool,
  not any GUI surface. A saved template was unreadable by construction.

Nothing wrote a template and nothing read one (22 dead of 52 methods). At
every ``Workshop.__init__``, the PATHS registry made ``os.makedirs`` create
an empty ``templates/`` directory on the operator's disk, indefinitely, for
no writer and no reader.

Why delete rather than wire (the operator's rule: delete if superseded or
better exists, wire otherwise -- verified):
- Better code exists for the load-bearing use. Proposal copy is served by
  ``agents/knowledge/proposal_templates.py`` -- the LIVE A/B intro-rotation
  mechanism with win-rate biasing (``pick_intro``/``record_win``), wired at
  ``agents/earning/proposal.py`` -- which is strictly better than a static
  proposal skeleton: it learns which copy wins instead of repeating one.
- ``workflow_planner.py`` claimed the "steps per platform" domain but was
  never imported by anything; its only consumer was a dead
  `build_workflow_plan` accessor, and the module was deleted with it
  (ARCH-ENG-254, W-04).
- Document skeletons (application / research_note / invoice) are what an
  LLM persona generates natively; a hardcoded [PLACEHOLDER] scaffold
  competes with, not complements, model output.

Executable record (AY-04's own concern -- "a deletion with no executable
check is a claim"): these tests pin the removal so the next audit cannot
recount the subsystem as a live surface, and pin the behavioral residue --
no Workshop init creates an empty templates/ directory, forever.
"""

import ast
import pathlib
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
WORKSHOP = REPO / "agents" / "knowledge" / "workshop.py"
PROPOSAL_TEMPLATES = REPO / "agents" / "knowledge" / "proposal_templates.py"
PROPOSAL = REPO / "agents" / "earning" / "proposal.py"


class TheDeletionHolds(unittest.TestCase):

    def test_the_subsystem_is_gone(self):
        src = WORKSHOP.read_text(encoding="utf-8")
        tree = ast.parse(src)
        cls = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.ClassDef) and n.name == "Workshop")
        methods = {m.name for m in cls.body if isinstance(m, ast.FunctionDef)}
        self.assertNotIn("get_template", methods)
        self.assertNotIn("save_template", methods)

    def test_the_registry_stops_mkdir_an_empty_directory(self):
        """The deleted subsystem's real residue: PATHS made every Workshop
        init create templates/ on the operator's disk for no reader."""
        src = WORKSHOP.read_text(encoding="utf-8")
        tree = ast.parse(src)
        registry_keys = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "PATHS"
                            for t in node.targets)
                    and isinstance(node.value, ast.Dict)):
                registry_keys = [
                    k.value for k in node.value.keys
                    if isinstance(k, ast.Constant)
                ]
        self.assertIsNotNone(registry_keys, "PATHS registry must exist")
        self.assertNotIn("templates", registry_keys,
                         "the removed category cannot be re-registered"
                         " (comments explaining the removal are fine; a"
                         " live key is not)")

        import os
        root = tempfile.mkdtemp(prefix="ws245_")
        from agents.knowledge.workshop import Workshop
        ws = Workshop(root)
        self.assertNotIn("templates", ws.paths)
        self.assertFalse(
            os.path.isdir(os.path.join(root, "templates")),
            "init must not create a directory no code writes or reads")

    def test_the_replacement_is_live_and_registered(self):
        """Better code exists AND is actually wired -- the deleting this
        asserts is a superseding, not a regression of capability."""
        import agents.knowledge.proposal_templates as pt
        for fn in ("pick_intro", "record_win", "best_intro"):
            self.assertTrue(callable(getattr(pt, fn, None)))
        proposal_src = PROPOSAL.read_text(encoding="utf-8")
        self.assertIn("proposal_templates", proposal_src,
                      "the live A/B mechanism must remain wired"
                      " (proposal.py imports pick_intro)")


if __name__ == "__main__":
    unittest.main()
