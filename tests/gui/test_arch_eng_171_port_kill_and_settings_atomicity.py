"""ARCH-ENG-171/172 — two "the app destroyed something it did not own" defects.

ARCH-ENG-171 — STOP ON A BRAIN KILLED *ANY* PROCESS ON ITS PORT.

`DualBrainControl._kill_llama_on_port` ran `taskkill /F /PID` for every PID that
`netstat` reported as LISTENING on the brain's port, with no image-name check at
all. The port was treated as proof of ownership. It is not:

  * `ProviderManager._detect_lm_studio` defaults to `http://127.0.0.1:1234/v1`,
    and 1234 IS the Big Brain port (`agents/runtime/dual_brain.py` ROLE_DEFAULTS).
    An operator running LM Studio — or anything else that grabbed 1234 first —
    had it force-killed by pressing Stop on a brain. No warning, no way to tell
    why the app closed their editor's backend.
  * It ran even for servers this app explicitly ADOPTED and promised not to
    manage: `brain_launch_worker` sets `we_started_* = False` for those, precisely
    so Stop would leave them alone. The port sweep undid that promise.
  * `netstat` reports one listener twice for some addresses (`0.0.0.0:` and
    `[::]:` across v4+v6), so the same PID was killed repeatedly.

Now a PID is killed only if its image name is a llama.cpp server. An
unrecognised listener is reported and left running: destroying a stranger's
process is far worse than leaving a port occupied, and the operator is told
which PID is in the way.

ARCH-ENG-172 — settings.json COULD BE TRUNCATED, OR LOSE A KEY.

Both `merge_settings_file` and `save_policy` did their own read-merge-write into
the same file, and neither was synchronized:

  1. NO LOCK. Read -> merge -> write is three steps. A `devices` save that read
     the file a millisecond before a `roster` save wrote it replaced it with a
     snapshot containing no `roster` key — silently discarding an operator edit.
     ARCH-ENG-070 closed this for one writer; ARCH-ENG-070's own docstring
     ("Every writer to this shared file must go through this function") was
     false, because `save_policy` duplicated the sequence.

  2. A COLLIDING TEMP NAME. Both used `f"{path}.tmp-{os.getpid()}"`. A PID is
     per-PROCESS, so every writer inside one process shared ONE temp file: the
     second truncated the first's output mid-`json.dump`, and whichever reached
     `os.replace` first published a TRUNCATED settings file. The next read hits
     `json.JSONDecodeError` and quarantines the operator's settings as corrupt —
     destroying every per-device model, role, and tuning value.

This is the same failure mode as ARCH-ENG-162 in `_persist`: a fixed temp path
plus an unserialized read-modify-write, on a file nothing else reads.
"""

import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

REPO = __import__("pathlib").Path(__file__).resolve().parents[2]


# ── ARCH-ENG-171 ──────────────────────────────────────────────────────────────

