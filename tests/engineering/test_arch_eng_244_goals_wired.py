"""ARCH-ENG-244 / BF-01 + BF-02 -- GoalTracker is live, guarded, and visible.

The finding
-----------
The ENTIRE ``GoalTracker`` (20 methods) was unreachable: zero external
references, only its smoke-test ``hasattr``. Worse, the one place that
guarded a credit (``add_evidence``: verified AND amount > 0 before
incrementing ``current_usd``) was dead, while the method that DID increment
(``add_earnings``) claimed "verified" in its docstring and had no guard in
its body -- the guard and the unguarded copy of the same money statement
sat 35 lines apart (11Q). And the event seam BF-03 recorded: ``process_event``
read details["amount_usd"] and event types ('earning.freelance', ...) that
no production code ever emitted -- AUTO-MATCHING goals onto events by a
vocabulary that never existed.

Operator disposition: FULL WIRING. The pieces, in dependency order:

1. BF-02 fixed first (11Q's own sequence rule): ``add_earnings`` DELETED.
   ``add_evidence`` is the single credit path and keeps its guard -- a
   credit exists if and only if an evidence row is verified and its amount
   is positive.
2. process_event rewritten to the REAL production contract (ARCH-ENG-243's
   typed earning event: event_type "earning", details
   revenue/platform/action "finalized:<state>", revenue being the
   lifecycle's VERIFIED-EFFECTIVE value). ``_auto_match_event`` deleted --
   the tracker now refuses to guess what an unbound amount belongs to.
   Credits bind through an explicit details["goal_id"/"goal:" tag], or the
   operator-declared metadata.platforms on a goal; a paid finalize on a
   declared platform credits the first active goal that declared it. Non-
   paid states are RECORDED as evidence rows (verified=False) and never
   move money; a "paid" state with revenue 0 (the ledger refused it)
   cannot credit a cent.
3. main.py's event-logger hook (_on_event_logged) forwards every event to
   GoalTracker.instance().process_event -- the same seam that feeds the
   alert engine. Guarded: telemetry-side failures cannot break logging.
4. The Management tab's Earning Goals card is the operator surface the
   class never had: create (title/path/target/platforms), pause/resume,
   delete, and a live progress table backed by tracker.summary(). Goals
   are visible, and credits arrive automatically without the operator
   ever editing a row.

Vacuity: against the pre-fix sources, the source scans fail (add_earnings
present, auto-match present, no bridge, no card); the behavioral card test
fails because there is no goals table at all.
"""

import ast
import pathlib
import os
import tempfile
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parents[2]

GOAL_SYSTEM = REPO / "agents" / "earning" / "goal_system.py"
MAIN = REPO / "main.py"
MANAGEMENT = REPO / "gui" / "tabs" / "management_tab.py"
CATALOG = REPO / "agents" / "knowledge" / "help_catalog.py"


def _src(path):
    return path.read_text(encoding="utf-8")


class TheSingleCreditPath(unittest.TestCase):

    def test_add_earnings_is_gone(self):
        """BF-02: the unguarded duplicate cannot return; its docstring's
        claim ("verified") has one guarded owner now."""
        src = _src(GOAL_SYSTEM)
        self.assertNotIn("def add_earnings", src)
        tree = ast.parse(src)
        names = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn("add_earnings", names,
                         "no caller may resurrect the unguarded path")

    def test_the_guard_is_anchored_in_add_evidence(self):
        src = _src(GOAL_SYSTEM)
        start = src.index("def add_evidence")
        body = src[start:src.index("def list_evidence")]
        self.assertIn("if evidence.verified and evidence.amount_usd > 0", body,
                      "the one money decision must stay in the one place")

    def test_the_unguarded_credit_cannot_be_reached_by_event_either(self):
        """process_event credits only through add_evidence."""
        src = _src(GOAL_SYSTEM)
        start = src.index("def process_event")
        body = src[start:src.index("def _row_to_goal")]
        self.assertIn("add_evidence", body,
                      "the event path must go through the single guard")
        self.assertNotIn("current_usd = current_usd", body,
                         "process_event must not carry its own SQL increment")


