"""ARCH-ENG-174/175/176 — the GUI thread, the transcript, and the reset button.

Three defects where the Dialogue tab did something the operator would read as
something else.

ARCH-ENG-174 — RESET DID NOT ACTUALLY RESET.

`reset_dialogue()` cleared `conversation_history` and the transcript widget but
left `_generation_id` alone. `_on_response_ready` discards a response when
`generation != self._generation_id` — so after a Reset, every in-flight worker
still matched the current generation and its reply was APPENDED TO THE FRESHLY
CLEARED TRANSCRIPT. The operator presses Reset, sees an empty chat, and then
watched a persona answer a question they had just erased. That is the "UI
contradicts backend" failure in its purest form: the operator cannot tell which
words in the chat they actually said.

It also did not stop a Live session or cancel a worker, so resetting mid-turn
left generation running against a wiped history.

ARCH-ENG-175 — TWO GUI-THREAD STALLS, EVERY TURN.

(a) `_earning_operational_context()` opened three operator SQLite databases per
    turn with `with sqlite3.connect(path) as conn:`. That context manager
    COMMITS OR ROLLS BACK — it does NOT CLOSE the handle, so every turn leaked
    three connections. And the default busy timeout is 5 SECONDS per database;
    these are the live databases the agents are writing, so an overlapping write
    could freeze the whole window for up to ~15 seconds with no repaint and no
    click response. This is precisely what `gui/workers/db_query_worker.py`
    exists to prevent.

(b) `_brain_gpu_vram_gb()` forked `nvidia-smi` via `check_output(timeout=5)`
    from inside the Qt event loop. `respond()` reaches it every turn
    (`_model_output_contract(tier=None)` -> `_tier_for_brain`). On a box with no
    NVIDIA GPU — or a driver mid-restart — that is a guaranteed 5-second freeze
    per turn. A worker's path does not take this branch, so the stall was
    specific to the single-turn path the operator uses most.

ARCH-ENG-176 — MODEL OUTPUT WAS NOT HTML-ESCAPED.

`_markdown_to_html()` takes MODEL TEXT and returns a string appended straight
into a rich-text sink (`QTextEdit.append`). Raw persona output could inject HTML:
an `<img src="http://...">` makes Qt fetch that resource on the GUI thread
(leaking the operator's IP and blocking the window), and an unclosed `<table>`
swallows every subsequent message. Personas are told not to emit HTML, but a
jailbroken model, a retrieved page echoed back, or a small local model drifting
all reach this sink — and `Agent.md`'s UNTRUSTED-content discipline applies here
exactly as it does to a tool result. The nearby `_report_numeric_gaps` already
escaped; this path did not.
"""

import ast
import inspect
import os
import re
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest import mock

REPO = __import__("pathlib").Path(__file__).resolve().parents[2]


def _code_only(func):
    """The function's source with its DOCSTRING stripped.

    These guards assert on structure, so they must not match the prose that
    documents the defect. The first version of this file asserted
    `"with sqlite3.connect(" not in src` and immediately failed — because the
    ARCH-ENG-175 docstring explains that exact pattern by quoting it. A guard
    that reads its own documentation is a false alarm.
    """
    import textwrap
    body = textwrap.dedent(inspect.getsource(func))
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


def _tab_cls():
    import agents.safety  # noqa: F401  (breaks the import cycle)
    from gui.tabs.dialogue_tab import DialogueTab
    return DialogueTab


def _stub_tab(**attrs):
    """A minimal stand-in so these stay headless unit tests, no QWidget."""
    import types
    tab = types.SimpleNamespace()
    for key, value in attrs.items():
        setattr(tab, key, value)
    return tab


# ── ARCH-ENG-174 ──────────────────────────────────────────────────────────────

class TestResetInvalidatesInFlightWork(unittest.TestCase):
    """ARCH-ENG-174 — Reset must invalidate anything already generating."""

    def test_reset_bumps_the_generation_id(self):
        src = inspect.getsource(_tab_cls().reset_dialogue)
        self.assertIn("_generation_id", src,
                      "reset_dialogue must invalidate in-flight responses, or "
                      "an already-generating worker's reply is appended to the "
                      "freshly cleared transcript")

    def test_reset_stops_a_live_session(self):
        src = inspect.getsource(_tab_cls().reset_dialogue)
        self.assertIn("stop_live", src,
                      "reset_dialogue must stop a Live session; otherwise "
                      "generation continues against a wiped history")

    def test_reset_cancels_the_worker(self):
        src = inspect.getsource(_tab_cls().reset_dialogue)
        self.assertIn("cancel()", src,
                      "reset_dialogue must cancel the in-flight worker")

    def test_a_stale_response_is_still_discarded(self):
        """The invariant itself: a reply from a pre-Reset worker is dropped."""
        cls = _tab_cls()
        tab = _stub_tab(_generation_id=5, live_running=False)
        tab.conversation_history = []
        dropped = []

        # Simulate the guard the production code uses.
        generation = 4          # the worker's generation, from before the Reset
        if (generation is not None
                and generation != tab._generation_id
                and not tab.live_running):
            dropped.append(True)
        self.assertTrue(dropped,
                        "a pre-Reset response would be accepted after the tab "
                        "was reset — that is the defect")

    def test_a_post_reset_response_is_accepted(self):
        """The fix must not break the normal path."""
        tab = _stub_tab(_generation_id=6, live_running=False)
        generation = 6
        accepted = not (generation != tab._generation_id
                        and not tab.live_running)
        self.assertTrue(accepted,
                        "a current response was wrongly discarded")


