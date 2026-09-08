"""tests/test_dual_brain_coordinator.py — Canonical cross-model collaboration (v2.1).

Offline/mock-first: a fake model_fn replaces inference, so the typed, durable,
cycle-safe handoff protocol is verified with no network/model or QApplication.
"""

import unittest

from agents.comms import EventBus, Message, MessageType, MessageStatus
from agents.comms_log import MessageLog
from agents.dual_brain_runtime import BrainRole, DualBrainRuntime
from agents.dual_brain_coordinator import (
    CollaborationStage,
    DualBrainCoordinator,
    RunRecord,
    StageRun,
    STAGE_ROLES,
    STAGE_REQUEST_TYPE,
    STAGE_RESULT_TYPE,
)


def _fresh_coordinator(model_fn=None, stages=None):
    bus = EventBus.reset_instance()
    log = MessageLog(":memory:")
    return DualBrainCoordinator(
        runtime=DualBrainRuntime.from_env({}),
        model_fn=model_fn,
        bus=bus,
        log=log,
        stage_roles=stages,
    )


class TestProtocol(unittest.TestCase):
    def test_message_types_registered(self):
        # Request types must be request-typed; result types result-typed.
        for stage in CollaborationStage:
            self.assertIn(STAGE_REQUEST_TYPE[stage], {
                MessageType.PLAN_REQUEST, MessageType.RESEARCH_REQUEST,
                MessageType.REVIEW_REQUEST, MessageType.EXECUTION_REQUEST})
            self.assertIn(STAGE_RESULT_TYPE[stage], {
                MessageType.PLAN_RESULT, MessageType.RESEARCH_RESULT,
                MessageType.REVIEW_RESULT, MessageType.EXECUTION_RESULT})
        self.assertIn(MessageType.AUTONOMOUS_RUN_UPDATE,
                      MessageType.__members__.values())

    def test_stage_role_routing(self):
        self.assertEqual(STAGE_ROLES[CollaborationStage.PLAN], BrainRole.BIG)
        self.assertEqual(STAGE_ROLES[CollaborationStage.RESEARCH], BrainRole.SMALL)
        self.assertEqual(STAGE_ROLES[CollaborationStage.REVIEW], BrainRole.BIG)
        self.assertEqual(STAGE_ROLES[CollaborationStage.EXECUTE], BrainRole.SMALL)


class TestCollaborate(unittest.TestCase):
    def test_full_handoff_succeeds(self):
        calls = []

        def fake_model(role, stage, prompt):
            calls.append((role, stage))
            return f"{stage.value}-result"

        coord = _fresh_coordinator(model_fn=fake_model)
        run = coord.collaborate("Earn $500 this week")

        self.assertIsInstance(run, RunRecord)
        self.assertTrue(run.ok)
        self.assertEqual(run.status, MessageStatus.DONE)
        self.assertEqual(run.final_result, "execute-result")
        self.assertEqual(len(run.stages), 4)
        # Each stage hit the expected role.
        self.assertEqual(calls[0], (BrainRole.BIG, CollaborationStage.PLAN))
        self.assertEqual(calls[1], (BrainRole.SMALL, CollaborationStage.RESEARCH))
        self.assertEqual(calls[2], (BrainRole.BIG, CollaborationStage.REVIEW))
        self.assertEqual(calls[3], (BrainRole.SMALL, CollaborationStage.EXECUTE))
        # Every stage succeeded.
        self.assertTrue(all(s.success for s in run.stages))

    def test_stage_failure_fails_run_and_stops(self):
        def fail_after(role, stage, prompt):
            if stage == CollaborationStage.REVIEW:
                raise RuntimeError("red flag detected")
            return "ok"

        coord = _fresh_coordinator(model_fn=fail_after)
        run = coord.collaborate("go")

        self.assertFalse(run.ok)
        self.assertEqual(run.status, MessageStatus.FAILED)
        self.assertIn("review", run.error)
        # Plan + research ran; review failed; execute never ran.
        self.assertEqual([s.stage for s in run.stages],
                         [CollaborationStage.PLAN, CollaborationStage.RESEARCH,
                          CollaborationStage.REVIEW])
        self.assertFalse(run.stages[-1].success)


class TestDurableLedger(unittest.TestCase):
    def test_each_stage_persists_request_and_result(self):
        bus = EventBus.reset_instance()
        log = MessageLog(":memory:")
        coord = DualBrainCoordinator(
            runtime=DualBrainRuntime.from_env({}),
            model_fn=lambda role, stage, prompt: "ok",
            bus=bus, log=log,
        )
        run = coord.collaborate("persist me")
        # 4 stages x 2 (request+result) + 1 AUTONOMOUS_RUN_UPDATE terminal = 9.
        self.assertEqual(log.count(), 9)
        records = log.all()
        types = [r["message_type"] for r in records]
        for stage in CollaborationStage:
            self.assertIn(STAGE_REQUEST_TYPE[stage].value, types)
            self.assertIn(STAGE_RESULT_TYPE[stage].value, types)
        # Correlation id threads through every stage.
        for r in records:
            if r["message_type"].startswith("PLAN"):
                self.assertEqual(r["correlation_id"], run.correlation_id)

    def test_run_ledger_retrievable(self):
        coord = _fresh_coordinator(model_fn=lambda role, stage, prompt: "ok")
        run = coord.collaborate("ledger")
        self.assertIs(coord.get_run(run.run_id), run)
        self.assertEqual(len(coord.list_runs()), 1)
        d = run.to_dict()
        self.assertEqual(d["run_id"], run.run_id)
        self.assertEqual(len(d["stages"]), 4)


class TestLoopSafety(unittest.TestCase):
    def test_requests_are_cycle_safe_on_bus(self):
        # A coordinator request is a REQUEST_TYPES message, so the bus's
        # loop prevention applies (e.g. a self-routed request is rejected).
        bus = EventBus.reset_instance()
        coord = DualBrainCoordinator(
            runtime=DualBrainRuntime.from_env({}),
            model_fn=lambda role, stage, prompt: "ok",
            bus=bus,
            log=MessageLog(":memory:"),
        )
        # Re-publishing the same request message_id must be dedup'd.
        coord.collaborate("loop")
        run = coord.list_runs()[0]
        request = Message(
            message_type=MessageType.PLAN_REQUEST,
            source="coordinator", destination="big",
            correlation_id=run.correlation_id,
            payload={"run_id": run.run_id})
        # Fresh message_id -> accepted.
        self.assertTrue(bus.publish(request))
        request.message_id = request.message_id  # reuse same id (dedup)
        request.message_id = run.stages[0].request_id  # duplicate id
        # Re-publish of an already-delivered request id is rejected.
        self.assertFalse(bus.publish(request))


class TestCustomRouting(unittest.TestCase):
    def test_stage_roles_override(self):
        # Route research to BIG instead of SMALL.
        roles = dict(STAGE_ROLES)
        roles[CollaborationStage.RESEARCH] = BrainRole.BIG
        coord = _fresh_coordinator(
            model_fn=lambda role, stage, prompt: "ok", stages=roles)
        run = coord.collaborate("custom")
        research = next(s for s in run.stages if s.stage == CollaborationStage.RESEARCH)
        self.assertEqual(research.role, BrainRole.BIG)

    def test_subset_of_stages(self):
        coord = _fresh_coordinator(model_fn=lambda role, stage, prompt: "ok")
        run = coord.collaborate("subset", stages=[CollaborationStage.PLAN,
                                                  CollaborationStage.REVIEW])
        self.assertEqual(len(run.stages), 2)


if __name__ == "__main__":
    unittest.main()
