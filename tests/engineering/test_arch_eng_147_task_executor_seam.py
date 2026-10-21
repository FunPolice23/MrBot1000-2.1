"""ARCH-ENG-147 — the autonomous loop's execution stage could never run the task
executor, so every "executed" run silently executed nothing.

The ledger's standing P1: `AutonomousLoop._stage_execute` guards on
`hasattr(self.task_executor, 'run')` and then calls `self.task_executor.run(task)`.
`TaskExecutor` (`agents/earning/executor.py`) defines `execute(self, task, entry)`
and no `run` anywhere. OBSERVED by execution: `hasattr(TaskExecutor, 'run')` is
False, `hasattr(TaskExecutor, 'execute')` is True.

So the guard is permanently False, the stage falls into the `else` branch,
sets `error = "no_task_executor"` / `executed = False`, and the loop finalizes
"failed — Task execution was not completed" for a component that IS constructed
and fully wired at `app/earning_pipeline.py:166-170`. The failure message names a
missing component that is present, which is why it read as an infrastructure gap
rather than a wiring bug.

Two arity/shape mismatches accompany it, so a naive rename to `execute` is not
enough:
  * `execute` needs TWO positionals (`task`, `entry`) — the portfolio entry.
  * `execute` treats `task` as a DICT (`task.get("task_type")` at step 1,
    `task.get("required_capabilities")` at step 3), while the stage built a
    `Task` spec object. Passing the spec would raise AttributeError on `.get`.

The fix guards on `execute`, looks up the portfolio entry (the same way
`_stage_rerank` does), and passes the task as a dict. When no portfolio entry
exists the stage still fails CLOSED — it never fabricates a success.
"""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from agents.earning.executor import TaskExecutor


def _fake_opp(opp_id="opp-1"):
    return SimpleNamespace(
        id=opp_id,
        opportunity_id=opp_id,
        task_type="WRITING",
        required_skills=["writing"],
        estimated_effort=1.0,
        description="write a thing",
    )


def _facts(opp_id="opp-1"):
    return SimpleNamespace(
        opportunity_id=opp_id,
        provenance=SimpleNamespace(level="FACT"),
    )


class _RecordingExecutor:
    """Stands in for TaskExecutor and records exactly how it was called."""

    def __init__(self):
        self.calls = []

    def execute(self, task, entry):
        self.calls.append({"task": task, "entry": entry})
        return SimpleNamespace(success=True, errors=[], status="paid")


class TestStageExecuteReachesTheExecutor(unittest.TestCase):

    def _loop(self, executor, portfolio=None):
        from agents.services.autonomous_loop import AutonomousLoop

        return AutonomousLoop(
            SimpleNamespace(task_executor=executor, portfolio=portfolio)
        )

    def test_task_executor_exposes_execute_not_run(self):
        """The contract the guard must match — reproduces the mismatch."""
        self.assertTrue(hasattr(TaskExecutor, "execute"))
        self.assertFalse(hasattr(TaskExecutor, "run"))

    def test_stage_execute_calls_execute_with_task_and_entry(self):
        """The defect: the guard never matched, so `execute` was never called."""
        ex = _RecordingExecutor()
        entry = SimpleNamespace(opportunity_id="opp-1")
        portfolio = SimpleNamespace(
            load_all=lambda: [entry],
            get=lambda _id: entry,
        )
        result = SimpleNamespace(opportunity_id="opp-1", stages=[], errors=[])

        ok = self._loop(ex, portfolio=portfolio)._stage_execute(
            result, _fake_opp(), _facts()
        )

        self.assertTrue(ok, "stage must report the executor actually ran")
        self.assertEqual(len(ex.calls), 1, "execute() must be reached")
        # task must be a DICT (execute calls task.get(...)), not a Task spec object
        self.assertIsInstance(ex.calls[0]["task"], dict)
        self.assertEqual(ex.calls[0]["task"]["task_type"], "WRITING")
        # the portfolio entry must be handed through
        self.assertIs(ex.calls[0]["entry"], entry)

    def test_stage_execute_fails_closed_without_an_executor(self):
        """No executor must never become a success."""
        result = SimpleNamespace(opportunity_id="opp-1", stages=[], errors=[])
        ok = self._loop(None)._stage_execute(result, _fake_opp(), _facts())
        self.assertFalse(ok)
        self.assertTrue(
            any(s.stage == "execute" for s in result.stages),
            "the stage must still be recorded",
        )

    def test_stage_execute_fails_closed_when_executor_reports_failure(self):
        ex = _RecordingExecutor()

        class _Failing(_RecordingExecutor):
            def execute(self, task, entry):
                self.calls.append({"task": task, "entry": entry})
                return SimpleNamespace(success=False, errors=["boom"], status="failed")

        result = SimpleNamespace(opportunity_id="opp-1", stages=[], errors=[])
        ok = self._loop(_Failing(), portfolio=SimpleNamespace(load_all=lambda: []))._stage_execute(
            result, _fake_opp(), _facts()
        )
        self.assertFalse(ok)

    def test_no_site_still_probes_the_absent_run_method(self):
        """Every executor probe must use `execute`, or the two sites drift again.

        `AutonomousLoop.run` itself is the loop's own public entry point and is
        NOT part of this contract — only probes of `task_executor` matter.
        """
        import inspect
        import re

        from agents.services.autonomous_loop import AutonomousLoop

        src = inspect.getsource(AutonomousLoop)
        probes = re.findall(r"task_executor[^\n]*", src)
        self.assertTrue(probes, "expected to find the executor references")
        for probe in probes:
            if "hasattr" not in probe:
                continue
            self.assertIn(
                "execute", probe,
                f"an executor probe must test `execute`, not the absent `run`: {probe.strip()}",
            )
            self.assertNotRegex(probe, r"['\"]run['\"]")


if __name__ == "__main__":
    unittest.main()
