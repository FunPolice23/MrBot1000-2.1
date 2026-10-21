"""ARCH-ENG-201 — a security blocklist that silently ignored edits.

`agents/brains/base_worker.py` defined the security blocklist twice and then
imported it, so the definition was overwritten 146 lines later:

    107:  FILENAME_BLOCKLIST = { ...14 entries... }      <- defined here
    ...
    253:  from agents.brains.worker_safety import (
    254:      BLOCKED_MIME_TYPES, FILENAME_BLOCKLIST, ...  <- and replaced here

Both copies happened to agree, so nothing appeared wrong.

## Why this was a trap rather than a redundancy

The failure mode is *silent and total*. Anyone who edited the literal at line 107
would see no error, no failed test, and no change in behaviour, because the
import at line 253 had already won. Every check would pass while the edit did
nothing.

That is worse than having no blocklist at all. A blocklist that visibly exists
and visibly lists fourteen sensitive filenames reads as *maintained*. It
communicates "this is handled" to everyone who later reasons about whether
`.bashrc` or `id_rsa` can be read — including the operator, and including the
agents. A defence that looks maintained but ignores edits does not just fail to
protect; it actively misleads.

## The fix

`worker_safety` is the single definition and `base_worker` imports it. The names
remain importable from `base_worker`, because callers across the codebase do
`from agents.brains.base_worker import FILENAME_BLOCKLIST`.

The test below pins the *property*, not the spelling: no assignment to either
name may exist in `base_worker` at all, so there is nothing left to silently
lose.
"""

import ast
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
BASE_WORKER = REPO / "agents" / "brains" / "base_worker.py"
WORKER_SAFETY = REPO / "agents" / "brains" / "worker_safety.py"

NAMES = ("FILENAME_BLOCKLIST", "BLOCKED_MIME_TYPES")


def _assigned_names(path):
    """Every name this module binds with `=`, via AST (not substring)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            out.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.add(node.target.id)
    return out


class TestNoShadowedDefinitionRemains(unittest.TestCase):
    """ARCH-ENG-201 — nothing in `base_worker` may define these names."""

    def test_base_worker_defines_neither_name(self):
        assigned = _assigned_names(BASE_WORKER)
        for name in NAMES:
            with self.subTest(name=name):
                self.assertNotIn(
                    name, assigned,
                    f"base_worker assigns {name} again. Any such assignment is "
                    f"dead -- the import from worker_safety on a later line wins "
                    f"silently, and an edit to the assignment would do nothing")

    def test_worker_safety_is_the_single_definition(self):
        assigned = _assigned_names(WORKER_SAFETY)
        for name in NAMES:
            with self.subTest(name=name):
                self.assertIn(
                    name, assigned,
                    f"{name} must be defined in worker_safety; that module is "
                    f"the single source of truth")

    def test_base_worker_still_re_exports_the_names(self):
        """Removing the definition must NOT break existing importers.

        `from agents.brains.base_worker import FILENAME_BLOCKLIST` is used
        across the codebase. The fix moved the definition; it did not make the
        name unreachable.
        """
        src = BASE_WORKER.read_text(encoding="utf-8")
        for name in NAMES:
            with self.subTest(name=name):
                self.assertRegex(
                    src, rf"from agents\.brains\.worker_safety import \([^)]*\b{name}\b"
                         rf"|from agents\.brains\.worker_safety import \b{name}\b",
                    f"{name} is no longer re-exported from base_worker; callers "
                    f"doing `from ...base_worker import {name}` would ImportError")


class TestRuntimeActuallyUsesTheOneDefinition(unittest.TestCase):
    """ARCH-ENG-201 — the re-export must be the *same object*, not a copy.

    A copy would reintroduce exactly the defect: two lists that can drift.
    """

    def test_the_names_are_identical_objects(self):
        from agents.brains import base_worker, worker_safety

        for name in NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(base_worker, name), getattr(worker_safety, name),
                    f"base_worker.{name} is a distinct object from "
                    f"worker_safety.{name}; two copies can drift, which is the "
                    f"bug this ticket fixes")

    def test_the_blocklist_is_not_empty(self):
        """A vacuity probe: an accidentally-emptied list would pass every
        identity check above while blocking nothing."""
        from agents.brains.worker_safety import (BLOCKED_MIME_TYPES,
                                                 FILENAME_BLOCKLIST)

        self.assertGreaterEqual(
            len(FILENAME_BLOCKLIST), 14,
            "the enforced blocklist shrank; the sensitive filenames "
            "(id_rsa, passwd, shadow, sudoers...) must stay blocked")
        self.assertGreaterEqual(len(BLOCKED_MIME_TYPES), 4)
        # Spot-check the entries whose loss would matter most.
        for name in (".env", "id_rsa", "passwd", "shadow", "sudoers",
                     ".bashrc", "credentials.json"):
            with self.subTest(name=name):
                self.assertIn(name, FILENAME_BLOCKLIST)


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-201 — the detector must fail on the original defect."""

    def test_a_local_assignment_would_be_detected(self):
        bad = "FILENAME_BLOCKLIST = {'a'}\n"
        assigned = {
            t.id for n in ast.walk(ast.parse(bad))
            if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)
        }
        self.assertIn("FILENAME_BLOCKLIST", assigned,
                      "the detector cannot see a plain assignment, so it would "
                      "pass while the shadowed definition returned")

    def test_the_comment_naming_the_old_defect_is_not_an_assignment(self):
        """The explanatory comment mentions `FILENAME_BLOCKLIST = {`.

        A substring-based detector would match the comment documenting the bug
        and report a false positive forever. AST is used precisely to avoid
        that.
        """
        src = BASE_WORKER.read_text(encoding="utf-8")
        self.assertIn("FILENAME_BLOCKLIST", src,
                      "the module should still discuss the old defect")
        self.assertNotIn(
            "FILENAME_BLOCKLIST", _assigned_names(BASE_WORKER),
            "the ARCH-ENG-201 comment block contains the text "
            "'FILENAME_BLOCKLIST = {' but it must not parse as an assignment")

    def test_the_reason_is_recorded_in_the_source(self):
        """The next editor must know the literal is gone on purpose."""
        src = BASE_WORKER.read_text(encoding="utf-8")
        self.assertRegex(
            src, r"ARCH-ENG-201",
            "the removal needs a marker, or a future reader will "
            "helpfully re-add the constant")
        # The marker must explain WHY, not just that.
        self.assertRegex(
            src, r"worker_safety",
            "the ARCH-ENG-201 comment must name worker_safety as the single "
            "definition")