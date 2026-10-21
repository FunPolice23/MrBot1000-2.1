"""ARCH-ENG-227 - the propose hop, the practice rehearsal, and the deferral.

## The empty loop

`CoderWorker` was the only class that could ever call
`self_improvement_commands.propose_code_patch`, and it had **zero callers
anywhere in the codebase** -- not in production, not in `agents/__init__.py`'s
lazy exports, not via importlib.

So the entire Self-Improvement chain -- propose -> approve -> apply -> verify ->
rollback -> post-apply monitor -- was fully built, fully approval-gated, and
unreachable. The only producer of a proposal was `monitor_applied`'s own
self-heal, which requires an applied patch, which requires an approval. The
loop was closed and empty.

## Two more unreachable mechanisms

Both were correct code, tested, and never wired:

- **`register_module` had zero callers.** `_module_to_file` was permanently
  empty, so `_resolve_for_inuse` returned `None` for every dotted module name,
  `mark_in_use("gui.tabs.chat")` silently did nothing, and `_in_use_files` stayed
  empty forever. That made both deferral guards -- in `apply_approved` and in
  `drain` -- unreachable, because both test `... and self._in_use_files and ...`.
  "Apply when the target is free" could not happen.

- **`drain()` had zero callers.** Even a correctly queued patch would have sat
  forever, so an approved change could silently never land.

## Why the rehearsal exists

`CodePatchService.verify` runs `py_compile` and nothing else -- deliberately,
since it writes into a running program's own source. So a patch could compile
cleanly and still be wrong, and a human would be asked to approve a change
proven only to be syntactically valid.

`PatchSandbox` applies the patch to a COPY under the workshop's practice folder
and verifies the copy. Three properties are load-bearing and all tested: the
real target is never touched; the practice copy is KEPT so the approver can
inspect exactly what was rehearsed; and a rehearsal that fails is a REFUSAL, not
a warning -- no proposal is created.

## What this still does not do

Nothing here changes the running program. The rehearsal proves a patch is
well-formed enough to deserve a human's attention; it does not prove the patch
is *correct*, and it does not replace approval.
"""

import ast
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _fresh_repo():
    root = tempfile.mkdtemp(prefix="arch227_repo_")
    os.makedirs(os.path.join(root, "pkg"), exist_ok=True)
    with open(os.path.join(root, "pkg", "mod.py"), "w", encoding="utf-8") as fh:
        fh.write("def f():\n    return 1\n")
    return root


def _fresh_shop():
    return tempfile.mkdtemp(prefix="arch227_shop_")


def _read(root, rel="pkg/mod.py"):
    with open(os.path.join(root, rel), encoding="utf-8") as fh:
        return fh.read()


ORIGINAL = "def f():\n    return 1\n"
PATCHED = "def f():\n    return 2\n"


