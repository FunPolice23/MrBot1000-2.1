"""B1 — a lost GPU must be explained (reboot hint), not silently dropped.

`_detect_gpus` treats nvidia-smi's "GPU is lost" / "Unable to determine the
device handle" lines as a diagnostic: it records a reboot hint in
`_LAST_DETECT_ERROR` while STILL returning the healthy GPU(s) — a lost GPU is
NOT "no GPUs". The Providers & GPU device panel and the Live Log surface the
hint so a missing GPU is explained rather than silently absent.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest import mock  # noqa: E402

from agents.runtime import device_registry as dr  # noqa: E402

_HEALTHY = (
    "0, NVIDIA GeForce RTX 5060 Ti, 16384, GPU-abc123, 8.9\n"
    "Unable to determine the device handle for GPU0000:01:00.0\n"
)
_HEALTHY_ONLY = "0, NVIDIA GeForce RTX 5060 Ti, 16384, GPU-abc123, 8.9\n"


def test_gpu_lost_line_records_reboot_hint_and_keeps_healthy_gpu():
    """A lost second GPU must not hide the healthy one, and the error must
    carry a reboot hint."""
    with mock.patch.object(dr, "_run_nvidia_smi", return_value=_HEALTHY):
        devs = dr._detect_gpus()
    assert devs, "a lost second GPU must not hide the healthy one"
    assert any(d.index == 0 for d in devs), "healthy GPU (index 0) missing"
    err = (dr._LAST_DETECT_ERROR or "").lower()
    assert "reboot" in err, f"no reboot hint in {dr._LAST_DETECT_ERROR!r}"
    assert "lost" in err or "device handle" in err


def test_detect_devices_still_returns_healthy_gpu_on_lost():
    """`detect_devices` returns the healthy GPU even when a card is lost."""
    with mock.patch.object(dr, "_run_nvidia_smi", return_value=_HEALTHY):
        devs = dr.detect_devices(include_cpu=True)
    assert any(d.kind == "gpu" and d.index == 0 for d in devs), (
        "healthy GPU missing from detect_devices")
    assert "reboot" in (dr._LAST_DETECT_ERROR or "").lower()


def test_clean_probe_leaves_no_error():
    """A clean probe (no lost GPU) must not record a spurious error."""
    with mock.patch.object(dr, "_run_nvidia_smi", return_value=_HEALTHY_ONLY):
        dr._detect_gpus()
    assert dr._LAST_DETECT_ERROR == "", (
        "a clean probe must not record an error")