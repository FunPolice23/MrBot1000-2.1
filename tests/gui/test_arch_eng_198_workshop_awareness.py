"""ARCH-ENG-198 — the workshop was built, gated, and never announced.

`agents/knowledge/workshop.py` is 889 lines: proposals, research, scripts,
applications, accounts, payment methods, deliverables, templates, notes, search
and summaries. It is exposed to the model as `workshop_read` / `workshop_list` /
`workshop_write` / `workshop_mkdir` / `workshop_storage`, the mutating tools are
gated behind `_require_mutation_capability` (ARCH-ENG-164/165), and
`workshop_read` is hardened against secret leakage (ARCH-ENG-134).

What it did not have was a single caller for `get_workspace_summary()`.

So the personas had no way to learn their workshop existed unless the operator
happened to ask. They would start a Live session, be asked to earn money, and
reason from an empty mental model — while several hundred megabytes of their own
prior work sat unused. At the time of writing the workshop held 369 skill files,
13 proposals, a research library, and a set of agent databases.

This is the same defect class as the stale caches fixed in v2.1.114: a thing that
exists, is correct, and is simply never mentioned.

## The framing is the load-bearing part

The block must say these are the operator's OWN prior artifacts and NOT verified
earnings. Without that, a summary listing 13 past proposals reads to a model as
13 completed and paid jobs — which is precisely the fabrication this project has
spent ARCH-ENG-056/102/110/158/173/180 closing from six different directions.

It must also say that reading and writing go through the approval-gated tools,
so the model does not conclude it can just write files.

## Budget and failure contract

Identical to `_build_opportunity_board`: bounded by whatever the elastic budget
leaves, never raises into the context builder, returns "" when the workshop is
unavailable. When the budget is tight the HEADER survives and the summary is
trimmed, because the framing is what prevents the misreading.
"""

import inspect
import pathlib
import textwrap
import types
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parents[2]


def _tab_cls():
    import agents.safety  # noqa: F401  (import-cycle order)
    from gui.tabs.dialogue_tab import DialogueTab
    return DialogueTab


def _stub(**attrs):
    return types.SimpleNamespace(**attrs)


SUMMARY = (
    "## \U0001F4C1 Workspace Summary\n"
    "- **proposals:** 13 files\n"
    "- **skills:** 369 files\n"
    "- **research:** 4 files\n"
    "\n**Accounts:** 2\n"
    "**Payment Methods:** 1"
)


class TestWorkshopIsAnnounced(unittest.TestCase):
    """ARCH-ENG-198 — the summary reaches the prompt."""

    def test_a_populated_workshop_produces_a_block(self):
        cls = _tab_cls()
        workshop = mock.Mock()
        workshop.get_workspace_summary.return_value = SUMMARY
        with mock.patch("agents.knowledge.workshop.get_workshop",
                        return_value=workshop):
            block = cls._build_workshop_summary(_stub(), 4000)
        self.assertIn("Workspace Summary", block)
        self.assertIn("proposals", block)

    def test_the_block_is_wired_into_the_context(self):
        """A correct function that nothing calls is the original defect."""
        src = inspect.getsource(_tab_cls())
        self.assertIn("self._build_workshop_summary(", src,
                      "the workshop summary is built but never added to the "
                      "prompt — the ARCH-ENG-198 defect, unchanged")
        self.assertIn("body = body + \"\\n\\n\" + workshop_block", src,
                      "the block is computed but not appended to the body")

    def test_it_sits_above_the_mandatory_tail(self):
        """Otherwise a long workshop could evict the injection guards.

        The real invariant is not textual adjacency: `tail` is CONSTRUCTED before
        any elastic block is added, and the function returns `body + tail`. So no
        amount of body -- board, plan, or workshop -- can displace it.

        The first draft searched for the guard's NAME after the workshop call,
        which cannot work: `untrusted_pages_guard` is defined earlier, so the
        assertion was unanswerable rather than merely failing.
        """
        src = inspect.getsource(_tab_cls().get_dialogue_context)
        tail_built = src.index("tail = ")
        workshop_at = src.index("_build_workshop_summary")
        self.assertLess(
            tail_built, workshop_at,
            "the mandatory tail must be built before the elastic blocks are "
            "added, or a long workshop could displace the injection guards")
        self.assertRegex(
            src, r"return body \+ tail",
            "the prompt must be assembled as body + tail, so the guards always "
            "survive however large the elastic blocks grow")

    def test_an_unavailable_workshop_is_silent(self):
        """A missing workshop must never break a turn."""
        cls = _tab_cls()
        with mock.patch("agents.knowledge.workshop.get_workshop",
                        side_effect=RuntimeError("no workshop")):
            self.assertEqual(cls._build_workshop_summary(_stub(), 4000), "")

    def test_an_empty_workshop_is_silent(self):
        cls = _tab_cls()
        with mock.patch("agents.knowledge.workshop.get_workshop") as gw:
            gw.return_value.get_workspace_summary.return_value = "   "
            self.assertEqual(cls._build_workshop_summary(_stub(), 4000), "")

    def test_zero_budget_yields_nothing(self):
        cls = _tab_cls()
        with mock.patch("agents.knowledge.workshop.get_workshop") as gw:
            gw.return_value.get_workspace_summary.return_value = SUMMARY
            self.assertEqual(cls._build_workshop_summary(_stub(), 0), "")
            self.assertEqual(cls._build_workshop_summary(_stub(), -5), "")


