"""ARCH-ENG-247 / AN-02 -- bus cancellation is WIRED, first production use.

The finding (11u)
-----------------
`publish(msg, token=...)` stored a token into `_tokens` / `_tokens_by_corr`,
`_prune` bounded them, `cancel()` looked them up, and `CancellationToken`
provided `cancel`/`wait`/`cancelled` -- but NO production call site ever
passed `token=`, `get_token` (the only constructor) was dead, and -- the
deeper defect -- `_deliver` never READ the token at all. So `cancel()` could
return True while changing absolutely nothing: a documented bus feature
("Cancellation (via CancellationToken)") that was unreachable AND inert.

Operator disposition: WIRE IT (not delete).

The wire, honestly
------------------
Cancellation needs three things to be real, and all three now exist:

1. A PUBLISHER. The dual-brain coordinator's docstring claimed every stage
   "publishes a typed REQUEST then a typed RESULT on the EventBus", but its
   `_record` only wrote the local MessageLog -- the bus had zero production
   publishers and its one subscriber (QtEventBridge) had nothing to read.
   `_record` now publishes (guarded: bus delivery cannot break orchestration).

2. AN OWNER OF A TOKEN. Each run gets `bus.get_token(correlation_id)`;
   every stage message is published with it.

3. A CONSUMER THAT PULLS IT, AND DELIVERY THAT HONOURS IT. `_deliver`
   consults the token before and between handlers (a cancelled correlation's
   remaining deliveries are refused and counted in `cancelled_drops`), and
   `collaborate` checks it at every stage boundary. The Collaboration tab
   grew a Stop button: it cancels the active run, the handoff stops before
   the next stage (so no further model money is spent), and the terminal
   run update is published outside the token so the operator still SEES the
   cancellation.

Scope statement: cancellation is cooperative. A stage's model call is
synchronous and is never interrupted mid-call -- the token is checked at
safe points, which is what a cancellation token is for.

Vacuity: against the pre-fix sources, `_deliver` ignores a cancelled token
(the mid-delivery handler still receives), `cancel_active_run` does not
exist, and the source scans fail.
"""

import inspect
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
COMMS = REPO / "agents" / "core" / "comms.py"
COORDINATOR = REPO / "agents" / "cognition" / "coordinator.py"
TAB = REPO / "gui" / "tabs" / "collaboration_tab.py"


class TheBusHonoursCancellation(unittest.TestCase):

    def test_delivery_consults_the_token(self):
        src = COMMS.read_text(encoding="utf-8")
        start = src.index("def _deliver")
        body = src[start:src.index("def _is_cancelled")]
        self.assertIn("_is_cancelled(msg)", body,
                      "delivery must consult the token, not just store it")
        self.assertIn("cancelled_drops", body,
                      "a refused delivery must be observable")

    def test_a_cancelled_correlation_stops_remaining_handlers(self):
        """Behavioral: handler 1 cancels the chain; handler 2 must not run.
        Pre-fix this test fails -- the token was set and ignored."""
        from agents.core.comms import EventBus, Message, MessageType
        bus = EventBus()
        seen = []

        def first(msg):
            seen.append("first")
            # A handler cancelling its own correlation: the cooperative case.
            self.assertTrue(bus.cancel(msg.correlation_id, "stop the chain"))

        def second(msg):
            seen.append("second")

        bus.subscribe(first)
        bus.subscribe(second)
        token = bus.get_token("corr-247")
        msg = Message(
            message_type=MessageType.NOTIFICATION,
            source="test", destination="gui",
            correlation_id="corr-247", payload={"text": "hello"})
        bus.publish(msg, token=token)
        self.assertIn("first", seen)
        self.assertNotIn("second", seen,
                         "a cancelled chain must not reach later handlers")
        self.assertGreaterEqual(bus.snapshot()["cancelled_drops"], 1)

    def test_a_cancel_before_publish_delivers_nothing(self):
        from agents.core.comms import EventBus, Message, MessageType
        bus = EventBus()
        seen = []
        bus.subscribe(lambda m: seen.append(m.message_id))
        token = bus.get_token("corr-247b")
        token.cancel("cancelled before delivery")
        msg = Message(
            message_type=MessageType.NOTIFICATION, source="test",
            destination="gui", correlation_id="corr-247b", payload={})
        bus.publish(msg, token=token)
        self.assertEqual(seen, [])


