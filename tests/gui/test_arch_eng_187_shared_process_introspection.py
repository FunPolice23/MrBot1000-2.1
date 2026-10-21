"""ARCH-ENG-187 — two copies of "is that our server?", already disagreeing.

`DualBrainControl` and `ProviderStatusChecker.check_llama_process` each needed to
answer the same question: *is a llama.cpp server listening on this port, and is
it ours?* Each had its own implementation. They had already drifted into two
different bugs.

`check_llama_process` was the worse of the two:

    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq llama.exe", ...])
    return "llama.exe" in result.stdout

Two independent reasons it could never be right:

1. It filtered `llama.exe`, but the app spawns `llama-server.exe`
   (`BrainLaunchWorker`). The filter matched nothing, so on a machine running
   four llama-servers it returned **False**. A detector that always says "no" is
   worse than no detector at all, because a reader cannot distinguish a genuine
   negative from a broken check.

2. It accepted a `port` argument and then **ignored it entirely** — it asked
   "is any llama process running anywhere?" while appearing to answer "is the
   server on THIS port up?". Different questions; only the second is useful.

It also used `capture_output=True`, the ARCH-ENG-116-broken subprocess form,
and had **zero call sites** — so it read as a working safety check that nothing
happened to use yet. A dormant broken check is the hardest kind to notice: no
failure ever surfaces.

The duplication itself is the root cause, so the fix is structural. `is_llama_
server_image`, `process_image_name`, `pids_listening_on` and `llama_server_pids_on`
now live once in `device_registry` (which already owned process introspection via
`_run_nvidia_smi`), and both callers delegate. The probe and the kill path now
use the *same* predicate for "ours", so they cannot disagree about which
processes the application is allowed to terminate (ARCH-ENG-171).
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


def _dr():
    from agents.runtime import device_registry
    return device_registry


# ── The shared predicate ──────────────────────────────────────────────────────

class TestLlamaImagePredicate(unittest.TestCase):
    """ARCH-ENG-187 — one definition of "ours", correct this time."""

    def test_the_image_the_app_actually_spawns_is_recognised(self):
        """THE REGRESSION: the old filter was `llama.exe`, the app runs
        `llama-server.exe`, so this returned False on a machine with servers."""
        check = _dr().is_llama_server_image
        self.assertTrue(check("llama-server.exe"),
                        "the executable this app spawns was not recognised")
        self.assertTrue(check("LLAMA-SERVER.EXE"), "casing must not matter")

    def test_the_legacy_alias_is_still_recognised(self):
        self.assertTrue(_dr().is_llama_server_image("llama.exe"))

    def test_other_programs_are_not_ours(self):
        check = _dr().is_llama_server_image
        for foreign in ("lm studio.exe", "python.exe", "node.exe", "ollama.exe",
                        "chrome.exe", "notepad.exe", "llama-server-helper.exe",
                        "xllama.exe", "llamaserver.exe", "", None):
            with self.subTest(image=foreign):
                self.assertFalse(check(foreign),
                                 f"{foreign!r} is not a process we may terminate")

    def test_the_predicate_is_not_a_substring_match(self):
        """`llama-server-helper.exe` CONTAINS "llama" but is somebody else's.

        This is the anti-vacuity proof for the whole predicate: if "ours" were
        decided by searching the name for the string "llama", this case would be
        accepted and the application would be entitled to terminate it.
        """
        self.assertIn("llama", "llama-server-helper.exe",
                      "the probe no longer contains the substring it tests for")
        self.assertFalse(_dr().is_llama_server_image("llama-server-helper.exe"),
                         "a name merely CONTAINING llama was treated as ours")


# ── The shared enumeration ────────────────────────────────────────────────────

class TestPortEnumeration(unittest.TestCase):
    """ARCH-ENG-187 — one enumeration, de-duplicated."""

    NETSTAT = (
        "  TCP    0.0.0.0:1234          0.0.0.0:0              LISTENING       1111\n"
        "  TCP    [::]:1234             [::]:0                 LISTENING       1111\n"
        "  TCP    127.0.0.1:1234        0.0.0.0:0              LISTENING       2222\n"
        "  TCP    127.0.0.1:1234        127.0.0.1:5555         ESTABLISHED     3333\n"
        "  TCP    127.0.0.1:5678        0.0.0.0:0              LISTENING       4444\n"
    )

    def _patched(self, netstat=None, images=None):
        images = images or {}
        texts = {
            "netstat": self.NETSTAT if netstat is None else netstat,
            "tasklist": "",
        }

        def fake_run(argv, *a, **kw):
            tool = argv[0]
            if tool == "netstat":
                return mock.Mock(returncode=0, stdout=texts["netstat"].encode())
            if tool == "tasklist":
                pid = argv[2].split()[-1]
                name = images.get(int(pid), "")
                if not name:
                    return mock.Mock(returncode=0, stdout=b"")
                return mock.Mock(
                    returncode=0,
                    stdout=f'"{name}","1112","Console","1","10,000 K"\r\n'.encode())
            raise AssertionError(f"unexpected command: {argv}")

        return mock.patch("subprocess.run", side_effect=fake_run)

    def test_only_listening_sockets_on_that_port_are_returned(self):
        dr = _dr()
        with self._patched():
            pids = dr.pids_listening_on(1234)
        self.assertEqual(sorted(pids), [1111, 2222],
                         "an ESTABLISHED connection or a different port leaked in")

    def test_the_duplicate_v4_v6_row_is_reported_once(self):
        """netstat prints one socket twice; killing the same PID twice races."""
        dr = _dr()
        with self._patched():
            pids = dr.pids_listening_on(1234)
        self.assertEqual(pids.count(1111), 1,
                         "the same PID was listed twice (v4 and v6 rows)")

    def test_a_port_with_no_listener_yields_an_empty_list(self):
        dr = _dr()
        with self._patched(netstat=""):
            self.assertEqual(dr.pids_listening_on(9999), [])

    def test_a_non_numeric_port_does_not_raise(self):
        dr = _dr()
        with self._patched():
            self.assertEqual(dr.pids_listening_on("not-a-port"), [])
            self.assertEqual(dr.pids_listening_on(None), [])

    def test_a_failed_command_yields_nothing_rather_than_raising(self):
        """ARCH-ENG-186/187: a failed query says nothing about the machine."""
        dr = _dr()
        with mock.patch("subprocess.run", side_effect=OSError("WinError 50")):
            self.assertEqual(dr.pids_listening_on(1234), [])
            self.assertEqual(dr.process_image_name(1111), "")

    def test_a_non_zero_exit_yields_nothing(self):
        dr = _dr()
        with mock.patch("subprocess.run",
                        return_value=mock.Mock(returncode=1, stdout=b"garbage")):
            self.assertEqual(dr.pids_listening_on(1234), [])


class TestOursVersusTheirs(unittest.TestCase):
    """ARCH-ENG-187 — the port tells you WHO; the image tells you WHOSE."""

    NETSTAT = ("  TCP    0.0.0.0:1234          0.0.0.0:0              "
               "LISTENING       1111\n")

    def _scan(self, images):
        dr = _dr()

        def fake_run(argv, *a, **kw):
            if argv[0] == "netstat":
                return mock.Mock(returncode=0, stdout=self.NETSTAT.encode())
            pid = int(argv[2].split()[-1])
            name = images.get(pid, "")
            if not name:
                return mock.Mock(returncode=0, stdout=b"")
            return mock.Mock(
                returncode=0,
                stdout=f'"{name}","1","Console","1","10,000 K"\r\n'.encode())

        with mock.patch("subprocess.run", side_effect=fake_run):
            return dr.llama_server_pids_on(1234)

    def test_our_own_server_is_reported(self):
        self.assertEqual(self._scan({1111: "llama-server.exe"}), [1111])

    def test_lm_studio_on_the_same_port_is_not_ours(self):
        """1234 is both the Big Brain port and LM Studio's default."""
        self.assertEqual(self._scan({1111: "LM Studio.exe"}), [],
                         "another program's process was reported as ours")

    def test_a_mixed_listener_set_returns_only_ours(self):
        dr = _dr()
        netstat = ("  TCP    0.0.0.0:1234          0.0.0.0:0              "
                   "LISTENING       1111\n"
                   "  TCP    0.0.0.0:1234          0.0.0.0:0              "
                   "LISTENING       2222\n")

        def fake_run(argv, *a, **kw):
            if argv[0] == "netstat":
                return mock.Mock(returncode=0, stdout=netstat.encode())
            pid = int(argv[2].split()[-1])
            name = {1111: "llama-server.exe", 2222: "LM Studio.exe"}[pid]
            return mock.Mock(returncode=0,
                             stdout=f'"{name}","1","Console","1","10,000 K"\r\n'.encode())

        with mock.patch("subprocess.run", side_effect=fake_run):
            self.assertEqual(dr.llama_server_pids_on(1234), [1111])


