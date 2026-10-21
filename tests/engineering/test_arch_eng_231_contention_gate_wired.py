"""ARCH-ENG-231 -> ARCH-ENG-310 — the launch never refuses on VRAM.

## What was wrong

`agents/runtime/brain_contention.py` is the only component in this codebase
that reasons about VRAM, system RAM **and** CPU cores together, across all
committed placements. It had zero production callers until ARCH-ENG-231 wired
it into the launch path as a fail-closed gate that REFUSED a launch when the
VRAM estimate outran free VRAM by a severe threshold (4 GB, later relaxed to
6 GB in c7ac5fe).

That was still a threshold on an ESTIMATE, and it fired on a real workload:
on the operator's 16 GB card, a ~22 GB big brain sits ~6.2 GB over — over the
line twice. Both times the operator overrode it with `MRBOT_ALLOW_RISKY_LAUNCH=1`
and the model worked (slower, with the excess spilling to system RAM). The
operator's decision is final on this trade: **a model larger than the card is
allowed to load, with a warning about being slower. Never a refusal.**

## What this pins (ARCH-ENG-310, warn-only)

1. **An over-budget launch PROCEEDS** — `_contention_gate` always returns "",
   and a launch whose estimate outruns free VRAM gets a WARNING appended to
   `_warn` that names the resource, the shortfall, and the fix.
2. **The warning says the launch continues and will be slower** — that is the
   operator's chosen contract, pinned so a future gate cannot quietly grow a
   `REFUSED` back into the message.
3. **A launch that fits emits no warning** — silence when the model fits, so
   the warning stays meaningful.
4. **An unestablishable footprint emits no warning** — `can_add_brain` fails
   closed on unknown size, and warning there would flag every cloud provider
   and every model named rather than pathed.
5. **The gate never becomes a new reason for a launch to fail.** Any
   exception inside it is swallowed; `run()` proceeds regardless.
6. **`MRBOT_ALLOW_RISKY_LAUNCH=1` silences even the warning** — the legacy
   knob survives as an opt-out from the note.

`test_the_gate_is_reachable_at_all` still guards the original defect: a
multi-model accounting layer whose launch path stops calling it.
"""

import os
import struct
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _tiny_gguf(path, mb=1, n_layer=32, kv_head=8, head_dim=128):
    """A real, minimal GGUF with a KV shape `estimate_vram_gb` can read."""
    def u32(k, v):
        return struct.pack("<Q", len(k)) + k + struct.pack("<I", 4) + struct.pack("<I", v)

    def u64(k, v):
        return struct.pack("<Q", len(k)) + k + struct.pack("<I", 10) + struct.pack("<Q", v)

    blob = (u32(b"general.architecture", 0)
            + u32(b"llama.block_count", n_layer)
            + u32(b"llama.attention.head_count", 32)
            + u32(b"llama.attention.head_count_kv", kv_head)
            + u32(b"llama.embedding_length", 4096)
            + u64(b"llama.attention.key_length", head_dim))
    with open(path, "wb") as fh:
        fh.write(b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0)
                 + struct.pack("<Q", 7) + blob + b"\0" * (mb * 1024 * 1024))


class _GateHarness(unittest.TestCase):
    def setUp(self):
        from agents.runtime import dual_brain as db
        from gui.workers.brain_launch_worker import BrainLaunchPrepWorker as W
        self.W = W
        self.cfg = db.build_config(db.BrainRole.BIG)
        self.tmp = tempfile.mkdtemp(prefix="arch310_")
        self.small = os.path.join(self.tmp, "tiny.gguf")
        self.med = os.path.join(self.tmp, "med.gguf")
        _tiny_gguf(self.small, mb=1)
        _tiny_gguf(self.med, mb=900)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.pop("MRBOT_ALLOW_RISKY_LAUNCH", None)

    def gate(self, model, context=None):
        """Run the gate; return (gate_return, self._warn afterwards)."""
        w = self.W.__new__(self.W)
        w.cfg = self.cfg
        if context is not None:
            w.cfg.context = context
        w.small = False
        w.gpu_device_index = 0
        w._warn = ""
        ret = w._contention_gate("Big", model)
        return ret, w._warn


class TestAnOverBudgetLaunchProceedsWithAWarning(_GateHarness):
    def test_an_impossible_launch_is_warned_about_not_refused(self):
        """ARCH-ENG-310: a model that cannot fit still RETURNS '' to run()."""
        big = os.path.join(self.tmp, "huge.gguf")
        _tiny_gguf(big, mb=600, n_layer=200, kv_head=64, head_dim=128)
        ret, warn = self.gate(big, context=65536)
        self.assertEqual(ret, "", "the gate refused an over-budget launch")
        self.assertTrue(warn, "an over-budget launch carried no warning")

    def test_the_warning_names_the_resource_and_the_shortfall(self):
        big = os.path.join(self.tmp, "huge2.gguf")
        _tiny_gguf(big, mb=600, n_layer=200, kv_head=64, head_dim=128)
        _, warn = self.gate(big, context=65536)
        lowered = warn.lower()
        self.assertIn("vram", lowered,
                      f"the warning names no resource: {warn[:140]}")
        self.assertRegex(
            warn, r"short ~[\d.]+ GB",
            f"the warning carries no shortfall number: {warn[:140]}")

    def test_the_warning_names_the_fix(self):
        big = os.path.join(self.tmp, "huge3.gguf")
        _tiny_gguf(big, mb=600, n_layer=200, kv_head=64, head_dim=128)
        _, warn = self.gate(big, context=65536)
        lowered = warn.lower()
        self.assertTrue(
            any(word in lowered for word in ("context", "layers", "smaller")),
            f"the warning offers no way to full speed: {warn[:140]}")

    def test_the_warning_says_the_launch_continues_and_will_be_slower(self):
        """The operator-facing contract: load anyway, generation slower."""
        big = os.path.join(self.tmp, "huge4.gguf")
        _tiny_gguf(big, mb=600, n_layer=200, kv_head=64, head_dim=128)
        _, warn = self.gate(big, context=65536)
        lowered = warn.lower()
        self.assertIn("load anyway", lowered, warn[:180])
        self.assertIn("slower", lowered, warn[:180])
        self.assertNotIn("refus", lowered,
                         "the warning grew a refusal back into itself")

    def test_warning_logs_do_not_lose_the_earlier_notes(self):
        """The gate MERGES into `_warn`; step 2/2b notes must survive."""
        big = os.path.join(self.tmp, "huge5.gguf")
        _tiny_gguf(big, mb=600, n_layer=200, kv_head=64, head_dim=128)
        ret, warn = self.gate(big, context=65536)
        self.assertIn("VRAM contention", warn)