class TestTheSandboxNeverTouchesTheRealFile(unittest.TestCase):
    def setUp(self):
        self.repo = _fresh_repo()
        self.shop = _fresh_shop()
        from agents.services.patch_sandbox import PatchSandbox
        self.sb = PatchSandbox(self.repo, self.shop)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.shop, ignore_errors=True)

    def test_a_rehearsal_leaves_the_original_byte_identical(self):
        """The single most important property. A bug here is catastrophic."""
        before = _read(self.repo)
        self.sb.rehearse("pkg/mod.py", PATCHED)
        self.sb.rehearse("pkg/mod.py", "def f(:\n")
        self.assertEqual(_read(self.repo), before,
                         "the rehearsal modified the real source file")

    def test_a_broken_patch_fails_the_rehearsal(self):
        result = self.sb.rehearse("pkg/mod.py", "def f(:\n")
        self.assertFalse(result["ok"], "a syntax error passed the rehearsal")

    def test_a_good_patch_passes(self):
        self.assertTrue(self.sb.rehearse("pkg/mod.py", PATCHED)["ok"])

    def test_the_practice_copy_is_kept_for_inspection(self):
        """A rehearsal whose evidence is deleted is not evidence."""
        r = self.sb.rehearse("pkg/mod.py", PATCHED)
        self.assertTrue(os.path.isfile(r["practice_path"]),
                        "the rehearsed copy was discarded, so the approver "
                        "cannot see what was tested")
        with open(r["practice_path"], encoding="utf-8") as fh:
            self.assertEqual(fh.read(), PATCHED)

    def test_the_copy_is_seeded_from_the_real_file(self):
        """So the rehearsal runs against real surrounding code."""
        r = self.sb.rehearse("pkg/mod.py", PATCHED)
        self.assertIsNotNone(r["seeded_from"])
        self.assertEqual(os.path.abspath(r["seeded_from"]),
                         os.path.join(self.repo, "pkg", "mod.py"))

    def test_a_new_file_has_no_original_and_is_flagged(self):
        r = self.sb.rehearse("pkg/brand_new.py", "x = 1\n")
        self.assertTrue(r["ok"])
        self.assertTrue(r["is_new_file"])

    def test_paths_escaping_the_repo_are_refused(self):
        from agents.services.patch_sandbox import SandboxError
        for bad in ("../outside.py", os.path.join(self.repo, "..", "esc.py")):
            with self.subTest(target=bad):
                with self.assertRaises(SandboxError):
                    self.sb.rehearse(bad, "x = 1\n")

    def test_the_practice_root_is_outside_the_repo(self):
        self.assertFalse(
            os.path.commonpath([os.path.abspath(self.sb.practice_root),
                                os.path.abspath(self.repo)])
            == os.path.abspath(self.repo),
            "the practice folder is inside the repository")

    def test_prune_bounds_the_practice_folder(self):
        for i in range(6):
            self.sb.rehearse("pkg/mod.py", PATCHED, run_id=f"run{i:02d}")
        self.sb.prune(keep=3)
        self.assertEqual(len(os.listdir(self.sb.practice_root)), 3)


class TestProposeEnforcesBackupThenRehearsalThenApproval(unittest.TestCase):
    """The three ordered steps. Order is the design."""

    def setUp(self):
        self.repo = _fresh_repo()
        self.shop = _fresh_shop()
        os.environ["MRBOT_PATCH_PRACTICE_ROOT"] = self.shop
        import agents.services.code_patch_service as cps
        from agents.services.code_patch_service import CodePatchService
        self.cps = cps
        self.svc = CodePatchService(root_dir=self.repo, approval_queue=None)
        self._prev = cps._CODE_PATCH_SERVICE
        cps._CODE_PATCH_SERVICE = self.svc
        from agents.safety.handlers import _tool_propose_code_patch
        self.propose = _tool_propose_code_patch

    def tearDown(self):
        self.cps._CODE_PATCH_SERVICE = self._prev
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.shop, ignore_errors=True)

    # -- step 2: rehearsal is a refusal, not a warning --
    def test_a_failing_rehearsal_creates_no_proposal(self):
        out = self.propose({"target": "pkg/mod.py",
                            "new_content": "def f(:\n",
                            "motivation": "fix the return"})
        self.assertTrue(out.startswith("[Patch refused"), out[:120])
        self.assertEqual(len(self.svc._patches), 0,
                         "a patch that failed rehearsal was registered")

    def test_a_refusal_names_the_practice_copy(self):
        """So the agent (and the operator) can see WHY it failed."""
        out = self.propose({"target": "pkg/mod.py",
                            "new_content": "def f(:\n",
                            "motivation": "fix"})
        self.assertIn("practice", out.lower())
        self.assertIn("does not compile", out)

    # -- nothing changes at propose time --
    def test_a_successful_proposal_changes_nothing(self):
        out = self.propose({"target": "pkg/mod.py", "new_content": PATCHED,
                            "motivation": "return 2", "authored_by": "edward"})
        self.assertIn("PROPOSED", out)
        self.assertEqual(_read(self.repo), ORIGINAL,
                         "proposing modified the target; proposal must never "
                         "be an application")

    # -- step 1: backup taken BEFORE the human is asked --
    def test_a_backup_exists_at_propose_time(self):
        self.propose({"target": "pkg/mod.py", "new_content": PATCHED,
                      "motivation": "return 2"})
        backups = os.listdir(self.svc.backup_dir)
        self.assertTrue(backups,
                        "no backup at propose time, so a later revert has "
                        "nothing to go back to")
        with open(os.path.join(self.svc.backup_dir, backups[0]),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read(), ORIGINAL,
                             "the backup does not hold the original content")

    def test_the_proposal_records_where_it_was_rehearsed(self):
        """Evidence travels with the proposal into the approval UI."""
        self.svc.propose.__self__  # noqa: B018 - attribute access sanity
        out = self.propose({"target": "pkg/mod.py", "new_content": PATCHED,
                            "motivation": "return 2"})
        self.assertIn("practice", out.lower())
        patch = next(iter(self.svc._patches.values()))
        self.assertIn("practice", patch.detail.lower())

    # -- refusals --
    def test_missing_arguments_are_refused(self):
        for args in ({}, {"target": "pkg/mod.py"},
                     {"target": "pkg/mod.py", "new_content": PATCHED},
                     {"target": "pkg/mod.py", "new_content": "  "}):
            with self.subTest(args=sorted(args)):
                self.assertTrue(self.propose(args).startswith("[Patch refused"))
        self.assertEqual(len(self.svc._patches), 0)

    def test_an_unavailable_service_is_refused_cleanly(self):
        self.cps._CODE_PATCH_SERVICE = None
        out = self.propose({"target": "pkg/mod.py", "new_content": PATCHED,
                            "motivation": "m"})
        self.assertIn("no code patch service", out.lower())
        self.assertEqual(_read(self.repo), ORIGINAL)


