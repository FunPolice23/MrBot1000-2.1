"""
test_comms_integration.py — Real Manager/Summarizer/EarningPipeline bus wiring.

Exercises the ACTUAL classes (not mocks of the protocol) end-to-end:
  GUI -> bus USER_REQUEST -> Chat(Summarizer) -> bus TASK_REQUEST -> Manager
  -> bus TASK_RESULT/MODEL_RESULT -> correlated reply.

No LLM is invoked: the CEO/LLM/IO paths are stubbed with deterministic fakes
so the test asserts the *structured routing + correlation*, which is the part
the redesign changed. The bus protocol itself is covered in test_comms.py.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.comms import EventBus, Message, MessageType, MessageStatus
import manager as M
import agents.summarizer as S
import earning_pipeline as EP


class FakeWorker:
    research_folder = None
    def llm(self, *a, **k):
        return "stub"
    def research_all(self):
        return {}


class TestGuiToChatWiring(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus.reset_instance()
        self.sum = S.SummarizerThread(FakeWorker(), db=None, manager=None)

    def test_user_request_reaches_chat_queue_with_correlation(self):
        req = Message(MessageType.USER_REQUEST, "gui", "chat", payload={"text": "hi"})
        self.bus.publish(req)
        item = self.sum._chat_queue.get_nowait()
        self.assertIsInstance(item, Message)
        self.assertEqual(item.message_id, req.message_id)
        self.assertEqual(item.correlation_id, req.correlation_id)


class TestChatRoutesTaskToManager(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus.reset_instance()
        self.mgr = M.ManagerThread(api_key="x", worker=FakeWorker(), db=None)
        self.sum = S.SummarizerThread(FakeWorker(), db=None, manager=self.mgr)
        self.captured = []
        self.bus.subscribe_type(MessageType.TASK_REQUEST, lambda m: self.captured.append(m))

    def test_task_intent_publishes_structured_task_request(self):
        # Force the router to classify this as a manager/task intent.
        self.sum._chat_router.classify = lambda text: type(
            "D", (), {"route_to": "manager", "use_main_model": True, "reason": "task"})()
        req = Message(MessageType.USER_REQUEST, "gui", "chat", payload={"text": "fix the bug"})
        # Simulate the chat thread dequeuing the bus message and handling it.
        self.sum._handle_chat(req.text(), bus_msg=req)
        self.assertEqual(len(self.captured), 1)
        task = self.captured[0]
        self.assertEqual(task.message_type, MessageType.TASK_REQUEST)
        self.assertEqual(task.source, "chat")
        self.assertEqual(task.destination, "manager")
        self.assertEqual(task.correlation_id, req.correlation_id)
        self.assertEqual(task.parent_message_id, req.message_id)


class TestManagerBusReplyCorrelated(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus.reset_instance()
        self.mgr = M.ManagerThread(api_key="x", worker=FakeWorker(), db=None)
        # Stub the CEO/LLM/IO so no model call happens.
        self.mgr._get_research = lambda: {}
        self.mgr._build_context = lambda *a, **k: ""
        self.mgr._ceo_decide = lambda *a, **k: "NO_ACTION: handled in test"
        self.mgr._llm_call = lambda *a, **k: "manager says hi"
        self.mgr._execute_with_worker = lambda *a, **k: ("done", True, None)
        self.results = []
        self.bus.subscribe_type(MessageType.MODEL_RESULT, lambda m: self.results.append(m))
        self.bus.subscribe_type(MessageType.TASK_RESULT, lambda m: self.results.append(m))

    def test_manager_replies_with_correlation(self):
        req = Message(MessageType.TASK_REQUEST, "chat", "manager",
                      payload={"text": "do thing"})
        self.mgr.msg_queue.put(req)
        self.mgr._handle_bus_message(req)
        self.assertEqual(len(self.results), 1)
        res = self.results[0]
        self.assertEqual(res.correlation_id, req.correlation_id)
        self.assertEqual(res.parent_message_id, req.message_id)
        self.assertEqual(res.source, "manager")
        self.assertEqual(res.destination, "chat")


class TestOpportunityUpdateReachesGui(unittest.TestCase):
    def test_earning_pipeline_emits_update(self):
        bus = EventBus.reset_instance()
        gui = []
        bus.subscribe_type(MessageType.OPPORTUNITY_UPDATE, lambda m: gui.append(m))
        import tempfile, shutil
        tmp = tempfile.mkdtemp(prefix="hermes-comms-int-")
        try:
            ep = EP.EarningPipeline(db_path=os.path.join(tmp, "ep.db"))
            o = EP.Opportunity(id="opZ", source="social", type="gig", platform="Reddit",
                               payment_type="usd", estimated_usd_value=5.0, min_amount=5.0,
                               url="https://x", found_at=0.0)
            ep.track_opportunity(o, "failed", note="int")
            self.assertEqual(len(gui), 1)
            self.assertEqual(gui[0].payload["opportunity_id"], "opZ")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestNoCircularLoopEndToEnd(unittest.TestCase):
    def test_chat_manager_chat_bounce_rejected(self):
        bus = EventBus.reset_instance()
        mgr = M.ManagerThread(api_key="x", worker=FakeWorker(), db=None)
        # gui -> chat USER_REQUEST
        req = Message(MessageType.USER_REQUEST, "gui", "chat", payload={"text": "q"})
        self.assertTrue(bus.publish(req))
        # chat -> manager TASK_REQUEST (correlated)
        task = req.derive(MessageType.TASK_REQUEST, source="chat", destination="manager")
        self.assertTrue(bus.publish(task))
        # manager would bounce a TASK_REQUEST back to chat (same correlation):
        # this replays the (manager,chat) edge -> rejected.
        bounce = task.derive(MessageType.TASK_REQUEST, source="manager", destination="chat")
        ok = bus.publish(bounce)
        self.assertFalse(ok)
        self.assertGreaterEqual(bus.loop_violations, 1)


class TestQtEventBridge(unittest.TestCase):
    """P4: the Qt delivery bridge must re-emit every bus Message as a Qt signal
    on the GUI thread so widgets observe events without model internals."""
    def test_bridge_reemits_bus_messages(self):
        # NOTE: do NOT create a QCoreApplication here. Qt allows only one
        # application instance per process; a QCoreApplication created here
        # poisons later GUI tests, whose QApplication.instance() would then
        # return that non-GUI app and crash when building QWidgets. QtEventBridge
        # is a QObject with a direct, same-thread signal, so it works without an
        # application instance.
        from agents.comms import QtEventBridge
        bus = EventBus.reset_instance()
        bridge = QtEventBridge(bus=bus, parent=None)
        received = []
        bridge.message.connect(lambda m: received.append(m))
        bus.publish(Message(MessageType.OPPORTUNITY_UPDATE, "earning_pipeline",
                            "gui", payload={"opportunity_id": "opQ", "current_stage": "paid"}))
        # QtEventBridge subscribes synchronously, so delivery is immediate.
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].payload["opportunity_id"], "opQ")


if __name__ == "__main__":
    unittest.main()
