"""ARCH-ENG-204 — the one component that wrote source without a backup gate.

## What was wrong

`CodePatchService` already implemented the full workflow an agent needs to
modify its own source: propose → human approval → **backup** → atomic write →
verify → rollback, plus `monitor_applied()` which re-verifies afterwards and
emits a *new gated revert proposal* when a patched file later breaks.

It was fully wired. `composition_root.py:161` builds it, `self_improvement_commands`
proposes and applies against it, `main.py:1600` runs the regression monitor, and
`registration_panel.py:142` routes registration patches through it.

`CoderWorker` was the single holdout. All three of its write methods called
`self.safe_write_file(...)` directly, so an agent rewrite of the program's own
source skipped approval, skipped verify, and had no rollback path — while every
neighbouring component went through the gate.

## The second, quieter hole

`safe_write_file` did take a backup before editing, but:

    except Exception as e:
        self.log_signal.emit(f"Backup skipped: {e}")

**It warned and wrote anyway.** A full disk, a locked file, or a permissions
error silently degraded the guarantee from "a recoverable copy exists" to "we
tried, and if that failed we overwrote anyway" — and `safe_write_file` still
returned True, so the caller logged "Created safely". A safety mechanism that
degrades silently and reports success is worse than one that is absent: the only
evidence anything went wrong was a log line most callers never surface.

The contract is now the one the operator asked for: **no edit without a backup.**
A failed or unusable backup blocks the write.

## The two distinctions this preserves

* **Creating a new file** has no prior content to lose and no backup to take.
  Creation still uses `safe_write_file` — not a gate, but not a hazard.
* **Editing an existing file** goes through `propose_code_patch`, which touches
  nothing until a human approves that exact item.

And when no patch service is attached, `CoderWorker` **refuses** rather than
falling back to an ungated write.
"""

import ast
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
CODER = REPO / "agents" / "services" / "coder.py"
FILESYSTEM = REPO / "agents" / "safety" / "filesystem.py"


def _coder_class():
    tree = ast.parse(CODER.read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == "CoderWorker")


def _methods(node):
    return {m.name: m for m in node.body if isinstance(m, ast.FunctionDef)}


class TestCoderNoLongerWritesUngated(unittest.TestCase):
    """ARCH-ENG-204 — the three write methods must go through the gate."""

    def setUp(self):
        self.methods = _methods(_coder_class())

    def _called_attrs(self, method):
        return [c.func.attr for c in ast.walk(method)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)]

    def test_analyze_and_fix_is_gated(self):
        called = self._called_attrs(self.methods["analyze_and_fix"])
        self.assertIn("_submit_edit", called,
                      "analyze_and_fix writes source ungated again")
        self.assertNotIn("safe_write_file", called)

    def test_file_write_is_gated(self):
        called = self._called_attrs(self.methods["file_write"])
        self.assertIn("_submit_edit", called,
                      "file_write writes source ungated again")
        self.assertNotIn("safe_write_file", called)

    def test_refactor_is_gated(self):
        called = self._called_attrs(self.methods["refactor"])
        self.assertIn("_submit_edit", called,
                      "refactor writes source ungated again")
        self.assertNotIn("safe_write_file", called)

    def test_safe_write_file_exists_only_for_new_files(self):
        """The one legitimate use: creating a file has nothing to lose."""
        body = ast.unparse(self.methods["_submit_edit"])
        self.assertIn("safe_write_file", body)
        self.assertRegex(
            body, r"os\.path\.exists\(file_path\)",
            "the ungated write must be guarded by an existence check, so it "
            "only ever creates a NEW file")
        # The existence check must come BEFORE the write.
        self.assertLess(
            body.index("os.path.exists(file_path)"),
            body.index("safe_write_file"),
            "the ungated write happens before the new-file check")


class TestTheGateIsRefusedNotBypassedWhenUnavailable(unittest.TestCase):
    """ARCH-ENG-204 — no silent degradation to an ungated write."""

    def test_missing_service_is_a_refusal(self):
        """The dangerous alternative is returning `success` with no gate."""
        body = ast.unparse(_methods(_coder_class())["_submit_edit"])
        self.assertRegex(
            body, r'["\']status["\']:\s*["\']blocked["\']',
            "with no patch service the agent must refuse, not fall back to a "
            "direct write")
        self.assertNotRegex(
            body, r'self\.safe_write_file\([^)]*\)\s*\n?\s*return\s*\{"ok":\s*True',
            "an ungated write reporting success is back")