class TestDeferralIsActuallyReachable(unittest.TestCase):
    """`register_module` and `drain` had zero callers."""

    def setUp(self):
        self.repo = _fresh_repo()
        from agents.services.code_patch_service import CodePatchService
        self.svc = CodePatchService(root_dir=self.repo, approval_queue=None)
        self.target = os.path.join(self.repo, "pkg", "mod.py")
        self.svc._is_approved = lambda gate: True

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def _patch(self):
        from agents.services.code_patch_service import CodePatch
        p = CodePatch(target_path=self.target, authored_by="edward",
                      motivation="m", detail="d", patch_text=PATCHED)
        self.svc._patches[p.patch_id] = p
        return p

    def _import_repo_module(self):
        """Create and import a module INSIDE the temp repo.

        `root_dir` is the temp repo in these tests, so a module from the real
        repository is correctly outside it -- containment working as designed.
        To exercise resolution, the module has to live in the repo being patched.
        """
        import importlib
        pkg = os.path.join(self.repo, "pkg")
        name = "arch227_live_mod"
        with open(os.path.join(pkg, f"{name}.py"), "w", encoding="utf-8") as fh:
            fh.write("VALUE = 1\n")
        if self.repo not in sys.path:
            sys.path.insert(0, self.repo)
        try:
            mod = importlib.import_module(f"pkg.{name}")
            importlib.reload(mod)
            return f"pkg.{name}"
        finally:
            if self.repo in sys.path:
                sys.path.remove(self.repo)

    def test_a_dotted_module_name_resolves_without_registration(self):
        """`_module_to_file` is empty; resolution must not depend on it."""
        self.assertEqual(self.svc._module_to_file, {},
                         "precondition: nothing registered")
        dotted = self._import_repo_module()
        resolved = self.svc._resolve_for_inuse(dotted)
        self.assertIsNotNone(resolved,
                             "a dotted module inside the repo no longer "
                             "resolves, so mark_in_use is a silent no-op again")
        self.assertEqual(os.path.abspath(resolved),
                         os.path.join(self.repo, "pkg",
                                      dotted.rsplit(".", 1)[-1] + ".py"))

    def test_an_unimportable_dotted_name_still_returns_none(self):
        """So the fallback did not turn into "everything resolves"."""
        self.assertIsNone(self.svc._resolve_for_inuse("not.a.real.module_xyz"))

    def test_a_module_outside_the_repo_still_returns_none(self):
        """The bug this assertion was written for.

        `importlib` happily resolves `json` to the stdlib copy under the Python
        install. Accepting that put a path the patch service could never write
        to into `_in_use_files`, where it could only ever produce a confusing
        match. A dotted name is worth resolving only if it names something
        inside this repo.
        """
        self.assertIsNone(self.svc._resolve_for_inuse("json"),
                          "a stdlib module resolved to a file path; the "
                          "resolver does not respect repo containment")
        self.assertIsNone(self.svc._resolve_for_inuse("os"),
                          "another stdlib module slipped through")

    def test_mark_in_use_by_dotted_name_actually_marks(self):
        dotted = self._import_repo_module()
        self.svc.mark_in_use(dotted)
        expected = os.path.join(self.repo, "pkg",
                                dotted.rsplit(".", 1)[-1] + ".py")
        self.assertIn(os.path.abspath(expected), self.svc._in_use_files)

    def test_an_in_use_target_is_queued_not_clobbered(self):
        p = self._patch()
        self.svc.mark_in_use(self.target)
        result = self.svc.apply_approved(p, approval_id=p.patch_id)
        self.assertEqual(result.get("status"), "queued", result)
        self.assertEqual(_read(self.repo), ORIGINAL,
                         "an in-use file was overwritten instead of queued")

    def test_releasing_the_file_alone_does_not_apply(self):
        """Freeing and applying are SEPARATE steps, deliberately.

        An earlier draft of this ticket folded the drain into `mark_free`. The
        pre-existing tests caught it: a caller that frees a file and then drains
        -- the documented pattern -- found the queue already emptied and got
        `[]` back. So `mark_free` frees, and `drain` applies.
        """
        p = self._patch()
        self.svc.mark_in_use(self.target)
        self.svc.apply_approved(p, approval_id=p.patch_id)
        self.assertEqual(len(self.svc._pending), 1)

        self.svc.mark_free(self.target)
        self.assertEqual(_read(self.repo), ORIGINAL,
                         "mark_free applied a patch; freeing and applying "
                         "must stay separate steps")
        self.assertEqual(len(self.svc._pending), 1,
                         "mark_free emptied the queue")

    def test_the_wiring_actually_calls_drain(self):
        """`drain` had zero callers, so a queued patch stranded forever.

        This is the regression: if nobody calls drain, an approved change never
        lands and the operator believes it did.
        """
        import inspect
        from agents.services import self_improvement_commands as sic
        self.assertTrue(hasattr(sic, "apply_deferred"),
                        "the drain helper no longer exists")
        self.assertIn("apply_deferred",
                      inspect.getsource(sic.approve_and_apply),
                      "the approval path no longer picks up deferred patches")
        src = (REPO / "main.py").read_text(encoding="utf-8")
        self.assertIn("apply_deferred", src,
                      "the self-improvement monitor tick no longer drains")

    def test_releasing_then_draining_applies_the_queued_patch(self):
        """The documented pattern, still working."""
        p = self._patch()
        self.svc.mark_in_use(self.target)
        self.svc.apply_approved(p, approval_id=p.patch_id)
        self.svc.mark_free(self.target)
        self.svc.drain()
        self.assertEqual(_read(self.repo), PATCHED,
                         "free then drain did not apply the queued patch")
        self.assertEqual(self.svc._pending, [])

    def test_the_applied_patch_can_be_reverted_from_its_backup(self):
        p = self._patch()
        self.svc.mark_in_use(self.target)
        self.svc.apply_approved(p, approval_id=p.patch_id)
        self.svc.mark_free(self.target)
        self.svc.drain()
        record = self.svc._applied.get(p.patch_id) or {}
        backup = record.get("backup_path")
        self.assertTrue(backup and os.path.isfile(backup),
                        "no backup recorded, so the applied change is "
                        "irreversible")
        self.assertTrue(self.svc._rollback(backup, self.target))
        self.assertEqual(_read(self.repo), ORIGINAL,
                         "rollback did not restore the original")

    def test_mark_free_with_nothing_waiting_does_nothing(self):
        self.svc.mark_free(self.target)      # must not raise


