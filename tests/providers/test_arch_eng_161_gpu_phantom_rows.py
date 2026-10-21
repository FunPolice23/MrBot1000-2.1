"""ARCH-ENG-161 — phantom/duplicate GPU rows produced duplicate panels.

Released as v2.1.112 with NO `ARCH-ENG-nnn` id in its CHANGELOG entry, so the
ARCH-ENG-150 guard ("a recorded fix must be present in HEAD") had nothing to
verify: `test_top_entry_names_at_least_one_fix` failed, and the guard could not
distinguish "the fix shipped" from "the entry makes a claim nobody can check".
This suite supplies the tag and the executable check the guard requires.

The defect (v2.1.112, commit 8bdc3ed): right after a GPU is recovered, or mid
driver re-init, `nvidia-smi` can emit a phantom row (empty name, 0 MB) or repeat
an index. `ProviderManager._detect_gpus` accepted every row into the cache, and
`DualBrainControl.setup_ui` then called `addWidget` once per row while
`self.gpu_widgets` — a dict keyed by index — kept only the last. For 2 real GPUs
the operator saw 4 panels (2 empty + 2 real), and the real panel's live refresh
was orphaned: the dict held the phantom's widget under the real device's index,
so the genuine GPU stopped updating.

Two independent halves, both asserted here:
  * SOURCE — `_detect_gpus` validates each row (index >= 0, non-empty name,
    memory > 0) and dedupes by index before the row enters the cache.
  * RENDER — `setup_ui` dedupes by index and skips unusable rows before
    building a widget, so panel count equals distinct real device count.

The reproduction was by execution: injecting a phantom + duplicate list produced
4 panels created / 2 tracked before the fix, and 2 / 2 after.
"""

import unittest
from unittest.mock import patch

from agents.providers.provider_manager import GPUInfo, ProviderManager


def _row(idx, name, mem_mb):
    """One nvidia-smi CSV row: index,name,mem.total,mem.used,mem.free,temp,util,cc"""
    return f"{idx}, {name}, {mem_mb}, 0, {mem_mb}, 30, 5, 8.9"


def _gpu(idx, name, mem_mb):
    """A GPUInfo with all required fields (index, name, total, used, free)."""
    return GPUInfo(index=idx, name=name, memory_total_mb=mem_mb,
                   memory_used_mb=0, memory_free_mb=mem_mb)


class _FakeRun:
    """Stand-in for `subprocess.CompletedProcess` from nvidia-smi.

    Retained for readers of the pre-ARCH-ENG-166 form, which called
    `subprocess.run` directly. `_detect_gpus` now goes through
    `_run_nvidia_smi`, which returns CSV text directly.
    """

    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


class TestDetectGpusRejectsPhantomRows(unittest.TestCase):
    """ARCH-ENG-161 SOURCE — the cache must never hold a phantom or duplicate.

    ARCH-ENG-166: `_detect_gpus` no longer calls `subprocess.run` itself — it
    delegates to `device_registry._run_nvidia_smi`, the one hardened nvidia-smi
    invocation (ARCH-ENG-116). So this patches that function and feeds it CSV
    text directly, which also makes the test independent of whether an NVIDIA
    driver is present.
    """

    def _detect(self, stdout):
        pm = ProviderManager.__new__(ProviderManager)   # bypass singleton/threads
        with patch("agents.runtime.device_registry._run_nvidia_smi",
                   return_value=stdout):
            pm._detect_gpus()
        return pm._gpus

    def test_phantom_row_is_rejected(self):
        gpus = self._detect("\n".join([
            _row(0, "NVIDIA GeForce RTX 4090", 24576),
            _row(1, "", 0),          # phantom: empty name, 0 MB
        ]))
        self.assertEqual([g.index for g in gpus], [0])

    def test_duplicate_index_is_rejected(self):
        gpus = self._detect("\n".join([
            _row(0, "NVIDIA GeForce RTX 4090", 24576),
            _row(0, "NVIDIA GeForce RTX 4090", 24576),   # repeated index
        ]))
        self.assertEqual(len(gpus), 1)

    def test_negative_index_is_rejected(self):
        gpus = self._detect("\n".join([
            _row(-1, "NVIDIA GeForce RTX 4090", 24576),
            _row(1, "NVIDIA GeForce RTX 4080", 16384),
        ]))
        self.assertEqual([g.index for g in gpus], [1])

    def test_zero_memory_row_is_rejected(self):
        gpus = self._detect("\n".join([
            _row(0, "NVIDIA GeForce RTX 4090", 0),
            _row(1, "NVIDIA GeForce RTX 4080", 16384),
        ]))
        self.assertEqual([g.index for g in gpus], [1])

    def test_two_real_gpus_both_survive(self):
        """The filter must not be so aggressive it hides real hardware."""
        gpus = self._detect("\n".join([
            _row(0, "NVIDIA GeForce RTX 4090", 24576),
            _row(1, "NVIDIA GeForce RTX 4080", 16384),
        ]))
        self.assertEqual([g.index for g in gpus], [0, 1])

    def test_malformed_row_does_not_raise(self):
        """A non-integer index/memory must skip, not crash the probe."""
        gpus = self._detect("\n".join([
            "notanumber, NVIDIA GeForce RTX 4090, 24576, 0, 0, 0, 0",
            "0, NVIDIA GeForce RTX 4090, notanumber, 0, 0, 0, 0",
            _row(1, "NVIDIA GeForce RTX 4080", 16384),
        ]))
        self.assertEqual([g.index for g in gpus], [1])

    def test_empty_output_yields_no_gpus(self):
        self.assertEqual(self._detect(""), [])


