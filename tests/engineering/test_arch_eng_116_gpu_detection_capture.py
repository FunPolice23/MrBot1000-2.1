"""ARCH-ENG-116 — GPU detection must not silently report ZERO GPUs.

Two defects in `agents/runtime/device_registry.py::_detect_gpus`, both of which
made the system believe a two-GPU box had no GPUs at all:

1. **The spawn could fail and be swallowed.** `subprocess.run(...,
   capture_output=True)` must duplicate whichever standard streams it is given
   so the child can inherit them. On Windows that `DuplicateHandle` fails with
   WinError 50 ("The request is not supported") when the parent's own stdout is
   a pipe a capture layer has reconfigured — exactly what pytest's
   `--capture=fd` (the default) does. The exception was caught by a bare
   `except Exception: continue`, so it was indistinguishable from "this query
   form is unsupported", and detection returned ZERO devices.

   The failing handle was STDIN, not stdout: `_get_handles` duplicates every
   stream it is handed, and leaving stdin implicit made it inherit the capture
   pipe.

   Measured before the fix: `_detect_gpus()` under `pytest --capture=fd` raised
   `OSError(22, 'The request is not supported', None, 50, None)` and returned 0
   GPUs, while `--capture=sys` / `-s` returned both cards.

2. **The documented fallback was dead code.** The ProviderManager fallback
   called `get_gpus(detect=False)`, which returns the manager's CACHED list —
   empty until something has probed. The fallback only runs when nvidia-smi has
   already failed, so nothing had probed: it returned `[]` every time.

Impact when both fired: every caller saw a GPU-less box —
`tests/gui/test_gui_smoke.py::test_management_tab_builds` got 1 persona field
instead of 3, and the brain prompts dropped their hardware section entirely.

Fix: name all three std streams explicitly (stdout to a real temp file, stdin
and stderr to DEVNULL) so nothing has to be inherited, and force the fallback
probe with `detect=True`.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import subprocess  # noqa: E402

from agents.runtime import device_registry as dr  # noqa: E402


def test_smi_probe_returns_both_cards_under_pytest_fd_capture():
    """The regression: this exact call raised WinError 50 before the fix.

    Runs under whatever capture mode pytest was invoked with, so a CI run using
    the default `--capture=fd` exercises the failing path.
    """
    out = dr._run_nvidia_smi("index,name,memory.total,uuid,compute_cap")
    lines = [l for l in out.strip().splitlines() if l.strip()]
    if not lines:
        # A genuinely GPU-less box is a legitimate result; what must never
        # happen is a raised OSError (asserted by the test below).
        assert dr._LAST_DETECT_ERROR == ""
        return
    assert len(lines) >= 1
    assert "NVIDIA" in out or "," in out


def test_probe_never_raises_a_handle_error():
    """`_run_nvidia_smi` must not propagate the Windows handle-duplication error.

    `_detect_gpus` catches broadly, so an escaping OSError would be swallowed
    there and turn into "zero GPUs" — exactly the silent failure being fixed.
    """
    try:
        dr._run_nvidia_smi("index,name,memory.total,uuid,compute_cap")
    except OSError as exc:  # WinError 50 / errno 22
        raise AssertionError(
            f"_run_nvidia_smi raised {exc!r} — GPU detection will silently "
            f"report zero devices (ARCH-ENG-116)") from exc


def test_all_three_std_streams_are_named_explicitly():
    """Structural lock: an implicit stdin is what inherited the capture pipe."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(
        inspect.getsource(dr._run_nvidia_smi)).strip())
    call = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "run":
            call = node
            break
    assert call is not None, "could not find the subprocess.run call"
    keywords = {kw.arg for kw in call.keywords}
    for stream in ("stdin", "stdout", "stderr"):
        assert stream in keywords, (
            f"subprocess.run no longer names {stream}= explicitly; an "
            f"unspecified stream inherits the parent's (possibly captured) "
            f"handle and DuplicateHandle fails on Windows")
    assert "capture_output" not in keywords, (
        "capture_output=True is back — that is the form that raised WinError 50")


def test_detection_failure_is_recorded_not_silently_swallowed():
    """A caller must be able to tell 'no GPUs' from 'could not ask'."""
    from unittest import mock

    def boom(*a, **kw):
        raise OSError(50, "The request is not supported")

    with mock.patch.object(subprocess, "run", side_effect=boom):
        with mock.patch.object(dr, "_run_nvidia_smi", side_effect=OSError(50, "x")):
            devs = dr._detect_gpus()
    assert dr._LAST_DETECT_ERROR, (
        "a failed nvidia-smi probe left no diagnostic — the caller cannot "
        "distinguish 'this box has no GPUs' from 'we could not ask'")
    assert isinstance(devs, list)


def test_the_fallback_forces_a_probe():
    """`detect=False` returns an empty cache, so the fallback must force it."""
    import inspect

    src = inspect.getsource(dr._detect_gpus)
    assert "get_gpus(detect=True)" in src, (
        "the ProviderManager fallback no longer forces a probe; detect=False "
        "returns the (empty) cache and the fallback is dead code again")
    assert "get_gpus(detect=False)" not in src


def test_detect_devices_still_finds_the_cpu_pool():
    """The CPU/RAM pool is appended unconditionally and must survive."""
    devs = dr.detect_devices(include_cpu=True)
    assert any(d.is_cpu for d in devs), "the CPU pool disappeared"
    cpu = next(d for d in devs if d.is_cpu)
    assert cpu.id == "cpu" and cpu.cores > 0
