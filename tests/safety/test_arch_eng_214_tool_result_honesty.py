"""ARCH-ENG-214 — a failed tool call was recorded as a completed one.

## What was wrong

`chat_completion._tool_status` classifies a tool RESULT string so the UI can
trust it. Its deny-list covered eight shapes. **The handlers emit thirty distinct
bracket prefixes, nineteen of which are failures.**

So `[Query error: no such table: opportunities]` — returned by a handler that had
executed no query at all — classified as `"executed"`.

The consequences were not cosmetic. `_tool_status` feeds:

* the trace the operator reads in the transcript,
* `action_state="completed"` in the tool trace entry,
* a minted `execution_id`.

So a failed database query was written into the dialogue ledger as a
**completed tool action**. The model was told the call had succeeded, and would
reason from that on the next turn.

This is ARCH-ENG-173's exact failure mode, closed for two shapes and left open
for the other nineteen. A deny-list that is written by hand and never checked
against its source is a claim, not a control.

## The fix

The list is now **derived from the handlers**, not guessed: every literal
returned from `handlers.py`, `web_eyes.py`, `workshop.py` and `legacy_tools.py`
that begins with a bracketed failure word.

Success prefixes are deliberately **not** listed — `[Account added]`,
`[Payment method added]`, `[Proposal created]` and `[Workshop folder created]`
really did execute, and marking them as errors would be the mirror-image lie.
Both directions are asserted below.

## The anti-drift guard

`TestEveryHandlerFailureIsCovered` re-walks the handlers at test time and fails
if any failure prefix is not in the list. That is the part that matters: the
list can no longer go stale without a red test, which is exactly how this defect
survived the ticket that introduced the mechanism.
"""

import ast
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]

# Every module that returns a tool-result string.
SOURCES = (
    "agents/safety/handlers.py",
    "agents/safety/legacy_tools.py",
    "agents/integrations/web_eyes.py",
    "agents/knowledge/workshop.py",
)

# Bracketed prefixes that report SUCCESS. Excluded from the deny-list on
# purpose -- these really did execute.
SUCCESS_PREFIXES = frozenset({
    "[account added", "[payment method added", "[proposal created",
    "[workshop folder created", "[command succeeded",
    # ARCH-ENG-248: the typed surface's successes. "[proposal status" is the
    # success shape ("[Proposal status: file -> Sent]"); its failure sibling
    # carries its own marker ("[proposal status not updated").
    "[account removed", "[application created", "[deliverable added",
    "[note added", "[proposal status", "[research note created",
    "[script created",
})


def _bracketed_prefixes():
    """Every `[Word ...]` prefix the handlers can return.

    Walks `ast.Return` and unparses, so f-strings are handled. A substring scan
    of the raw source would also match comments and docstrings; this returns
    only what can actually reach the caller.
    """
    found = {}
    for rel in SOURCES:
        path = REPO / rel
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Return) or node.value is None:
                continue
            try:
                text = ast.unparse(node.value)
            except Exception:
                continue
            match = re.match(r"f?[\"']\[([A-Za-z][A-Za-z ]*?)[:\]]", text)
            if not match:
                continue
            prefix = f"[{match.group(1).lower()}"
            found.setdefault(prefix, set()).add(rel)
    return found


def _markers():
    import agents.safety  # noqa: F401  -- break the circular import
    from agents.dialogue.chat_completion import _NOT_EXECUTED_MARKERS
    return {m.lower() for m in _NOT_EXECUTED_MARKERS}


class TestEveryHandlerFailureIsCovered(unittest.TestCase):
    """ARCH-ENG-214 — the anti-drift guard. This is the important one."""

    def test_no_handler_failure_prefix_is_missing(self):
        markers = _markers()
        prefixes = _bracketed_prefixes()
        self.assertGreaterEqual(
            len(prefixes), 20,
            "the prefix scan found almost nothing, so this guard would pass "
            "vacuously")
        uncovered = [
            f"{p} ({', '.join(sorted(srcs))})"
            for p, srcs in sorted(prefixes.items())
            if p not in SUCCESS_PREFIXES
            and not any(m in p for m in markers)
        ]
        self.assertEqual(
            uncovered, [],
            f"these handler failure prefixes are not in "
            f"_NOT_EXECUTED_MARKERS, so they classify as 'executed': {uncovered}")

    def test_success_prefixes_are_still_reported_as_executed(self):
        """The mirror-image check: a fix must not invent failures."""
        import agents.safety  # noqa: F401
        from agents.dialogue.chat_completion import _tool_status

        for prefix in SUCCESS_PREFIXES:
            with self.subTest(prefix=prefix):
                self.assertEqual(
                    _tool_status(f"{prefix} ok"), "executed",
                    f"{prefix} really did execute; reporting it as an error "
                    f"would be the mirror-image lie")