class TestTheToolIsRegisteredEverywhereItMustBe(unittest.TestCase):
    """Schema, gate, dispatch -- a tool missing any one is unreachable."""

    def test_the_schema_exists(self):
        from agents.safety.tools import get_all_tools
        names = {t["function"]["name"] for t in get_all_tools()}
        self.assertIn("propose_code_patch", names)

    def test_the_schema_tells_the_model_this_changes_nothing(self):
        """The description is the model's only warning. It must be honest."""
        from agents.safety.tools import get_all_tools
        desc = next(t["function"]["description"] for t in get_all_tools()
                    if t["function"]["name"] == "propose_code_patch")
        self.assertIn("DOES NOT change anything", desc)

    def test_it_is_classified_mutating_not_readonly(self):
        """READONLY would let the gate ALLOW it with no human in the loop."""
        from agents.safety.gate import MUTATING_TOOL_NAMES, READONLY_TOOL_NAMES
        self.assertIn("propose_code_patch", MUTATING_TOOL_NAMES)
        self.assertNotIn("propose_code_patch", READONLY_TOOL_NAMES)

    def test_it_has_a_dispatch_entry(self):
        src = (REPO / "agents" / "safety" / "dispatch.py").read_text(encoding="utf-8")
        self.assertIn('"propose_code_patch": runtime._tool_propose_code_patch', src)

    def test_the_service_is_reachable_without_a_gui(self):
        """The handler has no MainWindow, so it needs its own accessor."""
        src = (REPO / "agents" / "services" / "code_patch_service.py") \
            .read_text(encoding="utf-8")
        self.assertIn("def get_code_patch_service", src)
        import agents.services.code_patch_service as cps
        self.assertTrue(callable(cps.get_code_patch_service))