class TheRealEventContract(unittest.TestCase):

    def test_auto_match_is_deleted(self):
        """The invented vocabulary ('earning.freelance', amount_usd) keyed
        events that never existed; a tracker that credits on it would be
        crediting on a fiction."""
        self.assertNotIn("_auto_match_event", _src(GOAL_SYSTEM))

    def test_process_event_reads_the_live_stream(self):
        src = _src(GOAL_SYSTEM)
        start = src.index("def process_event")
        body = src[start:src.index("def _row_to_goal")]
        for token in ("event_type', '') != 'earning'",
                      "details.get('revenue'", "finalized:"):
            self.assertIn(token, body)
        # The dead event vocabulary must not survive in EXECUTABLE code:
        # string constants anywhere (dict keys, emitted event names) that
        # name the invented event types are a resurrection of auto-match.
        # Docstrings are excluded -- the real contract's own docstring
        # quotes the dead names as history.
        tree = ast.parse(src)
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
                first = node.body[0] if node.body else None
                if (isinstance(first, ast.Expr)
                        and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    docstrings.add(id(first.value))
        literals = [
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in docstrings
        ]
        for dead in ("earning.freelance", "earning.microtask",
                     "payment.received"):
            self.assertNotIn(
                dead, "\x00".join(literals),
                f"dead vocabulary '{dead}' cannot appear in executable code")

    def test_uncertainty_never_becomes_a_credit(self):
        """Non-paid states and refused payments are recorded, credited
        never; the wording must say so where the money moves."""
        src = _src(GOAL_SYSTEM)
        self.assertIn("the tracker does NOT guess", src)


class TheSeamIsWired(unittest.TestCase):

    def test_main_forwards_events_to_the_tracker(self):
        tree = ast.parse(_src(MAIN))
        hit = False
        for node in ast.walk(tree):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "_on_event_logged"):
                body = ast.get_source_segment(_src(MAIN), node) or ""
                hit = ("GoalTracker" in body
                       and "process_event" in body
                       and "_on_event_logged" in body)
                # and it must be guarded like the alerting feed beside it
                self.assertIn("except Exception", body,
                              "a tracker failure must not break the log path")
        self.assertTrue(hit, "main.py's event hook must feed GoalTracker")

    def test_event_logger_helper_is_the_producer_this_consumes(self):
        """Guarded coupling: process_event expects ARCH-ENG-243's contract;
        if the emitter's shape drifts, this test and the emitter's own
        tests must both fail."""
        src = _src(REPO / "agents" / "core" / "event_logger.py")
        start = src.index("def earning_event")
        body = src[start:src.index("def safety_event")]
        for key in ("revenue", "platform", "action"):
            self.assertIn(key, body)


class TheOperatorSurface(unittest.TestCase):
    """The Management tab card: without it the class would have been
    write-only. This is the piece 11Q said ' Wellness of wiring' needed."""

    def test_the_management_tab_has_a_goals_card(self):
        src = _src(MANAGEMENT)
        for token in ("Earning Goals", "def refresh_goals",
                      "def _on_goal_create", "def _on_goal_pause_resume",
                      "def _on_goal_delete",
                      "metadata", "platforms"):
            self.assertIn(token, src)

    def test_the_catalog_describes_the_card(self):
        import agents.knowledge.help_catalog as hc
        matches = [e for e in hc.FEATURES
                   if "Goals" in e["feature"] or "Goals" in e["category"]]
        self.assertTrue(matches,
                        "a real operator surface must be in the help catalog")
        joined = " ".join(m["description"] for m in matches)
        self.assertIn("goal_system", joined,
                      "the entry's grounding must name the tracker module")
        self.assertIn("verified", joined.lower(),
                      "the entry must carry the only-verified-credits rule")


