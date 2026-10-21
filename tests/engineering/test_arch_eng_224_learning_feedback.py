"""ARCH-ENG-224 - learning that never learned, and a fetch with no witness.

## A. Autonomous learning fed nothing back

`EarningDiscoveryService.discover` bound the scan statistics to `_stats` -- the
conventional name for a value you do not intend to use -- and threw them away:

    found, errors, _stats = discovery.discover(requested, page=page, query=query)

Those statistics are the only per-source attribution in the system:
`by_source` (how many results each source produced), `errors` (which failed),
`by_category`. And `DiscoveryScheduler._source_quality` reads exactly those
facts to decide what to search next.

So the scheduler selected tasks from a reliability table that stayed empty
forever. `record_outcome` was called only from `run_task`, inside
`run_discovery_cycle` -- which has no callers anywhere in the codebase. The live
path was `EarningPipeline.discover`, which bypassed the scheduler entirely.

The live database proved it: `opportunity_memory` held 195 rows while
`search_strategy`, `strategy_memory`, `learning_history` and
`outcome_memory_v2` were all zero. Discovery ran constantly and nothing it
learned was ever kept.

## B. `web_check` was the only agent URL fetch with no visibility

`web_search` and `web_read` both call `_announce_agent_web`, which pushes into
the Web Browser tab's activity log. `web_check` did not -- and it issues a real
HEAD request to whatever URL it is given. It is SSRF-guarded, and it is
READONLY so the SafetyGate allows it with no approval, so an agent could probe
hosts and leave no trace anywhere in the operator's UI.

From the operator's point of view all three tools do the same visible thing: an
agent fetched a URL. All three must announce.
"""

import ast
import os
import pathlib
import unittest
from unittest.mock import Mock

REPO = pathlib.Path(__file__).resolve().parents[2]
HANDLERS = REPO / "agents" / "safety" / "handlers.py"
DISCOVERY = REPO / "agents" / "earning" / "discovery.py"
PIPELINE = REPO / "app" / "earning_pipeline.py"


class _Stats:
    """Shaped like the real DiscoveryStats the engine returns."""

    def __init__(self, by_source=None, errors=None, by_category=None):
        self.by_source = by_source or {}
        self.errors = errors or {}
        self.by_category = by_category or {}


class TestSchedulerGetsWhatTheScanProduced(unittest.TestCase):
    """Part A -- the write side, with a scheduler that records what it is told."""

    def _harness(self, stats, scheduler_raises=False):
        from app.earning_pipeline import EarningPipeline

        class Service:
            last_stats = None

            def discover(self, sources=None, on_found=None, page=1, query=None):
                self.last_stats = stats
                return ["opp-1"]

        class Sched:
            def __init__(self):
                self.outcomes = []
                self.searched = []

            def record_outcome(self, source, strategy_id, success=False,
                               revenue=0.0, error=False, now=None):
                if scheduler_raises:
                    raise RuntimeError("scheduler exploded")
                self.outcomes.append((source, bool(error), bool(success)))

            def mark_searched(self, category, now=None):
                self.searched.append(category)

        class Pipeline:
            discovery_service = Service()
            discovery_scheduler = Sched()
            _log = staticmethod(lambda m: None)
            discover = EarningPipeline.discover

        return Pipeline()

    def test_a_productive_source_is_recorded_as_a_clean_run(self):
        p = self._harness(_Stats(by_source={"upwork": 5}))
        p.discover(sources=["upwork"])
        self.assertIn(("upwork", False, False), p.discovery_scheduler.outcomes,
                      "a source that produced results told the scheduler "
                      "nothing; the reliability table stays empty")

    def test_a_failing_source_is_recorded_as_an_error(self):
        """So its backoff grows instead of it being retried forever."""
        p = self._harness(_Stats(by_source={"upwork": 1}, errors={"fiverr": "boom"}))
        p.discover(sources=["upwork"])
        self.assertIn(("fiverr", True, False), p.discovery_scheduler.outcomes,
                      "a source that errored was not reported, so its backoff "
                      "never grows")

    def test_searched_categories_are_marked(self):
        p = self._harness(_Stats(by_source={"web": 2},
                                by_category={"freelance": 2, "social": 0}))
        p.discover(sources=["web"])
        self.assertIn("freelance", p.discovery_scheduler.searched)
        self.assertIn("social", p.discovery_scheduler.searched)

    def test_discovery_never_reports_success_for_a_find(self):
        """Finding an opportunity is not earning from it.

        Success arrives later through the opportunity lifecycle. Claiming it
        here would teach the scheduler that every scan was profitable.
        """
        p = self._harness(_Stats(by_source={"upwork": 99}))
        p.discover(sources=["upwork"])
        self.assertFalse(any(ok for _, _, ok in p.discovery_scheduler.outcomes),
                         "a scan that merely FOUND something was recorded as a "
                         "success; the scheduler would learn that discovery "
                         "always pays")

    def test_the_result_is_still_returned(self):
        """The fix must not change what discovery yields."""
        p = self._harness(_Stats(by_source={"upwork": 1}))
        self.assertEqual(p.discover(sources=["upwork"]), ["opp-1"])

    def test_a_scheduler_failure_cannot_break_a_scan(self):
        """Telemetry must never be load-bearing."""
        p = self._harness(_Stats(by_source={"upwork": 5}), scheduler_raises=True)
        self.assertEqual(p.discover(sources=["upwork"]), ["opp-1"],
                         "a failure in scheduler feedback aborted discovery")

    def test_no_stats_means_no_feedback_but_no_crash(self):
        """A source layer that returns no stats object must not raise."""
        p = self._harness(None)
        self.assertEqual(p.discover(sources=["upwork"]), ["opp-1"])


