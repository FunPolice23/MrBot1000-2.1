"""ARCH-ENG-216 — a payment outcome overwrote an opportunity's quality score.

## The category error

`PortfolioEntry.policy_score` is declared `float` and means "how attractive is
this opportunity". `autonomous_loop` assigned to it:

    # Keep policy scoring truthful: completed-unpaid runs are not
    # successful paid outcomes.
    entry.policy_score = result.paid

`result.paid` is a **bool** meaning "did this particular run get paid". Those are
different questions, so this was a category error before it was a type error —
the comment states an intent the code defeats.

The visible effect: every opportunity the autonomous loop touched was written as
`0.0`, rendered **"0%"** in the Opportunities tab, and then hidden by that tab's
minimum-score filter. Work the agent had actually performed disappeared from the
operator's view.

`entry.explanation` was worse. `PortfolioEntry` has no such field, so the
assignment was silently dropped by `add()`'s 24-column INSERT. It read as though
the reasoning were being recorded. It was not.

## Why the field had no legitimate writer

`QueuePolicy.score()` computed exactly the right value. `compute_scores()`
returned it — and threw it away, because that is a *read* path and must not
write. So the column's only writer was the wrong one above.

## The second defect: a unit mismatch

`score()` returns an **unbounded weighted sum**, not a 0..1 fraction. With every
normalised term at 1.0 it reaches 4.5; the cost terms can drag it below zero.
Observed range ≈ -0.8 .. 3.4.

The Opportunities tab treats the value as a percentage — it renders
`policy_score * 100` and filters on `policy_score < min_percent / 100`. So a
legitimate score of 1.04 displayed as **"104%"**, and an operator's "minimum
50%" actually meant 0.5 on a 0..3.4 scale, far more permissive than intended.

The persisted contract is now 0..1. `score()` keeps its own semantics because
`ranked_by_score` sorts on it; `rescore_all` normalises on the way to disk. The
tests assert ordering is preserved, since that is the one thing normalisation
must not break.
"""

import ast
import os
import pathlib
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
PORTFOLIO = REPO / "agents" / "earning" / "opportunity_portfolio.py"
LOOP = REPO / "agents" / "services" / "autonomous_loop.py"
BUILDER = REPO / "gui" / "builders" / "tab_feature_builders.py"


def _build():
    from agents.earning.opportunity_portfolio import (OpportunityPortfolio,
        PortfolioEntry, WorkQueue, QueuePolicy, CapacityConfig)
    db = os.path.join(tempfile.mkdtemp(prefix="arch216_"), "p.db")
    pf = OpportunityPortfolio(db_path=db)
    return pf, WorkQueue(pf, QueuePolicy(), CapacityConfig())


class TestTheBoolOverwriteIsGone(unittest.TestCase):
    """ARCH-ENG-216 — the category error."""

    def test_nothing_writes_policy_score_in_the_loop(self):
        """`policy_score` is unambiguously the portfolio's field.

        An earlier draft of this test also flagged `explanation`, which was
        wrong: `autonomous_loop.py:1141` legitimately sets
        `result.explanation` on a LOCAL run-result object. Matching on the
        attribute name alone cannot tell `entry.explanation` from
        `result.explanation`, so the check was right to be narrowed.
        """
        tree = ast.parse(LOOP.read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if getattr(target, "attr", None) == "policy_score":
                        offenders.append(
                            f"line {node.lineno}: {ast.unparse(target)} = "
                            f"{ast.unparse(node.value)[:50]}")
        self.assertEqual(
            offenders, [],
            f"the autonomous loop writes policy_score: {offenders}. A payment "
            f"outcome is not an opportunity's attractiveness")

    def test_a_portfolio_entry_never_gets_an_explanation(self):
        """Scoped to ENTRY variables, so a local `result.explanation` is fine."""
        tree = ast.parse(LOOP.read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Attribute):
                    continue
                if target.attr != "explanation":
                    continue
                owner = ast.unparse(target.value)
                if "entry" in owner.lower() or "portfolio" in owner.lower():
                    offenders.append(f"line {node.lineno}: {owner}.explanation")
        self.assertEqual(
            offenders, [],
            f"an explanation is assigned to a portfolio entry: {offenders}. "
            f"PortfolioEntry has no such field, so it is silently dropped by "
            f"the 24-column INSERT while reading as though it was recorded")

    def test_the_local_result_explanation_is_left_alone(self):
        """Calibration: the guard must not flag legitimate code."""
        tree = ast.parse(LOOP.read_text(encoding="utf-8"))
        found = any(
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Attribute) and t.attr == "explanation"
                    and ast.unparse(t.value) == "result"
                    for t in node.targets)
            for node in ast.walk(tree))
        self.assertTrue(found,
                        "the local `result.explanation` assignment is gone; the "
                        "scoped guard above would no longer be proving anything")

    def test_the_reason_is_recorded(self):
        self.assertIn("ARCH-ENG-216", LOOP.read_text(encoding="utf-8"))


