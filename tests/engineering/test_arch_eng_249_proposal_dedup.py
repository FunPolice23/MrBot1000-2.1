"""ARCH-ENG-249 / AF-01 -- the proposals table gets its writer, its dedup
guard, and an honest count.

The finding (11m)
-----------------
`AgentDB.proposal_exists` was dead, and its docstring named the defect it was
written for: *"the job queue re-discovers the same Fiverr/Upwork gigs each
cycle, and the old save path blindly inserted a new row each time."* The sweep
assumed the write path was live and only the guard was unreachable.

It was worse. `add_proposal` had ZERO callers anywhere -- main.py, app/,
agents/, gui/, tests/ -- and `get_proposals` was dead too. So the `proposals`
table was never written, while `count_proposals()` is read LIVE by DB Stats
(main.py:2088). The operator was shown a proposal count that was structurally
always zero.

Operator disposition: wire `add_proposal` + `proposal_exists` at
`submit_gig_proposal` (not delete the table or the KPI).

The wire
--------
`agents/earning/proposal.py` gained an optional `persist_proposal_fn`; the
pipeline passes `_persist_submitted_proposal`, which writes ONE row per
title+platform, `status="submitted"`, using `proposal_exists` as the guard.
It is called only on the success path (after the platform accepted the
proposal), and a persistence failure cannot turn an accepted proposal into a
reported failure.

Also removed: 121 lines of unreachable code in
`EarningPipeline.submit_gig_proposal` that sat after its `return
submit_proposal_service(...)`. The service has owned that flow since it was
extracted; the copy underneath could never run, so it was a second, silently
stale implementation of the very path this fix touches.

Vacuity: against the pre-fix sources the two submissions produce zero rows
(no persist call exists), and the unreachable-block scan fails.
"""

import ast
import pathlib
import tempfile
import unittest
from types import SimpleNamespace

REPO = pathlib.Path(__file__).resolve().parents[2]
PIPELINE = REPO / "app" / "earning_pipeline.py"
SERVICE = REPO / "agents" / "earning" / "proposal.py"


class _Reviewer:
    def __init__(self, can_submit=True):
        self.can_submit = can_submit

    def review(self, description, draft, job_title=""):
        return SimpleNamespace(
            can_submit=self.can_submit,
            summary="all requirements covered" if self.can_submit else "too short")


class _Client:
    def __init__(self):
        self.submissions = 0

    def can_submit(self):
        return True

    def submit_proposal(self, job_id=None, cover="", budget=0.0):
        self.submissions += 1
        return {"proposal_id": f"p{self.submissions}", "submitted_by": "me"}


def _opportunity(title="Build a scraper"):
    return SimpleNamespace(
        id="job-1", title=title, platform="upwork",
        description="need a scraper", payment_amount=150.0,
        estimated_usd_value=150.0, proposal_variant=None,
    )


class TheTableGetsWritten(unittest.TestCase):

    def setUp(self):
        from app.earning_pipeline import EarningPipeline
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = str(pathlib.Path(self.tmp.name) / "pipeline.db")
        self.pipe = EarningPipeline(
            db_path=self.db_path,
            memory_path=str(pathlib.Path(self.tmp.name) / "memory.db"),
            log_fn=lambda *a, **k: None,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _count(self):
        from app.database import AgentDB
        db = AgentDB(db_path=self.db_path)
        try:
            return db.count_proposals()
        finally:
            db.close()

    def test_a_submitted_proposal_is_persisted(self):
        result = self.pipe.submit_gig_proposal(
            _opportunity(), "Dear client, here is the plan.",
            reviewer=_Reviewer(), confirm_cb=lambda summary: True,
            client=_Client())
        self.assertTrue(result.success, result.message)
        self.assertEqual(self._count(), 1,
                         "the proposals table must reflect the submission "
                         "(DB Stats reads this count live)")

    def test_a_rediscovered_gig_is_not_duplicated(self):
        """AF-01's exact scenario: the same gig discovered twice."""
        from app.earning_pipeline import EarningPipeline
        client = _Client()
        for _ in range(2):
            result = self.pipe.submit_gig_proposal(
                _opportunity(), "Dear client, same plan.",
                reviewer=_Reviewer(), confirm_cb=lambda summary: True,
                client=client)
            self.assertTrue(result.success, result.message)
        self.assertEqual(client.submissions, 2)
        self.assertEqual(self._count(), 1,
                         "proposal_exists is the guard AF-01 documented; a "
                         "re-discovered gig must not insert a second row")

    def test_a_declined_proposal_is_not_persisted(self):
        result = self.pipe.submit_gig_proposal(
            _opportunity(), "Dear client.",
            reviewer=_Reviewer(), confirm_cb=lambda summary: False,
            client=_Client())
        self.assertFalse(result.success)
        self.assertEqual(result.action_taken, "human_declined")
        self.assertEqual(self._count(), 0,
                         "nothing was submitted, so nothing may be recorded")

    def test_a_review_blocked_proposal_is_not_persisted(self):
        result = self.pipe.submit_gig_proposal(
            _opportunity(), "short",
            reviewer=_Reviewer(can_submit=False),
            confirm_cb=lambda summary: True, client=_Client())
        self.assertFalse(result.success)
        self.assertEqual(self._count(), 0)

    def test_a_preexisting_row_still_dedups(self):
        from app.database import AgentDB
        db = AgentDB(db_path=self.db_path)
        try:
            db.add_proposal(gig_title="Build a scraper", platform="upwork",
                            budget_usd=150.0, draft="older draft")
        finally:
            db.close()
        self.pipe.submit_gig_proposal(
            _opportunity(), "new draft",
            reviewer=_Reviewer(), confirm_cb=lambda summary: True,
            client=_Client())
        self.assertEqual(self._count(), 1)

    def test_persistence_is_never_fatal(self):
        """An unwritable DB must not un-submit an accepted proposal."""
        self.pipe.db_path = "Z:\\does\\not\\exist\\x.db"
        result = self.pipe.submit_gig_proposal(
            _opportunity("Other gig"), "Dear client.",
            reviewer=_Reviewer(), confirm_cb=lambda summary: True,
            client=_Client())
        self.assertTrue(result.success,
                        "the platform accepted it; a persistence error must "
                        "not be reported as a submission failure")


class TheStaleCopyIsGone(unittest.TestCase):

    def test_submit_gig_proposal_has_nothing_after_its_return(self):
        """121 lines of a second, unreachable submission flow used to sit
        after the service delegation. Dead code in the exact path this fix
        touches is how the old assumptions survived."""
        tree = ast.parse(PIPELINE.read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "submit_gig_proposal")
        last = fn.body[-1]
        self.assertIsInstance(last, ast.Return,
                              "the service delegation must be the whole body")
        self.assertEqual(len([n for n in fn.body if isinstance(n, ast.Return)]), 1)

    def test_the_service_calls_the_persist_hook(self):
        src = SERVICE.read_text(encoding="utf-8")
        self.assertIn("persist_proposal_fn", src)
        fn = src[src.index("persist_proposal_fn is not None"):]
        self.assertIn("persist_proposal_fn(opportunity, draft)", fn)


if __name__ == "__main__":
    unittest.main()