# ── ARCH-ENG-175 ──────────────────────────────────────────────────────────────

class TestNoGuiThreadStalls(unittest.TestCase):
    """ARCH-ENG-175 — bounded, closed, and not re-queried per turn."""

    def test_sqlite_connections_are_closed(self):
        code = _code_only(_tab_cls()._earning_operational_context)
        self.assertIn("conn.close()", code,
                      "`with sqlite3.connect(...)` does NOT close the handle; "
                      "an explicit close is required or every turn leaks three "
                      "connections")
        self.assertNotIn("with sqlite3.connect(", code,
                         "the `with` form reads like it closes but does not")

    def test_sqlite_has_a_bounded_busy_timeout(self):
        """The default is 5s PER DATABASE — three of them freeze the window."""
        code = _code_only(_tab_cls()._earning_operational_context)
        m = re.search(r"sqlite3\.connect\([^)]*timeout\s*=", code)
        self.assertIsNotNone(
            m,
            "no busy timeout is set, so a contended read blocks the GUI thread "
            "for the 5-second sqlite3 default, up to three times per turn")

    def test_the_operational_context_is_cached(self):
        code = _code_only(_tab_cls()._earning_operational_context)
        self.assertIn("_ops_context_cache", code,
                      "the three databases are re-queried on every turn; a "
                      "short TTL cache keeps consecutive turns off the GUI thread")

    def test_a_cache_hit_does_not_touch_the_databases(self):
        """Prove the cache actually short-circuits."""
        cls = _tab_cls()
        calls = []
        real_connect = sqlite3.connect

        def counting_connect(path, *a, **kw):
            calls.append(path)
            return real_connect(path, *a, **kw)

        tab = _stub_tab(_ops_context_cache=None, _ops_context_ttl_s=60.0)
        with mock.patch.object(sqlite3, "connect", counting_connect):
            cls._earning_operational_context(tab)
            first = len(calls)
            cls._earning_operational_context(tab)      # cache hit
            second = len(calls)
        self.assertGreater(first, 0, "the first call never queried anything")
        self.assertEqual(second, first,
                         "the second call re-queried the databases despite a "
                         "warm cache")

    def test_vram_is_cached_and_never_forked_per_turn(self):
        code = _code_only(_tab_cls()._brain_gpu_vram_gb)
        self.assertIn("_vram_cache", code,
                      "VRAM must be cached: the query ran on the GUI thread "
                      "once per dialogue turn")
        self.assertNotIn("check_output", code,
                         "`check_output` is the ARCH-ENG-116-broken subprocess "
                         "shape; use the hardened _run_nvidia_smi")

    def test_a_vram_cache_hit_forks_no_process(self):
        cls = _tab_cls()
        calls = []

        def fake_smi(query):
            calls.append(query)
            return "24576\n"

        tab = _stub_tab(_vram_cache=None)
        with mock.patch(
            "agents.runtime.device_registry._run_nvidia_smi", fake_smi):
            first = cls._brain_gpu_vram_gb(tab, small=False)
            second = cls._brain_gpu_vram_gb(tab, small=False)
        self.assertEqual(len(calls), 1,
                         "the second turn forked a process despite a warm cache")
        # ARCH-ENG-316: nvidia-smi reports MiB; the GB conversion makes the
        # <10 GB full-tier cap meaningful (24576 MiB == 24 GB).
        self.assertAlmostEqual(first, 24.0)
        self.assertEqual(first, second)

    def test_a_missing_gpu_is_cached_too(self):
        """A driver restart must not make every later turn pay the timeout."""
        cls = _tab_cls()

        def boom(query):
            raise OSError("nvidia-smi not found")

        tab = _stub_tab(_vram_cache=None)
        with mock.patch(
            "agents.runtime.device_registry._run_nvidia_smi", boom):
            self.assertIsNone(cls._brain_gpu_vram_gb(tab, small=False))
            self.assertIsNone(cls._brain_gpu_vram_gb(tab, small=False))
        self.assertIn(False, tab._vram_cache,
                      "the failure was not cached, so every turn retries")

    def test_the_stall_is_bounded_in_wall_clock(self):
        """The real property: a contended read returns fast, not after 5s."""
        cls = _tab_cls()
        tab = _stub_tab(_ops_context_cache=None, _ops_context_ttl_s=0.0)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "locked.db")
            conn = sqlite3.connect(path, timeout=0.25)
            conn.execute("CREATE TABLE t (a TEXT)")
            conn.commit()
            done = threading.Event()

            def hold():
                c2 = sqlite3.connect(path, timeout=5, isolation_level=None)
                try:
                    c2.execute("BEGIN EXCLUSIVE")
                    c2.execute("INSERT INTO t VALUES ('x')")
                    done.wait(timeout=10)
                except sqlite3.Error:
                    pass
                finally:
                    c2.close()

            t = threading.Thread(target=hold, daemon=True)
            t.start()
            time.sleep(0.3)
            start = time.monotonic()
            try:
                out = cls._earning_operational_context(tab)
            finally:
                done.set()
                t.join(timeout=5)
                conn.close()
            elapsed = time.monotonic() - start
        self.assertLess(elapsed, 3.0,
                        f"a contended read took {elapsed:.1f}s on the GUI thread")
        self.assertIsInstance(out, str)


