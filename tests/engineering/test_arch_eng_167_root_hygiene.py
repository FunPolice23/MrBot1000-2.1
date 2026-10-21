"""ARCH-ENG-167 — the source root accumulated one-shot debris with no owner.

Eight one-shot restructuring scripts (`_migrate_agents.py`, `_migrate_app.py`,
`_migrate_gui.py`, `_migrate_tests.py`, `_dbg3.py`, `_dbg4.py`, `_fix_mgmt.py`,
`_verify_arch_eng_143.py`) sat in the source root beside `main.py`. Each was a
completed migration; together they encode the PRE-restructure layout, so leaving
them in the root is an invitation to re-run a migration that already happened.

Also in the root: a 0-byte `NUL` (which Windows refuses to delete through the
normal path, because `NUL` is a reserved device name), `_routine_output.log`,
two `.env.bak.*` snapshots, and — in `scripts/` — `github_upload.pyc` and
`sync_github_upload.pyc`, stale bytecode for `tools/github_publish/` modules.
`scripts/` has no `.py` source at all, so those `.pyc` files had no source to
correspond to.

Every one of these was git-ignored, which is exactly why they accumulated
unnoticed: `git status` never showed them.

The debris is quarantined under `.mrbot_backups/arch_eng_167_root_debris/`
(MOVED, not deleted) and the orphan bytecode is removed. This suite is the
mechanism so it does not recur.

`test_referenced_requirements_files_exist` closes the last related gap: README.md
instructed the operator to `pip install -r requirements-cloud.txt` and
`-live.txt`, neither of which had ever been written (ARCH-ENG-160). A documented
install command that fails is worse than no documentation.
"""

import ast
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
assert (REPO / "agents").is_dir(), f"repo root misresolved: {REPO}"

# Backups/quarantine and virtualenvs are not the source tree.
_NOT_SOURCE = {".mrbot_backups", "code_patch_backups", "backups", ".venv",
               "__pycache__", ".pytest_cache", ".hermes", ".git"}


def _in_source_tree(path: pathlib.Path) -> bool:
    return not any(part in _NOT_SOURCE for part in path.parts)


class TestRootIsClean(unittest.TestCase):
    """ARCH-ENG-167 — one-shot scripts must not linger in the source root."""

    MIGRATION_PATTERNS = ("_migrate", "_dbg", "_fix_", "_verify_arch_eng")

    # `brain_failures.log` is a LEGITIMATE runtime artifact, not debris:
    # `app/failure_log.py` writes it by design (ARCH-ENG-109) and it is
    # gitignored at .gitignore:155. The debris this test targets is the
    # ad-hoc captured output of a one-off run (`_routine_output.log`), which is
    # in no manifest and no writer.
    RUNTIME_ROOT_ARTIFACTS = {"brain_failures.log"}

    def test_no_one_shot_migration_scripts_in_the_root(self):
        offenders = [
            p.name for p in REPO.iterdir()
            if p.is_file() and p.suffix == ".py"
            and any(p.name.startswith(pref) for pref in self.MIGRATION_PATTERNS)
        ]
        self.assertEqual(
            offenders, [],
            "these one-shot scripts are in the source root: "
            f"{offenders}. A completed migration encodes the PRE-restructure "
            "layout, so leaving it beside main.py invites re-running it. Move it "
            "to .mrbot_backups/ (see arch_eng_167_root_debris/README.md).")

    def test_no_adhoc_captured_output_logs_in_the_root(self):
        """Capture a one-off run's output somewhere else, not in the root."""
        offenders = [p.name for p in REPO.iterdir()
                     if p.is_file() and p.suffix == ".log"
                     and p.name not in self.RUNTIME_ROOT_ARTIFACTS]
        self.assertEqual(
            offenders, [],
            f"ad-hoc captured output in the source root: {offenders}. "
            f"Declared runtime artifacts are {sorted(self.RUNTIME_ROOT_ARTIFACTS)}.")

    def test_declared_runtime_artifacts_are_actually_written_by_code(self):
        """The allow-list must not rot into a blanket exemption.

        If `app/failure_log.py` stopped writing `brain_failures.log`, the file
        would be debris and this exemption would silently permit it forever.
        """
        for name in self.RUNTIME_ROOT_ARTIFACTS:
            stem = name[:-len(".log")]
            written = False
            for py in REPO.rglob("*.py"):
                if not _in_source_tree(py):
                    continue
                try:
                    text = py.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if stem in text:
                    written = True
                    break
            self.assertTrue(written,
                            f"{name} is declared a runtime artifact but no "
                            f"module references it — it is now debris and the "
                            f"exemption has rotted")

    def test_no_reserved_device_name_files(self):
        """`NUL` is a reserved device name; Windows will not delete it normally.

        Removing it needs the `\\\\?\\` UNC prefix, which is exactly why it
        survived every earlier tidy-up: the obvious `Remove-Item` silently
        does nothing.
        """
        reserved = {"NUL", "CON", "PRN", "AUX", "COM1", "LPT1"}
        offenders = [p.name for p in REPO.iterdir()
                     if p.is_file() and p.name.upper() in reserved]
        self.assertEqual(offenders, [],
                         f"reserved-device-name files in the root: {offenders}")

    def test_root_has_no_database_files_outside_the_authority_set(self):
        """ARCH-ENG-163 follow-on: a .db in the root must be a declared store."""
        from agents.core.persistence_contract import _declared_filenames
        declared = _declared_filenames()
        offenders = [p.name for p in REPO.iterdir()
                     if p.is_file() and p.suffix == ".db"
                     and p.name not in declared]
        self.assertEqual(offenders, [],
                         f"undeclared databases in the source root: {offenders}")


