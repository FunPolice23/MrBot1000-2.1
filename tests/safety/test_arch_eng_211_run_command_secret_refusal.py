"""ARCH-ENG-211 — the hardened command path was MORE permissive than the old one.

## What was wrong

`agents/safety/legacy_tools._run_command` (reached via the Big Brain tool loop)
scanned the parsed argv and refused any command naming a credential store:

    for token in argv:
        name = Path(token).name
        if name and _is_secret_file(Path(name)):
            return "[Command refused: ...]"

`agents/safety/handlers._tool_run_command` — the *other* dispatcher — had **no
such scan**. It went straight to `subprocess.run`.

ARCH-ENG-133 had already established the intent. Its comment in
`legacy_tools.py:24` reads:

    ... using the SAME authority (`_is_secret_file`) so there is
    one blocklist, not two that can drift

The *blocklist* was one, because `_is_secret_file` lives in `handlers.py` and
both modules imported it. What actually drifted was whether each dispatcher
**consulted it at all**. So the guard that was supposed to be defence in depth
existed on exactly one of the two paths that mattered.

Consequence: `run_command("type .env")` was refused through one entry point and
executed through the other. `resolve_command_cwd(None)` defaults to
`PROJECT_ROOT`, which is where `.env` (hundreds of keys), `wallet.key` and the
platform vault live. The Approvals panel shows the operator a plain-looking
command, so the human review that ARCH-ENG-133 relies on as its outer layer
sees nothing unusual.

## The fix

`refuse_secret_argv` in `handlers.py` is now the single implementation, and
both dispatchers call it. One function, one authority, two entry points.

The test below asserts the *parity* rather than the behaviour of either path in
isolation, because parity is the property that was actually broken: each path
alone looked correct enough.
"""

import ast
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
HANDLERS = REPO / "agents" / "safety" / "handlers.py"
LEGACY = REPO / "agents" / "safety" / "legacy_tools.py"

SECRET_COMMANDS = (
    "type .env",
    "cat wallet.key",
    "type credentials.json",
    "head -n 5 .env",
)
CLEAN_COMMANDS = (
    "git log",
    "echo hello",
    "python -c pass",
)


def _fn(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name)


class TestTheRefusalWorks(unittest.TestCase):
    """ARCH-ENG-211 — the shared implementation."""

    def test_secret_stores_are_refused(self):
        from agents.safety.handlers import refuse_secret_argv

        for cmd in SECRET_COMMANDS:
            with self.subTest(cmd=cmd):
                argv = cmd.split()
                refusal = refuse_secret_argv(argv)
                self.assertTrue(refusal,
                                f"{cmd!r} names a credential store and was "
                                f"allowed through")
                self.assertIn("Command refused", refusal)

    def test_ordinary_commands_pass(self):
        from agents.safety.handlers import refuse_secret_argv

        for argv in (["git", "log"], ["echo", "hello"], ["python", "-c", "pass"]):
            with self.subTest(argv=argv):
                self.assertEqual(refuse_secret_argv(argv), "",
                                 f"{argv} was wrongly refused; the guard would "
                                 f"become useless if it blocked everything")

    def test_a_bare_filename_token_is_matched_by_basename(self):
        """`type .env` names the store without a path."""
        from agents.safety.handlers import refuse_secret_argv

        self.assertTrue(refuse_secret_argv(["type", ".env"]))
        self.assertTrue(refuse_secret_argv(["cat", "./wallet.key"]))


