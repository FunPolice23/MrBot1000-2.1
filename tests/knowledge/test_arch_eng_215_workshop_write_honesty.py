"""ARCH-ENG-215 — workshop writers reported success for files that were never written.

## The defect

`Workshop.write_file` returns `False` for an unsafe path, an exceeded storage
quota, an empty disk, a permission error, or **any other exception** — its
`except` clause swallows everything and returns `False`.

Seven creator methods discarded that boolean and returned the path anyway:

    self.write_file(filepath, content)
    return filepath

So a quota exhaustion produced `[Proposal created: proposals/proposal_acme.md]`
for a file that did not exist. The agent would tell the operator it had prepared
the proposal, and the operator would look for a document that was never written.

This is the same shape as the ARCH-ENG-204 backup bug — log a warning, write
anyway, report success — and it is the shape this codebase keeps producing:
**a claim the code has not verified.**

## The fix

`Workshop._write_or_raise` raises `WorkshopWriteError` when the write does not
happen. Raising is safe here because every tool handler already wraps the call
in `try/except Exception` and returns `[<Tool> error: ...]`, which the
ARCH-ENG-214 deny-list classifies as NOT executed.

The failure therefore travels the whole chain truthfully:

    quota exceeded -> raise -> "[Proposal error: ...]" -> _tool_status -> error

and the transcript records an error rather than a completed action.

## Note on the creator set

At the time of the fix, only `create_proposal` had a caller (`handlers.py:317`).
The other six -- `add_research`, `create_script`, `create_application`,
`add_deliverable`, `save_template`, `add_note` -- had none, so they were
unreachable today. They were fixed rather than removed because they are
coherent Workshop API surface and the fix costs one line each; removing public
API is a separate decision and should not be smuggled into an honesty fix.

ARCH-ENG-245 (AY-02, 11G) later made that separate decision in the other
direction and removed `save_template` with the whole template subsystem: its
pair-partner `get_template` served hardcoded strings and never read the
`templates/` directory `save_template` wrote, so a saved template was
unreadable by construction. The creator set here is now six; every one still
goes through `_write_or_raise`.
"""

import ast
import pathlib
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
WORKSHOP = REPO / "agents" / "knowledge" / "workshop.py"

# Every creator that used to discard write_file's boolean.
FIXED = (
    ("create_proposal", "proposal"),
    ("add_research", "research"),
    ("create_script", "script"),
    ("create_application", "application"),
    ("add_deliverable", "deliverable"),
    # ("save_template", "template") removed with the template subsystem
    # (ARCH-ENG-245, AY-02 -- see the docstring note above).
    ("add_note", "note"),
)


def _method(name):
    tree = ast.parse(WORKSHOP.read_text(encoding="utf-8"))
    cls = next(n for n in ast.walk(tree)
               if isinstance(n, ast.ClassDef) and n.name == "Workshop")
    return next(m for m in cls.body
                if isinstance(m, ast.FunctionDef) and m.name == name)


class TestNoWriterDiscardsTheResult(unittest.TestCase):
    """ARCH-ENG-215 — structural, so it cannot come back."""

    def test_no_creator_discards_write_file(self):
        tree = ast.parse(WORKSHOP.read_text(encoding="utf-8"))
        cls = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.ClassDef) and n.name == "Workshop")
        discarded = []
        for fn in [m for m in cls.body if isinstance(m, ast.FunctionDef)]:
            if fn.name == "_write_or_raise":
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Expr)
                        and isinstance(node.value, ast.Call)
                        and isinstance(node.value.func, ast.Attribute)
                        and node.value.func.attr == "write_file"):
                    discarded.append(f"{fn.name}:{node.lineno}")
        self.assertEqual(
            discarded, [],
            f"these methods discard write_file's boolean and would report a "
            f"file that was never written: {discarded}")

    def test_every_creator_goes_through_the_helper(self):
        for name, _ in FIXED:
            with self.subTest(method=name):
                body = ast.unparse(_method(name))
                self.assertIn("_write_or_raise", body,
                              f"{name} does not check whether the write "
                              f"happened")

    def test_write_file_still_reports_failure(self):
        """The fix must not change write_file's contract."""
        self.assertIn("-> bool", ast.unparse(_method("write_file")))