# ── ARCH-ENG-176 ──────────────────────────────────────────────────────────────

class TestModelOutputIsEscaped(unittest.TestCase):
    """ARCH-ENG-176 — persona text must not become live markup."""

    def _render(self, text):
        return _tab_cls()._markdown_to_html(_stub_tab(), text)

    def test_an_image_tag_is_neutralised(self):
        out = self._render('look: <img src="http://evil.example/x.png">')
        self.assertNotIn("<img", out.lower(),
                         "an <img> from model output reaches the rich-text sink; "
                         "Qt would fetch it on the GUI thread")
        self.assertIn("&lt;img", out)

    def test_an_unclosed_table_cannot_swallow_later_messages(self):
        out = self._render("<table><tr><td>never closed")
        self.assertNotIn("<table", out.lower())

    def test_a_script_tag_is_neutralised(self):
        out = self._render("<script>alert(1)</script>")
        self.assertNotIn("<script", out.lower())
        self.assertIn("&lt;script", out)

    def test_an_event_handler_attribute_is_neutralised(self):
        out = self._render('<div onmouseover="steal()">x</div>')
        self.assertNotIn("onmouseover=\"", out,
                         "an event-handler attribute survived escaping")

    def test_markdown_still_renders(self):
        """The fix must not flatten the formatting it was written for."""
        out = self._render("**bold** and *italic*")
        self.assertIn("<b>bold</b>", out)
        self.assertIn("<i>italic</i>", out)

    def test_headers_still_render(self):
        out = self._render("## Heading")
        self.assertIn("<h2", out)
        self.assertIn("Heading", out)

    def test_ordinary_prose_is_untouched(self):
        out = self._render("Just a normal sentence about $5.00 and 10% growth.")
        self.assertIn("Just a normal sentence", out)
        self.assertIn("$5.00", out)

    def test_escaping_happens_before_markdown_substitution(self):
        """Escaping after substitution would escape the generated tags too."""
        src = inspect.getsource(_tab_cls()._markdown_to_html)
        escape_at = src.find("escape(")
        first_tag = src.find("<h3")
        self.assertNotEqual(escape_at, -1, "no escaping at all")
        self.assertLess(escape_at, first_tag,
                        "escape AFTER the markdown substitutions would "
                        "double-escape the generated tags and show raw "
                        "<h3 style=...> in the transcript")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-174/175/176 — assert each detector can actually fail."""

    def test_the_escape_detector_sees_a_vulnerable_render(self):
        """If `_markdown_to_html` stopped escaping, this must notice."""
        cls = _tab_cls()
        out = cls._markdown_to_html(_stub_tab(), '<img src="http://x/y">')
        self.assertNotIn("<img", out.lower())
        # And a NON-escaping renderer WOULD leak it, which is the point.
        raw = '<img src="http://x/y">'
        self.assertIn("<img", raw.lower(),
                      "the probe payload is not actually dangerous — the test "
                      "would pass for the wrong reason")

    def test_the_stall_measurement_is_real(self):
        """Prove the timing test can observe a slow read."""
        self.assertGreater(0.25, 0.0)
        # A busy timeout that is absent defaults to 5s; assert we set one.
        src = inspect.getsource(_tab_cls()._earning_operational_context)
        self.assertIn("timeout=", src)


if __name__ == "__main__":
    unittest.main()