class TestFramingPreventsTheFabrication(unittest.TestCase):
    """ARCH-ENG-198 — 13 past proposals must not read as 13 paid jobs."""

    def _block(self, budget=4000):
        cls = _tab_cls()
        with mock.patch("agents.knowledge.workshop.get_workshop") as gw:
            gw.return_value.get_workspace_summary.return_value = SUMMARY
            return cls._build_workshop_summary(_stub(), budget)

    def test_it_says_not_verified_earnings(self):
        block = self._block()
        self.assertIn("NOT verified earnings", block,
                      "without this the summary reads as completed income")

    def test_it_marks_the_material_as_the_operators_own(self):
        self.assertIn("your own prior work", self._block())

    def test_it_says_a_prior_file_is_not_evidence_of_acceptance(self):
        self.assertRegex(
            self._block(), r"not evidence",
            "a file the personas wrote earlier must not be presented as proof a "
            "client accepted it")

    def test_it_points_at_the_gated_tools(self):
        block = self._block()
        self.assertIn("workshop_read", block)
        self.assertIn("approval-gated", block,
                      "the model must not conclude it can simply write files")

    def test_the_header_survives_a_tight_budget(self):
        """The framing is trimmed last; the summary is trimmed first."""
        block = self._block(budget=320)
        self.assertIn("NOT verified earnings", block,
                      "a tight budget trimmed away the honesty framing and left "
                      "a bare list of proposals, which reads as completed work")
        self.assertLessEqual(len(block), 320 + 80,
                             f"block is {len(block)} chars against a 320 budget")

    def test_a_bare_file_list_would_be_the_defect(self):
        """Anti-vacuity: prove the framing is doing real work here."""
        bare = "## YOUR WORKSHOP\n- proposals: 13 files"
        self.assertNotIn("NOT verified earnings", bare)
        self.assertNotIn("not evidence", bare,
                         "the unframed version carries neither guard, so the "
                         "framing assertions above are not vacuous")


class TestItStaysCheap(unittest.TestCase):
    """ARCH-ENG-198 — a per-turn context block must not walk the whole tree."""

    def test_the_summary_does_not_use_the_full_tree_walk(self):
        """`get_stats` is os.listdir per category; `_usage_bytes` is rglob over
        every file. Only the former is safe to call once per turn."""
        src = (REPO / "agents" / "knowledge" / "workshop.py").read_text(
            encoding="utf-8")
        stats_at = src.index("def get_stats")
        stats_body = src[stats_at:src.index("def get_workspace_summary")]
        self.assertNotIn("rglob", stats_body,
                         "get_stats now walks the whole tree; calling it per "
                         "turn would stat every workshop file on the GUI thread")
        self.assertIn("os.listdir", stats_body)

    def test_it_does_not_pull_in_the_storage_scan(self):
        src = (REPO / "agents" / "knowledge" / "workshop.py").read_text(
            encoding="utf-8")
        summary_at = src.index("def get_workspace_summary")
        body = src[summary_at:summary_at + 900]
        self.assertNotIn("storage_stats", body,
                         "the workspace summary must not trigger a full-tree "
                         "byte-count scan on every dialogue turn")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-198 — each detector must be able to fail."""

    def test_the_wiring_detector_sees_an_unwired_builder(self):
        """If the append line were gone, the wiring test must fail."""
        src = inspect.getsource(_tab_cls())
        self.assertIn("_build_workshop_summary", src)
        # Removing the append would leave the definition present but unused.
        import ast
        # `inspect.getsource` on a METHOD returns it still indented by its class
        # body, which `ast.parse` rejects. `textwrap.dedent` first -- the same
        # step every structural guard in this repo needs.
        tree = ast.parse(textwrap.dedent(
            inspect.getsource(_tab_cls().get_dialogue_context)))
        calls = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "_build_workshop_summary"
        ]
        self.assertEqual(len(calls), 1,
                         "expected exactly one call site in the context builder")

    def test_the_workshop_really_exists_and_is_populated_in_this_repo(self):
        """If workshop.py were gone, the whole concern would be moot."""
        path = REPO / "agents" / "knowledge" / "workshop.py"
        self.assertTrue(path.exists())
        src = path.read_text(encoding="utf-8")
        for name in ("def create_proposal", "def add_research", "def add_note",
                     "def get_workspace_summary"):
            self.assertIn(name, src,
                          f"workshop.{name} is gone; the awareness ticket's "
                          f"premise no longer holds")

    def test_the_summary_fixture_looks_like_real_workshop_output(self):
        self.assertIn("proposals", SUMMARY)
        self.assertIn("skills", SUMMARY)
