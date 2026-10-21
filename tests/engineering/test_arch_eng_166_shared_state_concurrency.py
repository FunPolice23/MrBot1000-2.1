"""ARCH-ENG-166 — three shared-state defects with no owner.

Each of these is a correctness problem in a structure shared by many callers,
where nothing asserted the property and so nothing broke when it was violated.

1. `HumanApprovalQueue` READS TOOK NO LOCK.
   Writes were locked (`enqueue`, `decide`); reads were not. `pending()`,
   `all()`, `find_by_id()`, `items_for_kind()` and `_find()` iterated
   `self._items` unguarded, and `_items` is also TRUNCATED by the history bound
   (`_MAX_RETAINED_ITEMS`). One shared queue instance is mutated from GUI
   threads, the safety guard's decision thread, and every worker that enqueues.

   `find_by_id` is the lookup every irreversible-action consumer uses to confirm
   a human decision — `platform_submitter.execute_approved`,
   `live_trading._is_approved`, `code_patch_service._is_approved`,
   `SafetyGuard._decide_in_shared_queue` — so a torn read there is a
   financial-integrity bug, not a tidiness one.

   `decide()` was worse than unguarded: it called `_find()` and read
   `item.status` BEFORE acquiring the lock, so two threads could both observe
   PENDING and both decide the same irreversible action. Check-then-act, split
   across a lock boundary.

2. `EventBus` RETENTION MAPS GREW WITHOUT BOUND.
   `_inflight`, `_delivered`, `_edges`, `_tokens` and `_tokens_by_corr` were
   keyed by message_id / correlation_id and cleared only by `reset()`. Every
   message the peer council, coordinator and discovery loop ever sent stayed
   reachable for the life of the process, and `_edges` — the loop-prevention
   replay set — never expired a single edge. Now bounded FIFO, with IN_FLIGHT
   messages exempt so a live chain is never truncated out from under
   `_prior_sources`.

3. THREE COPIES OF THE `nvidia-smi` QUERY, TWO OF THEM BROKEN.
   `device_registry._run_nvidia_smi`, `ProviderManager._detect_gpus` and
   `llm.detect_vram_gb` each built their own `subprocess.run`. ARCH-ENG-116
   established that the `capture_output=True` form raises
   `OSError(22, 'The request is not supported')` / WinError 50 on Windows when
   the parent's stdout is a reconfigured pipe — which is exactly what
   `pytest --capture=fd` does. `device_registry` had the temp-file fix; the
   other two had the broken form, so GPU detection and VRAM sizing silently
   returned "no GPU" under test. All three now share the hardened invocation.
"""

import ast
import inspect
import pathlib
import threading
import unittest
from unittest.mock import patch

from agents.core.comms import EventBus, Message, MessageStatus, MessageType
from agents.safety.approval import (
    ApprovalItem, ApprovalKind, ApprovalStatus, HumanApprovalQueue,
)


# ── 1. HumanApprovalQueue ─────────────────────────────────────────────────────

