"""ARCH-ENG-208/209 — two defects found by auditing the dead-code report's claims.

## ARCH-ENG-208 — `PROTECTED_SOURCE_FILES` was defined twice, and the smaller copy won

`agents/brains/base_worker.py` assigned the same name twice: **29 entries** at
line 83 and **14 entries** at line 129. The later assignment won, so only 14
files were ever protected. Sixteen were silently unprotected, including
`wallet_manager.py`, `opportunity_lifecycle.py`, `fiverr_client.py`,
`upwork_client.py`, `airdrop_claimer.py` and `defi_scanner.py`.

This is ARCH-ENG-201's exact failure mode — a security list that ignores edits —
one constant away from the duplicate that ticket fixed in the same file. The two
copies were **not nested**: the winner *added* `earning_memory.py`, so it was a
different set rather than a subset. That is why it never surfaced as "some
entries missing" in a review, and why a count comparison would have been
misleading too (29 vs 14 looks like shrinkage; the truth is a swap).

The surviving definition is the **union** of both, so nothing either copy
intended is lost.

## ARCH-ENG-209 — `"type": "tc.function"` in the tool-call serialisation

`big_brain.py` emitted `"type": "tc.function"` when replaying assistant
tool_calls into conversation history. The OpenAI tool-call schema requires
`"type": "function"`. A conforming provider rejects the request outright; a
lenient one may drop the tool calls silently. Either way the Big Brain loses
its tool calls on any turn that used one.

These are pinned structurally rather than by a runtime call, because the first
one is a silent security regression that no functional test would notice: the
enforced set simply gets smaller and nothing complains.
"""

import ast
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
BASE_WORKER = REPO / "agents" / "brains" / "base_worker.py"
BIG_BRAIN = REPO / "agents" / "brains" / "big_brain.py"

# Files the 29-entry copy protected and the 14-entry winner had dropped.
WAS_UNPROTECTED = (
    "wallet_manager.py", "opportunity_lifecycle.py", "fiverr_client.py",
    "upwork_client.py", "airdrop_claimer.py", "airdrop_scanner.py",
    "defi_scanner.py", "shared_context.py",
    "document_scanner.py", "task_workspace.py", "earning_discoverer.py",
    "content_generator.py",
    # "workflow_planner.py" was on this historical list; the module itself was
    # deleted at ARCH-ENG-254 (W-04) -- nothing imported it. The other fifteen
    # remain protected, which is what this pin is for.
    "social_earning_platform.py", "microtask_client.py",
)


def _assignments(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    out.append(ast.literal_eval(n.value))
    return out


class TestProtectedSourceFilesHasOneDefinition(unittest.TestCase):
    """ARCH-ENG-208 — the structural half."""

    def test_exactly_one_definition(self):
        sets = _assignments(BASE_WORKER, "PROTECTED_SOURCE_FILES")
        self.assertEqual(
            len(sets), 1,
            f"PROTECTED_SOURCE_FILES is assigned {len(sets)} times. A second "
            f"assignment silently wins, so editing the first does nothing.")

    def test_the_fifteen_previously_unprotected_files_are_protected(self):
        sets = _assignments(BASE_WORKER, "PROTECTED_SOURCE_FILES")
        self.assertEqual(len(sets), 1)
        for name in WAS_UNPROTECTED:
            with self.subTest(name=name):
                self.assertIn(
                    name, sets[0],
                    f"{name} is writable again. The winning 14-entry copy "
                    f"dropped it; nobody would see that from a count.")


class TestTheEnforcedSetIsTheOneThingEveryCallerReads(unittest.TestCase):
    """ARCH-ENG-208 — runtime, not just source."""

    def test_every_consequence_is_protected(self):
        from agents.brains.base_worker import PROTECTED_SOURCE_FILES

        # 29, not the union's original 30: workflow_planner.py was deleted at
        # ARCH-ENG-254 and removed from the live set. The floor still guards
        # against the silent shrinkage this ticket fixed.
        self.assertGreaterEqual(len(PROTECTED_SOURCE_FILES), 29)
        for name in WAS_UNPROTECTED:
            with self.subTest(name=name):
                self.assertIn(name, PROTECTED_SOURCE_FILES)

    def test_the_coder_sees_the_same_set(self):
        """A copy would reintroduce exactly the drift being fixed."""
        from agents.brains.base_worker import PROTECTED_SOURCE_FILES
        from agents.services import coder

        self.assertIs(coder.PROTECTED_SOURCE_FILES, PROTECTED_SOURCE_FILES)

    def test_both_writers_consult_it(self):
        """`safe_write_file` and `CoderWorker` are the two write paths."""
        filesystem = (REPO / "agents" / "safety" / "filesystem.py").read_text(
            encoding="utf-8")
        coder_src = (REPO / "agents" / "services" / "coder.py").read_text(
            encoding="utf-8")
        self.assertIn("PROTECTED_SOURCE_FILES", filesystem)
        self.assertIn("PROTECTED_SOURCE_FILES", coder_src)

    def test_the_reason_is_recorded_in_the_source(self):
        """The next editor must know this list was previously wrong."""
        src = BASE_WORKER.read_text(encoding="utf-8")
        self.assertIn("ARCH-ENG-208", src,
                      "the merge needs a marker, or someone will helpfully "
                      "restore a second copy")


class TestToolCallSerialisation(unittest.TestCase):
    """ARCH-ENG-209 — `"tc.function"` is not a valid OpenAI tool-call type."""

    def test_the_emitted_type_is_valid(self):
        src = BIG_BRAIN.read_text(encoding="utf-8")
        self.assertNotRegex(
            src, r'"type"\s*:\s*"tc\.',
            'a "tc.*" tool-call type is back; the OpenAI schema requires '
            '"function" and a conforming provider rejects the request')
        self.assertRegex(src, r'"type"\s*:\s*"function"')

    def test_every_tool_call_object_carries_a_type(self):
        """Every dict with a "function" key must declare the type correctly."""
        src = BIG_BRAIN.read_text(encoding="utf-8")
        for match in re.finditer(r'"type"\s*:\s*"([^"]+)"', src):
            with self.subTest(value=match.group(1)):
                self.assertEqual(
                    match.group(1), "function",
                    f"unexpected tool-call type {match.group(1)!r}")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-208/209 — each detector must be able to fail."""

    def test_the_duplicate_detector_sees_two(self):
        bad = 'A = {"x.py"}\nB = {"x.py", "y.py"}\n'
        tree = ast.parse(bad)
        found = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)]
        self.assertEqual(len(found), 2,
                         "the detector cannot see a second assignment, so it "
                         "would pass while the shadowing returned")

    def test_the_protected_file_probe_sees_an_unprotected_file(self):
        from agents.brains.base_worker import PROTECTED_SOURCE_FILES
        self.assertNotIn(
            "definitely_not_protected.py", PROTECTED_SOURCE_FILES,
            "the membership check cannot see a missing entry, so every "
            "'is protected' assertion would be vacuous")
        self.assertIn("main.py", PROTECTED_SOURCE_FILES,
                      "a sanity positive: main.py must be protected")

    def test_the_list_of_regressed_files_is_not_vacuous(self):
        # 14, not 16: workflow_planner.py was deleted at ARCH-ENG-254 (W-04)
        # and chat_router.py at ARCH-ENG-303 (E-01); both had no live importer.
        # The list must stay non-trivial.
        self.assertEqual(len(WAS_UNPROTECTED), 14)