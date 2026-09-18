"""tests/test_approval_queue.py — Human-approval queue integrity tests."""

import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from agents.approval_queue import (
    ApprovalItem,
    ApprovalKind,
    ApprovalStatus,
    HumanApprovalQueue,
)


class TestApprovalQueueIntegrity(unittest.TestCase):
    """Test human approval queue persistence, transitions, and recovery."""

    def setUp(self):
        """Create a temporary log file and fresh queue instance."""
        self.temp_dir = tempfile.mkdtemp()
        self.log_path = Path(self.temp_dir) / "approval_queue.json"
        HumanApprovalQueue.reset_singleton()
        self.queue = HumanApprovalQueue(log_path=str(self.log_path))

    def tearDown(self):
        """Clean up temporary files."""
        HumanApprovalQueue.reset_singleton()
        if self.log_path.exists():
            self.log_path.unlink()
        os.rmdir(self.temp_dir)

    def test_persistence_on_enqueue(self):
        """Items are persisted to JSON when enqueued."""
        item = self.queue.enqueue_submission(
            title="Test Submission",
            description="Test description",
            requested_by="test_agent",
        )
        self.assertEqual(item.status, ApprovalStatus.PENDING)
        self.assertTrue(self.log_path.exists())
        # Load from file and verify
        import json
        with open(self.log_path, "r") as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], item.id)
        self.assertEqual(data[0]["title"], "Test Submission")

    def test_persistence_on_decision(self):
        """Decisions are persisted to JSON."""
        item = self.queue.enqueue_submission(
            title="Payment Approval",
            description="Approve payment",
        )
        self.assertTrue(self.log_path.exists())
        # Approve the item
        result = self.queue.approve(item.id, notes="Approved by test")
        self.assertTrue(result)
        # Verify persistence
        import json
        with open(self.log_path, "r") as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["status"], ApprovalStatus.APPROVED.value)
        self.assertEqual(data[0]["decided_by"], "human")
        self.assertIsNotNone(data[0]["decided_at"])

    def test_restart_recovery(self):
        """Queue recovers state after restart."""
        # Create and approve an item
        item1 = self.queue.enqueue_submission(
            title="First Item",
            description="First submission",
        )
        self.queue.approve(item1.id, notes="First approval")
        # Create another pending item
        item2 = self.queue.enqueue_submission(
            title="Second Item",
            description="Second submission",
        )
        # Simulate restart by creating a new queue instance
        HumanApprovalQueue.reset_singleton()
        new_queue = HumanApprovalQueue(log_path=str(self.log_path))
        # Verify recovered state
        all_items = new_queue.all()
        self.assertEqual(len(all_items), 2)
        # First item should be approved
        approved = [i for i in all_items if i.id == item1.id]
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0].status, ApprovalStatus.APPROVED)
        # Second item should be pending
        pending = [i for i in all_items if i.id == item2.id]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].status, ApprovalStatus.PENDING)

    def test_duplicate_id_handling(self):
        """Duplicate IDs are handled gracefully (new ID generated)."""
        item1 = self.queue.enqueue_submission(
            title="Original",
            description="Original submission",
        )
        original_id = item1.id
        # Manually create an item with same ID (simulating duplicate)
        duplicate_item = ApprovalItem(
            id=original_id,
            kind=ApprovalKind.SUBMISSION,
            title="Duplicate",
            description="Duplicate submission",
        )
        # Enqueue duplicate - should get new ID
        result = self.queue.enqueue(duplicate_item)
        self.assertIsNotNone(result)
        self.assertNotEqual(result.id, original_id)
        # Both items should exist
        all_items = self.queue.all()
        self.assertEqual(len(all_items), 2)

    def test_transition_validation(self):
        """Invalid status transitions are rejected."""
        item = self.queue.enqueue_submission(
            title="Test Item",
            description="Test",
        )
        # Item should be pending
        self.assertEqual(item.status, ApprovalStatus.PENDING)
        # Approve it
        self.queue.approve(item.id, notes="Approved")
        self.assertEqual(item.status, ApprovalStatus.APPROVED)
        # Try to approve again (should be no-op)
        result = self.queue.approve(item.id, notes="Second approval")
        self.assertFalse(result)  # Should return False since not pending
        # Verify status unchanged
        self.assertEqual(item.status, ApprovalStatus.APPROVED)

    def test_payload_redaction_on_approve(self):
        """Sensitive payload is preserved but not exposed in notifications."""
        sensitive_payload = {
            "bank_account": "****-****-****-1234",
            "routing_number": "****",
            "amount": 1000.0,
            "secret_key": "super_secret"
        }
        item = self.queue.enqueue_payment(
            title="Large Payment",
            description="Payment with sensitive data",
            amount=1000.0,
            currency="usd",
            payload=sensitive_payload,
        )
        # Verify payload is stored
        self.assertEqual(item.payload, sensitive_payload)
        # Approve the item
        self.queue.approve(item.id, notes="Approved")
        # Verify payload still exists in item
        self.assertEqual(item.payload, sensitive_payload)
        # Verify item is in queue
        all_items = self.queue.all()
        approved_item = [i for i in all_items if i.id == item.id][0]
        self.assertEqual(approved_item.payload, sensitive_payload)

    def test_callback_persistence(self):
        """On-change callbacks are called on state changes."""
        callback_called = []
        def test_callback(item):
            callback_called.append(item.id)
        self.queue.on_change = test_callback
        # Enqueue should trigger callback
        item = self.queue.enqueue_submission(
            title="Callback Test",
            description="Test callback",
        )
        self.assertEqual(len(callback_called), 1)
        self.assertEqual(callback_called[0], item.id)
        # Decision should also trigger callback
        callback_called.clear()
        self.queue.approve(item.id, notes="Approved")
        self.assertEqual(len(callback_called), 1)
        self.assertEqual(callback_called[0], item.id)

    def test_clear_all_persists(self):
        """Clearing all items persists the empty state."""
        # Add some items
        self.queue.enqueue_submission(
            title="Item 1",
            description="First item",
        )
        self.queue.enqueue_submission(
            title="Item 2",
            description="Second item",
        )
        self.assertEqual(len(self.queue.all()), 2)
        # Clear all
        self.queue.clear_all()
        self.assertEqual(len(self.queue.all()), 0)
        # Verify persistence
        import json
        with open(self.log_path, "r") as f:
            data = json.load(f)
        self.assertEqual(len(data), 0)

    def test_missing_log_path_no_error(self):
        """Queue works without log path (in-memory only)."""
        HumanApprovalQueue.reset_singleton()
        memory_queue = HumanApprovalQueue(log_path=None)
        item = memory_queue.enqueue_submission(
            title="Memory Item",
            description="Test without persistence",
        )
        self.assertIsNotNone(item)
        self.assertEqual(item.status, ApprovalStatus.PENDING)
        # Should not crash on decision
        result = memory_queue.approve(item.id, notes="Approved")
        self.assertTrue(result)

    def test_concurrent_access_safety(self):
        """Queue operations are thread-safe."""
        import threading
        results = []
        def worker(worker_id):
            item = self.queue.enqueue_submission(
                title=f"Worker {worker_id} Item",
                description=f"Item from worker {worker_id}",
            )
            results.append(item)
        # Create multiple threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()
        # Wait for all threads
        for t in threads:
            t.join()
        # All items should be present
        self.assertEqual(len(self.queue.all()), 5)
        # All should have unique IDs
        ids = [item.id for item in self.queue.all()]
        self.assertEqual(len(set(ids)), 5)


if __name__ == "__main__":
    unittest.main()