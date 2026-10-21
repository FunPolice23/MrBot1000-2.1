"""ARCH-ENG-221 — two per-request costs that were being paid on every turn.

## A. Allocation tracing ran for the whole process lifetime

`agents/runtime/performance.py` called `tracemalloc.start()` at MODULE IMPORT,
unconditionally. `agents/runtime/__init__.py:4` re-exports from that module, so
merely importing anything under `agents.runtime` — including `device_registry`,
which `_hardware_line()` touches on every chat turn — switched allocation tracing
on for the entire process.

tracemalloc records every `PyObject` allocation and free in its own hash table:
typically a 2–4× slowdown on allocation-bound Python, with a trace table that
grows without bound. This application streams tokens, rebuilds prompts and
f-strings, and churns tens of thousands of `QTableWidgetItem` objects per minute
across six or more threads. It was paying that continuously to serve ONE
diagnostic — `snapshot()`'s current/peak memory figures.

It is now opt-in via `MRBOT_TRACE_MEMORY=1`. The snapshot reports
`memory_traced` explicitly, because `get_traced_memory()` returns `(0, 0)` when
tracing never started, and a diagnostic panel showing "0 bytes used" is a false
claim — the same failure mode this codebase keeps producing.

## B. The GGUF header was re-read on every chat turn

`gguf_meta.read_metadata` had no cache, while its siblings
`read_scalar_metadata` and `read_header_metadata` both did. It is reached from
`model_profile._read_gguf_metadata` → `big_brain.py:509` / `small_brain.py:301`,
i.e. once per `chat()` call per brain.

Its `_read_val` materialises vtype 9 values: `tokenizer.ggml.tokens` is
151k–293k entries and `merges` ~280k more, decoded into Python `str` objects.

Measured on a 10.36 GB GGUF on the target machine:

    cold  3672.6 ms   warm  0.213 ms   ->  17,267x

That cold figure is far worse than the ~300 ms an estimate predicted, because a
10 GB read on a 6-core machine with a spinning or cold-cache disk is dominated by
I/O. The important number is that it was paid **every turn**, not once.

### The bug this ticket's own first draft had

The cache key was named `key` — which the surrounding loop already binds to each
metadata key **string**. The value was therefore stored under whatever key
happened to be read last, and every lookup (using the tuple) missed. The cache
silently did nothing while appearing to be populated. `_cache_key` is the fix,
and `test_the_cache_key_is_not_shadowed_by_the_loop_variable` pins it.

The returned dict is copied on both store and fetch, so a caller mutating the
result cannot corrupt the cache for the next turn.
"""

import ast
import os
import pathlib
import struct
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
PERF = REPO / "agents" / "runtime" / "performance.py"
GGUF = REPO / "agents" / "providers" / "gguf_meta.py"


def _make_gguf(path, n_scalars=3, n_strings=1):
    """A minimal but real GGUF: header + a few K/V pairs."""
    kv = b""
    for i in range(n_scalars):
        k = f"general.architecture{i}".encode()
        kv += struct.pack("<Q", len(k)) + k
        kv += struct.pack("<I", 4)          # vtype UINT32
        kv += struct.pack("<I", i + 1)
    for i in range(n_strings):
        k = f"tokenizer.ggml.tokens{i}".encode()
        v = b"a,b,c"
        kv += struct.pack("<Q", len(k)) + k
        kv += struct.pack("<I", 8)          # vtype STRING
        kv += struct.pack("<Q", len(v)) + v
    n_kv = n_scalars + n_strings
    with open(path, "wb") as f:
        f.write(b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0)
                + struct.pack("<Q", n_kv) + kv)


class TestTracingIsOptIn(unittest.TestCase):
    """ARCH-ENG-221 — tracemalloc must not run in normal operation."""

    def test_the_module_does_not_start_tracing_on_import(self):
        """The whole point: an unconditional module-level start."""
        body = ast.unparse(ast.parse(PERF.read_text(encoding="utf-8")))
        self.assertNotIn(
            "tracemalloc.start()\n", body.split("_TRACE_MEMORY =")[0],
            "tracemalloc.start() runs unconditionally at import; a bare call "
            "outside the env guard reinstates a 2-4x whole-process tax")

    def test_it_is_gated_behind_the_env_flag(self):
        body = ast.unparse(ast.parse(PERF.read_text(encoding="utf-8")))
        self.assertIn("MRBOT_TRACE_MEMORY", body)
        self.assertRegex(body, r"if _TRACE_MEMORY:\s*\n\s*tracemalloc\.start")

    def test_importing_agents_runtime_does_not_trace(self):
        """The re-export in agents/runtime/__init__.py is what made this global."""
        import subprocess
        import sys
        code = (
            "import tracemalloc, sys;"
            "sys.path.insert(0, r'%s');"
            "import agents.runtime;"
            "print(tracemalloc.is_tracing())" % REPO
        )
        out = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True, timeout=120,
                             encoding="utf-8", errors="replace")
        self.assertEqual(out.stdout.strip(), "False",
                         "importing agents.runtime started allocation tracing "
                         "again")

    def test_the_snapshot_says_whether_it_is_measured(self):
        from agents.runtime.performance import telemetry
        snap = telemetry.snapshot()
        self.assertIn("memory_traced", snap,
                      "the snapshot cannot distinguish a real measurement from "
                      "a 0-byte default")
        if not snap["memory_traced"]:
            self.assertEqual(snap.get("memory_current", 0), 0,
                             "untraced memory reported as a non-zero figure")


