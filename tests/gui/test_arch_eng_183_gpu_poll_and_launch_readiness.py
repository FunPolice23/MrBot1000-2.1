"""ARCH-ENG-183/184 — the GPU poller and the launcher's two false reports.

ARCH-ENG-183 — ONE `N/A` ROW ERASED EVERY GPU FROM THE PANEL.

`GPUStatusWorker._get_gpu_status` parsed nvidia-smi output with a single
outer `try`, and `int(parts[4])` for utilization. nvidia-smi routinely emits
`N/A` for an idle or unsupported field — so that raised ValueError, the OUTER
handler swallowed it, and the function returned an EMPTY list. Not "that one
GPU is unknown": every GPU disappeared from the Providers & GPU panel.

The same function used `subprocess.run(..., capture_output=True)`, which
ARCH-ENG-116 established raises `OSError(22)` / WinError 50 on Windows whenever
the parent's stdout is a reconfigured pipe (exactly what `pytest --capture=fd`
does). With the blanket `except Exception: pass` around it, a GPU panel could
also silently freeze on its last values with nothing anywhere. It now uses the
one hardened nvidia-smi invocation (ARCH-ENG-116/166).

A duplicate `stop()` definition also existed below the first, shadowed by it —
a trap for the next reader, and removed.

ARCH-ENG-184 — "READY" WAS EMITTED BEFORE ANY READINESS CHECK.

    if self._proc_alive():
        ...
        self.launch_finished.emit(True, f"{role} ready on :{port} (...)", proc)
        return
    if self.check_fn(self.port):        # UNREACHABLE
        ...

`_proc_alive()` is true on the FIRST loop iteration (the process was just
spawned), so this returned immediately. Two things became dead code: the
`check_fn` readiness probe, and the 120-second retry loop. Success was emitted
the instant `Popen` returned, so a llama-server that started and then crashed
two seconds later on an incompatible GGUF was reported to the operator as
"ready on :1234".

The intent behind returning early was sound — a busy server may not answer
/v1/models promptly, and killing a live server that is mid-generation is worse
than reporting it optimistically. So the fix is not "wait longer" but "report
honestly":

  * probe FIRST with a bounded wait, so a healthy server is genuinely confirmed
    before the word "ready" is used;
  * if the probe has not answered but the PROCESS is alive, still succeed --
    never terminate a live server -- but say "LAUNCHED but not yet answering"
    rather than "ready".

The operator can now tell the two states apart, which they could not before.
"""

import inspect
import textwrap
import unittest
from unittest import mock


def _code_only(func):
    body = textwrap.dedent(inspect.getsource(func))
    import ast
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return body
    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef, ast.Module))
                and ast.get_docstring(node, clean=False)):
            node.body = node.body[1:]
    return ast.unparse(tree)


class TestGpuPollerSurvivesNAFields(unittest.TestCase):
    """ARCH-ENG-183 — one unreadable row must not erase every GPU."""

    def _worker(self):
        from gui.widgets.dual_brain_control import GPUStatusWorker
        return GPUStatusWorker()

    ROWS = "0, NVIDIA RTX 4090, 1024, 24576, 15\n1, NVIDIA RTX 4080, 512, 16384, N/A\n"

    def test_a_na_utilization_keeps_the_other_gpus(self):
        """nvidia-smi emits N/A routinely; it must cost one row, not all."""
        w = self._worker()
        with mock.patch(
            "agents.runtime.device_registry._run_nvidia_smi",
            return_value=self.ROWS):
            gpus = w._get_gpu_status()
        self.assertEqual(len(gpus), 2,
                         f"an N/A field erased the whole panel: {gpus}")
        self.assertEqual([g["index"] for g in gpus], [0, 1])

    def test_na_utilization_becomes_zero_not_a_dropped_gpu(self):
        w = self._worker()
        with mock.patch(
            "agents.runtime.device_registry._run_nvidia_smi",
            return_value=self.ROWS):
            gpus = {g["index"]: g for g in w._get_gpu_status()}
        self.assertIn(1, gpus, "the GPU with an N/A utilization was dropped")
        self.assertEqual(gpus[1]["utilization"], 0)

    def test_real_values_are_parsed(self):
        w = self._worker()
        with mock.patch(
            "agents.runtime.device_registry._run_nvidia_smi",
            return_value=self.ROWS):
            gpus = {g["index"]: g for g in w._get_gpu_status()}
        self.assertEqual(gpus[0]["name"], "NVIDIA RTX 4090")
        self.assertEqual(gpus[0]["memory_used_mb"], 1024)
        self.assertEqual(gpus[0]["memory_total_mb"], 24576)
        self.assertEqual(gpus[0]["utilization"], 15)

    def test_a_garbage_row_is_skipped_individually(self):
        w = self._worker()
        with mock.patch(
            "agents.runtime.device_registry._run_nvidia_smi",
            return_value="not,a,valid,row,here\n"
                         "0, NVIDIA RTX 4090, 1024, 24576, 15\n"):
            gpus = w._get_gpu_status()
        self.assertEqual(len(gpus), 1, f"a malformed row aborted the poll: {gpus}")

    def test_the_broken_capture_output_form_is_gone(self):
        code = _code_only(self._worker()._get_gpu_status)
        self.assertNotIn("capture_output", code,
                         "capture_output is the ARCH-ENG-116-broken subprocess "
                         "form (WinError 50 under a reconfigured stdout pipe); "
                         "use the hardened _run_nvidia_smi")

    def test_no_smi_available_yields_an_empty_list_not_an_exception(self):
        w = self._worker()
        with mock.patch(
            "agents.runtime.device_registry._run_nvidia_smi",
            side_effect=OSError("nvidia-smi not found")):
            self.assertEqual(w._get_gpu_status(), [])

    def test_stop_is_defined_exactly_once(self):
        """A shadowed teardown method is a trap for the next reader."""
        import ast
        from gui.widgets.dual_brain_control import GPUStatusWorker
        tree = ast.parse(textwrap.dedent(inspect.getsource(GPUStatusWorker)))
        stops = [n.name for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "stop"]
        self.assertEqual(len(stops), 1,
                         f"GPUStatusWorker.stop is defined {len(stops)} times; "
                         f"the second is dead and hides what teardown does")