class TestTheGuardsCannotPassByReadingThemselves(unittest.TestCase):
    def test_the_service_registers_itself_on_construction(self):
        """If it did not, the tool would work only inside the GUI."""
        from agents.services.code_patch_service import CodePatchService, get_code_patch_service
        root = _fresh_repo()
        try:
            svc = CodePatchService(root_dir=root, approval_queue=None)
            self.assertIs(get_code_patch_service(), svc,
                          "a constructed service did not announce itself")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_the_backup_precedes_the_rehearsal_in_the_source(self):
        """Step 1 before step 2. If a rehearsal could run first, an approval
        could be raised with no backup yet taken."""
        import inspect
        from agents.safety.handlers import _tool_propose_code_patch
        src = inspect.getsource(_tool_propose_code_patch)
        self.assertLess(src.index("service.backup"),
                        src.index("sandbox.rehearse"),
                        "the rehearsal runs before the backup is taken")

    def test_the_rehearsal_precedes_the_proposal_in_the_source(self):
        import inspect
        from agents.safety.handlers import _tool_propose_code_patch
        src = inspect.getsource(_tool_propose_code_patch)
        self.assertLess(src.index("sandbox.rehearse"),
                        src.index("service.propose"),
                        "a proposal is raised before the rehearsal is checked")

    def test_mark_free_calls_drain_in_the_source(self):
        import inspect
        from agents.services.code_patch_service import CodePatchService
        self.assertIn("drain", inspect.getsource(CodePatchService.mark_free),
                      "mark_free no longer drains; queued patches strand again")


if __name__ == "__main__":
    unittest.main()