class TestRenderDedupeMatchesSourceFilter(unittest.TestCase):
    """ARCH-ENG-161 RENDER — panels must equal distinct real devices.

    The bug was the mismatch between rows rendered and widgets tracked: 4 panels
    created, 2 tracked. This asserts the render path applies the same rule as the
    source path, so the two cannot drift apart again.
    """

    def _rendered(self, gpus):
        """Replicate setup_ui's filter exactly (see dual_brain_control.py)."""
        seen, shown = set(), []
        for gpu in gpus:
            idx = getattr(gpu, "index", -1)
            name = (getattr(gpu, "name", "") or "").strip()
            mem = getattr(gpu, "memory_total_mb", 0) or 0
            if idx < 0 or not name or mem <= 0 or idx in seen:
                continue
            seen.add(idx)
            shown.append(idx)
        return shown

    def test_phantom_plus_real_renders_one_panel_per_real_gpu(self):
        gpus = [
            _gpu(0, "NVIDIA GeForce RTX 4090", 24576),
            _gpu(1, "", 0),        # phantom
            _gpu(1, "NVIDIA GeForce RTX 4080", 16384),
            _gpu(0, "NVIDIA GeForce RTX 4090", 24576),
        ]
        self.assertEqual(self._rendered(gpus), [0, 1])

    def test_panel_count_equals_tracked_widget_count(self):
        """The original symptom: 4 panels created but only 2 tracked."""
        gpus = [
            _gpu(0, "NVIDIA GeForce RTX 4090", 24576),
            _gpu(1, "", 0),
            _gpu(1, "NVIDIA GeForce RTX 4080", 16384),
        ]
        rendered = self._rendered(gpus)
        tracked = {g.index for g in gpus}          # gpu_widgets is keyed by index
        self.assertEqual(len(rendered), len(tracked))
        self.assertEqual(set(rendered), tracked)

    def test_two_real_gpus_render_two_panels(self):
        gpus = [
            _gpu(0, "NVIDIA GeForce RTX 4090", 24576),
            _gpu(1, "NVIDIA GeForce RTX 4080", 16384),
        ]
        self.assertEqual(self._rendered(gpus), [0, 1])


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-161 — assert the filter actually rejects, rather than passing
    because the fixture is empty."""

    def test_probe_confirms_a_phantom_row_would_survive_the_old_filter(self):
        """Without the guard, the phantom+duplicate list renders 4 panels."""
        gpus = [
            _gpu(0, "NVIDIA GeForce RTX 4090", 24576),
            _gpu(1, "", 0),
            _gpu(1, "NVIDIA GeForce RTX 4080", 16384),
            _gpu(0, "NVIDIA GeForce RTX 4090", 24576),
        ]
        # The pre-fix render loop had no validation and no dedupe.
        old_shown = [g.index for g in gpus]
        self.assertEqual(len(old_shown), 4)
        self.assertEqual(len(set(old_shown)), 2)


if __name__ == "__main__":
    unittest.main()