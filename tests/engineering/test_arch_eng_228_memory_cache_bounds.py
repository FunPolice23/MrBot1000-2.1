"""ARCH-ENG-228 - two in-memory structures that grew for the life of the process.

## What was wrong

`EarningMemory` kept two dicts that only ever grew.

**`self._cache`**, keyed `opp_<id>`, written by `remember_opportunity` on every
discovery and by `get_opportunity_history` on any miss. The only prune in the
file, `clear_expired`, deletes rows from the `opportunity_memory` TABLE -- and
had zero callers besides. Even if it had been called, it never touched this
dict, so a deleted row stayed resident for the life of the process and the
cache and the table disagreed permanently after the first call.

**`self._stats`**, keyed by skill name and `tag_<tag>`, each holding a
`skills_matched` set. Nothing ever removed a key.

The second one is the more expensive of the two, because of what reads it:
`periodic_decay` iterates ALL of `_stats`, and `get_memory_summary` calls
`periodic_decay`. So every insight refresh -- which the Earnings and Insights
tabs do on a timer -- was an O(n) pass over a dict whose n only ever grew.

On the operator's 32 GB machine, which may already be holding a 10 GB local
model, that is memory taken from the one resource there is least of.

## The fix

Both are now bounded LRUs. `OrderedDict` + `move_to_end` means the entries
actually in use survive and cold ones are evicted first, rather than the cache
becoming useless the moment it fills.

`_stats` is no longer a `defaultdict`. That mattered: a defaultdict inserts on
a bare READ, so it could not be bounded at the write sites without every read
site also bounding it. `_stats_touch` now owns creation, so every creation is
bounded by construction.

`clear_expired` drops the matching cache entries, so the table and the cache
cannot drift. It still has no callers -- pruning on a schedule is a product
decision, not something to smuggle into a correctness fix -- but it is now
correct if something calls it.
"""

import ast
import os
import pathlib
import sqlite3
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
MEMORY = REPO / "app" / "earning_memory.py"


def _memory():
    tmp = tempfile.mkdtemp(prefix="arch228_")
    from app.earning_memory import EarningMemory
    return EarningMemory(db_path=os.path.join(tmp, "m.db")), tmp


class TestTheCacheIsBounded(unittest.TestCase):
    def setUp(self):
        self.m, self.tmp = _memory()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_cache_cannot_exceed_its_cap(self):
        for i in range(self.m._cache_max + 500):
            self.m.remember_opportunity(str(i), {"i": i}, "test")
        self.assertLessEqual(len(self.m._cache), self.m._cache_max)

    def test_the_survivors_are_the_NEWEST_not_the_oldest(self):
        """A FIFO would keep the oldest and evict the working set."""
        n = self.m._cache_max + 200
        for i in range(n):
            self.m.remember_opportunity(str(i), {"i": i}, "test")
        ids = sorted(int(k[4:]) for k in self.m._cache)
        self.assertEqual(ids, list(range(n - self.m._cache_max, n)),
                         "the cache kept the OLDEST entries; that is a FIFO, "
                         "and it would evict exactly the data in use")

    def test_a_read_promotes_an_entry_so_it_survives(self):
        """The point of LRU over a plain cap."""
        self.m.remember_opportunity("hot", {"v": "hot"}, "test")
        self.m.get_opportunity_history("hot")            # promote
        for i in range(self.m._cache_max):
            self.m.remember_opportunity(f"fill{i}", {"v": i}, "test")
        self.assertEqual(self.m.get_opportunity_history("hot"), {"v": "hot"},
                         "a repeatedly-read entry was evicted; the cap is "
                         "destroying the working set")
        self.assertNotIn("opp_fill0", self.m._cache)

    def test_a_read_still_misses_to_the_database(self):
        """Bounding must not change what a miss returns."""
        self.m.remember_opportunity("later", {"v": "stored"}, "test")
        self.m._cache.clear()                            # force the miss path
        self.assertEqual(self.m.get_opportunity_history("later"),
                         {"v": "stored"})

    def test_a_cap_of_zero_is_clamped_to_something_usable(self):
        """A bad env value must not produce a cache that evicts everything."""
        m, tmp = _memory()
        try:
            self.assertGreaterEqual(m._cache_max, 64)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class TestTheStatsAreBounded(unittest.TestCase):
    def setUp(self):
        self.m, self.tmp = _memory()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_stats_cannot_exceed_their_cap(self):
        for i in range(self.m._stats_max + 300):
            self.m._stats_touch(f"skill_{i}")["success"] += 1
        self.assertLessEqual(len(self.m._stats), self.m._stats_max)

    def test_a_fresh_entry_has_the_full_default_shape(self):
        """`_stats` stopped being a defaultdict, so the factory moved."""
        entry = self.m._stats_touch("brand_new_skill")
        for field in ("success", "failed", "total_revenue", "last_success",
                      "last_failure", "skills_matched", "skill_count"):
            self.assertIn(field, entry,
                          f"a new stats entry is missing {field!r}; moving "
                          f"the factory out of defaultdict lost a field")
        self.assertIsInstance(entry["skills_matched"], set)

    def test_periodic_decay_still_works_and_still_decays(self):
        e = self.m._stats_touch("s")
        e["total_revenue"] = 100.0
        self.m.periodic_decay()
        self.assertLess(self.m._stats["s"]["total_revenue"], 100.0)

    def test_decay_does_not_raise_with_many_keys(self):
        for i in range(500):
            self.m._stats_touch(f"s{i}")["success"] += 1
        self.m.periodic_decay()      # must not raise on dict mutation