# ── The broken detector ───────────────────────────────────────────────────────

class TestCheckLlamaProcess(unittest.TestCase):
    """ARCH-ENG-187 — the always-False detector."""

    def test_it_recognises_the_executable_the_app_actually_spawns(self):
        from agents.providers.provider_lifecycle import ProviderStatusChecker
        with mock.patch(
            "agents.runtime.device_registry.llama_server_pids_on",
            return_value=[1111],
        ):
            self.assertTrue(
                ProviderStatusChecker.check_llama_process(port=1234),
                "a live llama-server was reported as absent — this check "
                "always returned False")

    def test_the_port_argument_is_no_longer_ignored(self):
        """It accepted `port` and never used it."""
        import agents.providers.provider_lifecycle as pl
        code = _code_only(pl.ProviderStatusChecker.check_llama_process)
        self.assertIn("port", code)
        with mock.patch(
            "agents.runtime.device_registry.llama_server_pids_on",
            return_value=[],
        ) as scan:
            pl.ProviderStatusChecker.check_llama_process(port=1234)
        scan.assert_called_once_with(1234)

    def test_no_port_means_no_confident_answer(self):
        """Guessing a default would silently report on the wrong server."""
        from agents.providers.provider_lifecycle import ProviderStatusChecker
        with mock.patch(
            "agents.runtime.device_registry.llama_server_pids_on",
            return_value=[1111],
        ) as scan:
            self.assertFalse(ProviderStatusChecker.check_llama_process())
        scan.assert_not_called()

    def test_the_broken_capture_output_form_is_gone(self):
        from agents.providers.provider_lifecycle import ProviderStatusChecker
        code = _code_only(ProviderStatusChecker.check_llama_process)
        self.assertNotIn("capture_output", code,
                         "capture_output is the ARCH-ENG-116-broken subprocess "
                         "form (WinError 50 under a reconfigured stdout pipe)")
        self.assertNotIn("llama.exe eq", code,
                         "the filter named llama.exe; the app spawns "
                         "llama-server.exe, so it matched nothing")

    def test_it_no_longer_parses_tasklist_itself(self):
        """Delegation, so probe and killer cannot drift apart again."""
        from agents.providers.provider_lifecycle import ProviderStatusChecker
        code = _code_only(ProviderStatusChecker.check_llama_process)
        self.assertNotIn("tasklist", code)
        self.assertIn("llama_server_pids_on", code)