class TestApprovalQueueReadsAreLocked(unittest.TestCase):
    """ARCH-ENG-166 — reads must hold the same lock as writes."""

    def _queue(self):
        HumanApprovalQueue.reset_singleton()
        return HumanApprovalQueue.instance()

    def _item(self, q, title="probe"):
        return q.enqueue(ApprovalItem(
            kind=ApprovalKind.ACTION, title=title, description="d",
            requested_by="test",
            payload={"tool": "run_command", "arguments": {"command": "echo hi"}},
        ))

    def _held_by(self, fn, *names):
        """True iff `fn` executes the body of every named method."""
        src = inspect.getsource(fn)
        for name in names:
            # a call to the shared lock accessor inside the body
            if "_get_lock()" not in src:
                return False, f"{fn.__name__} does not take the lock"
        return True, ""

    def test_pending_takes_the_lock(self):
        q = self._queue()
        ok, why = self._held_by(q.pending)
        self.assertTrue(ok, why)

    def test_all_takes_the_lock(self):
        q = self._queue()
        ok, why = self._held_by(q.all)
        self.assertTrue(ok, why)

    def test_find_by_id_takes_the_lock(self):
        q = self._queue()
        ok, why = self._held_by(q.find_by_id)
        self.assertTrue(ok, why)

    def test_items_for_kind_takes_the_lock(self):
        q = self._queue()
        ok, why = self._held_by(q.items_for_kind)
        self.assertTrue(ok, why)

    def test_decide_does_the_check_then_act_inside_one_critical_section(self):
        """`_find` and the PENDING test must not straddle the lock boundary.

        The defect was: `item = self._find(...)` and
        `if item.status != PENDING: return False` ran BEFORE
        `with self._get_lock():`. Two threads could both see PENDING.
        """
        src = inspect.getsource(type(self._queue()).decide)
        lock_at = src.find("_get_lock()")
        self.assertNotEqual(lock_at, -1, "decide no longer takes the lock")
        find_at = src.find("self._find(")
        check_at = src.find("!= ApprovalStatus.PENDING")
        self.assertTrue(find_at != -1 and check_at != -1)
        self.assertLess(
            lock_at, find_at,
            "decide() calls _find() BEFORE taking the lock — the PENDING check "
            "and the mutation are in different critical sections, so two "
            "threads can both decide the same irreversible action")
        self.assertLess(lock_at, check_at)

    def test_concurrent_decide_picks_one_winner(self):
        """Exactly one thread may win a single approval decision."""
        q = self._queue()
        item = self._item(q)
        winners = []
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            if q.decide(item.id, ApprovalStatus.APPROVED, notes="race"):
                winners.append(threading.get_ident())

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
            self.assertFalse(t.is_alive(), "decide() deadlocked under contention")
        self.assertEqual(len(winners), 1,
                         f"{len(winners)} threads decided the same approval")

    def test_concurrent_reads_and_decides_do_not_raise(self):
        """Readers must never observe the list mid-mutation."""
        q = self._queue()
        items = [self._item(q, f"probe-{i}") for i in range(20)]
        errors = []
        stop = threading.Event()

        def writer():
            for i in range(60):
                q.enqueue(ApprovalItem(
                    kind=ApprovalKind.ACTION, title=f"w{i}", description="d",
                    requested_by="test"))
                if i % 3 == 0 and items:
                    q.decide(items[0].id, ApprovalStatus.DENIED, notes="x")

        def reader():
            while not stop.is_set():
                try:
                    q.pending()
                    q.all()
                    for it in items:
                        q.find_by_id(it.id)
                except Exception as exc:
                    errors.append(repr(exc))

        threads = [threading.Thread(target=writer) for _ in range(3)]
        readers = [threading.Thread(target=reader) for _ in range(3)]
        for t in threads + readers:
            t.start()
        for t in threads:
            t.join(timeout=60)
        stop.set()
        for t in readers:
            t.join(timeout=30)
        self.assertEqual(errors, [], f"a reader raised: {errors[:3]}")

    def test_reads_return_snapshots_not_live_views(self):
        """A returned list must not alias the queue's own list."""
        q = self._queue()
        self._item(q)
        snapshot = q.all()
        before = len(snapshot)
        q.enqueue(ApprovalItem(kind=ApprovalKind.ACTION, title="new",
                               description="d", requested_by="test"))
        self.assertEqual(len(snapshot), before,
                         "all() returned a live view of the internal list")


# ── 2. EventBus retention ─────────────────────────────────────────────────────

def _msg(i, source="a", dest="b", corr=None):
    return Message(
        message_type=MessageType.TASK_REQUEST,
        source=source, destination=dest,
        payload={"i": i},
        message_id=f"m{i}",
        correlation_id=corr or f"c{i}",
    )


class TestEventBusRetentionIsBounded(unittest.TestCase):
    """ARCH-ENG-166 — the retention maps must not grow without bound."""

    def setUp(self):
        self.bus = EventBus()

    def test_default_retention_limit_is_set(self):
        self.assertGreater(self.bus._retention_limit, 0,
                           "no retention bound: the maps grow for the life of "
                           "the process")

    def test_publishing_many_messages_does_not_grow_the_maps_forever(self):
        self.bus._retention_limit = 50
        for i in range(500):
            self.bus.publish(_msg(i))
        for name in ("_delivered", "_edges", "_tokens", "_tokens_by_corr"):
            size = len(getattr(self.bus, name))
            self.assertLessEqual(
                size, 50 + 10,
                f"{name} grew to {size}, far past the 50-key retention limit")

    def test_pruned_keys_is_counted(self):
        """Pruning must be observable, not silent."""
        self.bus._retention_limit = 20
        for i in range(200):
            self.bus.publish(_msg(i))
        self.assertGreater(self.bus.pruned_keys, 0,
                           "keys were dropped without being counted")

    def test_snapshot_exposes_the_retention_state(self):
        """A slow leak must be observable rather than inferred."""
        snap = self.bus.snapshot()
        self.assertIn("pruned_keys", snap)
        self.assertIn("retention_limit", snap)
        self.assertIn("edges", snap)

    def test_inflight_messages_are_not_evicted(self):
        """A live chain must never be truncated mid-flight."""
        self.bus._retention_limit = 5
        msg = _msg(999)
        self.bus.publish(msg)
        self.assertEqual(self.bus._inflight.get("m999").message_id, "m999")
        for i in range(200):
            self.bus.publish(_msg(i))
        # m999 was published first, so FIFO would evict it -- but it is still
        # IN_FLIGHT, so it must survive.
        self.assertIn("m999", self.bus._inflight,
                      "an IN_FLIGHT message was evicted; a live correlation "
                      "chain would break its own parent walk in _prior_sources")

    def test_reset_still_clears_everything(self):
        for i in range(20):
            self.bus.publish(_msg(i))
        self.bus.reset()
        for name in ("_inflight", "_delivered", "_edges", "_tokens",
                     "_tokens_by_corr"):
            self.assertEqual(len(getattr(self.bus, name)), 0,
                             f"reset() did not clear {name}")