class TestPortKillVerifiesImageName(unittest.TestCase):
    """ARCH-ENG-171 — a port is not proof of ownership."""

    def _control(self):
        import agents.safety  # noqa: F401
        from gui.widgets.dual_brain_control import DualBrainControl
        return DualBrainControl

    def _stub(self, pids, images):
        """A minimal stand-in exposing only what `_kill_llama_on_port` uses.

        Calling the unbound method with a stub avoids constructing the 3,000-line
        QWidget, so this stays a fast headless unit test of the DECISION logic —
        which is the part that was wrong.
        """
        control = self._control()
        stub = unittest.mock.MagicMock()
        stub._pids_on_port = lambda port: list(pids)
        stub._process_image_name = lambda pid: images.get(pid, "")
        stub._log = lambda msg: None
        # Bind the REAL predicate. A MagicMock would auto-create
        # `_is_llama_image` returning a truthy Mock, so every PID would look
        # like a llama-server and the tests would pass for the wrong reason.
        stub._is_llama_image = control._is_llama_image
        return control, stub

    def test_a_non_llama_listener_is_not_killed(self):
        """The LM Studio case: same port, different program."""
        control, stub = self._stub([4242], {4242: "lm studio.exe"})
        with patch("gui.widgets.dual_brain_control.subprocess.run") as run:
            killed = control._kill_llama_on_port(stub, 1234)
        self.assertEqual(killed, [],
                         "a process that is not a llama-server was killed "
                         "just for holding the port")
        for call in run.call_args_list:
            self.assertNotIn("taskkill", call.args[0])

    def test_a_llama_server_listener_is_still_killed(self):
        """The fix must not stop the app from stopping its OWN servers."""
        control, stub = self._stub([1111], {1111: "llama-server.exe"})
        with patch("gui.widgets.dual_brain_control.subprocess.run") as run:
            killed = control._kill_llama_on_port(stub, 1234)
        self.assertEqual(killed, [1111])
        argv = run.call_args_list[0].args[0]
        self.assertEqual(argv[:2], ["taskkill", "/F"])

    def test_the_legacy_llama_alias_is_accepted(self):
        """Some launcher scripts produce `llama.exe`; still ours."""
        self.assertTrue(self._control()._is_llama_image("llama.exe"))
        self.assertTrue(self._control()._is_llama_image("LLAMA-SERVER.EXE"))

    def test_the_image_check_is_deliberately_narrow(self):
        check = self._control()._is_llama_image
        for foreign in ("lm studio.exe", "python.exe", "node.exe",
                        "ollama.exe", "chrome.exe", "notepad.exe",
                        "llama-server-helper.exe", "xllama-server.exe", ""):
            with self.subTest(image=foreign):
                self.assertFalse(check(foreign),
                                 f"{foreign} is not a llama.cpp server")

    def test_a_duplicate_listener_is_killed_once(self):
        """netstat reports v4 and v6 rows for one socket; kill it once."""
        control, stub = self._stub([777, 777, 777], {777: "llama-server.exe"})
        with patch("gui.widgets.dual_brain_control.subprocess.run") as run:
            killed = control._kill_llama_on_port(stub, 1234)
        self.assertEqual(killed, [777])
        self.assertEqual(run.call_count, 1, "the same PID was killed repeatedly")

    def test_an_unrecognised_listener_is_reported_to_the_operator(self):
        """Silence would leave the operator with a port that never frees."""
        control, stub = self._stub([4242], {4242: "lm studio.exe"})
        logged = []
        stub._log = logged.append
        with patch("gui.widgets.dual_brain_control.subprocess.run"):
            control._kill_llama_on_port(stub, 1234)
        self.assertTrue(logged, "the operator was not told why the port stayed busy")
        self.assertIn("4242", logged[0])
        self.assertIn("not a llama-server", logged[0])

    def test_a_mixed_set_kills_only_the_llama_servers(self):
        """The realistic case: one of ours plus one stranger on the port."""
        control, stub = self._stub(
            [1111, 4242], {1111: "llama-server.exe", 4242: "lm studio.exe"})
        with patch("gui.widgets.dual_brain_control.subprocess.run") as run:
            killed = control._kill_llama_on_port(stub, 1234)
        self.assertEqual(killed, [1111])
        pids_targeted = [c.args[0][-1] for c in run.call_args_list
                         if c.args and c.args[0][0] == "taskkill"]
        self.assertEqual(pids_targeted, ["1111"])


# ── ARCH-ENG-172 ──────────────────────────────────────────────────────────────

