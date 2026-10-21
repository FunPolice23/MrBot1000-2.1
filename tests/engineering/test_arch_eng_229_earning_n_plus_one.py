"""ARCH-ENG-229 - two N+1s, one of them on the discovery hot path.

## What was wrong

**`compute_all_metrics(dim)`** listed the DISTINCT values of a dimension, then
called `compute_opportunity_metrics(dim, v)` once per value. Each of those runs
an **unbounded** `SELECT ... FROM outcome_memory_v2 WHERE <dim> = ?`.

So the cost was *distinct values x full table scan*, plus a fresh
`sqlite3.connect` per call.

This is not an occasional report. `DiscoveryScheduler` calls it on every tick
to decide where to search next -- the very thing ARCH-ENG-224 just reconnected.
The learning loop was being made live on top of an N x full-scan.

**`get_task_type_history_all()`** had the same shape: SELECT DISTINCT, then one
`get_task_type_history(k)` per key, each opening its own connection, to produce
N rows.

## The contract these tests pin

The rewrite is not a "should be equivalent" claim -- it is checked. For every
dimension value, every field of the resulting `LearningMetrics` must equal what
the original per-value implementation produced, to within float tolerance. A
faster aggregator that quietly reorders a recency weight is worse than the N+1,
because it changes what the scheduler decides.

`test_the_rewrite_is_identical_not_merely_faster` is the load-bearing test. The
speed assertions exist only to catch an accidental reintroduction of the loop.

Also pinned: the `global` arm is untouched (one query already), an unknown
dimension still falls back to global, and a dimension with no rows yields an
empty list rather than raising.
"""

import math
import os
import random
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

STATES = ["accepted", "completed", "paid", "failed", "rejected_apply",
          "abandoned", "submitted", "payment_disputed"]
CATS = ["freelance", "social", "defi", "airdrop", "crypto"]
PLATS = ["upwork", "fiverr"]
TTYPES = ["coding", "writing", "research"]

FIELDS = ("acceptance_rate", "completion_rate", "payment_rate", "failure_rate",
          "cancellation_rate", "average_revenue", "average_net_profit",
          "average_effort_hours", "average_hourly_return",
          "expected_vs_actual_return", "sample_size", "confidence",
          "cold_start")


def _assert_same_metric(test, a, b, msg=""):
    """ARCH-ENG-234: compare the aggregated fields at a tolerance the float
    mechanism can actually meet.

    `_seeded_memory` stamps every record with ``time.time()`` at seed time, so
    the recency weights (``recency_weight(ts, now)`` with ``now`` pinned but the
    ts values fresh from the clock) differ run to run. The two aggregation
    paths sum the SAME weighted values in different association order, so the
    difference between them is float-association noise -- measured at ~1e-11
    and proven to drift with the wall clock (two bare-code runs 90s apart gave
    errors that moved AND crossed the boundary during the same day). ``places=12``
    (abs 5e-13) meant "equal to within noise", which is not a property a
    magnitude-weighted sum of ~400 rows can guarantee.

    ``math.isclose(rel_tol=1e-9)`` keeps the test's original teeth: a genuinely
    reordered recency weighting changes a weighted mean at ~1e-3 scale, ten
    orders larger than the association noise this accepts. The abs floor keeps
    near-zero rate fields comparable.
    """
    ok = math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    test.assertTrue(ok, f"{msg}{a} != {b} beyond rel_tol 1e-9 "
                        f"(difference {b - a})")


def _seeded_memory(n=400, seed=7):
    tmp = tempfile.mkdtemp(prefix="arch229_")
    from app.earning_memory import EarningMemory
    m = EarningMemory(db_path=os.path.join(tmp, "m.db"))
    rnd = random.Random(seed)
    for i in range(n):
        m.record_outcome_v2(
            f"opp{i}", rnd.choice(STATES),
            platform=rnd.choice(PLATS), category=rnd.choice(CATS),
            task_type=rnd.choice(TTYPES),
            revenue=rnd.choice([0, 10, 50, 200.0]),
            net_profit=rnd.uniform(-5, 120),
            effort_hours=rnd.uniform(0.1, 3),
            time_spent_hours=rnd.uniform(0.2, 4),
            predicted_revenue=rnd.uniform(0, 200))
    return m, tmp


class TestTheRewriteIsIdenticalNotMerelyFaster(unittest.TestCase):
    """The load-bearing test. A faster wrong aggregator is worse than the N+1."""

    @classmethod
    def setUpClass(cls):
        cls.m, cls.tmp = _seeded_memory()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _assert_same(self, dim):
        # A FIXED reference instant for both sides. `recency_weight(ts, None)`
        # resolves "now" to time.time() at each call, so comparing two calls
        # made microseconds apart compares two different measurement instants
        # and drifts by ~1e-10 relative. `compute_all_metrics` now takes `now`
        # for exactly this reason: one tick, one instant.
        now = 1_800_000_000.0
        new = {x.value: x for x in self.m.compute_all_metrics(dim, now=now)}
        checked = 0
        for value in list(new):
            original = self.m.compute_opportunity_metrics(dim, value, now=now)
            for f in FIELDS:
                a, b = getattr(new[value], f), getattr(original, f)
                with self.subTest(dim=dim, value=value, field=f):
                    if isinstance(a, float):
                        _assert_same_metric(self, a, b, f"{value}.{f} changed")
                    else:
                        self.assertEqual(a, b)
                checked += 1
        self.assertGreater(checked, 0,
                           f"no field was compared for dim={dim!r}; the "
                           f"equivalence check proved nothing")

    def test_category_metrics_are_unchanged(self):
        self._assert_same("category")

    def test_platform_metrics_are_unchanged(self):
        self._assert_same("platform")

    def test_task_type_metrics_are_unchanged(self):
        self._assert_same("task_type")

    def test_the_seeded_data_actually_has_rows(self):
        """Otherwise every equivalence check above compares empty to empty."""
        self.assertGreaterEqual(len(self.m.compute_all_metrics("category")), 3)


