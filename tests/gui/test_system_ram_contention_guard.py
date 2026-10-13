"""System-RAM contention guard for brain launch (v2.1.55, ARCH-ENG-055).

A GPU brain is NOT VRAM-isolated: llama.cpp mmaps the GGUF, so the model's
weights live in the system page cache and get faulted into resident RAM under
memory pressure. When the CPU/RAM brain generates it builds its KV cache and
drains system RAM; the GPU brain's ~10 GB model then goes resident, the two
footprints collide, and the GPU brain's llama-server hits a failed allocation
and ABORTS — silently (no OS crash, no GPU TDR). Measured live: a 10.7 GB GPU
model spiked 378 MB -> 11.4 GB resident right as the CPU brain built its 32k
KV, then died ("big brain terminal just exits when I Chat the small brain").

``BrainLaunchPrepWorker._system_ram_contention_warn`` sums the REAL resident
RAM of the OTHER running servers plus this brain's own projected weights+KV,
compares against currently-available RAM, and returns a loud warning when the
total would leave too little headroom. Warn-only — llama.cpp legitimately
spills, so the operator decides, never a hard block.
"""
import os

import pytest

from gui.workers.brain_launch_worker import BrainLaunchPrepWorker


SMALL_MODEL = ("D:/llama.cpp/models/Qwen3-4B-Thinking-2507-GGUF/"
               "Qwen3-4B-Thinking-2507-Q6_K.gguf")


class _FakeCfg:
    def __init__(self, context=32768, kv_cache="f16"):
        self.context = context
        self.kv_cache = kv_cache


def _worker(model=SMALL_MODEL, port=1235, cfg=None):
    w = BrainLaunchPrepWorker.__new__(BrainLaunchPrepWorker)  # bypass QThread
    w.port = port
    w.model_path = model
    w.cfg = cfg or _FakeCfg()
    return w


@pytest.mark.skipif(not os.path.exists(SMALL_MODEL),
                    reason="small-brain GGUF not present on this machine")
class TestSystemRamContentionGuard:
    def test_warns_when_combined_footprint_exceeds_headroom(self, monkeypatch):
        """Crash-time inputs (19 GB free, big brain resident 8.2 GB) must warn."""
        w = _worker()
        monkeypatch.setattr(BrainLaunchPrepWorker, "_available_ram_gb",
                            staticmethod(lambda: 19.0))
        monkeypatch.setattr(BrainLaunchPrepWorker, "_other_servers_ram_gb",
                            staticmethod(lambda exclude_port: (8.2, [("Big/GPU", 8.2)])))
        msg = w._system_ram_contention_warn("Small", SMALL_MODEL)
        assert msg, "must warn when combined RAM leaves too little headroom"
        assert "SYSTEM-RAM RISK" in msg
        assert "Big/GPU" in msg            # names the contending brain
        assert "Lower the context" in msg   # gives the actionable fix

    def test_no_warn_when_plenty_of_ram(self, monkeypatch):
        """Negative control: abundant RAM + nothing else running -> silent."""
        w = _worker()
        monkeypatch.setattr(BrainLaunchPrepWorker, "_available_ram_gb",
                            staticmethod(lambda: 40.0))
        monkeypatch.setattr(BrainLaunchPrepWorker, "_other_servers_ram_gb",
                            staticmethod(lambda exclude_port: (0.0, [])))
        assert w._system_ram_contention_warn("Small", SMALL_MODEL) == ""

    def test_lowering_context_removes_warning(self, monkeypatch):
        """The named fix (lower context) actually resolves the risk."""
        # Same tight RAM, but an 8k context KV is far smaller -> fits.
        w = _worker(cfg=_FakeCfg(context=8192, kv_cache="f16"))
        monkeypatch.setattr(BrainLaunchPrepWorker, "_available_ram_gb",
                            staticmethod(lambda: 19.0))
        monkeypatch.setattr(BrainLaunchPrepWorker, "_other_servers_ram_gb",
                            staticmethod(lambda exclude_port: (8.2, [("Big/GPU", 8.2)])))
        assert w._system_ram_contention_warn("Small", SMALL_MODEL) == ""

    def test_headroom_threshold_respected(self, monkeypatch):
        """Above the 4 GB floor -> silent; clearly below -> warns.

        (Uses comfortable margins rather than the exact float boundary, since
        the KV estimate and the weights read use slightly different GB units.)
        """
        weights_gb = os.path.getsize(SMALL_MODEL) / (1024.0 ** 3)
        own = weights_gb + 4.8  # 32k f16 KV ~4.8 GB

        w_safe = _worker()
        monkeypatch.setattr(BrainLaunchPrepWorker, "_available_ram_gb",
                            staticmethod(lambda: own + 8.0))   # 8 GB headroom
        monkeypatch.setattr(BrainLaunchPrepWorker, "_other_servers_ram_gb",
                            staticmethod(lambda exclude_port: (0.0, [])))
        assert w_safe._system_ram_contention_warn("Small", SMALL_MODEL) == ""

        w_tight = _worker()
        monkeypatch.setattr(BrainLaunchPrepWorker, "_available_ram_gb",
                            staticmethod(lambda: own + 1.0))   # 1 GB headroom
        assert w_tight._system_ram_contention_warn("Small", SMALL_MODEL) != ""

    def test_guard_never_raises_on_bad_inputs(self, monkeypatch):
        """A probe failure must degrade to no-warning, never crash the launch."""
        w = _worker(model="/nonexistent/model.gguf")
        monkeypatch.setattr(BrainLaunchPrepWorker, "_available_ram_gb",
                            staticmethod(lambda: 0.0))  # reader failed
        # even with a huge 'other' footprint, avail<=0 short-circuits to ""
        monkeypatch.setattr(BrainLaunchPrepWorker, "_other_servers_ram_gb",
                            staticmethod(lambda exclude_port: (999.0, [("x", 999.0)])))
        assert w._system_ram_contention_warn("Small", "/nonexistent/model.gguf") == ""


class TestRamProbes:
    def test_available_ram_reader_returns_positive(self):
        """The ctypes GlobalMemoryStatusEx reader works on this host."""
        val = BrainLaunchPrepWorker._available_ram_gb()
        assert val > 0, "available-RAM reader should return a positive value"

    def test_other_servers_reader_is_safe_with_no_servers(self):
        """No llama-servers running -> (0.0, []), never an exception."""
        total, details = BrainLaunchPrepWorker._other_servers_ram_gb(exclude_port=1234)
        assert isinstance(total, float)
        assert isinstance(details, list)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
