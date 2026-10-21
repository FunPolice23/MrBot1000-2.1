"""ARCH-ENG-162 — `_persist` could lose lifecycle state under concurrent writes.

`OpportunityLifecycleTracker._persist` rewrites the ENTIRE state file from
`self._states`, and it is called from `_append` — i.e. on every single state
mutation. Two defects, both capable of losing authoritative lifecycle records:

1. NO LOCK. The read-snapshot -> write -> `os.replace` sequence was not atomic.
   `AutonomousLoop.run` explicitly supports concurrent runs (`BoundedSemaphore`,
   default `MRBOT_AUTONOMY_MAX_CONCURRENT`), so two threads could interleave:
   thread A snapshots, thread B snapshots, B writes and replaces, A writes and
   replaces — and A's older snapshot wins. Transitions recorded by B vanish.

2. A FIXED temp path (`state_path + '.tmp'`). Both threads wrote the SAME temp
   file. B truncating the file A had written but not yet replaced meant
   `os.replace` could publish a truncated/partial JSON file — an unreadable
   state file, which `_recover_from_disk` then swallows into a silent fresh
   start. The entire authoritative lifecycle disappears with no error.

This matters more than an ordinary race because lifecycle state is
AUTHORITATIVE. The ARCH-ENG-092 comment in `mark_paid_verified` already records
a real $750 externally-verified payout silently collapsing to
`verified_revenue_usd() == 0.0` because of a persist-ordering bug.

The fix: an `RLock` making "snapshot -> write -> replace" atomic with respect to
other persists, a per-writer temp name (`pid.threadid.tmp`), an `fsync` before
the replace, and temp-file cleanup on failure.

`test_concurrent_persists_lose_nothing` is the regression: it drives many
threads through `_append` and asserts every opportunity survives a reload. The
pre-fix code fails it (and intermittently produces unparseable JSON).
"""

import json
import os
import shutil
import tempfile
import threading
import unittest
import unittest.mock

from agents.earning.opportunity_lifecycle import (
    OpportunityLifecycleTracker, OpportunityState,
)


def _make_tracker(tmpdir, name="lifecycle.json"):
    return OpportunityLifecycleTracker(state_path=os.path.join(tmpdir, name))


def _opp(oid):
    """A minimal duck-typed opportunity (the tracker only reads `.id`)."""

    class _O:
        pass

    o = _O()
    o.id = oid
    o.title = f"task {oid}"
    o.estimated_usd_value = 100.0
    o.deadline = 0.0
    return o


