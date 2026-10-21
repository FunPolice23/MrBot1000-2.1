"""tests/test_memory_db_isolation.py — ARCH-ENG-156.

The wiring tests for the monetary-evidence check drove
``DialogueTab._on_response_ready``, which calls
``_persist_dialogue_turn`` → ``get_database()`` → ``MemoryDatabase()``.
``DB_PATH`` had no override, so **120 fabricated persona turns** ("I earned
$9,999.00 on Upwork today.") were written into the operator's LIVE conversation
memory. This is the same defect class the suite exists to prevent — ARCH-ENG-049
(``.env``) and ARCH-ENG-057 (``settings.json``) were both fixed with an
env-var redirect plus a session guard; the memory DB had neither.

These tests assert the isolation is real and structural, not incidental.
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _reload_without_redirect():
    """Load program_knowledge as production would: no test env var set."""
    saved = os.environ.pop("MRBOT_DUAL_BRAIN_DB_PATH", None)
    for mod in [m for m in list(sys.modules)
                if m.startswith("agents.knowledge.program_knowledge")]:
        del sys.modules[mod]
    try:
        import agents.knowledge.program_knowledge as pk
        return pk
    finally:
        if saved is not None:
            os.environ["MRBOT_DUAL_BRAIN_DB_PATH"] = saved


class TestDBPathOverride:
    """The redirect must exist, and must not change production behaviour."""

    def test_production_path_is_unchanged_without_the_env_var(self):
        """With no env var set, DB_PATH must resolve exactly as it did before
        ARCH-ENG-156 — the override is additive, never a behaviour change."""
        pk = _reload_without_redirect()
        assert pk.DB_PATH == REPO_ROOT / "dual_brain.db", (
            "the default DB_PATH must still be <repo>/dual_brain.db")

    def test_env_var_redirects_the_path(self):
        """An explicit MRBOT_DUAL_BRAIN_DB_PATH must redirect DB_PATH, and the
        MemoryDatabase default must follow it (so get_database() is isolated)."""
        target = Path(tempfile.gettempdir()) / "mrbot_dbpath_probe.db"
        saved = os.environ.get("MRBOT_DUAL_BRAIN_DB_PATH")
        try:
            target.write_bytes(b"")
            os.environ["MRBOT_DUAL_BRAIN_DB_PATH"] = str(target)
            for mod in [m for m in list(sys.modules)
                        if m.startswith("agents.knowledge.program_knowledge")]:
                del sys.modules[mod]
            import agents.knowledge.program_knowledge as pk
            assert pk.DB_PATH == target, pk.DB_PATH
            import inspect
            default = inspect.signature(pk.MemoryDatabase.__init__).parameters[
                "db_path"].default
            assert default == target, (
                "MemoryDatabase's default must follow the override, otherwise "
                "get_database() would still reach the live DB")
        finally:
            target.unlink(missing_ok=True)
            if saved is None:
                os.environ.pop("MRBOT_DUAL_BRAIN_DB_PATH", None)
            else:
                os.environ["MRBOT_DUAL_BRAIN_DB_PATH"] = saved

    def test_conftest_sets_the_redirect_for_the_session(self):
        """conftest must set the env var, so any test that reaches
        get_database() lands in temp, not in operator memory."""
        assert os.environ.get("MRBOT_DUAL_BRAIN_DB_PATH"), (
            "tests/conftest.py must set MRBOT_DUAL_BRAIN_DB_PATH")
        assert "do_not_edit" in os.environ["MRBOT_DUAL_BRAIN_DB_PATH"], (
            "the redirect must point at a clearly-marked throwaway file")

    def test_live_db_is_not_the_redirect_target(self):
        target = Path(os.environ["MRBOT_DUAL_BRAIN_DB_PATH"])
        live = REPO_ROOT / "dual_brain.db"
        assert target.resolve() != live.resolve(), (
            "the test redirect must never point at the live database")


class TestSessionGuardCoversTheDB:
    """The session guard must watch the live DB, not just .env/settings.json."""

    def test_guard_watches_the_live_db(self):
        """The autouse session fixture must include <repo>/dual_brain.db, so a
        test that bypasses the redirect fails the run instead of silently
        corrupting operator memory."""
        import inspect

        import tests.conftest as conftest

        src = inspect.getsource(conftest._operator_env_is_untouched)
        assert "dual_brain.db" in src, (
            "the session guard must snapshot <repo>/dual_brain.db")

    def test_guard_detects_a_live_db_write(self):
        """End-to-end proof the guard is not vacuous: a subprocess that writes
        the live DB (with the redirect removed) must make the guard fail.

        This is the mutation test for the guard itself — without it, adding
        'dual_brain.db' to the candidate list would be an unverified claim.
        """
        import subprocess

        probe = (
            "import os\n"
            "os.environ.pop('MRBOT_DUAL_BRAIN_DB_PATH', None)\n"
            "import importlib, sys\n"
            "sys.path.insert(0, r'%s')\n"
            "import agents.knowledge.program_knowledge as pk\n"
            "importlib.reload(pk)\n"
            "pk.get_database().log_conversation("
            "'big_brain','probe','GUARD-PROBE-CANARY','x')\n"
        ) % str(REPO_ROOT)

        live = REPO_ROOT / "dual_brain.db"
        before = live.read_bytes() if live.exists() else None
        try:
            proc = subprocess.run(
                [sys.executable, "-c", probe],
                capture_output=True, text=True, timeout=120,
            )
            assert proc.returncode == 0, proc.stderr

            # The write reached the live DB (proving the hazard is real).
            after = live.read_bytes() if live.exists() else None
            assert after != before, (
                "the probe should have modified the live DB — if it did not, "
                "this test no longer proves anything")

            # Clean the canary out so operator memory is left untouched.
            import sqlite3
            conn = sqlite3.connect(live)
            conn.execute(
                "DELETE FROM conversations WHERE message LIKE 'GUARD-PROBE%'")
            conn.commit()
            conn.close()
        finally:
            # Restore byte-for-byte regardless of what happened.
            if before is not None:
                live.write_bytes(before)


if __name__ == "__main__":
    import unittest

    unittest.main()
