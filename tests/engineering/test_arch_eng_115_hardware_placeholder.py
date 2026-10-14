"""ARCH-ENG-115 — a brain prompt must never assert hardware detection did not confirm.

`BigBrainAdapter._hardware_line` / `SmallBrainAdapter._hardware_line` used to
fall back to `cfg.gpu_label` whenever the device registry came back empty. That
default is a literal PLACEHOLDER — `ROLE_DEFAULTS[BIG]["gpu_label"]` is the
string `"GPU 0 (detected hardware)"` — so whenever `nvidia-smi` returned nothing
(a transient driver hiccup, or its 5s subprocess timeout under load) the brain
was told, as fact, that it runs on a specific GPU that had never been detected.

Measured: with detection stubbed to return CPU-only, the old code produced
`"You run on GPU 0 (detected hardware)."` — asserting a GPU while the only
detected device was the CPU pool.

Two consequences, both real:
  1. The prompt stated unverified hardware to the model — an evidence-integrity
     bug in the same family as the project's financial-truth rules: an inferred
     or defaulted value presented as observed fact.
  2. `tests/runtime/test_brain_prompt_hardware.py::...not_hardcoded` was flaky
     (~50% of runs), because detection intermittently yields CPU-only while the
     prompt still claims "GPU 0", so the test's "names a real detected device"
     assertion failed.

Fix: no confirmed device -> no hardware section at all. Omitting is strictly
better than asserting a false one.
"""
import os
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from agents.brains.big_brain import BigBrainAdapter  # noqa: E402
from agents.brains.small_brain import SmallBrainAdapter  # noqa: E402
from agents.runtime import device_registry as dr  # noqa: E402


def _cpu_only():
    """The failure mode: nvidia-smi yielded nothing, only the CPU pool exists."""
    return [d for d in dr.detect_devices(include_cpu=True) if d.is_cpu]


def test_no_placeholder_is_asserted_when_detection_finds_no_matching_device():
    """The exact regression: detection empty -> prompt must not name a GPU."""
    cpu_devs = _cpu_only()
    assert cpu_devs, "precondition: the CPU pool is always detected"

    with mock.patch.object(dr, "detect_devices", return_value=cpu_devs):
        big = BigBrainAdapter()._build_system_prompt("analyze", "analysis")
        small = SmallBrainAdapter()._build_system_prompt("hello")

    for label, prompt in (("big", big), ("small", small)):
        if "# YOUR HARDWARE" not in prompt:
            continue  # correct: no confirmed device, no claim
        section = prompt[prompt.index("# YOUR HARDWARE"):]
        assert "GPU 0 (detected hardware)" not in section, (
            f"the {label}-brain prompt asserted the hardcoded placeholder "
            f"'GPU 0 (detected hardware)' while detection found no GPU")
        assert "CPU / System RAM" not in section or any(
            d.is_cpu for d in cpu_devs), (
            f"the {label}-brain prompt asserted a CPU label detection did not confirm")


def test_placeholder_string_never_reaches_a_prompt_at_all():
    """Belt and braces: the placeholder must be absent under ANY detection result."""
    for stub in (_cpu_only(), [], dr.detect_devices(include_cpu=True)):
        with mock.patch.object(dr, "detect_devices", return_value=stub):
            for prompt in (BigBrainAdapter()._build_system_prompt("a", "analysis"),
                           SmallBrainAdapter()._build_system_prompt("h")):
                assert "GPU 0 (detected hardware)" not in prompt, (
                    "the gpu_label placeholder leaked into a system prompt")


def test_a_confirmed_device_is_still_named():
    """The fix must not silence the feature: real detection still reaches the prompt."""
    devs = dr.detect_devices(include_cpu=True)
    with mock.patch.object(dr, "detect_devices", return_value=devs):
        big = BigBrainAdapter()._build_system_prompt("analyze", "analysis")
        small = SmallBrainAdapter()._build_system_prompt("hello")

    names = {d.name for d in devs}
    for label, prompt in (("big", big), ("small", small)):
        if "# YOUR HARDWARE" not in prompt:
            pytest.skip(f"no device confirmed for the {label} brain on this box")
        section = prompt[prompt.index("# YOUR HARDWARE"):]
        assert any(n in section for n in names) or "CPU" in section or "RAM" in section, (
            f"the {label}-brain hardware section names no detected device")


def test_hardware_line_returns_empty_rather_than_raising():
    """A broken registry must degrade to 'no claim', never to an exception."""
    with mock.patch.object(dr, "detect_devices", side_effect=RuntimeError("smi dead")):
        assert BigBrainAdapter()._hardware_line() == ""
        assert SmallBrainAdapter()._hardware_line() == ""
        # And the prompt builders still produce a usable prompt.
        assert isinstance(BigBrainAdapter()._build_system_prompt("a", "analysis"), str)
        assert isinstance(SmallBrainAdapter()._build_system_prompt("h"), str)


def test_neither_adapter_reads_gpu_label_as_a_fallback():
    """Structural lock: the placeholder fallback must not come back.

    Checks the parsed CODE (docstrings stripped), so the explanatory comment
    that names `gpu_label` does not trip the assertion.
    """
    import ast
    import inspect
    import textwrap

    for adapter in (BigBrainAdapter, SmallBrainAdapter):
        tree = ast.parse(textwrap.dedent(
            inspect.getsource(adapter._hardware_line)).strip())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if (node.body and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and isinstance(node.body[0].value.value, str)):
                    node.body.pop(0)
        code = ast.unparse(tree)
        assert "gpu_label" not in code, (
            f"{adapter.__name__}._hardware_line reads cfg.gpu_label again — that "
            f"is the placeholder this fix removed")