class TestReadMetadataIsCached(unittest.TestCase):
    """ARCH-ENG-221 — the GGUF header must not be re-read per turn."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="arch221_")
        self.model = os.path.join(self.tmp, "tiny.gguf")
        _make_gguf(self.model)
        from agents.providers import gguf_meta
        self.m = gguf_meta
        self.m._FULL_CACHE.clear()

    def tearDown(self):
        self.m._FULL_CACHE.clear()

    def test_a_repeat_read_returns_the_same_dict(self):
        a = self.m.read_metadata(self.model)
        b = self.m.read_metadata(self.model)
        self.assertEqual(a, b)
        self.assertTrue(a, "the synthetic GGUF produced no metadata at all")

    def test_the_second_read_actually_hits_the_cache(self):
        self.m.read_metadata(self.model)
        key = next(iter(self.m._FULL_CACHE))
        self.assertEqual(len(self.m._FULL_CACHE), 1)
        self.assertIsInstance(key, tuple,
                              "the cache is keyed by something other than the "
                              "(path, mtime, size) tuple")
        # A read must not re-parse: corrupt the file and the cache still serves.
        self.m._FULL_CACHE[key]["__probe__"] = 1
        self.assertIn("__probe__", self.m.read_metadata(self.model),
                      "the second read re-parsed the file instead of serving "
                      "the cache")

    def test_the_returned_dict_is_a_copy(self):
        """A caller mutating the result must not poison the next turn."""
        first = self.m.read_metadata(self.model)
        first["injected"] = True
        second = self.m.read_metadata(self.model)
        self.assertNotIn("injected", second,
                         "callers share the cached dict; a mutation in one "
                         "turn corrupts every later turn")

    def test_a_changed_file_is_re_read(self):
        first = self.m.read_metadata(self.model)
        _make_gguf(self.model, n_scalars=7)
        second = self.m.read_metadata(self.model)
        self.assertNotEqual(first, second,
                            "editing the model on disk did not invalidate the "
                            "cache; the stale header would size VRAM wrongly")

    def test_a_missing_file_returns_empty_without_caching(self):
        self.assertEqual(self.m.read_metadata(os.path.join(self.tmp, "gone.gguf")),
                         {})
        self.assertEqual(len(self.m._FULL_CACHE), 0)

    def test_the_cache_is_bounded(self):
        for i in range(self.m._FULL_CACHE_MAX + 4):
            p = os.path.join(self.tmp, f"m{i}.gguf")
            _make_gguf(p)
            self.m.read_metadata(p)
        self.assertLessEqual(len(self.m._FULL_CACHE), self.m._FULL_CACHE_MAX,
                             "the metadata cache grows without bound")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-221 — each detector must be able to fail."""

    def test_the_cache_key_is_not_shadowed_by_the_loop_variable(self):
        """THE BUG THIS TICKET'S OWN FIRST DRAFT HAD.

        The key was named `key`, which the surrounding parse loop already binds
        to each metadata key STRING. So the value was stored under the last
        string read and every tuple lookup missed -- a cache that appeared
        populated and did nothing.
        """
        tree = ast.parse(GGUF.read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "read_metadata")
        cache_var = None
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and isinstance(node.value, ast.Tuple):
                        if any(isinstance(e, ast.Attribute) and e.attr == "st_mtime_ns"
                               for e in node.value.elts):
                            cache_var = t.id
        self.assertIsNotNone(cache_var, "no (path, mtime, size) key found")
        self.assertNotEqual(
            cache_var, "key",
            "the cache key reuses `key`, which the parse loop rebinds to a "
            "metadata key STRING; the entry is stored under that string and "
            "every tuple lookup misses")
        # And the loop must actually rebind it, proving the collision is real.
        loop_binds_key = any(
            isinstance(node, ast.Assign)
            for node in ast.walk(fn)
            for t in getattr(node, "targets", [])
            if isinstance(t, ast.Name) and t.id == "key")
        self.assertTrue(loop_binds_key,
                        "the parse loop no longer binds `key`; if that changed, "
                        "re-check whether this guard is still meaningful")

    def test_the_synthetic_gguf_is_readable(self):
        """Otherwise every cache test above passes on an empty dict."""
        from agents.providers import gguf_meta
        tmp = tempfile.mkdtemp(prefix="arch221b_")
        path = os.path.join(tmp, "t.gguf")
        _make_gguf(path)
        self.assertTrue(gguf_meta.read_metadata(path),
                        "the synthetic GGUF produced no metadata, so the cache "
                        "tests would pass vacuously")

    def test_the_shadowing_guard_would_catch_the_original_bug(self):
        """Show the detector fails on a known-bad file, not just the good one.

        An earlier draft of this guard asserted only that the variable is not
        named `key`. That is a claim about spelling: rename it to `key_` and the
        guard passes while the collision is still possible. This version builds
        the ORIGINAL broken function and runs the same detector over it.
        """
        broken = '''
def read_metadata(path):
    key = (path, st.st_mtime_ns, st.st_size)
    for _ in range(n_kv):
        (kl,) = struct.unpack("<Q", f.read(8))
        key = f.read(kl).decode("utf-8", "replace")
    _FULL_CACHE[key] = out
'''
        fixed = GGUF.read_text(encoding="utf-8")

        def detect(source):
            fn = next(n for n in ast.walk(ast.parse(source))
                      if isinstance(n, ast.FunctionDef) and n.name == "read_metadata")
            var = None
            for node in ast.walk(fn):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name) and isinstance(node.value, ast.Tuple):
                            if any(isinstance(e, ast.Attribute)
                                   and e.attr == "st_mtime_ns" for e in node.value.elts):
                                var = t.id
            return var

        self.assertEqual(detect(broken), "key",
                         "the known-bad source does not reproduce the bug, so "
                         "the guard below proves nothing")
        self.assertNotEqual(detect(fixed), "key")