# ── 3. One nvidia-smi invocation ──────────────────────────────────────────────

class TestNvidiaSmiIsQueriedInOnePlace(unittest.TestCase):
    """ARCH-ENG-166 — three copies, two of them the broken form."""

    FILES = ("agents/providers/provider_manager.py",
             "agents/runtime/llm.py",
             "agents/runtime/device_registry.py")

    def _repo(self):
        return pathlib.Path(__file__).resolve().parents[2]

    @staticmethod
    def _nvidia_smi_spawn_sites(src):
        """Every `subprocess.run`/`Popen` call whose ARGV names nvidia-smi.

        AST, not text: all three files legitimately still contain the string
        "capture_output=True" (for unrelated subprocess work) and "nvidia-smi"
        (in comments, docstrings, and the shared helper's name). A substring
        check therefore flags correct code — the exact false alarm that disarms
        a guard, which the ARCH-ENG-150 docstring calls out as the way a
        control loses its value.
        """
        tree = ast.parse(src)

        def literal_strings(node):
            return [e.value for e in ast.walk(node)
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]

        # `subprocess.run(argv, ...)` passes a NAME, not a literal, so the
        # string lives in a nearby assignment. Resolve name args to their
        # bindings in the same module before searching for "nvidia-smi".
        bindings = {}
        for node in ast.walk(tree):
            targets = getattr(node, "targets", None)
            if not targets:
                continue
            for t in targets:
                if isinstance(t, ast.Name):
                    bindings.setdefault(t.id, []).append(node.value)

        def mentions_nvidia_smi(node, depth=0):
            if any("nvidia-smi" in s for s in literal_strings(node)):
                return True
            if depth > 2 or not isinstance(node, ast.Name):
                return False
            return any(mentions_nvidia_smi(v, depth + 1)
                       for v in bindings.get(node.id, ()))

        sites = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute)
                    and func.attr in ("run", "Popen")):
                continue
            args = list(node.args) + [kw.value for kw in node.keywords]
            if any(mentions_nvidia_smi(a) for a in args):
                sites.append(node)
        return sites

    def _sites_by_file(self):
        out = {}
        for rel in self.FILES:
            out[rel] = self._nvidia_smi_spawn_sites(
                (self._repo() / rel).read_text(encoding="utf-8"))
        return out

    def test_exactly_one_module_spawns_nvidia_smi(self):
        spawners = {rel: len(sites) for rel, sites in self._sites_by_file().items()
                    if sites}
        self.assertEqual(
            len(spawners), 1,
            f"expected exactly one nvidia-smi spawner, found {spawners} — each "
            f"copy is a place the ARCH-ENG-116 Windows fix can be missed again")

    def test_the_one_spawner_is_not_capture_output(self):
        """The survivor must NOT use `capture_output=True`.

        That form raises OSError(22) / WinError 50 on Windows when the parent's
        stdout is a reconfigured pipe, which is exactly what
        `pytest --capture=fd` does; GPU detection then reported "no GPU" on a
        machine that had two.
        """
        spawners = {r: s for r, s in self._sites_by_file().items() if s}
        self.assertEqual(len(spawners), 1, f"expected one spawner: {spawners}")
        rel, sites = next(iter(spawners.items()))
        for site in sites:
            kwargs = {kw.arg for kw in site.keywords if kw.arg}
            self.assertNotIn(
                "capture_output", kwargs,
                f"{rel} spawns nvidia-smi with capture_output (the ARCH-ENG-116 "
                f"broken form); use device_registry._run_nvidia_smi instead")

    def test_the_callers_delegate_to_the_hardened_helper(self):
        for rel in ("agents/providers/provider_manager.py",
                    "agents/runtime/llm.py"):
            src = (self._repo() / rel).read_text(encoding="utf-8")
            self.assertIn("_run_nvidia_smi", src,
                          f"{rel} must delegate to device_registry."
                          f"_run_nvidia_smi, the ARCH-ENG-116 hardened form")

    def test_detect_vram_still_works_through_the_helper(self):
        with patch("agents.runtime.device_registry._run_nvidia_smi",
                   return_value="24576\n16384\n"):
            from agents.runtime.llm import detect_vram_gb
            self.assertEqual(detect_vram_gb(), (24576 + 16384) // 1024)

    def test_detect_vram_never_raises_on_empty_output(self):
        with patch("agents.runtime.device_registry._run_nvidia_smi",
                   return_value=""):
            from agents.runtime.llm import detect_vram_gb
            self.assertGreaterEqual(detect_vram_gb(), 0)


if __name__ == "__main__":
    unittest.main()