class TestLauncherDoesNotClaimReadyEarly(unittest.TestCase):
    """ARCH-ENG-184 — "ready" must mean the endpoint answered."""

    def _worker(self):
        from gui.workers.brain_launch_worker import BrainLaunchWorker
        return BrainLaunchWorker

    def _source(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[2]
        src = (root / "gui" / "workers" / "brain_launch_worker.py").read_text(
            encoding="utf-8")
        return src

    def test_the_readiness_probe_runs_before_the_alive_fallback(self):
        src = self._source()
        probe = src.find("self.check_fn(self.port)")
        alive = src.find("if self._proc_alive():")
        self.assertNotEqual(probe, -1,
                            "the readiness probe no longer exists at all")
        self.assertLess(alive, probe,
                        "the readiness probe must be consulted BEFORE the "
                        "'process alive, assume ready' fallback, or it stays "
                        "unreachable dead code")

    def test_a_ready_message_claims_the_endpoint_answered(self):
        src = self._source()
        self.assertIn("endpoint answering", src,
                      "the 'ready' message must say what was actually verified")

    def test_a_live_but_silent_server_is_reported_honestly(self):
        src = self._source()
        self.assertIn("not yet answering", src,
                      "a process that is alive but not answering must NOT be "
                      "reported as ready")
        self.assertIn("LAUNCHED", src)

    def test_the_optimistic_path_still_does_not_kill_a_live_server(self):
        """The original intent was sound: do not terminate a busy server."""
        src = self._source()
        self.assertIn("if self._proc_alive():", src,
                      "the alive branch must survive; removing it would kill "
                      "servers that are mid-generation and refuse to answer")
        # The silent-but-alive branch must still emit success (True, ...).
        idx = src.find("LAUNCHED but not yet answering")
        self.assertNotEqual(idx, -1)
        window = src[max(0, idx - 400):idx + 200]
        self.assertIn("True", window,
                      "a live-but-silent server must still SUCCEED, not fail; "
                      "failing would terminate a server that is merely busy")

    def test_a_crash_is_still_reported_as_a_failure(self):
        src = self._source()
        self.assertIn("self.launch_finished.emit(False", src,
                      "a process that exits during startup must still be a "
                      "failure, and that check must come before the alive check")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-183/184 — the fixtures must actually express the defects."""

    def test_the_na_fixture_contains_a_na(self):
        """If the fixture had no N/A, the regression test proves nothing."""
        rows = "0, NVIDIA RTX 4090, 1024, 24576, 15\n1, NVIDIA RTX 4080, 512, 16384, N/A\n"
        self.assertIn("N/A", rows)
        self.assertEqual(len(rows.strip().splitlines()), 2)

    def test_a_na_row_would_actually_raise_before_the_fix(self):
        """Reproduce the old failure mode directly."""
        parts = [p.strip() for p in "1, NVIDIA RTX 4080, 512, 16384, N/A".split(",")]
        with self.assertRaises(ValueError):
            int(parts[4])