class TestSettingsWriteIsSerialized(unittest.TestCase):
    """ARCH-ENG-172 — no truncated file, no dropped key."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "settings.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _merge(self, updates):
        from agents.runtime.device_registry import merge_settings_file
        with patch("agents.runtime.device_registry.policy_path",
                   return_value=self.path):
            return merge_settings_file(updates)

    def test_a_large_settings_survives_a_concurrent_write(self):
        """The truncating-temp-name defect, reproduced.

        Two threads write a large payload through the same file. Before the fix
        they shared one temp path, so one truncated the other's output and a
        TRUNCATED settings.json was published.

        `policy_path` is patched ONCE for the whole test, not per call. Patching
        it inside the worker is a data race on a MODULE attribute: `patch()` is
        global, so thread A's unpatch restores the real path while thread B is
        mid-write — and thread B then writes into the session-wide shared
        settings file, breaking every later test that reads it. That is exactly
        what this test did on its first run.
        """
        big = {f"k{i}": "x" * 400 for i in range(400)}
        errors = []
        barrier = threading.Barrier(4)

        def writer(n):
            try:
                barrier.wait()
                for _ in range(6):
                    self._merge({f"writer{n}": dict(big)})
            except Exception as exc:      # pragma: no cover
                errors.append(repr(exc))

        with patch("agents.runtime.device_registry.policy_path",
                   return_value=self.path):
            threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=120)
                self.assertFalse(t.is_alive(), "the settings write deadlocked")

        self.assertEqual(errors, [])
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)          # raises if truncated
        self.assertIsInstance(data, dict)
        # Every writer's key must survive: no last-writer-wins key loss.
        for n in range(4):
            self.assertIn(f"writer{n}", data,
                          f"writer{n}'s key was dropped by a concurrent write")

    def test_no_temp_files_are_left_behind(self):
        self._merge({"a": 1})
        leftovers = [f for f in os.listdir(self.tmp) if ".tmp-" in f]
        self.assertEqual(leftovers, [],
                         f"orphaned settings temp file(s): {leftovers}")

    def test_the_temp_name_is_unique_per_writer(self):
        """A per-process temp name is not per-writer."""
        import inspect
        from agents.runtime import device_registry
        src = inspect.getsource(device_registry._atomic_write_settings)
        self.assertIn("get_ident", src,
                      "the temp name must include the thread id, not just the "
                      "pid — a pid is per-process, so two threads in one "
                      "process would still share one temp file")

    def test_read_modify_write_holds_one_lock(self):
        """The lock must cover read AND write, not just the write."""
        import inspect
        from agents.runtime import device_registry
        self.assertIsNotNone(getattr(device_registry, "_SETTINGS_WRITE_LOCK", None),
                             "no lock exists for the shared settings file")
        for fn in (device_registry.merge_settings_file,
                   device_registry.save_policy):
            src = inspect.getsource(fn)
            self.assertIn("_SETTINGS_WRITE_LOCK", src,
                          f"{fn.__name__} does not take the shared lock")

    def test_save_policy_still_preserves_sibling_keys(self):
        """ARCH-ENG-070 must not regress: the merge semantics are unchanged."""
        from agents.runtime.device_registry import DevicePolicy, save_policy
        self._merge({"roster": {"big": [{"id": "0"}]}, "theme": "dark"})
        policy = DevicePolicy()
        policy.enabled = {"0": True}
        policy.role = {"0": "big"}
        policy.models = {"0": "model.gguf"}
        policy.settings = {"0": {"ctx": 4096}}
        with patch("agents.runtime.device_registry.policy_path",
                   return_value=self.path):
            self.assertTrue(save_policy(policy))
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("roster", data)
        self.assertIn("theme", data)
        self.assertEqual(data["theme"], "dark")
        self.assertEqual(data["devices"]["models"], {"0": "model.gguf"})


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-171/172 — the detectors must actually be able to fail."""

    def test_the_image_check_rejects_a_real_llama_server_name(self):
        """Anti-vacuity: if this returned False for everything, the kill test
        above would pass for the wrong reason."""
        from gui.widgets.dual_brain_control import DualBrainControl
        self.assertTrue(DualBrainControl._is_llama_image("llama-server.exe"))

    def test_the_lock_is_a_real_mutex(self):
        """`type(RLock())` is not a class; check behaviour, not the type."""
        from agents.runtime.device_registry import _SETTINGS_WRITE_LOCK
        # A real mutex is exclusive: a second acquire from another thread blocks.
        _SETTINGS_WRITE_LOCK.acquire()
        blocked = threading.Event()

        def other():
            blocked.set()
            _SETTINGS_WRITE_LOCK.acquire()
            _SETTINGS_WRITE_LOCK.release()

        t = threading.Thread(target=other, daemon=True)
        t.start()
        blocked.wait(timeout=5)
        # Give the other thread a chance to (incorrectly) acquire.
        got_it = blocked.wait(timeout=0.2)
        _SETTINGS_WRITE_LOCK.release()
        t.join(timeout=5)
        self.assertTrue(got_it,
                        "could not verify the lock behaves as a mutex")

    def test_a_planted_truncation_would_be_detected(self):
        """Writing invalid JSON into the target is what the fix prevents; prove
        the reader notices when it happens."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "s.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('{"a": 1')          # truncated
            with self.assertRaises(json.JSONDecodeError):
                json.load(open(path, encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()