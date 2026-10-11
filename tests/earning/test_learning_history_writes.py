"""Regression test: processing an outcome populates learning_history so the
Self-Improvement tab shows real data (previously the table stayed empty)."""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture()
def loop():
    from app import earning_memory
    from app.earning_learning_loop import LearningLoop

    root = tempfile.mkdtemp()
    db = os.path.join(root, "earning_memory.db")
    memory = earning_memory.EarningMemory(db_path=db)
    yield LearningLoop(memory=memory), memory, db
    import shutil
    shutil.rmtree(root, ignore_errors=True)


def test_process_outcome_writes_learning_history(loop):
    learning_loop, memory, db = loop
    learning_loop.process_outcome(
        "opp_1",
        outcome_state="paid",
        platform="upwork",
        category="freelance",
        revenue=120.0,
        cost=10.0,
        evidence_ids=["ev_1"],
    )
    rows = memory.get_recent_learned(limit=10)
    assert len(rows) >= 1, "learning_history must be populated after an outcome"
    assert rows[0].get("type") == "outcome"
    assert "upwork" in rows[0]["insight"]


def test_rejected_outcome_does_not_write_learning_history(loop):
    learning_loop, memory, db = loop
    learning_loop.process_outcome("opp_2", outcome_state="invalid_state")
    rows = memory.get_recent_learned(limit=10)
    assert rows == [], "invalid outcome must not write a learning insight"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
