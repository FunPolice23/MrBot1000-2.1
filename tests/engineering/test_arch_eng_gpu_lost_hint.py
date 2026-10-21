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
    # ARCH-ENG-222: `detect_devices` memoises its result for 10 s so the
    # per-chat-turn `_hardware_line()` call stops spawning `nvidia-smi`. This
    # test replaces `_run_nvidia_smi` -- a dependency BELOW the memo -- so the
    # memo must be dropped first or the mock is never consulted and the
    # assertion below passes against whatever an earlier test left behind.
    dr.invalidate_device_cache()
    with mock.patch.object(dr, "_run_nvidia_smi", return_value=_HEALTHY):
        devs = dr.detect_devices(include_cpu=True)
    assert any(d.kind == "gpu" and d.index == 0 for d in devs), (
        "healthy GPU missing from detect_devices")
    assert "reboot" in (dr._LAST_DETECT_ERROR or "").lower()


def test_a_cache_hit_replays_the_error_that_belongs_to_its_devices():
    """ARCH-ENG-222: the error string and the device list must be one fact.

    `_LAST_DETECT_ERROR` is written by `_detect_gpus` and read by
    `dual_brain_control.py:800` to show the reboot hint. The cache stores the
    devices; if it did not also store and restore the error, a hit would return
    a device list from probe N alongside an error string from probe M+1 -- two
    observations from two different moments, presented as one.
    """
    dr.invalidate_device_cache()
    with mock.patch.object(dr, "_run_nvidia_smi", return_value=_HEALTHY):
        first = dr.detect_devices(include_cpu=True)
        first_err = dr._LAST_DETECT_ERROR
    assert "reboot" in first_err.lower(), "precondition: the probe did fail"

    # A second call, still inside the TTL, must replay the SAME error -- not
    # leave whatever a clean or failed probe last wrote to the global.
    second = dr.detect_devices(include_cpu=True)
    assert dr._LAST_DETECT_ERROR == first_err, (
        "a cache hit did not restore the error that belongs to the cached "
        f"devices: got {dr._LAST_DETECT_ERROR!r}, expected {first_err!r}")
    assert [d.id for d in second] == [d.id for d in first]


def test_invalidate_device_cache_forces_a_real_reprobe():
    """The escape hatch has to actually escape, or tests and callers are stuck."""
    dr.invalidate_device_cache()
    with mock.patch.object(dr, "_run_nvidia_smi", return_value=_HEALTHY_ONLY):
        dr.detect_devices(include_cpu=True)
    assert dr._LAST_DETECT_ERROR == "", "precondition: a clean probe, no error"

    # Cache is warm and clean. A lost-GPU probe must still be honoured.
    with mock.patch.object(dr, "_run_nvidia_smi", return_value=_HEALTHY):
        dr.detect_devices(include_cpu=True)   # cache hit; error restored to ""
        assert dr._LAST_DETECT_ERROR == ""
        dr.invalidate_device_cache()
        dr.detect_devices(include_cpu=True)
    assert "reboot" in (dr._LAST_DETECT_ERROR or "").lower(), (
        "invalidate_device_cache() did not force a real reprobe")


def test_clean_probe_leaves_no_error():
    """A clean probe (no lost GPU) must not record a spurious error."""
    with mock.patch.object(dr, "_run_nvidia_smi", return_value=_HEALTHY_ONLY):
        dr._detect_gpus()
    assert dr._LAST_DETECT_ERROR == "", (
        "a clean probe must not record an error")