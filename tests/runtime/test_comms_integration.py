"""
test_comms_integration.py — EventBus + EarningPipeline bus wiring.

Exercises the ACTUAL EventBus/EarningPipeline (not mocks) end-to-end. The
Manager/Summarizer routing classes were removed in the legacy-worker cleanup
(v2.1.77); the surviving bus protocol + earning-pipeline event emission is
covered here. The bus protocol itself is covered in test_comms.py.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.core.comms import EventBus, Message, MessageType, MessageStatus
import app.earning_pipeline as EP


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
        # The bus loop-guard still rejects a replayed (manager,chat) edge even
        # though the Manager class is gone — the protocol invariant survives.
        bus = EventBus.reset_instance()
        req = Message(MessageType.USER_REQUEST, "gui", "chat", payload={"text": "q"})
        self.assertTrue(bus.publish(req))
        task = req.derive(MessageType.TASK_REQUEST, source="chat", destination="manager")
        self.assertTrue(bus.publish(task))
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
        from agents.core.comms import QtEventBridge
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
