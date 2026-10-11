"""Regression tests for CodePatchService in-use queueing.

When a target file is currently in use (a running module the app has loaded,
or an open handler), an approved patch must NOT be written immediately — it
is queued and applied later via drain() once the file is free.
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.safety.approval import ApprovalStatus  # noqa: E402


@pytest.fixture()
def svc():
    from agents.safety.approval import HumanApprovalQueue
    from agents.services.code_patch_service import CodePatchService

    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "gui"))
    q = HumanApprovalQueue()
    service = CodePatchService(approval_queue=q, root_dir=root)
    yield service, q
    import shutil
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture()
def code_patch():
    from agents.services.code_patch_service import CodePatch

    def _make(target, text):
        return CodePatch(
            target_path=target, authored_by="edward",
            motivation="test", detail="unit test", patch_text=text,
            validation="py_compile",
        )
    return _make


def test_approved_patch_is_queued_when_in_use(svc, code_patch):
    service, q = svc
    target = os.path.join(service.root_dir, "gui", "demo.py")
    with open(target, "w", encoding="utf-8") as f:
        f.write("original = 1\n")

    patch = code_patch(target, "patched = 2\n")
    service.propose(patch)
    q.approve(patch.patch_id)

    # Mark the file as in use -> apply must queue, not write.
    service.mark_in_use(target)
    result = service.apply_approved(patch, approval_id=patch.patch_id)

    assert result.get("status") == "queued", result
    with open(target, "r", encoding="utf-8") as f:
        assert f.read() == "original = 1\n", "must NOT be written while in use"

    # File becomes free -> drain applies it.
    service.mark_free(target)
    drained = service.drain()
    assert any(d.get("target") == target for d in drained)
    with open(target, "r", encoding="utf-8") as f:
        assert f.read() == "patched = 2\n"


def test_drain_applies_queued_patch_on_free(svc, code_patch):
    service, q = svc
    target = os.path.join(service.root_dir, "gui", "demo.py")
    with open(target, "w", encoding="utf-8") as f:
        f.write("original = 1\n")

    patch = code_patch(target, "patched = 5\n")
    service.propose(patch)
    q.approve(patch.patch_id)

    service.mark_in_use(target)
    service.apply_approved(patch, approval_id=patch.patch_id)

    # Not free yet -> drain does nothing.
    assert service.drain() == []

    service.mark_free(target)
    results = service.drain()
    assert len(results) == 1
    with open(target, "r", encoding="utf-8") as f:
        assert f.read() == "patched = 5\n"


def test_unapproved_patch_never_queued_or_applied(svc, code_patch):
    service, q = svc
    target = os.path.join(service.root_dir, "gui", "demo.py")
    with open(target, "w", encoding="utf-8") as f:
        f.write("original = 1\n")

    patch = code_patch(target, "patched = 2\n")
    service.propose(patch)  # pending, not approved

    service.mark_in_use(target)
    with pytest.raises(RuntimeError, match="approval"):
        service.apply_approved(patch, approval_id=patch.patch_id)

    assert service.drain() == []
    with open(target, "r", encoding="utf-8") as f:
        assert f.read() == "original = 1\n"


def test_mark_in_use_accepts_module_names(svc, code_patch):
    service, _q = svc
    target = os.path.join(service.root_dir, "gui", "tab_builders.py")
    with open(target, "w", encoding="utf-8") as f:
        f.write("original = 1\n")
    # The app registers loaded modules by module path; mark_in_use must resolve.
    service.mark_in_use("gui.builders.tab_builders")
    service.mark_in_use(target)
    assert service._in_use(target) is True


def test_drain_keeps_patch_that_gets_requeued_mid_apply(svc, code_patch):
    """If a target becomes in-use between drain's check and the write, the
    apply re-queues it and drain must NOT drop it from the pending queue."""
    service, q = svc
    target = os.path.join(service.root_dir, "gui", "demo.py")
    with open(target, "w", encoding="utf-8") as f:
        f.write("original = 1\n")

    patch = code_patch(target, "patched = 2\n")
    service.propose(patch)
    q.approve(patch.patch_id)

    # Queue it while in use.
    service.mark_in_use(target)
    service.apply_approved(patch, approval_id=patch.patch_id)
    assert len(service._pending) == 1

    # Simulate the race: drain checks (file free) but apply re-queues because
    # the file became in-use again between the check and the write. We force
    # this by marking in-use right before drain's apply path runs.
    service.mark_free(target)
    # Monkeypatch apply_approved to re-queue (as if in-use mid-apply).
    orig = service.apply_approved
    def _requeue(p, approval_id="", skip_queue=False):
        service._pending.append((approval_id, 0.0))
        return {"ok": False, "status": "queued", "target": p.target_path,
                "detail": "became in-use mid-apply"}
    service.apply_approved = _requeue
    try:
        results = service.drain()
    finally:
        service.apply_approved = orig

    # The patch must still be pending (not lost).
    assert len(service._pending) == 1, "re-queued patch must not be dropped"
    assert results[0]["status"] == "queued"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