class TestSafeWriteFileNoLongerDegradesSilently(unittest.TestCase):
    """ARCH-ENG-204 — the quieter hole: backup failure used to be a warning."""

    def _safe_write(self):
        tree = ast.parse(FILESYSTEM.read_text(encoding="utf-8"))
        return next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef)
                    and n.name == "safe_write_file")

    def test_a_failed_backup_blocks_the_write(self):
        body = ast.unparse(self._safe_write())
        self.assertNotIn(
            "Backup skipped", body,
            "a failed backup is a warning again; it must block the write")
        self.assertRegex(
            body, r"(?s)except Exception as e:.*?return False",
            # `(?s)` is required: `ast.unparse` emits real newlines between the
            # handler and its `return False`, so a plain `.*?` cannot match.
            "the backup exception handler must return False, not fall through "
            "to the write")

    def test_a_zero_byte_backup_blocks_the_write(self):
        """A truncated backup is not a backup — it would restore to nothing."""
        body = ast.unparse(self._safe_write())
        self.assertRegex(
            body, r"st_size\s*==\s*0",
            "the backup's size must be checked; a copy that silently produced "
            "an empty file is not recoverable")

    def test_the_backup_still_happens_before_the_write(self):
        body = ast.unparse(self._safe_write())
        self.assertLess(
            body.index("shutil.copy2(full_path, backup_path)"),
            body.index("full_path.write_text(content"),
            "the backup must precede the write")

    def test_creating_a_new_file_is_not_treated_as_a_backup_failure(self):
        """No prior content means nothing to lose; a new file must still work."""
        body = ast.unparse(self._safe_write())
        self.assertIn("if full_path.exists():", body,
                      "the backup is conditional on the target existing")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-204 — each detector must be able to fail."""

    def test_the_gating_detector_sees_an_ungated_call(self):
        bad = ast.parse("def f(self):\n    return self.safe_write_file(p, c)\n")
        called = [c.func.attr for c in ast.walk(bad)
                  if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)]
        self.assertIn("safe_write_file", called,
                      "the detector cannot see an ungated write, so it would "
                      "pass while the holdout returned")

    def test_the_backup_detector_sees_the_old_warning(self):
        old = 'self.log_signal.emit(f"Backup skipped: {e}")'
        self.assertIn("Backup skipped", old)
        self.assertNotIn("Backup skipped",
                         ast.unparse(self_test_fs()))

    def _new_fs(self):
        tree = ast.parse(FILESYSTEM.read_text(encoding="utf-8"))
        return next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef)
                    and n.name == "safe_write_file")


def self_test_fs():
    tree = ast.parse(FILESYSTEM.read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef)
                and n.name == "safe_write_file")


class TestTheExistingServiceIsStillTheOneUsed(unittest.TestCase):
    """ARCH-ENG-204 — wiring to the live service, not a new parallel one."""

    def test_it_uses_the_shared_propose_command(self):
        body = ast.unparse(_methods(_coder_class())["_submit_edit"])
        self.assertRegex(
            body, r"from agents\.services\.self_improvement_commands import "
                   r"propose_code_patch",
            "CoderWorker must go through the shared approval-gated command so "
            "the feature flag and approval semantics stay in one place")

    def test_the_patch_service_is_injectable(self):
        init = _methods(_coder_class())["__init__"]
        params = [a.arg for a in init.args.args]
        self.assertIn("patch_service", params,
                      "the gate cannot be attached, so the wiring is inert")

    def test_it_refuses_protected_source_before_proposing(self):
        """The pre-existing guard must stay ahead of the proposal."""
        body = ast.unparse(_methods(_coder_class())["analyze_and_fix"])
        self.assertIn("PROTECTED_SOURCE_FILES", body)
        self.assertLess(body.index("PROTECTED_SOURCE_FILES"),
                        body.index("_submit_edit"),
                        "the protected-source refusal must precede the proposal")