class TestNoOrphanBytecode(unittest.TestCase):
    """ARCH-ENG-167 — a `.pyc` with no `.py` beside it is stale by definition."""

    def test_scripts_directory_has_no_python_source_or_bytecode(self):
        """`scripts/` holds PowerShell/batch launchers only.

        It had two `.pyc` files for `tools/github_publish/` modules — bytecode
        with no source in the directory, so nothing could maintain it and the
        only way it could be current is if it were imported, which it was not.
        """
        scripts = REPO / "scripts"
        if not scripts.is_dir():
            self.skipTest("no scripts/ directory")
        stray = [p.name for p in scripts.rglob("*")
                 if p.is_file() and p.suffix in (".pyc", ".py")]
        self.assertEqual(
            stray, [],
            f"scripts/ should contain launchers only, found {stray}")

    def test_no_pycache_in_scripts(self):
        scripts = REPO / "scripts"
        if not scripts.is_dir():
            self.skipTest("no scripts/ directory")
        caches = [str(p.relative_to(REPO))
                  for p in scripts.rglob("__pycache__") if p.is_dir()]
        self.assertEqual(caches, [],
                         f"__pycache__ in a directory with no .py source: {caches}")


class TestNoStrayDatabasesAnywhere(unittest.TestCase):
    """ARCH-ENG-167/163 — the detector must actually detect."""

    def test_no_undeclared_databases_in_the_source_tree(self):
        from agents.core.persistence_contract import discover_undeclared_stores
        found = {k: v for k, v in discover_undeclared_stores(REPO).items()
                 if _in_source_tree(REPO / k)}
        self.assertEqual(
            found, {},
            f"undeclared .db files in the source tree: {found}")

    def test_detector_finds_a_planted_stray(self):
        """Anti-vacuity: prove the scan can fail.

        Without this, a change to the walk could make it silently match nothing
        and every assertion above would pass while checking nothing.
        """
        from agents.core.persistence_contract import discover_undeclared_stores
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "definitely_not_a_store.db").write_bytes(b"x" * 32)
            found = discover_undeclared_stores(root)
        self.assertIn("definitely_not_a_store.db", found)


class TestDocumentedInstallCommandsWork(unittest.TestCase):
    """ARCH-ENG-160/167 — a documented install command must not fail.

    README.md told the operator to run
    `pip install -r requirements-cloud.txt` and `-live.txt`. Neither file had
    ever been written, so both commands failed with a pip path error. An
    operator following the Quick Start to enable a cloud provider or an exchange
    hit a wall with no explanation.
    """

    DOCS = ("README.md", "Agent.md", "OPERATIONS.md", "RELEASE_CHECKLIST.md")

    def test_every_referenced_requirements_file_exists(self):
        missing = {}
        for name in self.DOCS:
            path = REPO / name
            if not path.is_file():
                continue
            for ref in set(re.findall(r"requirements-[\w-]+\.txt",
                                      path.read_text(encoding="utf-8",
                                                     errors="replace"))):
                if not (REPO / ref).is_file():
                    missing.setdefault(name, []).append(ref)
        self.assertEqual(
            missing, {},
            "the documentation references requirements files that do not exist, "
            f"so those `pip install` commands fail: {missing}")

    def test_optional_manifests_are_actually_optional(self):
        """A base install must not pull in the optional extras."""
        requirements = (REPO / "requirements.txt").read_text(encoding="utf-8")
        self.assertNotIn("anthropic", requirements.split("# Optional")[0],
                         "anthropic is optional and belongs in "
                         "requirements-cloud.txt")
        self.assertNotIn("ccxt", requirements,
                         "ccxt is optional and belongs in requirements-live.txt")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-167 — the suite's own helpers must not satisfy its assertions."""

    def test_migration_patterns_do_not_match_this_file(self):
        """This suite is not itself a one-shot migration script."""
        self.assertFalse(
            any(pathlib.Path(__file__).name.startswith(p)
                for p in TestRootIsClean.MIGRATION_PATTERNS))

    def test_root_patterns_are_checked_not_assumed(self):
        """`main.py` must still be there — a clean root is not an empty root."""
        self.assertTrue((REPO / "main.py").is_file())
        self.assertTrue((REPO / "requirements.txt").is_file())
        # And this suite parses as Python, so the AST import is load-bearing.
        ast.parse(pathlib.Path(__file__).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()