class TestTheClassification(unittest.TestCase):
    """ARCH-ENG-214 — behaviour, both directions."""

    FAILURES = (
        "[Query error: no such table: opportunities]",
        "[Read error: boom]",
        "[File not found: notes.md]",
        "[Directory not found: /nope]",
        "[Database not found: unknown]",
        "[Command error: exit 1]",
        "[Command timed out]",
        "[Write error: path is outside the project workspace]",
        "[Read refused: .env is a credential/key store]",
        "[Fetch refused: private target]",
        "[List error: boom]",
        "[Check error: boom]",
        "[Workshop error: boom]",
        "[Workshop folder creation failed: permission denied]",
        "[Workshop storage error: quota exceeded]",
        "[Account error: boom]",
        "[Payment error: boom]",
        "[Proposal error: boom]",
    )

    def test_every_failure_is_not_executed(self):
        import agents.safety  # noqa: F401
        from agents.dialogue.chat_completion import _tool_status

        for result in self.FAILURES:
            with self.subTest(result=result[:40]):
                self.assertNotEqual(
                    _tool_status(result), "executed",
                    f"{result!r} reports a failure but is classified as a "
                    f"completed action")

    def test_real_results_are_executed(self):
        import agents.safety  # noqa: F401
        from agents.dialogue.chat_completion import _tool_status

        for result in ("", "page content here", "[Command succeeded with no output]",
                       "[Account added] demo", "[Proposal created] /p/p.md"):
            with self.subTest(result=result[:40]):
                self.assertEqual(_tool_status(result), "executed")

    def test_the_original_ticket_173_shapes_still_hold(self):
        """The two shapes ARCH-ENG-173 closed must not regress."""
        import agents.safety  # noqa: F401
        from agents.dialogue.chat_completion import _tool_status

        self.assertEqual(
            _tool_status("[PENDING APPROVAL] request_id=x; not executed."),
            "pending_approval")
        self.assertEqual(_tool_status("[BLOCKED] requires approval"), "blocked",
                         # `blocked`, not `error` -- a deliberate distinction,
                         # so the UI can tell a refusal from a malfunction. An
                         # earlier draft asserted "error" and was wrong.
                         )


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-214 — each detector must be able to fail."""

    def test_the_prefix_scan_finds_known_prefixes(self):
        prefixes = _bracketed_prefixes()
        self.assertIn("[query error", prefixes,
                      "the scan cannot see a known handler failure, so the "
                      "anti-drift guard proves nothing")
        self.assertIn("[command timed out", prefixes)

    def test_the_coverage_check_would_fail_on_an_uncovered_prefix(self):
        """Simulate a new handler failure nobody added to the list."""
        markers = _markers()
        invented = "[teleport error: engine offline]"
        self.assertFalse(
            any(m in invented for m in markers),
            "an uncovered failure prefix would still look covered, so the "
            "guard cannot detect drift")

    def test_the_classifier_can_see_a_success(self):
        """Otherwise the failure assertions could pass by rejecting everything."""
        import agents.safety  # noqa: F401
        from agents.dialogue.chat_completion import _tool_status

        self.assertEqual(_tool_status("[Account added] demo"), "executed",
                         "the classifier rejects successes, so every 'is not "
                         "executed' assertion is meaningless")

    def test_the_source_list_is_not_vacuous(self):
        self.assertGreaterEqual(len(SOURCES), 4)
        for rel in SOURCES:
            self.assertTrue((REPO / rel).exists(), f"{rel} is missing")