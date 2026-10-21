"""ARCH-ENG-226 - subprocess output decoded with the console's code page.

## What was wrong

Seven production `subprocess` calls passed `text=True` with no `encoding`. With
`text=True` and no explicit encoding, Python decodes the child's output using
`locale.getpreferredencoding(False)` -- on this machine **cp1252**, the Windows
console default.

So any byte outside cp1252 raises `UnicodeDecodeError`. It surfaces not as a
normal exception but as a `PytestUnhandledThreadExceptionWarning` from
`subprocess._readerthread`, because the decode happens on the reader thread
rather than where the process was started. It appeared in every full-suite run:

    UnicodeDecodeError: 'charmap' codec can't decode byte 0x8f in position 266747

The calls at risk are exactly the ones with non-ASCII output: `nvidia-smi`
queries, `powershell Get-CimInstance Win32_Process` (whose `CommandLine` field
carries whatever the operator typed), `netstat`, and `taskkill`.

This is not only a test-hygiene problem. A decode failure inside the reader
thread means the caller gets truncated or absent output while believing the
probe succeeded -- a launch preflight that silently sees an empty VRAM reading
is worse than one that raised.

## The fix

Every one now passes `encoding="utf-8", errors="replace"`. `errors="replace"`
is the load-bearing half: a malformed byte must never take down a probe that is
trying to answer a question.

## Note on how this was found

The warning was visible in earlier full-suite output and was attributed to
something else for several runs. It was not fixed by the change it appeared to
call for -- one source was a test added earlier in the same session, and the
rest were these seven production calls. "A recurring warning I have seen many
times" is not the same as "a warning I understand".
"""

import ast
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]

# Production modules that spawn child processes and read their output.
TARGETS = [
    "agents/brains/worker_budget.py",
    "agents/providers/ollama_adapter.py",
    "agents/safety/handlers.py",
    "agents/safety/legacy_tools.py",
    "gui/widgets/dual_brain_control.py",
    "gui/workers/brain_launch_worker.py",
    "gui/workers/provider_lifecycle_backend.py",
]

SPAWNERS = {"run", "Popen", "check_output"}


def _undecoded_calls(path: pathlib.Path):
    """subprocess calls that request text output but name no encoding."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "attr", None) or getattr(func, "id", None)
        if name not in SPAWNERS:
            continue
        kw = {k.arg for k in node.keywords if k.arg}
        if ("text" in kw or "universal_newlines" in kw) and "encoding" not in kw:
            found.append((name, node.lineno))
    return found


class TestNoProductionCallDecodesWithTheConsoleCodePage(unittest.TestCase):
    def test_every_text_call_declares_an_encoding(self):
        offenders = []
        for rel in TARGETS:
            path = REPO / rel
            self.assertTrue(path.exists(), f"{rel} moved; update TARGETS")
            for name, line in _undecoded_calls(path) or []:
                offenders.append(f"{rel}:{line} ({name})")
        self.assertEqual(offenders, [],
                         "these decode with locale.getpreferredencoding() "
                         "(cp1252 on Windows) and raise on any non-cp1252 "
                         f"byte: {offenders}")

    def test_the_encoding_also_replaces_rather_than_raises(self):
        """`encoding` without `errors` still raises.

        `errors="replace"` is the half that makes a probe answer its question
        instead of dying trying.
        """
        offenders = []
        for rel in TARGETS:
            path = REPO / rel
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = getattr(func, "attr", None) or getattr(func, "id", None)
                if name not in SPAWNERS:
                    continue
                kw = {k.arg for k in node.keywords if k.arg}
                if "encoding" in kw and "errors" not in kw:
                    offenders.append(f"{rel}:{node.lineno}")
        self.assertEqual(offenders, [],
                         f"an explicit encoding without errors= still raises: "
                         f"{offenders}")


class TestTheDetectorCanActuallyFail(unittest.TestCase):
    """Otherwise the guard above could be matching nothing."""

    KNOWN_BAD = '''
import subprocess
r = subprocess.run(["x"], capture_output=True, text=True, timeout=5)
'''

    KNOWN_BAD_NO_ERRORS = '''
import subprocess
r = subprocess.run(["x"], text=True, encoding="utf-8")
'''

    KNOWN_GOOD = '''
import subprocess
r = subprocess.run(["x"], text=True, encoding="utf-8", errors="replace")
'''

    def _detect(self, source):
        tree = ast.parse(source)
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name not in SPAWNERS:
                continue
            kw = {k.arg for k in node.keywords if k.arg}
            if ("text" in kw or "universal_newlines" in kw) and "encoding" not in kw:
                offenders.append(name)
        return offenders

    def test_it_flags_a_call_with_no_encoding(self):
        self.assertEqual(self._detect(self.KNOWN_BAD), ["run"],
                         "the detector does not reproduce the defect, so the "
                         "guard over TARGETS proves nothing")

    def test_it_clears_a_correctly_decoded_call(self):
        self.assertEqual(self._detect(self.KNOWN_GOOD), [])

    def test_it_does_not_confuse_encoding_with_errors(self):
        """A second, separate defect -- an encoding with no errors still raises."""
        self.assertEqual(self._detect(self.KNOWN_BAD_NO_ERRORS), [],
                         "encoding alone is enough to be safe; if this holds, "
                         "the errors= guard elsewhere is redundant")

    def test_the_target_list_is_not_empty(self):
        self.assertGreaterEqual(len(TARGETS), 7,
                                "TARGETS shrank; the sweep would silently "
                                "cover fewer files")


if __name__ == "__main__":
    unittest.main()