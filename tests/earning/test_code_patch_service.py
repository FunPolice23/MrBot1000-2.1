"""Regression tests for the approval-gated CodePatchService.

Safety guarantees under test:
1. A patch is only applied after that exact approval item is APPROVED.
2. target_path must resolve inside the repo root (no ../ escapes, no absolute
   path outside root, no symlink escape).
3. Only allowlisted extensions are patchable.
4. A backup is always created before the first write.
5. verify() runs (py_compile) after write; on failure the file is rolled back
   to its exact original bytes.
6. A declined / pending / unknown approval id is never applied.
7. The service never mutates a file for an unapproved patch.
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.safety.approval import (  # noqa: E402
    ApprovalItem,
    ApprovalKind,
    ApprovalStatus,
)


@pytest.fixture()
def service_root():
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, "gui"))
        yield root


def _make_patch(target_path, new_text="print('patched')\n", **kw):
    from agents.services.code_patch_service import CodePatch  # imported lazily
    return CodePatch(
        target_path=target_path,
        authored_by=kw.get("authored_by", "edward"),
        motivation=kw.get("motivation", "test"),
        detail=kw.get("detail", "unit test patch"),
        patch_text=new_text,
        validation=kw.get("validation", "py_compile"),
    )


# ── 3. allowlist guard ───────────────────────────────────────────────────────
def test_rejects_disallowed_extension(service_root):
    from agents.services.code_patch_service import CodePatchService
    svc = CodePatchService(approval_queue=None, root_dir=service_root)
    bad = os.path.join(service_root, "evil.exe")
    patch = _make_patch(bad)
    with pytest.raises(ValueError, match="extension"):
        svc._assert_patchable(patch)


# ── 1+6. pending approval is never applied ──────────────────────────────────
def test_unapproved_patch_not_applied(service_root):
    from agents.services.code_patch_service import CodePatchService
    svc = CodePatchService(approval_queue=None, root_dir=service_root, apply_anyway_for_tests=False)
    target = os.path.join(service_root, "gui", "demo.py")
    with open(target, "w", encoding="utf-8") as f:
        f.write("original = 1\n")
    patch = _make_patch(target, "patched = 2\n")

    # Without an approved approval id, must refuse.
    with pytest.raises(RuntimeError, match="approval"):
        svc.apply_approved(patch, approval_id="nonexistent", skip_queue=False)

    with open(target, "r", encoding="utf-8") as f:
        assert f.read() == "original = 1\n"


# ── 2. path escape guard ─────────────────────────────────────────────────────
def test_rejects_path_escape(service_root):
    from agents.services.code_patch_service import CodePatchService
    svc = CodePatchService(approval_queue=None, root_dir=service_root)
    outside = os.path.join(os.path.dirname(service_root), "outside.py")
    patch = _make_patch(outside)
    with pytest.raises(ValueError, match="(root|absolute|escape)"):
        svc._assert_patchable(patch)


def test_rejects_absolute_path_outside_root(service_root):
    from agents.services.code_patch_service import CodePatchService
    svc = CodePatchService(approval_queue=None, root_dir=service_root)
    patch = _make_patch("/etc/passwd.txt")
    with pytest.raises(ValueError, match="(root|absolute|escape)"):
        svc._assert_patchable(patch)


# ── 4+5. backup + verify + rollback ──────────────────────────────────────────
def test_apply_creates_backup_and_writes(service_root):
    from agents.services.code_patch_service import CodePatchService
    svc = CodePatchService(approval_queue=None, root_dir=service_root, apply_anyway_for_tests=True)
    target = os.path.join(service_root, "gui", "demo.py")
    with open(target, "w", encoding="utf-8") as f:
        f.write("original = 1\n")
    patch = _make_patch(target, "patched = 2\n")

    result = svc.apply_approved(patch, approval_id="test-approved", skip_queue=True)

    assert result is not None
    assert os.path.exists(result.get("backup_path", ""))
    with open(target, "r", encoding="utf-8") as f:
        assert f.read() == "patched = 2\n"


def test_failed_verify_rolls_back_to_original_bytes(service_root):
    from agents.services.code_patch_service import CodePatchService
    svc = CodePatchService(approval_queue=None, root_dir=service_root, apply_anyway_for_tests=True)
    target = os.path.join(service_root, "gui", "demo.py")
    original = "original = 1\n"
    with open(target, "w", encoding="utf-8") as f:
        f.write(original)
    # A syntactically broken patch — py_compile must fail.
    patch = _make_patch(target, "def broken(:\n")

    result = svc.apply_approved(patch, approval_id="test-approved", skip_queue=True)

    assert result.get("ok") is False, result
    with open(target, "r", encoding="utf-8") as f:
        assert f.read() == original, "file must be rolled back to original bytes"


# ── 2. symlink escape ────────────────────────────────────────────────────────
def test_rejects_symlink_escape(service_root):
    import tempfile
    from agents.services.code_patch_service import CodePatchService
    svc = CodePatchService(approval_queue=None, root_dir=service_root)
    with tempfile.TemporaryDirectory() as outside:
        link = os.path.join(service_root, "gui", "linked.py")
        target = os.path.join(outside, "real.py")
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unsupported on this platform")
        patch = _make_patch(link)
        with pytest.raises(ValueError, match="(root|escape|symlink)"):
            svc._assert_patchable(patch)


# ── integration: propose -> approve -> apply, deny -> no apply ──────────────
def test_propose_then_approve_applies(service_root):
    from agents.safety.approval import HumanApprovalQueue
    from agents.services.code_patch_service import CodePatchService, CodePatch

    q = HumanApprovalQueue()
    svc = CodePatchService(approval_queue=q, root_dir=service_root)
    target = os.path.join(service_root, "gui", "demo.py")
    with open(target, "w", encoding="utf-8") as f:
        f.write("original = 1\n")

    patch = _make_patch(target, "patched = 2\n")
    svc.propose(patch)
    assert q.pending_count() == 1

    # Pending: applying without approval must be refused.
    with pytest.raises(RuntimeError, match="approval"):
        svc.apply_approved(patch, approval_id=patch.patch_id)

    # Human approves -> apply succeeds, file patched.
    q.approve(patch.patch_id, notes="looks good")
    result = svc.apply_approved(patch, approval_id=patch.patch_id)
    assert result.get("ok") is True
    with open(target, "r", encoding="utf-8") as f:
        assert f.read() == "patched = 2\n"


def test_propose_then_deny_never_applies(service_root):
    from agents.safety.approval import HumanApprovalQueue
    from agents.services.code_patch_service import CodePatchService

    q = HumanApprovalQueue()
    svc = CodePatchService(approval_queue=q, root_dir=service_root)
    target = os.path.join(service_root, "gui", "demo.py")
    with open(target, "w", encoding="utf-8") as f:
        f.write("original = 1\n")

    patch = _make_patch(target, "patched = 2\n")
    svc.propose(patch)
    q.deny(patch.patch_id, notes="no")

    with pytest.raises(RuntimeError, match="approval"):
        svc.apply_approved(patch, approval_id=patch.patch_id)

    with open(target, "r", encoding="utf-8") as f:
        assert f.read() == "original = 1\n"


def test_propose_then_approve_bad_patch_rolls_back(service_root):
    from agents.safety.approval import HumanApprovalQueue
    from agents.services.code_patch_service import CodePatchService

    q = HumanApprovalQueue()
    svc = CodePatchService(approval_queue=q, root_dir=service_root)
    target = os.path.join(service_root, "gui", "demo.py")
    original = "original = 1\n"
    with open(target, "w", encoding="utf-8") as f:
        f.write(original)

    patch = _make_patch(target, "def broken(:\n")
    svc.propose(patch)
    q.approve(patch.patch_id)

    result = svc.apply_approved(patch, approval_id=patch.patch_id)
    assert result.get("ok") is False
    with open(target, "r", encoding="utf-8") as f:
        assert f.read() == original


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
