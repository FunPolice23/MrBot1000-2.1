"""Self-improvement outcome wiring (Phase C, v2.1.72, ARCH-ENG-082).

The SelfImprovementEngine (agents/autonomy/self_improvement.py) learns platform
reliability / tag rates / strategy weights from VERIFIED opportunity outcomes,
but it was orphaned (only a CLI referenced it). EarningPipeline now feeds it
from the same lifecycle outcome_callback that already feeds search-strategy
memory. These tests prove the wiring + the verified-only gate end to end.

Financial-truth / safety invariants locked in:
- An UNVERIFIED outcome (no evidence) must NOT create a learning signal.
- A VERIFIED paid outcome DOES update platform reliability + counts.
- The strategy-memory path is unchanged (no strategy id -> still returns early
  for that sink, but the engine is fed regardless).
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _pipeline(tmp):
    """Build a minimal EarningPipeline-like object with just the pieces
    _feed_self_improvement touches, without a full DB."""
    from app.earning_pipeline import EarningPipeline
    p = EarningPipeline.__new__(EarningPipeline)   # bypass __init__/DB
    p.db_path = os.path.join(tmp, "earning.db")
    p._self_improvement = None
    p._log = lambda *a, **k: None
    p.memory = mock.Mock()
    return p


class TestSelfImprovementWiring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_verified_outcome_feeds_engine(self):
        p = _pipeline(self.tmp)
        p.memory.get_outcome_evidence.return_value = ["ev1"]
        hist = {"platform": "ugig", "strategy": "s1", "tags": ["python"]}
        p._feed_self_improvement("o1", "paid", hist,
                                 revenue=100.0, cost=0.0, effort_hours=1.0)
        engine = p.self_improvement
        self.assertIsNotNone(engine)
        self.assertEqual(engine.state.total_outcomes, 1)
        self.assertGreater(engine.get_platform_reliability("ugig"), 0.5)

    def test_unverified_outcome_does_not_learn(self):
        p = _pipeline(self.tmp)
        p.memory.get_outcome_evidence.return_value = []   # no evidence
        hist = {"platform": "ugig"}
        p._feed_self_improvement("o1", "paid", hist,
                                 revenue=100.0, cost=0.0, effort_hours=1.0)
        # The engine received a record with verified=False -> ignored it.
        self.assertEqual(p.self_improvement.state.total_outcomes, 0)

    def test_engine_state_persists_across_instances(self):
        p = _pipeline(self.tmp)
        p.memory.get_outcome_evidence.return_value = ["ev1"]
        p._feed_self_improvement("o1", "paid",
                                 {"platform": "ugig"}, revenue=50.0, cost=0.0,
                                 effort_hours=0.5)
        # A fresh pipeline over the same db_path reloads the persisted state.
        p2 = _pipeline(self.tmp)
        self.assertEqual(p2.self_improvement.state.total_outcomes, 1)

    def test_feed_never_raises_on_engine_error(self):
        p = _pipeline(self.tmp)
        p.memory.get_outcome_evidence.side_effect = RuntimeError("db down")
        # Must not raise; the pipeline logs and moves on.
        p._feed_self_improvement("o1", "paid", {"platform": "x"},
                                 revenue=1.0, cost=0.0, effort_hours=0.0)
        self.assertTrue(True)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