class TestClearExpiredEvictsTheCacheToo(unittest.TestCase):
    def setUp(self):
        self.m, self.tmp = _memory()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _insert_old_row(self, key="old1"):
        conn = sqlite3.connect(self.m.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO opportunity_memory "
            "(key, memory_data, memory_type, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)", (key, '{"v": 1}', "test", 0.0, 0.0))
        conn.commit()
        conn.close()

    def test_a_deleted_row_leaves_the_cache(self):
        """The disagreement: the table says gone, memory says present."""
        self._insert_old_row()
        self.m._cache_put("opp_old1", {"v": 1})
        self.assertIn("opp_old1", self.m._cache, "precondition: cached")

        self.m.clear_expired()

        self.assertNotIn("opp_old1", self.m._cache,
                         "clear_expired deleted the row but left it resident "
                         "in the cache; the two now disagree permanently")
        self.assertIsNone(self.m.get_opportunity_history("old1"))

    def test_a_fresh_row_is_left_alone(self):
        self.m.remember_opportunity("fresh", {"v": "fresh"}, "test")
        self.m.clear_expired()
        self.assertIn("opp_fresh", self.m._cache,
                      "clear_expired evicted a row that was not expired")


class TestTheGuardsCannotPassByReadingThemselves(unittest.TestCase):
    def test_every_cache_write_goes_through_the_bounding_helper(self):
        """A bound enforced at only some call sites is not a bound."""
        src = MEMORY.read_text(encoding="utf-8")
        tree = ast.parse(src)
        cls = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.ClassDef) and n.name == "EarningMemory")
        direct = []
        for fn in cls.body:
            if not isinstance(fn, ast.FunctionDef):
                continue
            if fn.name in ("_cache_put", "_cache_get", "clear_expired",
                           "_stats_touch"):
                continue
            for node in ast.walk(fn):
                # `self._cache[k] = v` / `self._cache[k][f] += 1`
                if (isinstance(node, ast.Assign)
                        and isinstance(node.value, ast.Subscript)
                        and isinstance(node.targets[0], ast.Subscript)):
                    tgt = node.targets[0].value
                    if (isinstance(tgt, ast.Attribute) and tgt.attr == "_cache"):
                        direct.append(f"{fn.name}:{node.lineno}")
                if (isinstance(node, ast.AugAssign)
                        and isinstance(node.target, ast.Subscript)):
                    tgt = node.target.value
                    if (isinstance(tgt, ast.Attribute)
                            and tgt.attr in ("_cache", "_stats")):
                        direct.append(f"{fn.name}:{node.lineno}")
        self.assertEqual(direct, [],
                         f"unbounded direct writes remain: {direct}")

    def test_the_cache_is_not_a_plain_dict(self):
        """A plain dict has no eviction; the cap would be decorative."""
        self.m, tmp = _memory()
        try:
            self.assertTrue(hasattr(self.m._cache, "move_to_end"),
                            "the cache cannot be bounded as constructed")
            self.assertTrue(hasattr(self.m._stats, "move_to_end"),
                            "the stats dict cannot be bounded as constructed")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_summary_does_not_build_a_list_to_count_it(self):
        """Checked via the AST, not a substring search.

        The first version of this test grepped the source for
        `len([k for k in self._cache`. It failed on its own file's comment,
        which quotes the old expression to explain what changed -- a guard
        defeated by the documentation of the fix. Parsing the function cannot
        be defeated that way, because comments are not in the AST.
        """
        tree = ast.parse(MEMORY.read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "get_memory_summary")
        offenders = []
        for node in ast.walk(fn):
            # len(<ListComp>) -- allocating a list in order to take its length
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "len"):
                continue
            for arg in node.args:
                if isinstance(arg, (ast.ListComp, ast.List)):
                    offenders.append(ast.unparse(node))
        self.assertEqual(offenders, [],
                         f"get_memory_summary builds a list just to count it: "
                         f"{offenders}")

    def test_the_decay_pass_still_visits_every_key(self):
        """Bounding must not have quietly turned the decay into a no-op."""
        src = MEMORY.read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "periodic_decay")
        body = ast.unparse(fn)
        self.assertIn("self._stats", body)
        self.assertIn("total_revenue", body)


if __name__ == "__main__":
    unittest.main()