class TestTheWidgetDelegatesToo(unittest.TestCase):
    """ARCH-ENG-187 — one implementation, two callers, no second copy."""

    def _control(self):
        from gui.widgets.dual_brain_control import DualBrainControl
        return DualBrainControl

    def test_the_widget_does_not_reimplement_netstat_parsing(self):
        code = _code_only(self._control()._pids_on_port)
        self.assertNotIn("netstat", code,
                         "a second netstat parser will drift from the shared one")
        self.assertIn("pids_listening_on", code)

    def test_the_widget_does_not_reimplement_the_image_predicate(self):
        """It must be the SAME predicate, or probe and killer can disagree."""
        code = _code_only(self._control()._is_llama_image)
        self.assertIn("is_llama_server_image", code)
        self.assertNotIn("llama-server", code,
                         "a hardcoded name list is a second source of truth")

    def test_the_widget_and_the_checker_agree_on_what_is_ours(self):
        """The property that matters: one answer, regardless of who asks."""
        for name in ("llama-server.exe", "llama.exe", "LM Studio.exe",
                     "python.exe", "llama-server-helper.exe"):
            with self.subTest(image=name):
                widget = self._control()._is_llama_image(name)
                from agents.runtime.device_registry import is_llama_server_image
                self.assertEqual(widget, is_llama_server_image(name),
                                 "the probe and the killer disagree about "
                                 "which processes are ours")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-187 — the fixtures must express the defect."""

    def test_the_old_filter_would_have_missed_the_real_executable(self):
        """Prove the regression fixture is actually discriminating."""
        self.assertNotIn("llama.exe", "llama-server.exe")
        self.assertEqual(
            "llama.exe" in "llama-server.exe, Console, 1, 10,000 K", False)

    def test_the_netstat_fixture_really_contains_a_duplicate_row(self):
        fixture = TestPortEnumeration.NETSTAT
        pid_rows = [ln for ln in fixture.splitlines()
                    if "LISTENING" in ln and ln.rstrip().endswith("1111")]
        self.assertEqual(len(pid_rows), 2,
                         "the duplicate-row fixture lost its second v4/v6 line")

    def test_a_distinct_foreign_image_is_available_to_the_fixture(self):
        self.assertNotEqual("llama-server.exe", "LM Studio.exe")
