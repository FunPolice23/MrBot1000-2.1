"""A1 — rank_board_entries: the Dialogue board's ranked-feed adapter.

Targets BEHAVIOUR (best-first order, score+why per row, budget bound, fail-soft
to cold-start), so each test FAILS if the adapter stops sorting, drops rows, or
fabricates a score. Pure: a stub planner pins the ordering teeth; a real-planner
smoke test proves PortfolioEntry (the board's entry type) is handled without
crash — the reason the adapter uses the planner directly rather than the
`rank_opportunities` wrapper (which reads `.id` and would raise on PortfolioEntry).
"""
import sys
import unittest
from unittest import mock

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import agents.earning.got as got_mod
from agents.dialogue.opportunity_analysis import rank_board_entries


class _Entry:
    """Minimal PortfolioEntry-shaped stand-in (has opportunity_id, no .id)."""

    def __init__(self, oid):
        self.opportunity_id = oid


class _FakeRank:
    def __init__(self, oid, score, rec):
        self.opportunity_id = oid
        self.utility_score = score
        self.recommendation = rec


def _fake_planner(ranks, raises=False):
    class _FakePlanner:
        def __init__(self, opportunities, evidence_by_id=None):
            self.opportunities = opportunities

        def rank(self):
            if raises:
                raise RuntimeError("planner boom")
            return list(ranks)
    return _FakePlanner


class RankBoardEntriesTest(unittest.TestCase):
    def test_empty_entries_returns_empty_list(self):
        self.assertEqual(rank_board_entries([]), [])
        self.assertEqual(rank_board_entries(None), [])

    def test_ranked_order_highest_utility_first(self):
        entries = [_Entry("a"), _Entry("b"), _Entry("c")]
        ranks = [_FakeRank("a", 0.2, "hold"),
                 _FakeRank("b", 0.9, "candidate_for_existing_gates"),
                 _FakeRank("c", 0.5, "watch")]
        with mock.patch.object(got_mod, "OpportunityGraphPlanner",
                               _fake_planner(ranks)):
            out = rank_board_entries(entries)
        ids = [e.opportunity_id for (e, _s, _w) in out]
        scores = [s for (_e, s, _w) in out]
        self.assertEqual(ids, ["b", "c", "a"], "highest utility must come first")
        self.assertEqual(scores, [0.9, 0.5, 0.2])

    def test_each_row_has_score_and_why(self):
        entries = [_Entry("a")]
        ranks = [_FakeRank("a", 0.42, "candidate_for_existing_gates")]
        with mock.patch.object(got_mod, "OpportunityGraphPlanner",
                               _fake_planner(ranks)):
            out = rank_board_entries(entries)
        self.assertEqual(len(out), 1)
        entry, score, why = out[0]
        self.assertIs(entry, entries[0])
        self.assertIsInstance(score, float)
        self.assertTrue(why, "why/recommendation must be present per row")

    def test_limit_budget_respected(self):
        entries = [_Entry("a"), _Entry("b"), _Entry("c"), _Entry("d")]
        ranks = [_FakeRank("a", 0.1, "hold"), _FakeRank("b", 0.4, "watch"),
                 _FakeRank("c", 0.9, "candidate_for_existing_gates"),
                 _FakeRank("d", 0.2, "hold")]
        with mock.patch.object(got_mod, "OpportunityGraphPlanner",
                               _fake_planner(ranks)):
            out = rank_board_entries(entries, limit=2)
        self.assertEqual(len(out), 2)
        self.assertEqual([e.opportunity_id for (e, _s, _w) in out], ["c", "b"],
                         "limit keeps the top-N by utility")

    def test_unranked_entry_gets_zero_and_label_not_dropped(self):
        entries = [_Entry("a"), _Entry("missing")]
        ranks = [_FakeRank("a", 0.7, "watch")]  # 'missing' has no rank
        with mock.patch.object(got_mod, "OpportunityGraphPlanner",
                               _fake_planner(ranks)):
            out = rank_board_entries(entries)
        self.assertEqual(len(out), 2, "an unranked row is kept, never dropped")
        by_id = {e.opportunity_id: (s, w) for (e, s, w) in out}
        self.assertEqual(by_id["missing"], (0.0, "unranked"))

    def test_planner_failure_falls_back_to_cold_start_order(self):
        entries = [_Entry("a"), _Entry("b")]
        with mock.patch.object(got_mod, "OpportunityGraphPlanner",
                               _fake_planner([], raises=True)):
            out = rank_board_entries(entries)
        self.assertEqual([e.opportunity_id for (e, _s, _w) in out], ["a", "b"])
        self.assertTrue(all(s == 0.0 for (_e, s, _w) in out))

    def test_real_planner_handles_portfolio_entry_without_crash(self):
        # The board's real entry type is PortfolioEntry (opportunity_id, no .id).
        # This is why the adapter uses the planner (whose _id() handles it) and
        # NOT rank_opportunities (which reads .id and would raise).
        from agents.earning.opportunity_portfolio import PortfolioEntry
        entries = [PortfolioEntry(opportunity_id="p1"),
                   PortfolioEntry(opportunity_id="p2"),
                   PortfolioEntry(opportunity_id="p3")]
        out = rank_board_entries(entries)  # no patch: real GoT planner
        self.assertEqual(len(out), 3, "no PortfolioEntry row is dropped")
        for entry, score, why in out:
            self.assertIsInstance(score, float)
            self.assertIsInstance(why, str)
            self.assertTrue(why)


if __name__ == "__main__":
    unittest.main()