class TheRunIsCancellable(unittest.TestCase):

    def _coordinator(self, bus, model_fn):
        from agents.cognition.coordinator import DualBrainCoordinator
        from agents.core.comms import MessageType
        from agents.runtime.dual_brain import DualBrainRuntime
        from agents.core.comms_log import MessageLog
        return DualBrainCoordinator(
            runtime=DualBrainRuntime.from_env({}),
            model_fn=model_fn, bus=bus, log=MessageLog(":memory:"))

    def test_cancel_between_stages_stops_the_handoff(self):
        """The operator's Stop lands after stage 1: stage 2 must never run
        (that is the money-saving point of the token)."""
        from agents.cognition.coordinator import CollaborationStage
        from agents.core.comms import EventBus
        bus = EventBus()
        calls = []

        def model_fn(role, stage, prompt):
            calls.append(stage.value)
            if len(calls) == 1:
                self.assertTrue(coord.cancel_active_run("operator stop"))
            return f"result of {stage.value}"

        coord = self._coordinator(bus, model_fn)
        run = coord.collaborate(
            "earn 500", stages=[CollaborationStage.PLAN,
                                CollaborationStage.RESEARCH])
        self.assertEqual(calls, ["plan"],
                         "no stage may run after the cancel")
        self.assertEqual(run.status.value, "CANCELLED")
        self.assertEqual(len(run.stages), 1)
        self.assertIn("operator stop", run.error)

    def test_the_cancellation_is_still_visible(self):
        """The terminal run update must be delivered outside the token --
        an operator who stops a run still needs to see it stopped."""
        from agents.cognition.coordinator import CollaborationStage
        from agents.core.comms import EventBus, MessageType
        bus = EventBus()
        terminal = []

        def model_fn(role, stage, prompt):
            coord.cancel_active_run("stop")
            return "x"

        def record(msg):
            if msg.message_type == MessageType.AUTONOMOUS_RUN_UPDATE:
                terminal.append(msg.payload)

        bus.subscribe(record)
        coord = self._coordinator(bus, model_fn)
        coord.collaborate("earn 1", stages=[CollaborationStage.PLAN])
        self.assertTrue(terminal, "the cancelled run's update must arrive")
        self.assertEqual(terminal[-1]["run"]["status"], "CANCELLED")

    def test_cancel_with_no_active_run_is_a_no_op(self):
        from agents.core.comms import EventBus
        coord = self._coordinator(EventBus(), lambda r, s, p: "ok")
        self.assertFalse(coord.cancel_active_run("nothing to stop"))
        self.assertFalse(coord.cancel_run("missing-run-id"))


class TheOperatorHasAStop(unittest.TestCase):

    def test_the_tab_exposes_stop(self):
        src = TAB.read_text(encoding="utf-8")
        for token in ("stop_btn", "_stop_collaboration",
                      "cancel_active_run"):
            self.assertIn(token, src)
        # Stop must actually reach the coordinator, not just disable itself.
        fn = src[src.index("def _stop_collaboration"):
                 src.index("def _on_run_done")]
        self.assertIn("cancel_active_run", fn)

    def test_the_coordinator_publishes_stage_messages(self):
        """The bus's first live publisher: the docstring claim this class
        always made is now true (it only logged before)."""
        src = COORDINATOR.read_text(encoding="utf-8")
        start = src.index("def _record")
        body = src[start:src.index("def active_run_id")]
        self.assertIn("self.bus.publish(msg, token=token)", body)


if __name__ == "__main__":
    unittest.main()