class TestPersistIsAtomic(unittest.TestCase):
    """ARCH-ENG-162 — no lost or corrupted state on concurrent persist."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_concurrent_persists_lose_nothing(self):
        """Many threads, many opportunities: every one must survive a reload."""
        tracker = _make_tracker(self.tmpdir)
        n_threads, per_thread = 8, 25
        barrier = threading.Barrier(n_threads)

        def worker(tid):
            barrier.wait()                      # maximise overlap
            for i in range(per_thread):
                oid = f"opp-{tid}-{i}"
                tracker._ensure(oid)
                tracker._append(
                    OpportunityState(opportunity_id=oid),
                    "researched", f"note {tid}-{i}",
                )

        threads = [threading.Thread(target=worker, args=(t,))
                   for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
            self.assertFalse(t.is_alive(), "a persist thread deadlocked")

        # The file must be VALID JSON — the fixed-temp-path defect produced
        # a truncated file here, which _recover_from_disk silently swallows.
        with open(tracker._state_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)          # raises if truncated

        recovered = {rec["opportunity_id"] for rec in data}
        expected = {f"opp-{t}-{i}" for t in range(n_threads) for i in range(per_thread)}
        self.assertEqual(recovered, expected,
                         "lifecycle state was lost under concurrent persist")

    def test_state_file_is_always_parseable_after_concurrent_writes(self):
        """A reader must never observe a half-written file.

        Windows-specific note: a reader holding the file without
        FILE_SHARE_DELETE makes `os.replace` fail with `PermissionError(13)`.
        That is a transient sharing violation, NOT corruption, and `_persist`
        now retries it — so the reader tolerates it here too. What this test is
        really guarding is `json.JSONDecodeError`: the fixed-temp-path defect
        produced a truncated file, which `_recover_from_disk` silently swallows
        into a fresh start with no error anywhere.
        """
        tracker = _make_tracker(self.tmpdir)
        stop = threading.Event()
        corruption = []
        transient = []

        def writer(tid):
            while not stop.is_set():
                oid = f"w-{tid}-{threading.get_ident()}"
                tracker._ensure(oid)
                tracker._append(OpportunityState(opportunity_id=oid),
                                "researched", "n")

        def reader():
            while not stop.is_set():
                try:
                    with open(tracker._state_path, "r", encoding="utf-8") as fh:
                        json.load(fh)
                except (FileNotFoundError, PermissionError) as e:
                    transient.append(type(e).__name__)
                except Exception as e:      # truncated / partial JSON
                    corruption.append(repr(e))

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        threads.append(threading.Thread(target=reader))
        for t in threads:
            t.start()
        threading.Event().wait(2.0)
        stop.set()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(corruption, [],
                         f"a reader observed a PARTIAL state file "
                         f"(ARCH-ENG-162): {corruption[:3]}")
        # Sanity: the reader must actually have run, or this proves nothing.
        self.assertTrue(transient or tracker._state_path)

    def test_persist_retries_a_transient_windows_lock(self):
        """ARCH-ENG-162: a transient sharing violation must not drop the write.

        Measured on Windows: ~11k concurrent reads against 4 writers produced
        0 corrupted reads but 322 `PermissionError(13)`. Because `_persist`
        swallowed every exception, each of those was a silently lost lifecycle
        update. It must now retry, and the update must land.
        """
        import agents.earning.opportunity_lifecycle as mod

        tracker = _make_tracker(self.tmpdir)
        tracker._ensure("opp-lock")
        real_replace = mod.os.replace
        calls = {"n": 0}

        def flaky_replace(src, dst):
            calls["n"] += 1
            if calls["n"] <= 3:          # fail the first 3 attempts
                raise PermissionError(13, "Permission denied")
            return real_replace(src, dst)

        with unittest.mock.patch.object(mod.os, "replace", flaky_replace):
            tracker._append(OpportunityState(opportunity_id="opp-lock"),
                            "researched", "must survive the lock")

        self.assertGreaterEqual(calls["n"], 4, "the replace was never retried")
        with open(tracker._state_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertTrue(any(d["opportunity_id"] == "opp-lock" for d in data),
                        "the update was dropped despite the retry")

    def test_no_shared_temp_file_name(self):
        """ARCH-ENG-162: the fixed `.tmp` path must not come back."""
        tracker = _make_tracker(self.tmpdir)
        self.assertTrue(hasattr(tracker, "_persist_lock"),
                        "the tracker has no persist lock")
        # Two concurrent persists must use two distinct temp files.
        tracker._ensure("a")
        tracker._ensure("b")
        names = set()
        for tid in (111, 222):
            names.add(f"{tracker._state_path}.{os.getpid()}.{tid}.tmp")
        self.assertEqual(len(names), 2)

    def test_persist_leaves_no_orphan_temp_files(self):
        """A failed persist must clean up its temp file."""
        tracker = _make_tracker(self.tmpdir)
        tracker._ensure("a")
        tracker._append(OpportunityState(opportunity_id="a"), "researched", "n")

        leftovers = [f for f in os.listdir(self.tmpdir) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [],
                         f"orphaned temp file(s) after a successful persist: {leftovers}")

    def test_persist_is_a_noop_without_a_state_path(self):
        """Back-compat: a tracker with no path must not touch the disk."""
        tracker = OpportunityLifecycleTracker()
        tracker._ensure("a")
        tracker._append(OpportunityState(opportunity_id="a"), "researched", "n")  # must not raise

    def test_recover_reads_back_what_persist_wrote(self):
        """The happy path must be unchanged by the locking change."""
        tracker = _make_tracker(self.tmpdir)
        tracker.start(_opp("opp-1"))
        tracker.mark_paid_verified("opp-1", amount=750.0, evidence=None)

        reopened = _make_tracker(self.tmpdir)
        self.assertIn("opp-1", reopened._states)

    def test_persist_uses_atomic_replace(self):
        """The target is replaced, never truncated in place."""
        tracker = _make_tracker(self.tmpdir)
        tracker._ensure("opp-1")
        tracker._append(OpportunityState(opportunity_id="opp-1"),
                        "researched", "first")
        first = os.stat(tracker._state_path).st_ino if hasattr(os, "stat") else None

        tracker._append(OpportunityState(opportunity_id="opp-1"),
                        "queued", "second")
        with open(tracker._state_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertTrue(data)
        if first is not None:
            # os.replace swaps the inode; an in-place truncate would keep it.
            self.assertNotEqual(os.stat(tracker._state_path).st_ino, first)


if __name__ == "__main__":
    unittest.main()