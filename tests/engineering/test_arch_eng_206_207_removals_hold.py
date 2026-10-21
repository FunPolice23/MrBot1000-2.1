"""ARCH-ENG-206/207 — the removals must not come back, and must not be re-faked.

Two tickets recorded a deletion, which is easy to undo by accident:

* **ARCH-ENG-206** removed genuinely dead code (`workflow_engine.py`,
  `cost_tracker.py`, `agents/polish/`, seven `workshop.py` shims, two unused
  event-logger callbacks).
* **ARCH-ENG-207** deleted `DEADCODE_REPORT.md`, which recommended removing live
  code. Its stated reasons for keeping `agents/earning` cited a file that no
  longer exists, so its conclusions could not be re-derived from its evidence.

A deletion with no executable check is a claim, not a change: the next person
cannot tell deliberate removal from accidental loss, and a stale document
reaching the public mirror is worse than none — the failure it causes points at
the safety suite rather than at the document.

So these tests assert the absences directly, and assert the two distinctions
that are easy to get backwards:

* `credential_vault` and `registration` **stay**, and the package still imports.
* `get_workshop` and `create_proposal` **stay** — the audit that prompted their
  removal said "8 shims", but those two have 11 and 1 callers respectively.
"""

import ast
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]

# ARCH-ENG-206: deleted outright.
DELETED_FILES = (
    "agents/services/workflow_engine.py",
    # ARCH-ENG-254 (W-04): the planner that superseded workflow_engine was
    # itself never imported by anything; its only consumer was the dead
    # `build_workflow_plan` accessor, deleted with it.
    "agents/services/workflow_planner.py",
    "tests/earning/test_workflow_planner.py",
    "agents/core/cost_tracker.py",
    "agents/polish/cli_interface.py",
    "agents/polish/comprehensive_logging.py",
    "tests/earning/test_workflow_invariants.py",
)

# ARCH-ENG-205: deleted once the eager re-export was removed. Guarded here too
# because they and 206 share the same failure mode -- silent reappearance.
DELETED_ADAPTERS = (
    "agents/platforms/base.py",
    "agents/platforms/fiverr.py",
    "agents/platforms/github.py",
    "agents/platforms/prolific.py",
    "agents/platforms/reddit.py",
    "agents/platforms/upwork.py",
    "agents/platforms/registry.py",
)

# ARCH-ENG-207: the stale report.
DELETED_DOC = "DEADCODE_REPORT.md"


class TestRemovedFilesStayRemoved(unittest.TestCase):
    """ARCH-ENG-206/207 — the deletions are load-bearing."""

    def test_dead_modules_are_gone(self):
        for rel in DELETED_FILES:
            with self.subTest(path=rel):
                self.assertFalse(
                    (REPO / rel).exists(),
                    f"{rel} is back. It was dead: "
                    f"workflow_engine was superseded by a workflow planner "
                    f"that itself never got wired and was deleted "
                    f"(ARCH-ENG-254), cost_tracker by agents/safety/cost.py, "
                    f"and "
                    f"agents/polish's cli_interface had a main() with no "
                    f"__name__ guard so its advertised `python -m` was a "
                    f"silent no-op")

    def test_the_unreachable_adapters_stay_gone(self):
        for rel in DELETED_ADAPTERS:
            with self.subTest(path=rel):
                self.assertFalse((REPO / rel).exists())

    def test_the_stale_report_stays_deleted(self):
        self.assertFalse(
            (REPO / DELETED_DOC).exists(),
            "DEADCODE_REPORT.md is back. It recommended deleting the whole "
            "agents/platforms package, which would break "
            "tests/safety/test_trust_boundary.py and the registration panel, "
            "and justified agents/earning by citing a file that no longer "
            "exists. If a new sweep is wanted, write it from evidence.")

    def test_nothing_re_imports_them(self):
        """A surviving import would resurrect the code as an ImportError."""
        for name in ("workflow_engine", "cost_tracker",
                     "agents.polish", "platforms.base",
                     "platforms.registry"):
            hits = []
            for f in REPO.rglob("*.py"):
                if any(s in f.parts for s in (".venv", "__pycache__",
                                              "code_patch_backups",
                                              ".mrbot_backups")):
                    continue
                if "test_arch_eng_206" in f.name:
                    continue
                for i, ln in enumerate(f.read_text(encoding="utf-8",
                                                   errors="replace").splitlines(), 1):
                    if name in ln and ln.lstrip().startswith(("import ", "from ")):
                        hits.append(f"{f.relative_to(REPO)}:{i}")
            with self.subTest(name=name):
                self.assertEqual(hits, [],
                                 f"something still imports {name}: {hits}")


class TestWhatMustSurviveActuallyDid(unittest.TestCase):
    """ARCH-ENG-205/206 — the deletions must not have over-reached."""

    def test_the_live_platforms_files_are_present(self):
        for rel in ("agents/platforms/__init__.py",
                    "agents/platforms/credential_vault.py",
                    "agents/platforms/registration.py"):
            with self.subTest(path=rel):
                self.assertTrue((REPO / rel).exists(),
                                f"{rel} is load-bearing and was deleted")

    def test_credential_vault_still_imports(self):
        """The live half of the package must still work."""
        from agents.platforms.credential_vault import CredentialVault
        self.assertIsNotNone(CredentialVault)

    def test_the_two_live_workshop_shims_survived(self):
        """The audit said "8 shims". Two of them were live.

        `get_workshop` has 11 callers and `create_proposal` has 1. Removing
        either would have broken working code while satisfying the report.
        """
        import agents.knowledge.workshop as ws

        for name in ("get_workshop", "create_proposal"):
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(ws, name, None)),
                                f"{name} has real callers and must not be "
                                f"removed as a 'shim'")

    def test_the_trust_boundary_rules_are_still_tested(self):
        """Only the unused adapter IMPLEMENTATIONS went, not the rules."""
        src = (REPO / "tests" / "safety" / "test_trust_boundary.py").read_text(
            encoding="utf-8")
        self.assertIn("class TestTrustBoundary", src,
                      "the live trust-boundary assertions were removed along "
                      "with the adapters; agents/safety/trust.py is still "
                      "enforced")
        self.assertNotIn("class TestPlatformAdapters", src,
                         "the adapter tests outlived the adapters")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-206/207 — each detector must be able to fail."""

    def test_the_file_checks_see_a_present_file(self):
        present = REPO / "app" / "version.py"
        self.assertTrue(present.exists(),
                        "the existence detector cannot see a present file, so "
                        "it would pass while the deletions were reversed")
        self.assertFalse(
            (REPO / "agents/services/workflow_engine.py").exists(),
            "if this file is back, the deletion test is no longer proving "
            "anything")

    def test_the_list_of_guarded_paths_is_not_vacuous(self):
        self.assertGreaterEqual(len(DELETED_FILES), 5)
        self.assertGreaterEqual(len(DELETED_ADAPTERS), 7)

    def test_the_publish_allowlist_has_no_stale_entries(self):
        """Deleting a file the mirror lists makes the mirror config lie."""
        src = (REPO / "tools" / "github_publish" / "sync_github_upload.py").read_text(
            encoding="utf-8")
        for rel in DELETED_FILES + DELETED_ADAPTERS:
            if not (REPO / rel).exists():
                with self.subTest(path=rel):
                    self.assertNotIn(
                        rel, src,
                        f"the publish INCLUDE list still names {rel}, which no "
                        f"longer exists — the mirror allow-list has drifted")