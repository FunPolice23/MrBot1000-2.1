"""ARCH-ENG-243 / BD-01 + BD-02 -- the typed event emitters are LIVE.

The finding
-----------
``StructuredEventLogger`` carried four typed helpers: earning_event,
safety_event, llm_spend_event and heartbeat_event. ZERO of them were ever
called in production, so the Insights panel's KPIs -- the ones it derives
from the typed event log (spend via llm_spend est_usd, "Safety incidents"
via blocked safety warnings, the outcomes table via earning events) -- read
a log that nothing ever wrote. (The Phase-4 KPI test emitted the events
itself, which proved the READERS were wired and said nothing about the
producers.) Disposition (operator): wire earning_event, safety_event and
llm_spend_event; heartbeat_event is REMOVED -- it reported the legacy
manager heartbeat the runtime already retired (main.py keeps only a no-op
stub), and leaving the emitter would be BG-01's shape again: an interface
to a thing that does not exist.

The wired producers:

- llm_spend_event: big_brain / small_brain / worker_llm_mixin, at the same
  completion point where the call is recorded into llm_calls, using the
  same cost pricer (estimate_call_cost). Cost > 0 only -- local/unpriced
  calls stay 0.0 and are recorded in llm_calls, matching the panel's
  "Cloud API cost only" spend basis; the KPI's sum is unchanged by this.
- safety_event: the CostGuard trip (enforcement_skip_decision -- a single
  contract point feeding both brain adapters) and the filesystem write
  gate (safe_write_file's refusals, via one _blocked_signal helper).
- earning_event: the earning pipeline's finalize step
  (_record_strategy_outcome), receiving the LIFECYCLE'S EFFECTIVE values
  -- a payment verified down arrives with revenue 0, so the panel can
  never display a win the ledger refused.

Vacuity: against the pre-fix sources, every source-scan below fails while
the emitters are dead; the behavioral filesystem/cost-guard assertions
fail because no typed event is produced by a refusal/trip.
"""

import ast
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]

EVENT_LOGGER = REPO / "agents" / "core" / "event_logger.py"
BIG_BRAIN = REPO / "agents" / "brains" / "big_brain.py"
SMALL_BRAIN = REPO / "agents" / "brains" / "small_brain.py"
WORKER_MIXIN = REPO / "agents" / "brains" / "worker_llm_mixin.py"
COST = REPO / "agents" / "safety" / "cost.py"
FILESYSTEM = REPO / "agents" / "safety" / "filesystem.py"
PIPELINE = REPO / "app" / "earning_pipeline.py"
INSIGHTS = REPO / "gui" / "tabs" / "earning_insights.py"


def _src(path):
    return path.read_text(encoding="utf-8")


class TheHeartbeatEmitterIsGone(unittest.TestCase):
    """Disposition: heartbeat_event REMOVED with its legacy system."""

    def test_no_emitter_and_no_enum_member(self):
        src = _src(EVENT_LOGGER)
        self.assertNotIn("def heartbeat_event", src)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "EventType":
                members = [t.id for s in node.body
                           if isinstance(s, ast.Assign)
                           for t in s.targets
                           if isinstance(t, ast.Name)]
                self.assertNotIn(
                    "HEARTBEAT", members,
                    "the legacy heartbeat enumerator must not return")

    def test_the_liveness_note_is_at_the_helpers(self):
        src = _src(EVENT_LOGGER)
        for helper in ("earning_event", "safety_event", "llm_spend_event"):
            self.assertIn(f"def {helper}", src,
                          f"{helper} must remain defined")

    def test_alerting_does_not_filter_the_removed_event(self):
        """The default alert SET is constructed at startup (main.py):
        the survival-tier rule that filtered the removed HEARTBEAT event
        had to go with it."""
        src = (REPO / "agents" / "core" / "alerting.py").read_text(
            encoding="utf-8")
        self.assertNotIn("EventType.HEARTBEAT", src)
        self.assertNotIn("survival_tier_change_rule", src)

    def test_default_rules_still_construct_at_startup(self):
        """The concrete break the removal exposed: add_default_rules()
        raises AttributeError against the pre-fix alerting module
        (construction dereferences EventType.HEARTBEAT)."""
        import sys
        for mod in list(sys.modules):
            if mod.startswith("agents.core.alerting"):
                del sys.modules[mod]
        from agents.core.alerting import add_default_rules
        rules = add_default_rules()
        self.assertGreaterEqual(len(rules), 4)


class TheSpendEventsAreProduced(unittest.TestCase):
    """llm_spend_event fires where the call completes, with the same cost
    basis the DB records."""

    def test_both_brains_emit_after_recording_the_call(self):
        for path in (BIG_BRAIN, SMALL_BRAIN):
            self.assertIn("llm_spend_event", _src(path),
                          f"{path.name} must emit the typed spend event")

    def test_the_worker_path_emits_with_the_shared_pricer(self):
        src = _src(WORKER_MIXIN)
        self.assertIn("llm_spend_event", src)
        self.assertIn("estimate_call_cost", src,
                      "the worker must use the same cost pricer as the "
                      "brains so both bill on one basis")

    def test_emission_is_cost_gated(self):
        """Local/unpriced calls estimate 0.0 and must NOT become spend
        events (the panel's spend basis is cloud API cost only)."""
        src = _src(BIG_BRAIN)
        self.assertRegex(src, r"if _call_cost > 0")

    def test_cost_guard_trips_become_typed_safety_events(self):
        src = _src(COST)
        self.assertIn("safety_event", src,
                      "the CostGuard trip must be a typed safety event")
        self.assertIn('gate_type="cost_guard"', src)