class TestRefusedWritesRaise(unittest.TestCase):
    """ARCH-ENG-215 — behaviour, at the Workshop boundary."""

    def _workshop(self):
        from agents.knowledge.workshop import Workshop
        ws = Workshop()
        ws.root = tempfile.mkdtemp(prefix="arch215_")
        return ws

    def test_a_refused_write_raises(self):
        from agents.knowledge.workshop import WorkshopWriteError

        ws = self._workshop()
        ws._can_write = lambda path, size: False   # quota exhausted
        with self.assertRaises(WorkshopWriteError):
            ws.create_proposal("Blocked Co", "Blocked", "should not be written")

    def test_the_message_says_the_file_was_not_created(self):
        from agents.knowledge.workshop import WorkshopWriteError

        ws = self._workshop()
        ws._can_write = lambda path, size: False
        with self.assertRaises(WorkshopWriteError) as ctx:
            ws.create_proposal("Blocked Co", "Blocked", "x")
        self.assertIn("NOT created", str(ctx.exception),
                      "the error must not be mistakable for success")

    def test_a_successful_write_still_returns_the_path(self):
        import os

        ws = self._workshop()
        rel = ws.create_proposal("Acme", "Acme", "a real proposal")
        self.assertTrue(rel)
        self.assertTrue(os.path.exists(os.path.join(ws.root, rel)),
                        "a permitted write must still produce the file")


class TestTheAgentVisibleStringIsHonest(unittest.TestCase):
    """ARCH-ENG-215 — the whole chain, which is the point."""

    def _call(self, allow):
        import agents.safety  # noqa: F401  -- break the circular import
        import agents.knowledge.workshop as wmod
        from agents.safety.calling import _DISPATCH_CAPABILITY
        from agents.safety.handlers import _tool_workshop_proposal

        ws = wmod.get_workshop()
        ws.root = tempfile.mkdtemp(prefix="arch215_")
        ws._can_write = (lambda p, s: allow)
        return _tool_workshop_proposal(
            {"title": "T", "client": "C", "description": "d"},
            authorization=_DISPATCH_CAPABILITY)

    def test_a_refused_write_does_not_claim_creation(self):
        out = self._call(allow=False)
        self.assertNotIn("[Proposal created", out,
                         "the tool still reports a file it did not write")
        self.assertIn("[Proposal error", out)

    def test_a_refused_write_is_not_classified_as_executed(self):
        import agents.safety  # noqa: F401
        from agents.dialogue.chat_completion import _tool_status

        self.assertNotEqual(_tool_status(self._call(allow=False)), "executed",
                            "the transcript would record a completed action "
                            "for a write that never happened")

    def test_a_permitted_write_still_claims_creation(self):
        """The mirror-image check: honesty must not become permanent refusal."""
        out = self._call(allow=True)
        self.assertIn("[Proposal created", out)

        import agents.safety  # noqa: F401
        from agents.dialogue.chat_completion import _tool_status
        self.assertEqual(_tool_status(out), "executed")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-215 — each detector must be able to fail."""

    def test_the_discard_detector_sees_a_bare_call(self):
        bad = ast.parse(
            "class W:\n"
            "    def f(self):\n"
            "        self.write_file(p, c)\n"
            "        return p\n")
        found = []
        for fn in [n for n in ast.walk(bad) if isinstance(n, ast.FunctionDef)]:
            for node in ast.walk(fn):
                if (isinstance(node, ast.Expr)
                        and isinstance(node.value, ast.Call)
                        and isinstance(node.value.func, ast.Attribute)
                        and node.value.func.attr == "write_file"):
                    found.append(fn.name)
        self.assertEqual(found, ["f"],
                         "the detector cannot see a discarded write, so it "
                         "would pass while the defect returned")

    def test_the_refusal_probe_really_refuses(self):
        """If _can_write could not be made to fail, the tests above prove nothing."""
        ws = Workshop_factory()
        ws._can_write = lambda p, s: False
        self.assertFalse(ws.write_file("notes/x.md", "content"),
                         "write_file returned True with the quota guard "
                         "forcing failure")

    def test_the_method_lookup_can_find_every_creator(self):
        for name, _ in FIXED:
            with self.subTest(method=name):
                self.assertIsNotNone(_method(name))


def Workshop_factory():
    from agents.knowledge.workshop import Workshop
    ws = Workshop()
    ws.root = tempfile.mkdtemp(prefix="arch215_")
    return ws