class TestTheGateStaysSilentWhenTheModelFits(_GateHarness):
    """A warning on every launch is a warning the operator learns to ignore."""

    def test_a_small_model_at_normal_context_warns_nothing(self):
        ret, warn = self.gate(self.small, context=8192)
        self.assertEqual(ret, "")
        self.assertEqual(warn, "")

    def test_a_medium_model_at_normal_context_warns_nothing(self):
        ret, warn = self.gate(self.med, context=8192)
        self.assertEqual(ret, "")
        self.assertEqual(warn, "")

    def test_the_same_big_model_at_a_context_that_fits_warns_nothing(self):
        """Proves the warning tracks cost, not file size."""
        big = os.path.join(self.tmp, "huge6.gguf")
        _tiny_gguf(big, mb=600, n_layer=200, kv_head=64, head_dim=128)
        ret, warn = self.gate(big, context=512)
        self.assertEqual(ret, "")
        self.assertEqual(warn, "", "a model warned at 64k is still warned at "
                                   "512 tokens; the warning keys on the file, "
                                   "not the cost")


class TestAnUnknownFootprintStaysSilent(_GateHarness):
    def test_a_model_that_is_not_a_path_warns_nothing(self):
        """Cloud providers name their model; there is no file to measure."""
        ret, warn = self.gate("qwen3:8b-on-ollama", context=8192)
        self.assertEqual(ret, "")
        self.assertEqual(warn, "")

    def test_a_missing_file_warns_nothing(self):
        ret, warn = self.gate(os.path.join(self.tmp, "absent.gguf"))
        self.assertEqual(ret, "")
        self.assertEqual(warn, "")


class TestTheGateCannotBreakALaunch(_GateHarness):
    def test_an_exception_inside_the_gate_is_swallowed(self):
        w = self.W.__new__(self.W)
        w.cfg = self.cfg
        w.small = False
        w.gpu_device_index = 0
        w._warn = ""
        import agents.runtime.brain_contention as bc
        real = bc.can_add_brain

        def boom(*a, **k):
            raise RuntimeError("gate exploded")

        bc.can_add_brain = boom
        try:
            self.assertEqual(w._contention_gate("Big", self.med), "")
        finally:
            bc.can_add_brain = real

    def test_the_legacy_override_silences_even_the_warning(self):
        big = os.path.join(self.tmp, "huge7.gguf")
        _tiny_gguf(big, mb=600, n_layer=200, kv_head=64, head_dim=128)
        os.environ["MRBOT_ALLOW_RISKY_LAUNCH"] = "1"
        ret, warn = self.gate(big, context=65536)
        self.assertEqual(ret, "")
        self.assertEqual(warn, "", "MRBOT_ALLOW_RISKY_LAUNCH did not silence "
                                   "the contention warning")


class TestTheGateIsActuallyReachable(unittest.TestCase):
    """The defect WAS a multi-model layer with no callers. That is what this guards."""

    def test_the_launch_path_calls_the_gate(self):
        import ast
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[2]
               / "gui" / "workers" / "brain_launch_worker.py").read_text(encoding="utf-8")
        cls = next(n for n in ast.parse(src).body
                   if isinstance(n, ast.ClassDef) and n.name == "BrainLaunchPrepWorker")
        run = next(n for n in cls.body
                   if isinstance(n, ast.FunctionDef) and n.name == "run")
        body = ast.unparse(run)
        self.assertIn("_contention_gate", body,
                      "the launch path stopped consulting the contention gate; "
                      "the multi-model accounting layer is unreachable again")
        self.assertIn("prep_finished", body)

    def test_the_gate_still_runs_before_the_command_is_built(self):
        """The warning must exist before the launch prep finishes, not after."""
        import ast
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[2]
               / "gui" / "workers" / "brain_launch_worker.py").read_text(encoding="utf-8")
        cls = next(n for n in ast.parse(src).body
                   if isinstance(n, ast.ClassDef) and n.name == "BrainLaunchPrepWorker")
        run = next(n for n in cls.body
                   if isinstance(n, ast.FunctionDef) and n.name == "run")
        body = ast.unparse(run)
        gate_at = body.index("_contention_gate")
        cmd_at = body.index("build_llama_command")
        self.assertLess(gate_at, cmd_at,
                        "the gate now runs after the launch command is built")


if __name__ == "__main__":
    unittest.main()