class TheFilesystemGateReportsTypedBlocks(unittest.TestCase):

    def test_one_helper_reports_both_channels(self):
        src = _src(FILESYSTEM)
        self.assertIn("def _blocked_signal", src)
        helper_start = src.index("def _blocked_signal")
        helper_body = src[helper_start:src.find("def safe_write_file")]
        self.assertIn("safety_event", helper_body,
                      "the helper must emit the typed safety event")
        self.assertIn('gate_type="filesystem_write"', helper_body)
        # AND the old silent shape must be gone: no BLOCKED refusal returns
        # a bare False without the typed report.
        self.assertNotRegex(
            src[helper_start:],
            r'log_signal\.emit\(\s*f?"BLOCKED:[^)]*\)\s*\n\s*return\s+False',
            "a BLOCKED refusal that skips the typed report remained")

    def test_all_safe_write_refusals_route_through_the_helper(self):
        body = _src(FILESYSTEM)
        start = body.index("def safe_write_file")
        end = body.index("# Backup-before-edit")
        section = body[start:end]
        self.assertEqual(
            section.count("return self._blocked_signal("), 6,
            "every refusal above the backup step must report typed")


class TheEarningFinalizeReports(unittest.TestCase):

    def test_the_pipeline_finalize_emits_earning_event(self):
        src = _src(PIPELINE)
        start = src.index("def _record_strategy_outcome")
        body = src[start:src.index("def _feed_self_improvement")]
        self.assertIn("earning_event", body,
                      "a finalized outcome must produce a typed earning event")
        self.assertIn("effective", body.lower(),
                      "the emission must document that lifecycle-effective "
                      "values arrive")


class TheReadersStillMatchTheProducers(unittest.TestCase):

    def test_insights_keeps_its_wired_filters(self):
        src = _src(INSIGHTS)
        self.assertIn('event_type="llm_spend"', src)
        self.assertIn('event_type="safety"', src)
        self.assertIn('"earning"', src)
        # ...and its removed legacy does not come back as a dead reader.
        self.assertNotIn("last_event_of_type(\"heartbeat\")", src)
        self.assertNotIn("def set_heartbeat", src)
        self.assertNotIn("def set_tier", src)


class TheWiringBehaves(unittest.TestCase):
    """Behavioral: a typed refusal/trip actually lands in the shared log."""

    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    def test_filesystem_block_produces_a_safety_event(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from agents.safety.filesystem import WorkerFilesystemMixin
        from agents.core.event_logger import StructuredEventLogger

        class Mixin(WorkerFilesystemMixin):
            def __init__(self):
                class Sig:
                    emitted = []
                    def emit(self, text):
                        self.emitted.append(text)
                self.log_signal = Sig()
                self.max_file_size = 10 * 1024 * 1024

        el = StructuredEventLogger.instance()
        el.clear_in_memory()
        m = Mixin()
        # A PROTECTED app source: refused by the protected-source gate
        # (fires on the basename, before any path resolution), so the
        # exact refusal reason is deterministic.
        ok = m.safe_write_file("action_pipeline.py", "print('hi')\n")
        self.assertFalse(ok, "a protected app source must still be refused")
        events = [e for e in el.query(event_type="safety", limit=50)
                  if (e.details or {}).get("gate_type") == "filesystem_write"]
        self.assertEqual(
            len(events), 1,
            f"the refusal must produce exactly one typed safety event "
            f"({len(events)} found)")
        self.assertTrue(events[0].details["blocked"])
        self.assertIn("protected app source", events[0].details["description"])

    def test_cost_guard_trip_produces_a_safety_event(self):
        import os
        from unittest import mock
        from agents.safety.cost import enforcement_skip_decision
        from agents.core.event_logger import StructuredEventLogger

        class DB:
            def get_llm_cost_usd(self, days):
                return 9.0

        env = {"LLM_DAILY_BUDGET_USD": "5.0"}
        el = StructuredEventLogger.instance()
        el.clear_in_memory()
        with mock.patch.dict(os.environ, env, clear=False):
            skip, reason = enforcement_skip_decision("openai", DB())
        self.assertTrue(skip)
        events = [e for e in el.query(event_type="safety", limit=50)
                  if (e.details or {}).get("gate_type") == "cost_guard"]
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].details["blocked"])

    def test_cost_guard_pass_produces_no_event(self):
        """The pass path stays silent: telemetry volume belongs to trips."""
        import os
        from unittest import mock
        from agents.safety.cost import enforcement_skip_decision
        from agents.core.event_logger import StructuredEventLogger

        class QuietDB:
            def get_llm_cost_usd(self, days):
                return 0.0

        env = {"LLM_DAILY_BUDGET_USD": "5.0"}
        el = StructuredEventLogger.instance()
        el.clear_in_memory()
        with mock.patch.dict(os.environ, env, clear=False):
            skip, _ = enforcement_skip_decision("openai", QuietDB())
        self.assertFalse(skip)
        events = [e for e in el.query(event_type="safety", limit=50)
                  if (e.details or {}).get("gate_type") == "cost_guard"]
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