class TestTheGlobalArmIsUntouched(unittest.TestCase):
    def setUp(self):
        self.m, self.tmp = _seeded_memory(n=60)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_an_unknown_dimension_falls_back_to_global(self):
        out = self.m.compute_all_metrics("not_a_dimension")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].dim, "global")

    def test_global_still_matches_the_direct_call(self):
        now = 1_800_000_000.0
        direct = self.m.compute_opportunity_metrics("global", "global", now=now)
        got = self.m.compute_all_metrics("nope", now=now)[0]
        for f in FIELDS:
            with self.subTest(field=f):
                a, b = getattr(got, f), getattr(direct, f)
                if isinstance(a, float):
                    _assert_same_metric(self, a, b)
                else:
                    self.assertEqual(a, b)

    def test_a_dimension_with_no_rows_returns_an_empty_list(self):
        """Seeded rows exist for every real dimension, so make one empty."""
        import sqlite3
        conn = sqlite3.connect(self.m.db_path)
        conn.execute("DELETE FROM outcome_memory_v2")
        conn.commit()
        conn.close()
        self.assertEqual(self.m.compute_all_metrics("category"), [],
                         "an empty dimension must yield an empty list, not "
                         "a crash and not a fabricated row")


class TestTaskTypeHistoryAllIsEquivalent(unittest.TestCase):
    def setUp(self):
        self.m, self.tmp = _seeded_memory(n=40)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_it_matches_the_per_key_path(self):
        # Seeding writes patterns both ways; compare over EVERY key the grouped
        # version returns, not a hand-picked list. An earlier draft compared
        # only CATS and failed because record_outcome_v2(task_type=...) also
        # writes pattern_memory rows -- the grouped result was right and the
        # comparison set was too narrow.
        new = {h["task_type"]: h for h in self.m.get_task_type_history_all()}
        self.assertTrue(new, "no task-type patterns were written; the "
                             "comparison below would be vacuous")
        old = {k: (self.m.get_task_type_history(k) | {"task_type": k})
               for k in new}
        self.assertEqual(set(new), set(old), "different keys returned")
        for k in new:
            for f in ("success", "failed", "total", "success_rate",
                      "avg_revenue", "confidence", "task_type"):
                with self.subTest(key=k, field=f):
                    self.assertEqual(new[k][f], old[k][f],
                                     f"{k}.{f} changed")

    def test_explicitly_recorded_outcomes_also_appear(self):
        for k in CATS:
            self.m.record_task_type_outcome(k, k == "defi", 10.0)
        keys = {h["task_type"] for h in self.m.get_task_type_history_all()}
        for k in CATS:
            self.assertIn(k, keys,
                          "a key recorded via record_task_type_outcome is "
                          "missing from the grouped read")

    def test_a_cold_key_returns_the_zero_shape_not_a_crash(self):
        self.m.record_task_type_outcome("brand_new", True, 1.0)
        rows = {h["task_type"]: h for h in self.m.get_task_type_history_all()}
        self.assertIn("brand_new", rows)
        self.assertEqual(rows["brand_new"]["total"], 1)


class TestTheLoopIsNotReintroduced(unittest.TestCase):
    """Cheap enough to keep, and they catch an accidental reversion."""

    def setUp(self):
        self.m, self.tmp = _seeded_memory(n=300)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_compute_all_metrics_is_not_slower_than_the_per_value_path(self):
        t0 = time.perf_counter()
        self.m.compute_all_metrics("category")
        new_dt = time.perf_counter() - t0
        t0 = time.perf_counter()
        for v in CATS:
            self.m.compute_opportunity_metrics("category", v)
        old_dt = time.perf_counter() - t0
        # Not a tight bound: this is a "did the N+1 come back" tripwire, not a
        # benchmark. Machine noise on a cold DB can make these close.
        self.assertLessEqual(new_dt, old_dt * 1.5 + 0.05,
                             f"grouped {new_dt*1000:.1f} ms vs per-value "
                             f"{old_dt*1000:.1f} ms -- the N+1 looks back")

    def test_compute_all_metrics_opens_one_connection_not_n(self):
        import sqlite3
        opened = []
        real = sqlite3.connect

        def counting(*a, **k):
            opened.append(1)
            return real(*a, **k)

        sqlite3.connect = counting
        try:
            self.m.compute_all_metrics("category")
        finally:
            sqlite3.connect = real
        self.assertEqual(len(opened), 1,
                         f"{len(opened)} connections opened for one grouped "
                         f"query; the per-value path is back")

    def test_task_type_history_all_opens_one_connection(self):
        import sqlite3
        for k in CATS:
            self.m.record_task_type_outcome(k, True, 1.0)
        opened = []
        real = sqlite3.connect

        def counting(*a, **k):
            opened.append(1)
            return real(*a, **k)

        sqlite3.connect = counting
        try:
            self.m.get_task_type_history_all()
        finally:
            sqlite3.connect = real
        self.assertEqual(len(opened), 1,
                         f"{len(opened)} connections for one grouped query")


if __name__ == "__main__":
    unittest.main()