class TestBothDispatchersRefuse(unittest.TestCase):
    """ARCH-ENG-211 — parity is the property that was broken."""

    def test_legacy_path_refuses(self):
        from agents.safety.legacy_tools import _run_command

        for cmd in SECRET_COMMANDS:
            with self.subTest(cmd=cmd):
                out = _run_command(cmd)
                self.assertIn("Command refused", out,
                              f"the legacy path let {cmd!r} through")

    def test_the_hardened_path_refuses_too(self):
        """This is the regression. It previously ran the command.

        `_tool_run_command` checks the mutation capability FIRST and refuses an
        unauthorised caller before reaching any command logic. That refusal is
        correct and is tested elsewhere, but it means calling the handler bare
        never gets far enough to exercise the argv scan -- an earlier draft of
        this test passed for exactly that reason while proving nothing.

        So the dispatch capability token is supplied here. That is not a bypass
        of the gate under test: it is the precondition for reaching the scan,
        which is the layer this ticket is about.
        """
        from agents.safety.calling import _DISPATCH_CAPABILITY
        from agents.safety.handlers import _tool_run_command

        for cmd in SECRET_COMMANDS:
            with self.subTest(cmd=cmd):
                out = _tool_run_command({"command": cmd},
                                        authorization=_DISPATCH_CAPABILITY)
                self.assertIn(
                    "Command refused", out,
                    f"the dispatch path executed {cmd!r}; it had no argv scan")

    def test_the_scan_is_reached_before_any_subprocess(self):
        """Ordering, not just presence: the refusal must precede execution."""
        from agents.safety.calling import _DISPATCH_CAPABILITY
        from agents.safety.handlers import _tool_run_command

        body = ast.unparse(_fn(HANDLERS, "_tool_run_command"))
        self.assertLess(
            body.index("refuse_secret_argv"), body.index("subprocess.run"),
            "the argv scan must run before the command does, or a refused "
            "command has already executed by the time it is noticed")

    def test_the_two_paths_agree(self):
        """Neither path may be strictly more permissive than the other."""
        from agents.safety.calling import _DISPATCH_CAPABILITY
        from agents.safety.handlers import _tool_run_command
        from agents.safety.legacy_tools import _run_command

        for cmd in SECRET_COMMANDS + CLEAN_COMMANDS:
            with self.subTest(cmd=cmd):
                hardened = "Command refused" in _tool_run_command(
                    {"command": cmd}, authorization=_DISPATCH_CAPABILITY)
                legacy = "Command refused" in _run_command(cmd)
                self.assertEqual(
                    hardened, legacy,
                    f"the two dispatchers disagree about {cmd!r}: hardened "
                    f"refused={hardened}, legacy refused={legacy}")


class TestThereIsOnlyOneImplementation(unittest.TestCase):
    """ARCH-ENG-211 — so this cannot drift again."""

    def test_the_scan_exists_once(self):
        """Scoped to the two COMMAND runners.

        A package-wide grep for `_is_secret_file(Path(name))` is the wrong test:
        `refuse_secret_argv` itself contains that expression (it is the one
        implementation), and an unrelated handler uses the same idiom for a
        different check. Both are legitimate. Only a private scan inside a
        command runner is a defect.
        """
        offenders = []
        for path, fn in ((HANDLERS, "_tool_run_command"),
                         (LEGACY, "_run_command")):
            body = ast.unparse(_fn(path, fn))
            if "_is_secret_file" in body:
                offenders.append(f"{path.name}:{fn}")
        self.assertEqual(
            offenders, [],
            f"a private argv scan is back in {offenders}; both runners must "
            f"call handlers.refuse_secret_argv so they cannot drift")

    def test_the_shared_helper_is_where_the_scan_lives(self):
        body = ast.unparse(_fn(HANDLERS, "refuse_secret_argv"))
        self.assertIn("_is_secret_file", body,
                      "the shared helper must actually consult the blocklist")

    def test_both_call_the_shared_helper(self):
        for path, fn in ((HANDLERS, "_tool_run_command"),
                         (LEGACY, "_run_command")):
            with self.subTest(path=path.name):
                body = ast.unparse(_fn(path, fn))
                self.assertIn(
                    "refuse_secret_argv", body,
                    f"{fn} in {path.name} does not consult the shared scan")

    def test_the_unparseable_command_message_is_preserved(self):
        """Refusing must not swallow the pre-existing error contract."""
        src = HANDLERS.read_text(encoding="utf-8")
        self.assertIn("[Command error:", src,
                      "the unparseable-command message changed; a caller may "
                      "depend on that prefix")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-211 — each detector must be able to fail."""

    def test_the_refusal_check_can_see_an_allow(self):
        from agents.safety.handlers import refuse_secret_argv

        self.assertEqual(refuse_secret_argv(["git", "log"]), "",
                         "the detector cannot see an ALLOW, so a guard that "
                         "refused everything would pass")

    def test_the_parity_check_catches_a_one_sided_guard(self):
        """Simulate the original defect: only one path refuses."""
        def hardened(cmd):
            return "[Command refused]" if cmd == "type .env" else "ran it"

        def legacy(cmd):
            return "ran it"

        disagreements = [c for c in SECRET_COMMANDS + CLEAN_COMMANDS
                         if (("Command refused" in hardened(c))
                             != ("Command refused" in legacy(c)))]
        self.assertTrue(disagreements,
                        "the parity check cannot see a one-sided guard")

    def test_the_secret_command_list_is_not_vacuous(self):
        self.assertGreaterEqual(len(SECRET_COMMANDS), 4)
        self.assertTrue(any(".env" in c for c in SECRET_COMMANDS))