class TestTheScoreIsNowPersistedAndNormalised(unittest.TestCase):
    """ARCH-ENG-216 — the column's real writer."""

    def _entry(self, pf, oid, ehv, eff):
        from agents.earning.opportunity_portfolio import PortfolioEntry
        pf.add(PortfolioEntry(opportunity_id=oid, opportunity_ref={"id": oid},
                              expected_hourly_value=ehv, effort=eff))

    def test_rescore_all_persists_a_real_value(self):
        pf, wq = _build()
        self._entry(pf, "opp_1", 200.0, 1.0)
        self.assertEqual(pf.get("opp_1").policy_score, 0.0,
                         "precondition: the default is zero")
        wq.rescore_all()
        self.assertGreater(pf.get("opp_1").policy_score, 0.0,
                           "rescore_all must persist the computed score")

    def test_the_persisted_value_is_a_fraction(self):
        """The GUI multiplies by 100 and divides by 100; both need 0..1."""
        pf, wq = _build()
        self._entry(pf, "opp_1", 200.0, 1.0)
        wq.rescore_all()
        score = pf.get("opp_1").policy_score
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0,
                             f"{score} is outside 0..1, so the tab renders "
                             f"{score*100:.0f}% and its minimum filter is wrong")

    def test_the_raw_score_is_unbounded_but_the_stored_one_is_not(self):
        """Documents WHY normalisation is needed, so it is not 'simplified' out."""
        from agents.earning.opportunity_portfolio import QueuePolicy
        policy = QueuePolicy()
        ceiling = policy.theoretical_max()
        self.assertGreater(ceiling, 1.0,
                           "if the weighted sum no longer exceeds 1.0, the "
                           "normalisation is dead code and the GUI contract "
                           "should be revisited instead")

    def test_ordering_is_preserved(self):
        """The one thing normalisation must not break."""
        pf, wq = _build()
        self._entry(pf, "best", 200.0, 1.0)
        self._entry(pf, "weak", 5.0, 39.0)
        wq.rescore_all()
        best = pf.get("best").policy_score
        weak = pf.get("weak").policy_score
        self.assertGreater(best, weak,
                           "normalisation inverted the ranking")

    def test_the_read_path_still_does_not_write(self):
        """compute_scores must stay side-effect free.

        Compared by the PERSISTED value across the call. An earlier draft
        mutated the object returned by `get()` and compared that -- but `get()`
        deserialises a fresh PortfolioEntry on every call, so the mutation never
        touched the database and the assertion was vacuous.
        """
        pf, wq = _build()
        self._entry(pf, "opp_1", 200.0, 1.0)
        before = pf.get("opp_1").policy_score
        wq.compute_scores(0.0)
        after = pf.get("opp_1").policy_score
        self.assertEqual(before, after,
                         "compute_scores wrote to the database; it is a read "
                         "path and must not have side effects")

    def test_rescore_all_is_idempotent(self):
        pf, wq = _build()
        self._entry(pf, "opp_1", 200.0, 1.0)
        wq.rescore_all()
        self.assertEqual(wq.rescore_all(), 0,
                         "a second pass rewrote rows it should have skipped")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-216 — each detector must be able to fail."""

    def test_the_writer_detector_sees_a_bool_assignment(self):
        bad = ast.parse("entry.policy_score = result.paid")
        found = []
        for node in ast.walk(bad):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if getattr(target, "attr", None) in ("policy_score", "explanation"):
                        if ".paid" in ast.unparse(node.value):
                            found.append(ast.unparse(node))
        self.assertTrue(found,
                        "the detector cannot see the original assignment, so "
                        "it would pass while the category error returned")

    def test_the_score_scan_can_find_a_strong_entry(self):
        pf, wq = _build()
        from agents.earning.opportunity_portfolio import PortfolioEntry
        pf.add(PortfolioEntry(opportunity_id="x", opportunity_ref={"id": "x"},
                              expected_hourly_value=200.0, effort=1.0))
        wq.rescore_all()
        self.assertGreater(pf.get("x").policy_score, 0.0,
                           "a strong opportunity scored zero, so the "
                           "normalisation tests would pass vacuously")

    def test_the_gui_arithmetic_matches_the_stored_scale(self):
        """The whole point: the tab's *100 and /100 assume 0..1."""
        src = BUILDER.read_text(encoding="utf-8")
        self.assertIn("entry.policy_score * 100", src,
                      "the tab still renders policy_score as a percentage")
        self.assertIn("opp_min_score_spin.setRange(0, 100)", src,
                      "the minimum-score control is not a 0-100 percent range")