class TheCardBehaves(unittest.TestCase):
    """Offscreen: create + pause + delete through the card, on a temp DB."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        self._old_localappdata = os.environ.get("LOCALAPPDATA")
        self._tmpdir = tempfile.mkdtemp(prefix="goals244_")
        os.environ["LOCALAPPDATA"] = self._tmpdir
        from agents.earning.goal_system import GoalTracker
        self._old_instance = GoalTracker._instance
        GoalTracker._instance = None

    def tearDown(self):
        from agents.earning.goal_system import GoalTracker
        GoalTracker._instance = self._old_instance
        if self._old_localappdata is not None:
            os.environ["LOCALAPPDATA"] = self._old_localappdata
        else:
            os.environ.pop("LOCALAPPDATA", None)

    def test_create_pause_delete_roundtrip(self):
        from gui.tabs.management_tab import ManagementTab, QMessageBox
        # Offscreen modals never return and would hang the suite silently;
        # an unexpected information dialog is a DEFECT in the card's flow
        # (e.g. a pause/resume that lost the selection), so fail loudly.
        guard = mock.patch.object(
            QMessageBox, "information",
            side_effect=AssertionError("unexpected modal dialog"))
        guard.start()
        self.addCleanup(guard.stop)
        tab = ManagementTab()
        from PySide6.QtWidgets import QTableWidget
        self.assertIsInstance(tab.goals_table, QTableWidget,
                              "the card's table must exist")
        try:
            self.app.processEvents()  # fire the deferred initial refresh

            tab.goal_title_edit.setText("Earn $100 on Upwork")
            tab.goal_target_edit.setText("100")
            tab.goal_platforms_edit.setText("upwork, prolific")
            self.app.processEvents()
            self.assertEqual(tab.goals_table.rowCount(), 0,
                             "no goal yet")
            tab._on_goal_create()
            self.assertEqual(tab.goals_table.rowCount(), 1)
            from agents.earning.goal_system import GoalTracker, GoalStatus
            tracker = GoalTracker.instance()
            goals = tracker.list_all()
            self.assertEqual(len(goals), 1)
            self.assertEqual(
                goals[0].metadata.get("platforms"), ["upwork", "prolific"],
                "the platforms field must land in the operator binding")

            # Platform-bound credit arrives through the LIVE seam contract
            from types import SimpleNamespace
            tracker.process_event(SimpleNamespace(
                event_type="earning", source="llm_cost",
                details={"action": "finalized:paid", "revenue": 60.0,
                         "cost": 0.0, "platform": "upwork", "success": True},
                tags=["earning", "finalized:paid"]))
            self.assertEqual(tracker.get(goals[0].id).current_usd, 60.0)
            tab.refresh_goals()  # the card shows state on refresh/interaction
            status = tab.goals_status.text()
            self.assertIn("$60.00", status,
                          "the card must show the credited progress")

            tab.setCurrentCell = tab.goals_table.setCurrentCell
            tab.setCurrentCell(0, 0)
            tab._on_goal_pause_resume()
            self.assertEqual(tracker.get(goals[0].id).status,
                             GoalStatus.PAUSED.value)
            tab._on_goal_pause_resume()
            self.assertEqual(tracker.get(goals[0].id).status,
                             GoalStatus.ACTIVE.value)

            with mock.patch.object(
                    QMessageBox, "question", return_value=QMessageBox.No):
                tab._on_goal_delete()
            self.assertEqual(tracker.get(goals[0].id).status,
                             GoalStatus.ACTIVE.value,
                             "declining the confirm must not delete")
            with mock.patch.object(
                    QMessageBox, "question", return_value=QMessageBox.Yes):
                tab._on_goal_delete()
            self.assertIsNone(tracker.get(goals[0].id),
                              "accepting the confirm deletes goal + evidence")
        finally:
            pass


if __name__ == "__main__":
    unittest.main()