class TestTheStatsAreNoLongerDiscarded(unittest.TestCase):
    """A retained attribute is only useful if it is retained."""

    def test_discovery_service_keeps_last_stats(self):
        src = DISCOVERY.read_text(encoding="utf-8")
        self.assertRegex(src, r"self\.last_stats\s*=\s*_stats",
                         "the scan statistics are discarded again; the "
                         "scheduler has nothing to learn from")

    def test_last_stats_exists_before_the_first_scan(self):
        """Otherwise `hasattr` checks are meaningless."""
        src = DISCOVERY.read_text(encoding="utf-8")
        self.assertIn("self.last_stats = None", src,
                      "last_stats is only created inside discover(), so "
                      "reading it before a scan raises AttributeError")

    def test_the_binding_is_not_the_discard_name(self):
        """`_stats` is the convention for 'not used'. Bind the value."""
        src = DISCOVERY.read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "discover")
        # `self.last_stats = _stats` targets an Attribute, not a Name, so both
        # forms have to be collected or this guard passes vacuously.
        targets = []
        for n in ast.walk(fn):
            if not isinstance(n, ast.Assign):
                continue
            for t in n.targets:
                if isinstance(t, ast.Name):
                    targets.append(t.id)
                elif isinstance(t, ast.Attribute):
                    targets.append(t.attr)
        self.assertIn("last_stats", targets,
                      f"last_stats is never assigned in discover(); "
                      f"assignments are {sorted(set(targets))}")


class TestEveryWebToolAnnounces(unittest.TestCase):
    """Part B -- the invisible-fetch gap."""

    def _web_tools(self):
        """(name, handler) for every tool that fetches a URL."""
        import agents.safety.handlers as H
        out = []
        for attr in dir(H):
            if attr.startswith("_tool_web_"):
                out.append((attr, getattr(H, attr)))
        return out

    def test_the_three_web_tools_exist(self):
        """Otherwise the loop below proves nothing."""
        names = {n for n, _ in self._web_tools()}
        self.assertEqual(names, {"_tool_web_search", "_tool_web_read",
                                 "_tool_web_check"},
                         f"web tool set changed: {sorted(names)} -- update "
                         f"this test, do not let it silently cover fewer tools")

    def test_every_web_tool_announces(self):
        """An agent fetch the operator cannot see is a fetch nobody approved."""
        for name, fn in self._web_tools():
            with self.subTest(tool=name):
                src = ast.unparse(ast.parse(
                    __import__("inspect").getsource(fn)))
                self.assertIn("_announce_agent_web", src,
                              f"{name} fetches a URL but never announces it; "
                              f"the operator sees no trace of the request")

    def test_web_check_announces_with_its_own_kind(self):
        """So the activity log distinguishes a HEAD probe from a body read."""
        import inspect
        import agents.safety.handlers as H
        src = inspect.getsource(H._tool_web_check)
        self.assertIn('"agent web_check"', src,
                      "web_check announces under the wrong label, so the "
                      "operator cannot tell a probe from a page read")

    def test_the_announcement_happens_after_the_ssrf_guard(self):
        """A refused URL must not be announced as if it were fetched.

        Order matters: guard, then announce. Announcing first would put a URL
        in the operator's log that was never actually requested.
        """
        import inspect
        import agents.safety.handlers as H
        src = inspect.getsource(H._tool_web_check)
        self.assertLess(src.index("require_safe_fetch_url"),
                        src.index("_announce_agent_web"),
                        "web_check announces BEFORE the SSRF guard runs, so a "
                        "refused URL still appears in the operator's log")

    def test_web_check_still_refuses_unsafe_urls(self):
        """The announce must not have displaced the guard."""
        import agents.safety.handlers as H
        out = H._tool_web_check({"url": "http://127.0.0.1:22/"})
        self.assertNotIn("Online", str(out),
                         "a loopback URL was probed after the change")


if __name__ == "__main__":
    unittest.main()